"""
hardware_controller.py — GPIO management for PotatoSort AI Sorter
Raspberry Pi 5 — BCM pin numbering via gpiozero + lgpio backend

Hardware:
  DC Motor:   GPIO 17 — N-channel MOSFET or relay module (HIGH = motor on)
  Push Servo: GPIO 12 — Hardware PWM (50 Hz), 0° = 2% duty, 90° = 7% duty

Cross-platform: if gpiozero / lgpio is not available the module degrades to
stdout-only mock mode so the app runs on Windows / Linux dev machines.
"""

import sys
import time
import logging
import threading

logger = logging.getLogger(__name__)

# ── GPIO availability detection ────────────────────────────────────────────────
PLATFORM_PI = (sys.platform.startswith("linux") and
               any(p in open("/proc/cpuinfo", "r", errors="ignore").read()
                   for p in ("Raspberry", "BCM2")) if sys.platform.startswith("linux") else False)

try:
    from gpiozero import OutputDevice, Servo
    from gpiozero.pins.lgpio import LGPIOFactory
    _pin_factory = LGPIOFactory()
    GPIO_AVAILABLE = True
    logger.info("gpiozero + lgpio loaded — hardware GPIO mode active")
except Exception as _gpio_err:
    GPIO_AVAILABLE = False
    logger.warning(f"GPIO not available ({_gpio_err}) — running in mock/stub mode")

# ── Pin assignments ────────────────────────────────────────────────────────────
PIN_MOTOR = 17   # DC motor via MOSFET/relay
PIN_SERVO = 12   # 10g push servo (hardware PWM)

# Servo duty-cycle mapping: gpiozero Servo expects value in [-1.0 … +1.0]
# where -1 = min_pulse (0°) and +1 = max_pulse (90°).
# For a standard SG90 on RPi5 hardware PWM:
#   0°  → 0.5 ms pulse  → value = -1.0
#  90°  → 1.5 ms pulse  → value =  0.0 (mid)
# 180°  → 2.4 ms pulse  → value = +1.0
# We remap angle → gpiozero value linearly.
SERVO_MIN_ANGLE = 0
SERVO_MAX_ANGLE = 180
SERVO_EJECT_ANGLE = 90   # Push position
SERVO_HOME_ANGLE  = 0    # Rest position


def _angle_to_value(angle: float) -> float:
    """Map angle (0–180°) to gpiozero Servo value (-1.0 to +1.0)."""
    return (angle / 90.0) - 1.0


class HardwareController:
    """
    Manages the DC motor and push servo.

    Usage:
        hw = HardwareController()
        hw.setup()
        hw.motor_on()
        hw.servo_eject()
        hw.motor_off()
        hw.cleanup()
    """

    def __init__(self):
        self._motor = None
        self._servo = None
        self._servo_lock = threading.Lock()
        self._mock = not GPIO_AVAILABLE

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def setup(self):
        """Initialise GPIO devices. Safe to call multiple times."""
        if self._mock:
            logger.info("[MOCK] HardwareController.setup() — GPIO in stdout mode")
            return

        try:
            self._motor = OutputDevice(
                pin=PIN_MOTOR,
                active_high=True,
                initial_value=False,
                pin_factory=_pin_factory,
            )
            self._servo = Servo(
                pin=PIN_SERVO,
                initial_value=_angle_to_value(SERVO_HOME_ANGLE),
                min_pulse_width=0.5 / 1000,   # 0.5 ms → 0°
                max_pulse_width=2.4 / 1000,   # 2.4 ms → 180°
                pin_factory=_pin_factory,
            )
            logger.info(f"GPIO ready — Motor:GPIO{PIN_MOTOR}  Servo:GPIO{PIN_SERVO}")
        except Exception as e:
            logger.error(f"GPIO setup failed: {e} — falling back to mock mode")
            self._mock = True

    def cleanup(self):
        """Release all GPIO resources safely."""
        if self._mock:
            logger.info("[MOCK] HardwareController.cleanup()")
            return
        try:
            if self._motor:
                self._motor.off()
                self._motor.close()
            if self._servo:
                self._servo.value = _angle_to_value(SERVO_HOME_ANGLE)
                time.sleep(0.3)
                self._servo.close()
            logger.info("GPIO resources released")
        except Exception as e:
            logger.error(f"GPIO cleanup error: {e}")

    # ── Motor ─────────────────────────────────────────────────────────────────

    def motor_on(self):
        """Set DC motor GPIO 17 HIGH (motor running)."""
        if self._mock:
            print(f"[GPIO MOCK] Motor GPIO{PIN_MOTOR} → HIGH (ON)", flush=True)
            logger.info(f"[MOCK] Motor ON — GPIO{PIN_MOTOR}")
            return
        try:
            self._motor.on()
            logger.info(f"Motor ON — GPIO{PIN_MOTOR} HIGH")
        except Exception as e:
            logger.error(f"motor_on error: {e}")

    def motor_off(self):
        """Set DC motor GPIO 17 LOW (motor stopped)."""
        if self._mock:
            print(f"[GPIO MOCK] Motor GPIO{PIN_MOTOR} → LOW (OFF)", flush=True)
            logger.info(f"[MOCK] Motor OFF — GPIO{PIN_MOTOR}")
            return
        try:
            self._motor.off()
            logger.info(f"Motor OFF — GPIO{PIN_MOTOR} LOW")
        except Exception as e:
            logger.error(f"motor_off error: {e}")

    def motor_is_on(self) -> bool:
        """Return True if motor is currently active."""
        if self._mock:
            return False
        try:
            return bool(self._motor.value)
        except Exception:
            return False

    # ── Servo ─────────────────────────────────────────────────────────────────

    def servo_eject(self, eject_angle: float = SERVO_EJECT_ANGLE,
                    home_angle: float = SERVO_HOME_ANGLE,
                    hold_ms: float = 400):
        """
        Execute one eject cycle:
          1. Move servo to eject_angle (default 90°)
          2. Hold for hold_ms milliseconds
          3. Return to home_angle (default 0°)

        Thread-safe via lock — concurrent calls are serialised.
        """
        with self._servo_lock:
            self._servo_move(eject_angle)
            time.sleep(hold_ms / 1000.0)
            self._servo_move(home_angle)

    def _servo_move(self, angle: float):
        """Set servo to a specific angle (0–180°)."""
        angle = max(SERVO_MIN_ANGLE, min(SERVO_MAX_ANGLE, angle))
        val = _angle_to_value(angle)

        if self._mock:
            print(f"[GPIO MOCK] Servo GPIO{PIN_SERVO} → {angle:.0f}° (value={val:.3f})", flush=True)
            logger.info(f"[MOCK] Servo → {angle:.0f}° on GPIO{PIN_SERVO}")
            return
        try:
            self._servo.value = val
            logger.debug(f"Servo → {angle:.0f}° (value={val:.3f})")
        except Exception as e:
            logger.error(f"servo_move error: {e}")

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return a dict snapshot of current hardware state."""
        return {
            "mock_mode":   self._mock,
            "motor_pin":   PIN_MOTOR,
            "servo_pin":   PIN_SERVO,
            "motor_on":    self.motor_is_on(),
            "gpio_avail":  GPIO_AVAILABLE,
        }
