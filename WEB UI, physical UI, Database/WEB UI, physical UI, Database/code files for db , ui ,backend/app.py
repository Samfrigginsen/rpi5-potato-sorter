"""
app.py — Flask Web UI and API server for PotatoSort AI
Runs on the Raspberry Pi 5 local network (0.0.0.0:5000).

Endpoints:
  GET  /                  → Serve dashboard HTML
  GET  /video_feed        → MJPEG camera stream
  POST /api/command       → {action: start|stop|reset|purge|save|speed}
  GET  /api/state         → Full JSON state snapshot
  GET  /api/state/stream  → Server-Sent Events for live UI updates
  GET  /api/history       → Last N batch summaries from SQLite
  POST /api/speed         → {speed: HIGH|LOW}
"""

import json
import time
import threading
import logging
import uuid
from datetime import datetime
from flask import Flask, Response, jsonify, request, send_from_directory

from shared_state import sorter_state
from gpio_manager import GPIOManager
from vision_worker import VisionWorker
from database import Database
# FIX: Tier-2 hardware changed from a 128x64 SSD1306 graphical OLED to a
# 20x4 character LCD — see lcd_display.py (replaces oled_display.py).
from lcd_display import LCDDisplay
from telemetry_monitor import TelemetryMonitor

# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["JSON_SORT_KEYS"] = False

# ── Subsystems
gpio   = GPIOManager()
vision = VisionWorker(gpio=gpio)
db     = Database("sorter.db")
lcd    = LCDDisplay()
telmon = TelemetryMonitor()

# ── FIX (bug #3): guide's own recommended "best practice" (RAM counter +
# periodic DB sync) was never actually implemented — only stop/manual-save
# wrote to SQLite. A power cut mid-batch used to lose the ENTIRE session's
# counts. This background thread saves the running batch to the DB every
# AUTO_SAVE_INTERVAL_S seconds, so at most that much data can ever be lost.
AUTO_SAVE_INTERVAL_S = 300  # 5 minutes, per guide Part 3
_autosave_thread: threading.Thread | None = None
_autosave_stop_event = threading.Event()


# ──────────────────────────────────────────────────────────────────────────────
#  STARTUP / SHUTDOWN
# ──────────────────────────────────────────────────────────────────────────────

def _wire_gpio_callbacks():
    """Connect GPIO hardware callbacks to shared state commands."""

    def _do_start():
        _execute_start()

    def _do_stop():
        _execute_stop()

    def _do_reset():
        _execute_reset()

    def _do_purge():
        sorter_state.request_purge()
        lcd.update(sorter_state.snapshot())

    def _do_save():
        _save_batch_to_db()

    def _do_speed(speed: str):
        sorter_state.set_speed(speed)

    def _do_rotary_rotate(direction: int):
        # See shared_state.rotary_rotate(): adjusts calibration threshold
        # or toggles YES/NO depending on the current LCD menu screen.
        sorter_state.rotary_rotate(direction)
        lcd.update(sorter_state.snapshot())

    def _do_rotary_press():
        # See shared_state.rotary_press(): advances the menu, or on the
        # LOG_CONFIRM screen executes the highlighted choice.
        action = sorter_state.rotary_press()
        if action == "SAVE_CONFIRMED":
            _save_batch_to_db()
        lcd.update(sorter_state.snapshot())

    gpio.on_start          = _do_start
    gpio.on_stop           = _do_stop
    gpio.on_reset          = _do_reset
    gpio.on_purge          = _do_purge
    gpio.on_save           = _do_save
    gpio.on_speed_changed  = _do_speed
    gpio.on_rotary_rotate  = _do_rotary_rotate
    gpio.on_rotary_press   = _do_rotary_press


def _autosave_loop():
    """
    Background thread: every AUTO_SAVE_INTERVAL_S seconds, if a batch is
    currently running, flush the in-memory counts to SQLite. save_batch()
    is idempotent (see database.py FIX for bug #2) — it only adds the
    DELTA since the last save, so calling it repeatedly here, and again
    later on Stop, is now safe and does not double-count.
    """
    logger.info(f"Auto-save loop started — every {AUTO_SAVE_INTERVAL_S}s while running")
    while not _autosave_stop_event.wait(AUTO_SAVE_INTERVAL_S):
        try:
            if sorter_state.is_running:
                _save_batch_to_db()
                logger.info("Auto-save: periodic snapshot written to DB")
        except Exception as e:
            logger.error(f"Auto-save error: {e}")


def startup():
    logger.info("PotatoSort AI — starting subsystems")
    db.init()
    gpio.setup()
    _wire_gpio_callbacks()
    # Read physical speed toggle on boot
    initial_speed = gpio.read_speed_switch()
    sorter_state.set_speed(initial_speed)
    vision.start()
    lcd.start()
    telmon.start()

    global _autosave_thread
    _autosave_stop_event.clear()
    _autosave_thread = threading.Thread(
        target=_autosave_loop, daemon=True, name="AutoSave"
    )
    _autosave_thread.start()

    logger.info("All subsystems running — Flask ready")


