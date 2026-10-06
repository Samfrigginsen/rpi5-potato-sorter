"""
telemetry_monitor.py — System telemetry for the bottom hardware status bar
Polls CPU %, CPU temperature, and updates SharedState.telemetry every second.
Also fires the WARN LED and logs events when thresholds are exceeded.
"""

import time
import threading
import logging

logger = logging.getLogger(__name__)

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("psutil not installed — telemetry in stub mode")

# ── Thresholds
CPU_WARN_PCT   = 75.0   # % — trigger WARN LED
TEMP_WARN_C    = 65.0   # °C — trigger WARN LED
TEMP_CRIT_C    = 75.0   # °C — force stop


def _read_cpu_temp() -> float:
    """Read CPU temperature from the Pi's thermal zone."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read().strip()) / 1000.0
    except Exception:
        return 0.0


class TelemetryMonitor:
    def __init__(self):
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="TelemetryMon")
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        # Import here to avoid circular imports
        from shared_state import sorter_state

        while self._running:
            try:
                cpu = psutil.cpu_percent(interval=None) if PSUTIL_AVAILABLE else 0.0
                temp = _read_cpu_temp()

                sorter_state.telemetry.cpu_percent = cpu
                sorter_state.telemetry.cpu_temp_c  = temp

                # Threshold checks
                warn = (cpu >= CPU_WARN_PCT) or (temp >= TEMP_WARN_C)
                sorter_state.set_led("warn", warn)

                if temp >= TEMP_CRIT_C and sorter_state.is_running:
                    # MINOR FIX: `sorter_state` was already imported once at
                    # the top of _loop() — re-importing it here every time
                    # this branch fires was harmless but redundant.
                    logger.critical(f"CPU temp critical ({temp:.1f}°C) — emergency stop")
                    sorter_state.stop()

                # FIX (Quick Purge gap): this 1Hz beat is a convenient place
                # to end an expired purge — see shared_state.request_purge()
                # / check_purge_expiry(). Without this call, purge_active
                # would never clear itself and belt_speed_mps / the LCD's
                # [PURGE] status would stay boosted forever.
                sorter_state.check_purge_expiry()

            except Exception as e:
                logger.error(f"Telemetry error: {e}")

            time.sleep(1)
