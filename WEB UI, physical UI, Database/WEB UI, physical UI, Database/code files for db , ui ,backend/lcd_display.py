"""
lcd_display.py — 20x4 character LCD driver for PotatoSort AI Tier-2 interface

REPLACES the earlier oled_display.py. The Tier-2 hardware spec changed from
a 128x64 pixel-graphics SSD1306 OLED (driven via luma.oled + PIL, one pixel
at a time) to a 20-column x 4-row HD44780-compatible CHARACTER LCD, wired
through a PCF8574 I2C backpack. This is a different display paradigm —
you write fixed-width text into 4 addressable rows, there is no pixel
canvas — so the driver library and all rendering logic below are new.

Wiring (Raspberry Pi 5), same I2C bus as before:
  LCD VCC  → 5V    (Pin 2)   -- most 20x4 backpacks want 5V, not 3.3V
  LCD GND  → GND   (Pin 6)
  LCD SDA  → GPIO2 (Pin 3, I2C SDA)
  LCD SCL  → GPIO3 (Pin 5, I2C SCL)

Enable I2C: sudo raspi-config -> Interface Options -> I2C -> Enable
Find the backpack's address (commonly 0x27 or 0x3F): i2cdetect -y 1

Library: RPLCD (`pip install RPLCD`), using its I2C CharLCD backend.
"""

import threading
import time
import logging

from shared_state import sorter_state

logger = logging.getLogger(__name__)

# ── Try importing the hardware library; degrade gracefully on dev machines
try:
    from RPLCD.i2c import CharLCD
    RPLCD_AVAILABLE = True
except ImportError:
    RPLCD_AVAILABLE = False
    logger.warning("RPLCD not installed — LCD disabled (OK on dev machines)")

LCD_I2C_ADDRESS = 0x27   # Most common PCF8574 backpack address (alt: 0x3F)
LCD_COLS = 20
LCD_ROWS = 4


def _fit(text: str, width: int = LCD_COLS) -> str:
    """Truncate or right-pad `text` to exactly `width` characters."""
    return text[:width].ljust(width)