def shutdown():
    logger.info("Shutting down")
    _autosave_stop_event.set()
    if _autosave_thread:
        _autosave_thread.join(timeout=2)
    if sorter_state.is_running:
        _execute_stop()
    vision.stop()
    gpio.cleanup()
    lcd.stop()
    telmon.stop()


# ──────────────────────────────────────────────────────────────────────────────
#  CORE COMMAND HELPERS  (called by both GPIO callbacks and REST endpoints)
# ──────────────────────────────────────────────────────────────────────────────

def _make_batch_id() -> str:
    d = datetime.now()
    return f"BTH-{d.strftime('%y%m%d')}-{str(uuid.uuid4())[:4].upper()}"


def _execute_start():
    if sorter_state.is_running:
        return {"status": "already_running"}
    batch_id = _make_batch_id()
    sorter_state.start(batch_id)
    gpio.blink_run_led(True)
    gpio.set_led("warn", False)
    db.create_batch(batch_id, sorter_state.speed)
    lcd.update(sorter_state.snapshot())
    logger.info(f"Sorting started — {batch_id}")
    return {"status": "started", "batch_id": batch_id}


def _execute_stop():
    if not sorter_state.is_running:
        return {"status": "already_stopped"}
    sorter_state.stop()
    gpio.blink_run_led(False)
    _save_batch_to_db()
    lcd.update(sorter_state.snapshot())
    logger.info("Sorting stopped")
    return {"status": "stopped"}


def _execute_reset():
    sorter_state.reset()
    gpio.blink_run_led(False)
    gpio.set_led("warn", False)
    gpio.set_led("full", False)
    lcd.update(sorter_state.snapshot())
    return {"status": "reset"}


def _save_batch_to_db():
    snap = sorter_state.snapshot()
    if snap["batch_id"]:
        db.save_batch(
            batch_id    = snap["batch_id"],
            counts      = snap["counts"],
            duration_s  = snap["elapsed_s"],
            speed       = snap["speed"],
            reject_rate = snap["reject_rate"],
        )
        logger.info(f"Batch {snap['batch_id']} saved to DB")


# ──────────────────────────────────────────────────────────────────────────────
#  FLASK ROUTES
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the dashboard HTML (static or rendered template)."""
    return send_from_directory("static", "index.html")


@app.route("/video_feed")
def video_feed():
    """MJPEG camera stream — embed in <img src='/video_feed'>."""
    return Response(
        vision.generate_mjpeg(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/api/command", methods=["POST"])
def api_command():
    """
    Accepts:  { "action": "start" | "stop" | "reset" | "purge" | "save" }
    Returns:  { "status": "...", ... }
    """
    data = request.get_json(silent=True) or {}
    action = data.get("action", "").lower()

    if action == "start":
        result = _execute_start()
    elif action == "stop":
        result = _execute_stop()
    elif action == "reset":
        result = _execute_reset()
    elif action == "purge":
        sorter_state.request_purge()
        lcd.update(sorter_state.snapshot())
        result = {"status": "purge_requested"}
    elif action == "save":
        _save_batch_to_db()
        result = {"status": "saved", "batch_id": sorter_state.batch_id}
    else:
        return jsonify({"error": f"Unknown action: '{action}'"}), 400

    return jsonify(result)


@app.route("/api/speed", methods=["POST"])
def api_speed():
    data = request.get_json(silent=True) or {}
    speed = data.get("speed", "").upper()
    if speed not in ("HIGH", "LOW"):
        return jsonify({"error": "speed must be HIGH or LOW"}), 400
    sorter_state.set_speed(speed)
    return jsonify({"status": "ok", "speed": speed})


@app.route("/api/state")
def api_state():
    """Full state snapshot — polled by the Web UI every 2s as fallback."""
    return jsonify(sorter_state.snapshot())


@app.route("/api/state/stream")
def api_state_stream():
    """
    Server-Sent Events — Web UI subscribes to this for live updates.
    Each event is the full state JSON.
    """
    def _generate():
        try:
            while True:
                snap = sorter_state.snapshot()
                payload = json.dumps(snap)
                yield f"data: {payload}\n\n"
                time.sleep(0.5)   # 2 Hz update rate
        except GeneratorExit:
            pass

    return Response(
        _generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.route("/api/history")
def api_history():
    """Last N batches from SQLite."""
    n = min(int(request.args.get("n", 20)), 100)
    rows = db.get_recent_batches(n)
    return jsonify(rows)


@app.route("/api/health")
def api_health():
    return jsonify({
        "status": "ok",
        "ts": datetime.utcnow().isoformat() + "Z",
        "mode": sorter_state.mode,
    })


# ──────────────────────────────────────────────────────────────────────────────
#  ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    startup()
    try:
        app.run(
            host="0.0.0.0",
            port=5000,
            debug=False,       # Never True in production on Pi
            threaded=True,
            use_reloader=False,
        )
    finally:
        shutdown()
