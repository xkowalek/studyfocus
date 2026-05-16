import 'dart:async';
import 'dart:io';
import 'dart:math';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:wakelock_plus/wakelock_plus.dart';
import 'package:screen_brightness/screen_brightness.dart';
import 'package:volume_controller/volume_controller.dart';
import 'package:sensors_plus/sensors_plus.dart';
import 'package:audioplayers/audioplayers.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const StudyFocusLeashApp());
}

class StudyFocusLeashApp extends StatelessWidget {
  const StudyFocusLeashApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'StudyFocus Leash',
      theme: ThemeData.dark().copyWith(
        scaffoldBackgroundColor: const Color(0xFF040404),
      ),
      home: const LeashScreen(),
      debugShowCheckedModeBanner: false,
    );
  }
}

class LeashScreen extends StatefulWidget {
  const LeashScreen({super.key});

  @override
  State<LeashScreen> createState() => _LeashScreenState();
}

class _LeashScreenState extends State<LeashScreen> {
  // Kontroler pola tekstowego do ręcznego wpisania IP
  final TextEditingController _ipController = TextEditingController(text: '');
  final String pcPort = '8765';

  WebSocketChannel? _channel;
  String _status = "Gotowy do synchronizacji";
  bool _isConnected = false;

  // Stan "Obroży"
  bool _isLocked = false;
  bool _isAlarmActive = false;
  bool _inGracePeriod = false; // Czas bezpieczny na odłożenie telefonu

  // Kontrolery czujników i mediów
  StreamSubscription<AccelerometerEvent>? _accelSubscription;
  final AudioPlayer _audioPlayer = AudioPlayer();

  @override
  void initState() {
    super.initState();
    _audioPlayer.setReleaseMode(ReleaseMode.loop);
  }

  /// Próba automatycznego wykrycia PC przez Zeroconf/mDNS
  Future<void> _autoDiscoverPC() async {
    setState(() {
      _status = "Skanuję sieć Wi-Fi w poszukiwaniu PC...";
    });

    try {
      // 1. Pobieramy listę kart sieciowych telefonu, aby poznać podsieć (np. 192.168.0.X)
      final interfaces = await NetworkInterface.list();
      String? subnet;

      for (var interface in interfaces) {
        for (var addr in interface.addresses) {
          if (addr.type == InternetAddressType.IPv4 && !addr.isLoopback) {
            final parts = addr.address.split('.');
            if (parts.length == 4) {
              // Wyciągamy rdzeń sieci, np. "192.168.0."
              subnet = "${parts[0]}.${parts[1]}.${parts[2]}.";
              break;
            }
          }
        }
        if (subnet != null) break;
      }

      if (subnet == null) {
        setState(() => _status = "Błąd: Brak połączenia z Wi-Fi!");
        return;
      }

      // 2. Odpalamy 254 zapytania naraz (asynchronicznie) - to potrwa ułamek sekundy!
      List<Future<void>> scanTasks = [];
      int targetPort = int.parse(pcPort);

      for (int i = 1; i < 255; i++) {
        final testIp = "$subnet$i";

        // Próbujemy otworzyć czysty socket na porcie serwera Pythona
        final task =
            Socket.connect(
                  testIp,
                  targetPort,
                  timeout: const Duration(milliseconds: 800),
                )
                .then((socket) {
                  // Jeśli się połączył, to znaczy, że to nasz serwer StudyFocus!
                  socket.destroy();
                  if (mounted && !_isConnected) {
                    setState(() {
                      _ipController.text = testIp;
                      _status = "Automatycznie znaleziono PC: $testIp";
                    });
                    _connectToPC(); // Od razu odpalamy połączenie
                  }
                })
                .catchError((_) {
                  // Ignorujemy błędy dla adresów pod którymi nic nie stoi
                });

        scanTasks.add(task);
      }

      // Czekamy na zakończenie wszystkich zadań
      await Future.wait(scanTasks);

      if (!_isConnected && mounted) {
        setState(() {
          _status =
              "Nie znaleziono PC automatycznie. Przepisz IP ze stopki aplikacji PC.";
        });
      }
    } catch (e) {
      setState(() {
        _status = "Błąd skanowania sieci: $e";
      });
    }
  }

  void _connectToPC() {
    try {
      final ip = _ipController.text.trim();
      final wsUrl = Uri.parse('ws://$ip:$pcPort');
      _channel = WebSocketChannel.connect(wsUrl);

      setState(() {
        _status = "Połączono z serwerem PC ($ip)";
        _isConnected = true;
      });

      _channel!.stream.listen(
        (message) {
          if (message == 'LOCKED') {
            _activateLeash();
          } else if (message == 'UNLOCKED') {
            _deactivateLeash();
          }
        },
        onDone: () => _handleDisconnect(),
        onError: (e) => _handleDisconnect(),
      );
    } catch (e) {
      setState(() => _status = "Błąd połączenia. Sprawdź wpisany adres IP!");
    }
  }

  void _handleDisconnect() {
    if (_isLocked) {
      _triggerAlarm();
    }
    setState(() {
      _isConnected = false;
      _status = "Rozłączono z PC. Połącz ponownie.";
    });
  }

  Future<void> _activateLeash() async {
    setState(() {
      _isLocked = true;
      _isAlarmActive = false;
    });

    await WakelockPlus.enable();

    // WŁĄCZENIE TRYBU IMMERSYJNEGO - paski systemowe Androida całkowicie znikają
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);

