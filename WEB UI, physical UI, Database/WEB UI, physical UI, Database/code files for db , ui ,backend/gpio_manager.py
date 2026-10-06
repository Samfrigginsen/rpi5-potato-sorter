"""
gpio_manager.py — GPIO hardware interface for PotatoSort AI on Raspberry Pi 5

Tier 1 (Field):    3 push buttons (Start/Stop/Reset) + 4 status LEDs
Tier 2 (Storage):  Rotary Encoder + Speed Toggle + Purge Button + Batch Save Button

Uses RPi.GPIO (BCM mode). All hardware I/O is centralised here so the vision
worker and Flask layer never touch GPIO pins directly.
"""

import threading
import time
import logging
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# ── Try importing RPi.GPIO; fall back gracefully on non-Pi hardware
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
    logger.info("RPi.GPIO loaded — hardware mode")
except ImportError:
    GPIO_AVAILABLE = False
    logger.warning("RPi.GPIO not available — running in stub mode (OK on dev machines)")

# ──────────────────────────────────────────────────────────────────────────────
#  PIN ASSIGNMENTS  (BCM numbering — change to match your wiring)
# ──────────────────────────────────────────────────────────────────────────────

# ── Tier 1 — Field inputs
PIN_BTN_START  = 17   # Heavy-duty momentary push button
PIN_BTN_STOP   = 27   # Heavy-duty momentary push button
PIN_BTN_RESET  = 22   # Heavy-duty momentary push button

# ── Tier 1 — Status LEDs
PIN_LED_POWER  = 5    # Green — always on when Pi is running
PIN_LED_RUN    = 6    # Blue — blinks when sorting is active
PIN_LED_WARN   = 13   # Amber — high temp / low confidence alert
PIN_LED_BINFULL = 19  # Red — solenoid bin sensor full

# ── Tier 2 — Storage-side controls
PIN_ROTARY_CLK  = 23   # Rotary encoder CLK
PIN_ROTARY_DT   = 24   # Rotary encoder DT
PIN_ROTARY_SW   = 25   # Rotary encoder push switch (not used here but wired)
PIN_SPEED_SW    = 12   # SPDT speed toggle — HIGH pin reads HIGH/LOW
PIN_BTN_PURGE   = 16   # Quick purge button
PIN_BTN_SAVE    = 20   # Batch log save button

# ── Solenoid gates (one per bin, NPN transistor driver or relay)
PIN_SOL_LARGE   = 26   # Bin A — Large (>75mm)
PIN_SOL_MEDIUM  = 21   # Bin B — Medium (50-75mm)
PIN_SOL_SMALL   = 7    # Bin C — Small (<50mm)
PIN_SOL_REJECT  = 8    # Bin D — Reject / Blight

# ── Solenoid fire duration (ms) — adjust for your pneumatic valve
SOLENOID_PULSE_MS = 120

SOLENOID_MAP = {
    "large":  PIN_SOL_LARGE,
    "medium": PIN_SOL_MEDIUM,
    "small":  PIN_SOL_SMALL,
    "reject": PIN_SOL_REJECT,
}


