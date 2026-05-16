"""Serwer WebSocket + broadcast stanu blokady."""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Set


class LockSignalingServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8765) -> None:
        self.host = host
        self.port = port
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._server: asyncio.Server | None = None
        self._clients: Set[Any] = set()
        self._lock = threading.Lock()
        self._locked = False
        self._ready = threading.Event()
        
        # Callbacki do komunikacji z główną aplikacją GUI
        self.on_client_change = None
        self.on_message = None

    @property
    def port_bound(self) -> int:
        if self._server and self._server.sockets:
            return int(self._server.sockets[0].getsockname()[1])
        return self.port

    def is_locked(self) -> bool:
        with self._lock:
            return self._locked

    def wait_until_ready(self, timeout: float = 5.0) -> bool:
        return self._ready.wait(timeout)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        def thread_main() -> None:
            import websockets

            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            async def setup() -> None:
                self._server = await websockets.serve(self._handler, self.host, self.port)
                self._ready.set()

            self._loop.run_until_complete(setup())
            self._loop.run_forever()

        self._ready.clear()
        self._thread = threading.Thread(target=thread_main, daemon=True, name="StudyFocus-WS")
        self._thread.start()

    async def _handler(self, websocket: Any) -> None:
        self._clients.add(websocket)
        # Powiadom aplikację, że telefon się połączył
        if self.on_client_change:
            self.on_client_change(True)
            
        try:
            if self.is_locked():
                await websocket.send("LOCKED")
            else:
                await websocket.send("UNLOCKED")
                
            # Ciągłe nasłuchiwanie wiadomości zwrotnych z telefonu (np. CHEAT_DETECTED)
            async for message in websocket:
                if self.on_message:
                    if isinstance(message, bytes):
                        message = message.decode("utf-8")
                    self.on_message(message)
        except Exception:
            pass
        finally:
            self._clients.discard(websocket)
            # Powiadom aplikację o rozłączeniu (jeśli brak innych klientów)
            if self.on_client_change:
                self.on_client_change(len(self._clients) > 0)

    async def _broadcast(self, message: str) -> None:
        dead: list[Any] = []
        for ws in list(self._clients):
            try:
                await ws.send(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    def set_locked(self, locked: bool) -> None:
        with self._lock:
            self._locked = locked
        msg = "LOCKED" if locked else "UNLOCKED"
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._broadcast(msg), self._loop)

    def stop(self) -> None:
        if self._loop is None:
            return

        async def _close() -> None:
            if self._server:
                self._server.close()
                await self._server.wait_closed()
            for ws in list(self._clients):
                try:
                    await ws.close()
                except Exception:
                    pass
            self._clients.clear()

        try:
            fut = asyncio.run_coroutine_threadsafe(_close(), self._loop)
            fut.result(timeout=3.0)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)