    // Jasność do zera (czysty AMOLED)
    try {
      await ScreenBrightness().setApplicationScreenBrightness(0.0);
    } catch (e) {
      debugPrint('Brak uprawnień do jasności: $e');
    }

    _accelSubscription = accelerometerEventStream().listen((
      AccelerometerEvent event,
    ) {
      if (!_isLocked || _isAlarmActive || _inGracePeriod) return;

      double magnitude = sqrt(
        pow(event.x, 2) + pow(event.y, 2) + pow(event.z, 2),
      );

      // Czułość ustawiona na wysoką (0.7)
      if ((magnitude - 9.81).abs() > 0.7) {
        _triggerAlarm();
      }
    });
  }

  Future<void> _deactivateLeash() async {
    setState(() {
      _isLocked = false;
      _isAlarmActive = false;
    });

    _accelSubscription?.cancel();
    _audioPlayer.stop();
    WakelockPlus.disable();

    // PRZYWRÓCENIE PASKÓW SYSTEMOWYCH
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);

    try {
      await ScreenBrightness().resetApplicationScreenBrightness();
    } catch (e) {
      debugPrint('Brak uprawnień do resetu jasności: $e');
    }
  }

  void _triggerAlarm() {
    if (_isAlarmActive) return;

    setState(() => _isAlarmActive = true);

    SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);

    try {
      ScreenBrightness().resetApplicationScreenBrightness();
    } catch (e) {
      debugPrint(e.toString());
    }

    try {
      VolumeController().setVolume(1.0);
    } catch (e) {
      debugPrint("Błąd głośności: $e");
    }

    _channel?.sink.add('CHEAT_DETECTED');
    _audioPlayer.play(AssetSource('alarm.mp3'));
  }

  Future<void> _resetAlarmAndRelock() async {
    setState(() {
      _isAlarmActive = false;
      _isLocked = true;
      _inGracePeriod = true; // Bezpieczne 3 sekundy na odłożenie
    });

    _audioPlayer.stop();
    _channel?.sink.add('ALARM_MUTED'); // Informujemy serwer PC o uciszeniu

    SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);

    try {
      await ScreenBrightness().setApplicationScreenBrightness(0.0);
    } catch (e) {
      debugPrint(e.toString());
    }

    Timer(const Duration(seconds: 3), () {
      if (mounted) {
        setState(() {
          _inGracePeriod = false;
        });
      }
    });
  }

  @override
  void dispose() {
    _deactivateLeash();
    _ipController.dispose();
    _channel?.sink.close();
    _audioPlayer.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_isAlarmActive) {
      return Scaffold(
        backgroundColor: Colors.redAccent,
        body: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(
                Icons.warning_amber_rounded,
                size: 120,
                color: Colors.white,
              ),
              const SizedBox(height: 20),
              const Text(
                "OSZUSTWO WYKRYTE!",
                style: TextStyle(
                  fontSize: 32,
                  fontWeight: FontWeight.bold,
                  color: Colors.white,
                ),
              ),
              const SizedBox(height: 20),
              ElevatedButton(
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.black,
                  padding: const EdgeInsets.symmetric(
                    horizontal: 24,
                    vertical: 12,
                  ),
                ),
                onPressed: _resetAlarmAndRelock,
                child: const Text(
                  "Ucisz i zablokuj ponownie",
                  style: TextStyle(fontWeight: FontWeight.bold),
                ),
              ),
            ],
          ),
        ),
      );
    }

    if (_isLocked) {
      return PopScope(
        canPop: false,
        child: Scaffold(backgroundColor: Colors.black, body: Container()),
      );
    }

    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          child: Padding(
            padding: const EdgeInsets.all(24.0),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(
                  _isConnected ? Icons.phonelink_lock : Icons.link_off,
                  size: 80,
                  color: _isConnected ? const Color(0xFF1F6F4A) : Colors.grey,
                ),
                const SizedBox(height: 20),
                Text(
                  _isConnected ? "Telefon uzbrojony" : "Oczekiwanie na PC",
                  style: const TextStyle(
                    fontSize: 24,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 10),
                Text(
                  _status,
                  style: const TextStyle(color: Colors.grey),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 30),

                // Panel sterowania IP wyświetlany tylko przed połączeniem
                if (!_isConnected) ...[
                  ElevatedButton.icon(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.blueGrey.shade800,
                    ),
                    onPressed: _autoDiscoverPC,
                    icon: const Icon(Icons.youtube_searched_for),
                    label: const Text("SZUKAJ AUTOMATYCZNIE (mDNS)"),
                  ),
                  const SizedBox(height: 20),
                  const Text(
                    "LUB WPISZ ADRES IP RĘCZNIE:",
                    style: TextStyle(
                      fontSize: 11,
                      color: Colors.grey,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(height: 8),
                  SizedBox(
                    width: 260,
                    child: TextField(
                      controller: _ipController,
                      keyboardType: TextInputType.number,
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                        letterSpacing: 1.2,
                      ),
                      decoration: InputDecoration(
                        hintText: '192.168.x.x',
                        contentPadding: const EdgeInsets.symmetric(
                          vertical: 10,
                        ),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(8),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 20),
                  ElevatedButton(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFF1F6F4A),
                      padding: const EdgeInsets.symmetric(
                        horizontal: 60,
                        vertical: 15,
                      ),
                    ),
                    onPressed: _connectToPC,
                    child: const Text(
                      "POŁĄCZ",
                      style: TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.bold,
                        fontSize: 16,
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
