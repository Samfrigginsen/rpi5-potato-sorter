"""
shared_state.py — Thread-safe shared state for PotatoSort AI
Bridges GPIO hardware controls and Flask Web UI with a single source of truth.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SortCounts:
    large: int = 0
    medium: int = 0
    small: int = 0
    reject: int = 0

    @property
    def total(self) -> int:
        return self.large + self.medium + self.small + self.reject

    def as_dict(self) -> dict:
        return {
            "large": self.large,
            "medium": self.medium,
            "small": self.small,
            "reject": self.reject,
            "total": self.total,
        }

    def reset(self):
        self.large = self.medium = self.small = self.reject = 0


@dataclass
class Telemetry:
    cpu_percent: float = 0.0
    cpu_temp_c: float = 0.0
    inference_ms: float = 0.0
    fps: float = 0.0
    gpio_ok: bool = True
    db_ok: bool = True
    # ── Environmental sensor readings (Tier-2 cold-storage panel).
    # Populated by a real DHT22/SHT31-style sensor once wired up; until
    # then these stay at their default so the LCD still has something
    # sane to show instead of crashing on a missing reading.
    env_temp_c: float = 0.0
    env_humidity_pct: float = 0.0


# ── NEW: Tier-2 20x4 character-LCD menu screens, reachable via the
# rotary encoder's push-switch (PIN_ROTARY_SW). See gpio_manager.py for
# how rotation/press map onto these, and lcd_display.py for how each
# screen is actually rendered.
DISPLAY_MAIN               = "MAIN"
DISPLAY_CALIBRATE_MEDIUM   = "CALIBRATE_MEDIUM"   # Small/Medium size boundary
DISPLAY_CALIBRATE_LARGE    = "CALIBRATE_LARGE"    # Medium/Large size boundary
DISPLAY_BATCH_SUMMARY      = "BATCH_SUMMARY"
DISPLAY_LOG_CONFIRM        = "LOG_CONFIRM"

# Order the push-switch cycles through (LOG_CONFIRM's push instead
# executes the highlighted choice — see rotary_press() below).
_DISPLAY_MODE_CYCLE = [
    DISPLAY_MAIN,
    DISPLAY_CALIBRATE_MEDIUM,
    DISPLAY_CALIBRATE_LARGE,
    DISPLAY_BATCH_SUMMARY,
    DISPLAY_LOG_CONFIRM,
]

# ── Approximate average weight (kg) per potato in each bin — used only
# for the Batch Summary screen's "Estimated Total Weight" figure. Adjust
# these to match your local potato variety / the real average you weigh.
AVG_WEIGHT_KG = {"large": 0.28, "medium": 0.15, "small": 0.06, "reject": 0.10}

# ── Belt-speed presets shown on Line 1 of the LCD (m/s). PURGE_SPEED_MPS
# is the temporary speed used while a Quick Purge is active.
BELT_SPEED_HIGH_MPS = 0.40
BELT_SPEED_LOW_MPS  = 0.15
BELT_SPEED_PURGE_MPS = 0.65
PURGE_DURATION_S = 5.0  # how long a purge request boosts belt speed for


class SharedState:
    """
    Central state object accessed by all subsystems.
    Uses a reentrant lock so the same thread can acquire it multiple times
    (e.g., a callback that calls a helper that also reads state).
    """

    # ── System modes
    MODE_IDLE = "IDLE"
    MODE_RUNNING = "RUNNING"
    MODE_PAUSED = "PAUSED"
    MODE_ERROR = "ERROR"

    # ── Speed modes
    SPEED_LOW = "LOW"
    SPEED_HIGH = "HIGH"

    # ── Category labels (must match YOLO class names)
    CATEGORIES = ["large", "medium", "small", "reject"]

    def __init__(self):
        self._lock = threading.RLock()

        # ── Core state
        self._mode: str = self.MODE_IDLE
        self._speed: str = self.SPEED_HIGH
        self._batch_id: Optional[str] = None
        self._batch_start_ts: Optional[float] = None

        # ── Counts (in-memory, flushed to DB on stop/periodic)
        self._counts = SortCounts()

        # ── Telemetry
        self.telemetry = Telemetry()

        # ── LED / peripheral state (written by hardware, read by Flask)
        self._led_power: bool = True
        self._led_run: bool = False
        self._led_warn: bool = False
        self._led_bin_full: bool = False

        # ── Solenoid state (set momentarily per detection)
        self._active_solenoid: Optional[str] = None

        # ── Event log ring buffer (max 200 entries)
        self._events: list[dict] = []
        self._MAX_EVENTS = 200

        # ── Throughput history (last 10 one-minute windows)
        self._throughput_history: list[int] = []
        self._last_minute_count: int = 0

        # ── Purge flag (set by Tier-2 button or UI, cleared by sorter loop)
        self._purge_requested: bool = False
        # FIX: previously request_purge() just set this flag and NOTHING
        # ever consumed it — Quick Purge did nothing physically. Now a
        # purge also stamps an expiry time, and belt_speed_mps / the LCD's
        # [PURGE] status read off `_purge_active` until it lapses.
        self._purge_active: bool = False
        self._purge_until_ts: Optional[float] = None

        # ── NEW: mutable size-classification thresholds (mm). These used
        # to be hardcoded constants inside vision_worker.py, which is why
        # the rotary encoder's "calibration" feature had nothing to
        # actually adjust. Now vision_worker reads these live off
        # sorter_state on every frame.
        self._size_threshold_medium_mm: float = 50.0   # Small/Medium boundary
        self._size_threshold_large_mm: float = 75.0    # Medium/Large boundary

        # ── NEW: Tier-2 LCD menu state (see DISPLAY_* constants above)
        self._display_mode: str = DISPLAY_MAIN
        self._log_confirm_selected: str = "NO"  # toggled by rotating on the LOG_CONFIRM screen

    # ─────────────────────────────────────────────────────────────── Accessors

    @property
    def mode(self) -> str:
        with self._lock:
            return self._mode

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._mode == self.MODE_RUNNING

    @property
    def speed(self) -> str:
        with self._lock:
            return self._speed

    @property
    def batch_id(self) -> Optional[str]:
        with self._lock:
            return self._batch_id

    @property
    def counts(self) -> SortCounts:
        """Returns a snapshot copy — safe to read without holding the lock."""
        with self._lock:
            snap = SortCounts(
                large=self._counts.large,
                medium=self._counts.medium,
                small=self._counts.small,
                reject=self._counts.reject,
            )
        return snap

    @property
    def elapsed_seconds(self) -> float:
        with self._lock:
            if self._batch_start_ts is None:
                return 0.0
            return time.time() - self._batch_start_ts

    @property
    def purge_requested(self) -> bool:
        with self._lock:
            return self._purge_requested

    @property
    def purge_active(self) -> bool:
        with self._lock:
            return self._purge_active

    @property
    def size_threshold_medium_mm(self) -> float:
        """Small/Medium boundary (mm) — read live by vision_worker each frame."""
        with self._lock:
            return self._size_threshold_medium_mm

    @property
    def size_threshold_large_mm(self) -> float:
        """Medium/Large boundary (mm) — read live by vision_worker each frame."""
        with self._lock:
            return self._size_threshold_large_mm

    @property
    def display_mode(self) -> str:
        with self._lock:
            return self._display_mode

    @property
    def log_confirm_selected(self) -> str:
        with self._lock:
            return self._log_confirm_selected

    @property
    def belt_speed_mps(self) -> float:
        """
        Numeric belt speed (m/s) for the LCD's "V:0.40ms" field.
        While a purge is active this reports the boosted purge speed
        regardless of the HIGH/LOW toggle position.
        """
        with self._lock:
            if self._purge_active:
                return BELT_SPEED_PURGE_MPS
            return BELT_SPEED_HIGH_MPS if self._speed == self.SPEED_HIGH else BELT_SPEED_LOW_MPS

    @property
    def system_status(self) -> str:
        """
        One-word status for the LCD's Line 4 — [RUN] / [STOP] / [PURGE] / [WARN].
        Priority: an active purge or a warning condition is more urgent
        than the plain running/stopped state, so those are checked first.
        """
        with self._lock:
            if self._purge_active:
                return "PURGE"
            if self._led_warn:
                return "WARN"
            return "RUN" if self._mode == self.MODE_RUNNING else "STOP"

    @property
    def estimated_weight_kg(self) -> float:
        """Rough total weight of everything counted so far, for the Batch Summary screen."""
        with self._lock:
            c = self._counts
            return (
                c.large * AVG_WEIGHT_KG["large"]
                + c.medium * AVG_WEIGHT_KG["medium"]
                + c.small * AVG_WEIGHT_KG["small"]
                + c.reject * AVG_WEIGHT_KG["reject"]
            )

    # ─────────────────────────────────────────────────────────────── Commands

    def start(self, batch_id: str):
        with self._lock:
            self._mode = self.MODE_RUNNING
            self._batch_id = batch_id
            self._batch_start_ts = time.time()
            self._counts.reset()
            self._throughput_history.clear()
            self._last_minute_count = 0
            self._led_run = True
            self._led_warn = False
            self.log_event("SYS", f"Batch {batch_id} started · speed={self._speed}")

    def stop(self):
        with self._lock:
            self._mode = self.MODE_IDLE
            self._led_run = False
            total = self._counts.total
            self.log_event("SYS", f"Batch stopped · total={total}")

    def reset(self):
        with self._lock:
            self._mode = self.MODE_IDLE
            self._counts.reset()
            self._batch_id = None
            self._batch_start_ts = None
            self._led_run = False
            self._led_warn = False
            self._led_bin_full = False
            self._throughput_history.clear()
            self.log_event("SYS", "System reset · counters cleared")

    def set_speed(self, speed: str):
        with self._lock:
            if speed not in (self.SPEED_LOW, self.SPEED_HIGH):
                raise ValueError(f"Unknown speed: {speed}")
            self._speed = speed
            if self._mode == self.MODE_RUNNING:
                self.log_event("SYS", f"Speed changed to {speed}")

    def increment(self, category: str, confidence: float = 0.0, size_mm: float = 0.0):
        """Called by the vision worker for each detected potato."""
        with self._lock:
            if category == "large":
                self._counts.large += 1
            elif category == "medium":
                self._counts.medium += 1
            elif category == "small":
                self._counts.small += 1
            else:
                self._counts.reject += 1
            self._active_solenoid = category
            self.log_event(
                category.upper(),
                f"conf={confidence:.2f} · size≈{size_mm:.0f}mm",
            )

    def clear_solenoid(self):
        with self._lock:
            self._active_solenoid = None

    def set_led(self, name: str, value: bool):
        with self._lock:
            if name == "power":
                self._led_power = value
            elif name == "run":
                self._led_run = value
            elif name == "warn":
                self._led_warn = value
            elif name == "bin_full":
                self._led_bin_full = value

    def request_purge(self):
        """
        FIX: this used to only set `_purge_requested` — nothing ever read
        it, so pressing Quick Purge had no physical effect. Now it also
        activates `_purge_active` for PURGE_DURATION_S seconds; while
        active, belt_speed_mps reports the boosted purge speed and the
        LCD's status line shows [PURGE]. Call check_purge_expiry()
        periodically (telemetry_monitor's 1Hz loop does this) to end it.
        """
        with self._lock:
            self._purge_requested = True
            self._purge_active = True
            self._purge_until_ts = time.time() + PURGE_DURATION_S
            self.log_event("SYS", f"Belt purge requested — boosted speed for {PURGE_DURATION_S:.0f}s")

    def check_purge_expiry(self):
        """Call periodically (e.g. once a second) to end an expired purge."""
        with self._lock:
            if self._purge_active and self._purge_until_ts is not None:
                if time.time() >= self._purge_until_ts:
                    self._purge_active = False
                    self._purge_requested = False
                    self._purge_until_ts = None
                    self.log_event("SYS", "Purge complete — belt speed restored")

    def clear_purge(self):
        with self._lock:
            self._purge_requested = False
            self._purge_active = False
            self._purge_until_ts = None

    # ─────────────────────────────────────────────────────── Tier-2 LCD menu

    def set_size_threshold(self, boundary: str, mm: float):
        """
        boundary: "medium" (Small/Medium line) or "large" (Medium/Large line).
        Called from the CALIBRATE_* screens as the operator turns the
        rotary encoder. Clamped to a sane range and kept at least 5mm
        apart so the two boundaries can never cross/invert.
        """
        with self._lock:
            mm = max(10.0, min(150.0, mm))
            if boundary == "medium":
                mm = min(mm, self._size_threshold_large_mm - 5.0)
                self._size_threshold_medium_mm = mm
            elif boundary == "large":
                mm = max(mm, self._size_threshold_medium_mm + 5.0)
                self._size_threshold_large_mm = mm
            self.log_event("CAL", f"{boundary} threshold set to {mm:.0f}mm")

    def rotary_rotate(self, direction: int):
        """
        direction: +1 (CW) or -1 (CCW). What this does depends on the
        CURRENT screen — see DISPLAY_* constants:
          MAIN / BATCH_SUMMARY  → no-op (nothing to adjust there)
          CALIBRATE_MEDIUM/LARGE → nudge that threshold by 1mm
          LOG_CONFIRM            → toggle the YES/NO selection
        """
        with self._lock:
            if self._display_mode == DISPLAY_CALIBRATE_MEDIUM:
                self.set_size_threshold("medium", self._size_threshold_medium_mm + direction)
            elif self._display_mode == DISPLAY_CALIBRATE_LARGE:
                self.set_size_threshold("large", self._size_threshold_large_mm + direction)
            elif self._display_mode == DISPLAY_LOG_CONFIRM:
                self._log_confirm_selected = "YES" if self._log_confirm_selected == "NO" else "NO"

    def rotary_press(self) -> Optional[str]:
        """
        Short-press the encoder's push-switch. Returns an action string
        for app.py to act on ("SAVE_CONFIRMED"), or None if the press
        just navigated the menu.
          - On LOG_CONFIRM: executes the highlighted choice. YES returns
            "SAVE_CONFIRMED" (app.py should call _save_batch_to_db());
            NO just returns to the main screen.
          - Everywhere else: advances to the next screen in the cycle.
        """
        with self._lock:
            if self._display_mode == DISPLAY_LOG_CONFIRM:
                selected = self._log_confirm_selected
                self._display_mode = DISPLAY_MAIN
                self._log_confirm_selected = "NO"
                if selected == "YES":
                    self.log_event("SYS", "Batch save confirmed via LCD menu")
                    return "SAVE_CONFIRMED"
                self.log_event("SYS", "Batch save cancelled via LCD menu")
                return None
            idx = _DISPLAY_MODE_CYCLE.index(self._display_mode)
            self._display_mode = _DISPLAY_MODE_CYCLE[(idx + 1) % len(_DISPLAY_MODE_CYCLE)]
            return None

    def log_event(self, category: str, message: str):
        """Non-locking: caller must hold self._lock."""
        entry = {
            "ts": time.time(),
            "time": time.strftime("%H:%M:%S"),
            "category": category,
            "message": message,
        }
        self._events.append(entry)
        if len(self._events) > self._MAX_EVENTS:
            self._events.pop(0)

    def record_throughput_tick(self):
        """Call once per minute from a background thread."""
        with self._lock:
            current = self._counts.total
            rate = current - self._last_minute_count
            self._last_minute_count = current
            self._throughput_history.append(rate)
            if len(self._throughput_history) > 10:
                self._throughput_history.pop(0)

    # ─────────────────────────────────────────────────────────────── Snapshot

    def snapshot(self) -> dict:
        """Full state snapshot for SSE / API responses."""
        with self._lock:
            counts = self._counts.as_dict()
            total = counts["total"]
            reject_rate = (counts["reject"] / total * 100) if total else 0.0
            return {
                "mode": self._mode,
                "speed": self._speed,
                "batch_id": self._batch_id,
                "elapsed_s": round(time.time() - self._batch_start_ts, 1)
                if self._batch_start_ts
                else 0,
                "counts": counts,
                "reject_rate": round(reject_rate, 1),
                "leds": {
                    "power": self._led_power,
                    "run": self._led_run,
                    "warn": self._led_warn,
                    "bin_full": self._led_bin_full,
                },
                "active_solenoid": self._active_solenoid,
                "telemetry": {
                    "cpu_pct": round(self.telemetry.cpu_percent, 1),
                    "temp_c": round(self.telemetry.cpu_temp_c, 1),
                    "inference_ms": round(self.telemetry.inference_ms, 1),
                    "fps": round(self.telemetry.fps, 1),
                    "gpio_ok": self.telemetry.gpio_ok,
                    "db_ok": self.telemetry.db_ok,
                    # NEW: environmental readings for the Tier-2 LCD (Line 4)
                    "env_temp_c": round(self.telemetry.env_temp_c, 1),
                    "env_humidity_pct": round(self.telemetry.env_humidity_pct, 1),
                },
                "throughput_history": list(self._throughput_history),
                "events": list(self._events[-30:]),  # last 30 for SSE
                # NEW: everything the Tier-2 20x4 LCD / menu system needs
                "belt_speed_mps": round(self.belt_speed_mps, 2),
                "system_status": self.system_status,
                "purge_active": self._purge_active,
                "size_thresholds_mm": {
                    "medium": round(self._size_threshold_medium_mm, 1),
                    "large": round(self._size_threshold_large_mm, 1),
                },
                "display_mode": self._display_mode,
                "log_confirm_selected": self._log_confirm_selected,
                "estimated_weight_kg": round(self.estimated_weight_kg, 2),
            }


# Module-level singleton — imported everywhere
sorter_state = SharedState()