class LCDDisplay:
    """
    Drives the 20x4 character LCD for Tier-2 (cold-storage) use.
    Updated from SharedState via update() called by app.py on every state
    change. Runs a refresh thread at ~2 Hz so the live screen (Line 1-4
    below) stays current; alternate menu screens (calibration / batch
    summary / log confirm) are selected by sorter_state.display_mode and
    take over the same 4 rows while active.
    """

    def __init__(self):
        self._device = None
        self._lock = threading.Lock()
        self._latest_snap: dict = {}
        self._thread: threading.Thread | None = None
        self._running = False

        if RPLCD_AVAILABLE:
            try:
                self._device = CharLCD(
                    i2c_expander="PCF8574",
                    address=LCD_I2C_ADDRESS,
                    port=1,
                    cols=LCD_COLS,
                    rows=LCD_ROWS,
                    dotsize=8,
                )
                logger.info(f"LCD 20x4 initialised at {hex(LCD_I2C_ADDRESS)}")
            except Exception as e:
                logger.error(f"LCD init failed: {e}")

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._refresh_loop, daemon=True, name="LCD")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._device and RPLCD_AVAILABLE:
            try:
                self._device.clear()
            except Exception:
                pass

    def update(self, snap: dict):
        """
        Optional: force an immediate re-render from a snapshot the caller
        already has (used by app.py right after a button press, so the
        menu reacts instantly instead of waiting up to 0.5s for the next
        poll tick). Not required for correctness — see FIX note below.
        """
        with self._lock:
            self._latest_snap = snap
        if snap:
            self._render(self._build_lines(snap))

    # ─────────────────────────────────────────────────────────── Render loop

    def _refresh_loop(self):
        """
        FIX (live-update gap): the original OLED driver only ever
        re-rendered whatever snapshot app.py last pushed via update() —
        which app.py only called on start/stop/reset. That meant PASS/
        REJECT counts, bin percentages, and telemetry never actually
        moved on the physical display while a batch was running; the
        screen just kept redrawing the same stale numbers. This loop now
        pulls a FRESH snapshot from sorter_state itself every tick, so
        the LCD is always live regardless of whether anyone called
        update(). update() is kept only as an optional immediate-refresh
        helper for button presses (see above).
        """
        while self._running:
            snap = sorter_state.snapshot()
            lines = self._build_lines(snap)
            self._render(lines)
            time.sleep(0.5)  # 2 Hz

    # ─────────────────────────────────────────────────────────── Screen builders

    def _build_lines(self, snap: dict) -> list[str]:
        """Dispatch to the right 4-line screen builder for the current menu mode."""
        mode = snap.get("display_mode", "MAIN")
        if mode == "CALIBRATE_MEDIUM":
            return self._lines_calibrate(snap, "medium", "Small / Medium")
        if mode == "CALIBRATE_LARGE":
            return self._lines_calibrate(snap, "large", "Medium / Large")
        if mode == "BATCH_SUMMARY":
            return self._lines_summary(snap)
        if mode == "LOG_CONFIRM":
            return self._lines_log_confirm(snap)
        return self._lines_main(snap)

    def _lines_main(self, snap: dict) -> list[str]:
        """
        The real-time sorting view (4 lines), exactly per the Tier-2 spec:
          Line 1: Batch name & belt speed
          Line 2: Pass vs reject count
          Line 3: Small/Medium/Large bin percentages
          Line 4: Environmental temp/humidity & system status
        """
        counts = snap.get("counts", {})
        bid = snap.get("batch_id") or "NONE"
        batch_short = self._short_batch_label(bid)
        speed_mps = snap.get("belt_speed_mps", 0.0)

        total = counts.get("total", 0)
        passed = counts.get("large", 0) + counts.get("medium", 0) + counts.get("small", 0)
        reject = counts.get("reject", 0)

        pct_s = (counts.get("small", 0) / total * 100) if total else 0.0
        pct_m = (counts.get("medium", 0) / total * 100) if total else 0.0
        pct_l = (counts.get("large", 0) / total * 100) if total else 0.0

        env = snap.get("telemetry", {})
        temp_c = env.get("env_temp_c", 0.0)
        hum_pct = env.get("env_humidity_pct", 0.0)
        status = snap.get("system_status", "STOP")

        line1 = f"B:{batch_short:<8} V:{speed_mps:.2f}ms"
        line2 = f"PASS:{passed:04d}  REJ:{reject:04d}"
        line3 = f"S:{pct_s:.0f}% M:{pct_m:.0f}% L:{pct_l:.0f}%"
        line4 = f"{temp_c:.1f}C {hum_pct:.0f}%H  [{status}]"
        return [_fit(line1), _fit(line2), _fit(line3), _fit(line4)]

    def _lines_calibrate(self, snap: dict, boundary: str, label: str) -> list[str]:
        thresholds = snap.get("size_thresholds_mm", {})
        value_mm = thresholds.get(boundary, 0.0)
        return [
            _fit("CALIBRATE THRESHOLD"),
            _fit(f"{label} bound."),
            _fit(f"Value: {value_mm:.0f} mm"),
            _fit("Turn=adjust Push=next"),
        ]

    def _lines_summary(self, snap: dict) -> list[str]:
        weight_kg = snap.get("estimated_weight_kg", 0.0)
        elapsed_s = snap.get("elapsed_s", 0)
        h, rem = divmod(int(elapsed_s), 3600)
        m, s = divmod(rem, 60)
        return [
            _fit("BATCH SUMMARY"),
            _fit(f"Weight: {weight_kg:.1f} kg"),
            _fit(f"Runtime: {h:02d}:{m:02d}:{s:02d}"),
            _fit("Push=back to menu"),
        ]

    def _lines_log_confirm(self, snap: dict) -> list[str]:
        selected = snap.get("log_confirm_selected", "NO")
        yes = "[YES]" if selected == "YES" else " YES "
        no = "[NO]" if selected == "NO" else " NO "
        return [
            _fit("Save Batch to DB?"),
            _fit(f"   {yes}    {no}"),
            _fit("Turn=select"),
            _fit("Push=confirm"),
        ]

    @staticmethod
    def _short_batch_label(batch_id: str) -> str:
        """
        Batch IDs look like 'BTH-260921-A1B2'; Line 1 only has 8 chars to
        spare after 'B:'. Show the day-sequence-ish tail so it stays
        recognisable without overflowing the 20-col line.
        """
        if not batch_id or batch_id == "NONE":
            return "NONE"
        parts = batch_id.split("-")
        return "-".join(parts[1:])[:8] if len(parts) > 1 else batch_id[:8]

    # ─────────────────────────────────────────────────────────── Physical render

    def _render(self, lines: list[str]):
        if not RPLCD_AVAILABLE or not self._device:
            self._render_stub(lines)
            return
        try:
            for row, text in enumerate(lines):
                self._device.cursor_pos = (row, 0)
                self._device.write_string(text)
        except Exception as e:
            logger.error(f"LCD render error: {e}")

    def _render_stub(self, lines: list[str]):
        """Console render for dev machines without LCD hardware."""
        border = "+" + "-" * LCD_COLS + "+"
        print(border)
        for line in lines:
            print(f"|{line}|")
        print(border)