class GPIOManager:
    """
    Manages all GPIO hardware.  Callbacks are fired in the GPIO event thread;
    they must be lightweight — delegate heavy work to the sorter state.
    """

    def __init__(self):
        self._setup_done = False
        self._sol_lock = threading.Lock()   # Prevent solenoid races
        self._led_run_blinking = False
        self._led_run_thread: Optional[threading.Thread] = None

        # Rotary encoder state
        self._rotary_clk_last = None
        # FIX (menu gap): a plain "clk changed" edge detector can't tell
        # a real detent turn from contact bounce, and never distinguished
        # CW from CCW reliably. A minimal 2-bit state table (this
        # transition sequence is standard for cheap KY-040 style
        # encoders) debounces AND gives a clean +1/-1 direction per
        # detent. `_rotary_seq` accumulates transitions; a full detent
        # is 4 valid steps.
        self._rotary_seq = 0
        # Valid (old_state<<2 | new_state) transitions: +1 = CW, -1 = CCW, 0 = bounce/invalid
        self._ROTARY_TRANSITION_TABLE = {
            0b0001: -1, 0b0010: 1, 0b0100: 1, 0b0111: -1,
            0b1000: -1, 0b1011: 1, 0b1101: 1, 0b1110: -1,
        }
        self._rotary_state_last = 0b00

        # External callbacks — set by app.py after construction
        self.on_start:  Optional[Callable] = None
        self.on_stop:   Optional[Callable] = None
        self.on_reset:  Optional[Callable] = None
        self.on_purge:  Optional[Callable] = None
        self.on_save:   Optional[Callable] = None
        self.on_speed_changed: Optional[Callable[[str], None]] = None
        # NEW: Tier-2 LCD menu navigation (see shared_state.rotary_rotate/press)
        self.on_rotary_rotate: Optional[Callable[[int], None]] = None   # direction: +1 CW, -1 CCW
        self.on_rotary_press:  Optional[Callable[[], None]] = None

    # ─────────────────────────────────────────────────────────── Setup / Teardown

    def setup(self):
        if not GPIO_AVAILABLE:
            logger.warning("GPIO setup skipped — stub mode")
            return
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        # ── Inputs with pull-ups (buttons are active-LOW — connect to GND when pressed)
        for pin in (PIN_BTN_START, PIN_BTN_STOP, PIN_BTN_RESET,
                    PIN_BTN_PURGE, PIN_BTN_SAVE,
                    PIN_ROTARY_CLK, PIN_ROTARY_DT, PIN_ROTARY_SW):
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        # ── Speed toggle — SPDT, so we just read HIGH/LOW; no pull-up needed
        GPIO.setup(PIN_SPEED_SW, GPIO.IN)

        # ── Outputs
        for pin in (PIN_LED_POWER, PIN_LED_RUN, PIN_LED_WARN, PIN_LED_BINFULL,
                    PIN_SOL_LARGE, PIN_SOL_MEDIUM, PIN_SOL_SMALL, PIN_SOL_REJECT):
            GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)

        # Power LED always on
        GPIO.output(PIN_LED_POWER, GPIO.HIGH)

        # ── Event detection (falling edge = button pressed)
        GPIO.add_event_detect(PIN_BTN_START,  GPIO.FALLING, callback=self._cb_start,  bouncetime=300)
        GPIO.add_event_detect(PIN_BTN_STOP,   GPIO.FALLING, callback=self._cb_stop,   bouncetime=300)
        GPIO.add_event_detect(PIN_BTN_RESET,  GPIO.FALLING, callback=self._cb_reset,  bouncetime=300)
        GPIO.add_event_detect(PIN_BTN_PURGE,  GPIO.FALLING, callback=self._cb_purge,  bouncetime=200)
        GPIO.add_event_detect(PIN_BTN_SAVE,   GPIO.FALLING, callback=self._cb_save,   bouncetime=500)
        GPIO.add_event_detect(PIN_ROTARY_CLK, GPIO.BOTH,    callback=self._cb_rotary)
        GPIO.add_event_detect(PIN_ROTARY_DT,  GPIO.BOTH,    callback=self._cb_rotary)
        # FIX: PIN_ROTARY_SW was wired and set up as an input but never had
        # an event handler — the encoder's push-switch did nothing. Now it
        # drives Tier-2 LCD menu navigation (see on_rotary_press).
        GPIO.add_event_detect(PIN_ROTARY_SW,  GPIO.FALLING, callback=self._cb_rotary_press, bouncetime=250)
        GPIO.add_event_detect(PIN_SPEED_SW,   GPIO.BOTH,    callback=self._cb_speed,  bouncetime=100)

        self._setup_done = True
        logger.info("GPIO setup complete — all pins configured")

    def cleanup(self):
        self._led_run_blinking = False
        if GPIO_AVAILABLE and self._setup_done:
            # All outputs LOW before cleanup
            for pin in (PIN_LED_POWER, PIN_LED_RUN, PIN_LED_WARN, PIN_LED_BINFULL,
                        PIN_SOL_LARGE, PIN_SOL_MEDIUM, PIN_SOL_SMALL, PIN_SOL_REJECT):
                GPIO.output(pin, GPIO.LOW)
            GPIO.cleanup()
        logger.info("GPIO cleaned up")

    # ─────────────────────────────────────────────────────────── Button callbacks

    def _cb_start(self, channel):
        logger.debug("HW BTN: START")
        if self.on_start:
            self.on_start()

    def _cb_stop(self, channel):
        logger.debug("HW BTN: STOP")
        if self.on_stop:
            self.on_stop()

    def _cb_reset(self, channel):
        logger.debug("HW BTN: RESET")
        if self.on_reset:
            self.on_reset()

    def _cb_purge(self, channel):
        logger.debug("HW BTN: PURGE")
        if self.on_purge:
            self.on_purge()

    def _cb_save(self, channel):
        logger.debug("HW BTN: SAVE")
        if self.on_save:
            self.on_save()

    def _cb_speed(self, channel):
        if not GPIO_AVAILABLE:
            return
        speed = "HIGH" if GPIO.input(PIN_SPEED_SW) == GPIO.HIGH else "LOW"
        logger.debug(f"HW SPEED TOGGLE: {speed}")
        if self.on_speed_changed:
            self.on_speed_changed(speed)

    def _cb_rotary(self, channel):
        """
        Quadrature decoder for the rotary encoder (fires on EITHER CLK or
        DT changing). Drives Tier-2 LCD menu navigation via
        on_rotary_rotate(+1 / -1) — see shared_state.rotary_rotate().

        FIX: the old version only looked at CLK edges and guessed
        direction from a single DT read at that instant, which is a
        classic source of missed/duplicate/backwards steps on contact
        bounce. This uses the standard 2-bit gray-code state table: every
        (old_state, new_state) pair maps to a fixed +1/-1/invalid, so
        noise is ignored and a whole detent reliably yields ONE call to
        on_rotary_rotate.
        """
        if not GPIO_AVAILABLE:
            return
        clk = GPIO.input(PIN_ROTARY_CLK)
        dt  = GPIO.input(PIN_ROTARY_DT)
        new_state = (clk << 1) | dt

        transition = (self._rotary_state_last << 2) | new_state
        step = self._ROTARY_TRANSITION_TABLE.get(transition, 0)
        self._rotary_state_last = new_state

        if step == 0:
            return  # bounce / half-step / not a valid transition

        self._rotary_seq += step
        # 4 valid quarter-steps = 1 physical detent click on most KY-040 modules
        if abs(self._rotary_seq) >= 4:
            direction = 1 if self._rotary_seq > 0 else -1
            self._rotary_seq = 0
            logger.debug(f"Rotary: {'CW' if direction > 0 else 'CCW'}")
            if self.on_rotary_rotate:
                self.on_rotary_rotate(direction)

    def _cb_rotary_press(self, channel):
        logger.debug("HW BTN: ROTARY PRESS")
        if self.on_rotary_press:
            self.on_rotary_press()

    # ─────────────────────────────────────────────────────────── Solenoid

    def fire_solenoid(self, category: str):
        """
        Fires the solenoid gate for the given category.
        Runs in a thread so it doesn't block the vision worker.
        """
        if category not in SOLENOID_MAP:
            return
        pin = SOLENOID_MAP[category]
        t = threading.Thread(target=self._pulse_solenoid, args=(pin,), daemon=True)
        t.start()

    def _pulse_solenoid(self, pin: int):
        with self._sol_lock:
            if GPIO_AVAILABLE:
                GPIO.output(pin, GPIO.HIGH)
                time.sleep(SOLENOID_PULSE_MS / 1000)
                GPIO.output(pin, GPIO.LOW)
            else:
                # Stub: just sleep for the pulse duration
                time.sleep(SOLENOID_PULSE_MS / 1000)
                logger.debug(f"[STUB] Solenoid pulse on pin {pin}")

    # ─────────────────────────────────────────────────────────── LEDs

    def set_led(self, led: str, state: bool):
        pin_map = {
            "power": PIN_LED_POWER,
            "run":   PIN_LED_RUN,
            "warn":  PIN_LED_WARN,
            "full":  PIN_LED_BINFULL,
        }
        if led not in pin_map:
            return
        if GPIO_AVAILABLE:
            GPIO.output(pin_map[led], GPIO.HIGH if state else GPIO.LOW)

    def blink_run_led(self, enable: bool, interval: float = 0.5):
        """Start or stop the RUN LED blink pattern."""
        self._led_run_blinking = enable
        if enable and (self._led_run_thread is None or not self._led_run_thread.is_alive()):
            self._led_run_thread = threading.Thread(
                target=self._blink_loop, args=(interval,), daemon=True
            )
            self._led_run_thread.start()
        elif not enable:
            self.set_led("run", False)

    def _blink_loop(self, interval: float):
        state = False
        while self._led_run_blinking:
            state = not state
            self.set_led("run", state)
            time.sleep(interval)
        self.set_led("run", False)

    # ─────────────────────────────────────────────────────────── Speed read

    def read_speed_switch(self) -> str:
        """Poll the physical speed toggle switch (for initial state read on startup)."""
        if not GPIO_AVAILABLE:
            return "HIGH"
        return "HIGH" if GPIO.input(PIN_SPEED_SW) == GPIO.HIGH else "LOW"
