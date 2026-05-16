"""Rejestracja mDNS: usługa TCP + pole server=studyfocus.local."""

from __future__ import annotations

import logging
import socket
import threading
from typing import Optional

from zeroconf import ServiceInfo, Zeroconf

logger = logging.getLogger(__name__)


def _pick_ipv4_address() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("224.0.0.1", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class StudyFocusDiscovery:
    """Ogłasza _studyfocus._tcp oraz FQDN studyfocus.local (pole server w ServiceInfo)."""

    SERVICE_TYPE = "_studyfocus._tcp.local."
    SERVICE_NAME = "StudyFocus._studyfocus._tcp.local."

    def __init__(self, port: int) -> None:
        self._port = port
        self._zc: Optional[Zeroconf] = None
        self._info: Optional[ServiceInfo] = None

    def start(self) -> None:
        if self._zc is not None:
            return
        ip = _pick_ipv4_address()
        self._zc = Zeroconf()
        self._info = ServiceInfo(
            self.SERVICE_TYPE,
            self.SERVICE_NAME,
            addresses=[socket.inet_aton(ip)],
            port=self._port,
            properties={"app": "studyfocus", "path": "/"},
            server="studyfocus.local.",
        )
        self._zc.register_service(self._info)
        logger.info("Zeroconf: zarejestrowano %s na porcie %s (IP %s)", self.SERVICE_NAME, self._port, ip)

    def update_port(self, port: int) -> None:
        """Jeśli serwer WebSocket nasłuchuje na innym porcie niż założony, podmień rejestrację."""
        if port == self._port and self._info is not None:
            return
        self.stop()
        self._port = port
        self.start()

    def stop(self) -> None:
        if self._zc is None or self._info is None:
            return
        try:
            self._zc.unregister_service(self._info)
        except Exception as e:  # pragma: no cover
            logger.debug("unregister_service: %s", e)
        self._zc.close()
        self._zc = None
        self._info = None


def start_discovery_background(discovery: StudyFocusDiscovery) -> threading.Thread:
    def run() -> None:
        discovery.start()

    t = threading.Thread(target=run, daemon=True, name="StudyFocus-Zeroconf")
    t.start()
    return t
