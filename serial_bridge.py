"""
serial_bridge.py — USB serial transmission to ESP32 at 115200 baud

Sends single-byte grade commands over /dev/ttyUSB0 (or /dev/ttyACM0) to the
ESP32 co-processor which controls downstream sorting gates.

Protocol:
  Grade A → b'A\\n'
  Grade B → b'B\\n'
  Grade C → b'C\\n'
  IDLE    → b'I\\n'  (no-op, used for heartbeat testing)

Cross-platform:
  - On Windows or when pyserial cannot open the port, all transmissions
    are printed to stdout so the app can run on dev machines.
"""

import sys
import time
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# ── Serial availability ────────────────────────────────────────────────────────
try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False
    logger.warning("pyserial not installed — serial bridge in mock/stdout mode")

# ── Configuration ─────────────────────────────────────────────────────────────
BAUD_RATE          = 115_200
READ_TIMEOUT_S     = 1.0
WRITE_TIMEOUT_S    = 1.0
PREFERRED_PORTS    = ["/dev/ttyUSB0", "/dev/ttyACM0"]   # Tried in order on Linux
RECONNECT_DELAY_S  = 3.0
MAX_RECONNECT_TRIES = 5

# Valid grade bytes
VALID_GRADES = {"A", "B", "C", "I"}


class SerialBridge:
    """
    Manages the serial connection to the ESP32 and exposes a simple
    send_grade(grade) method.

    Thread-safe — a background thread keeps the port alive and auto-reconnects.
    """

    def __init__(self, port: Optional[str] = None, baud: int = BAUD_RATE):
        self._port_name: Optional[str] = port   # None → auto-detect
        self._baud = baud
        self._conn: Optional["serial.Serial"] = None
        self._lock = threading.Lock()
        self._connected = False
        self._mock = not SERIAL_AVAILABLE or sys.platform.startswith("win")
        self._stop_event = threading.Event()
        self._keeper_thread: Optional[threading.Thread] = None

        if self._mock:
            logger.info("SerialBridge: running in stdout/mock mode (no hardware serial)")

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self):
        """Open the serial port and start the keep-alive monitor thread."""
        if self._mock:
            logger.info("[SERIAL MOCK] SerialBridge started — transmissions go to stdout")
            return

        self._stop_event.clear()
        # Initial connect attempt
        self._try_connect()

        # Background keeper
        self._keeper_thread = threading.Thread(
            target=self._keep_alive_loop,
            daemon=True,
            name="SerialKeeper",
        )
        self._keeper_thread.start()
        logger.info("SerialBridge keep-alive thread started")

    def stop(self):
        """Close the serial port cleanly."""
        self._stop_event.set()
        if self._keeper_thread:
            self._keeper_thread.join(timeout=5)
        self._close()
        logger.info("SerialBridge stopped")

    # ── Public API ─────────────────────────────────────────────────────────────

    def send_grade(self, grade: str) -> bool:
        """
        Transmit a grade byte + newline to the ESP32.

        Args:
            grade: One of 'A', 'B', 'C', or 'I'.

        Returns:
            True if the byte was transmitted (or mocked), False on error.
        """
        grade = grade.upper().strip()
        if grade not in VALID_GRADES:
            logger.error(f"send_grade: invalid grade '{grade}' — must be A/B/C/I")
            return False

        payload = f"{grade}\n".encode("ascii")

        if self._mock:
            print(f"[SERIAL MOCK] → ESP32: grade='{grade}'  payload={payload!r}", flush=True)
            logger.info(f"[MOCK] Serial TX → '{grade}'")
            return True

        with self._lock:
            if not self._connected or self._conn is None:
                logger.warning(f"send_grade: not connected — grade '{grade}' not transmitted")
                return False
            try:
                self._conn.write(payload)
                self._conn.flush()
                logger.info(f"Serial TX → '{grade}' on {self._port_name}")
                return True
            except Exception as e:
                logger.error(f"Serial write error: {e}")
                self._connected = False
                return False

    def is_connected(self) -> bool:
        """Return True if the serial port is open and healthy."""
        if self._mock:
            return True   # Mock always "connected"
        return self._connected

    def status(self) -> dict:
        """Return a status dict for the API health endpoint."""
        return {
            "mock_mode":   self._mock,
            "connected":   self.is_connected(),
            "port":        self._port_name,
            "baud":        self._baud,
        }

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _auto_detect_port(self) -> Optional[str]:
        """Try the preferred port list first; fall back to first USB serial port found."""
        if not SERIAL_AVAILABLE:
            return None

        # Explicit preferred ports
        for p in PREFERRED_PORTS:
            try:
                s = serial.Serial(p, self._baud, timeout=0.5)
                s.close()
                logger.info(f"Auto-detected preferred port: {p}")
                return p
            except Exception:
                pass

        # Any USB serial port
        ports = [cp.device for cp in serial.tools.list_ports.comports()
                 if "USB" in (cp.description or "").upper() or
                    "ACM" in (cp.device or "").upper()]
        if ports:
            logger.info(f"Auto-detected fallback port: {ports[0]}")
            return ports[0]

        logger.warning("No serial port auto-detected")
        return None

    def _try_connect(self) -> bool:
        """Attempt to open the serial port. Returns True on success."""
        if not SERIAL_AVAILABLE:
            return False

        port = self._port_name or self._auto_detect_port()
        if not port:
            logger.warning("Serial: no port available to connect")
            return False

        try:
            conn = serial.Serial(
                port=port,
                baudrate=self._baud,
                timeout=READ_TIMEOUT_S,
                write_timeout=WRITE_TIMEOUT_S,
            )
            # Drain any leftover data
            time.sleep(0.1)
            conn.reset_input_buffer()
            conn.reset_output_buffer()

            with self._lock:
                if self._conn and self._conn.is_open:
                    self._conn.close()
                self._conn = conn
                self._port_name = port
                self._connected = True

            logger.info(f"Serial connected: {port} @ {self._baud} baud")
            return True
        except Exception as e:
            logger.error(f"Serial connect failed ({port}): {e}")
            self._connected = False
            return False

    def _close(self):
        """Close the serial port without error."""
        with self._lock:
            self._connected = False
            if self._conn:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    def _keep_alive_loop(self):
        """
        Background daemon: checks connection health every RECONNECT_DELAY_S
        seconds and reconnects if the port drops.
        """
        while not self._stop_event.wait(RECONNECT_DELAY_S):
            if not self._connected:
                logger.info("Serial keep-alive: attempting reconnect…")
                for attempt in range(1, MAX_RECONNECT_TRIES + 1):
                    if self._try_connect():
                        break
                    logger.warning(f"Reconnect attempt {attempt}/{MAX_RECONNECT_TRIES} failed")
                    if self._stop_event.wait(RECONNECT_DELAY_S):
                        return
            else:
                # Sanity-check the port is still open
                with self._lock:
                    if self._conn and not self._conn.is_open:
                        self._connected = False
                        logger.warning("Serial: port unexpectedly closed")
