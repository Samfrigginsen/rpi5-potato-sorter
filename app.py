"""
app.py — Flask Web Application for AI Potato Quality Sorter
Raspberry Pi 5 + IMX219 Camera + YOLOv8n-cls ONNX

Endpoints:
  GET  /                     → Dashboard HTML
  GET  /video_feed           → MJPEG camera stream
  GET  /api/status           → JSON system status snapshot
  POST /api/run-inspection   → Trigger full inspection cycle
  POST /api/motor/toggle     → Toggle DC motor on/off
  POST /api/servo/eject      → Trigger servo eject pulse
  GET  /api/health           → Health check

State Machine:
  IDLE → INSPECTING (motor on, capture 5 frames)
       → EJECTING   (motor off, inference, grade, serial TX, servo)
       → IDLE

A 10-second hard timeout resets to IDLE if any thread stalls.
"""

import sys
import os
import base64
import time
import threading
import logging
import json
from datetime import datetime

import cv2
import numpy as np
from flask import (
    Flask, Response, jsonify, render_template, request, send_from_directory
)

from hardware_controller import HardwareController
from serial_bridge import SerialBridge
from inference_engine import InferenceEngine

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ── Platform detection ────────────────────────────────────────────────────────
IS_PI = sys.platform.startswith("linux") and os.path.exists("/proc/device-tree/model")
logger.info(f"Platform: {'Raspberry Pi' if IS_PI else 'non-Pi (' + sys.platform + ')'}")

# ── picamera2 (IMX219 via libcamera) ─────────────────────────────────────────
PICAMERA_AVAILABLE = False
Picamera2 = None

if IS_PI:
    try:
        from picamera2 import Picamera2 as _Picam
        Picamera2 = _Picam
        PICAMERA_AVAILABLE = True
        logger.info("picamera2 loaded — IMX219 hardware camera mode")
    except Exception as _cam_err:
        logger.warning(f"picamera2 unavailable ({_cam_err}) — falling back to OpenCV/synthetic")

# ──────────────────────────────────────────────────────────────────────────────
#  Flask application
# ──────────────────────────────────────────────────────────────────────────────
app = Flask(
    __name__,
    static_folder="static",
    template_folder="templates",
)
app.config["JSON_SORT_KEYS"] = False

# ── Subsystems ────────────────────────────────────────────────────────────────
hw     = HardwareController()
serial = SerialBridge()
engine = InferenceEngine()

# ── Shared inspection state ────────────────────────────────────────────────────
INSPECTION_TIMEOUT_S = 10   # Hard ceiling; resets to IDLE on stall

_state_lock = threading.Lock()
_inspection_state = {
    "status":       "IDLE",   # IDLE | INSPECTING | EJECTING | ERROR
    "last_grade":   None,
    "last_result":  None,
    "session_count": 0,
    "grade_counts": {"A": 0, "B": 0, "C": 0},
    "started_at":   None,
    "finished_at":  None,
    "thumbnails":   [],       # list of base64-encoded JPEG strings
    "error":        None,
    "capture_span": 3.0,      # Duration over which to capture the 5 frames
}
_inspection_thread: threading.Thread | None = None

# ── Camera frame buffer ────────────────────────────────────────────────────────
_frame_lock      = threading.Lock()
_latest_frame:   bytes | None = None        # JPEG bytes for MJPEG stream
_camera_running  = threading.Event()
_camera_thread:  threading.Thread | None = None


# ══════════════════════════════════════════════════════════════════════════════
#  CAMERA SUBSYSTEM
# ══════════════════════════════════════════════════════════════════════════════

def _init_picamera2() -> "Picamera2 | None":
    """
    Initialise IMX219 via picamera2 at 640×480 Video configuration.
    Preserves the exact working initialisation pattern from the project.
    """
    try:
        cam = Picamera2()
        cfg = cam.create_video_configuration(
            main={"size": (640, 480), "format": "RGB888"}
        )
        cam.configure(cfg)
        cam.start()
        time.sleep(0.5)   # Allow auto-exposure to settle
        logger.info("picamera2 (IMX219) initialised at 640×480")
        return cam
    except Exception as e:
        logger.error(f"picamera2 init failed: {e}")
        return None


def _generate_synthetic_frame() -> np.ndarray:
    """Create an 640×480 synthetic BGR frame for demo/mock mode."""
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:] = (18, 15, 25)   # Dark background

    # Animated gradient
    t = time.time()
    for i in range(0, 640, 40):
        alpha = int(30 + 20 * abs(((t * 0.4 + i / 640) % 1) * 2 - 1))
        cv2.line(frame, (i, 0), (i, 480), (alpha, alpha + 10, alpha + 20), 1)

    # Fake potato ellipse
    cx = int(320 + 80 * np.sin(t * 0.5))
    cy = 240
    cv2.ellipse(frame, (cx, cy), (45, 30), t * 20 % 360, 0, 360, (30, 120, 200), -1)
    cv2.ellipse(frame, (cx, cy), (46, 31), 0, 0, 360, (60, 150, 230), 1)

    # Overlay text
    cv2.putText(frame, "SYNTHETIC FEED — No Camera",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 1)
    cv2.putText(frame, f"{datetime.now().strftime('%H:%M:%S')}",
                (10, 460), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (80, 80, 100), 1)
    return frame


def _camera_loop():
    """
    Background thread: continuously reads camera frames and stores the
    latest JPEG in the shared frame buffer for the MJPEG stream.
    """
    global _latest_frame

    cam = None
    cap = None

    if PICAMERA_AVAILABLE:
        cam = _init_picamera2()
    
    if cam is None:
        # Fallback: OpenCV VideoCapture
        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_FPS, 30)
            logger.info("Camera fallback: OpenCV VideoCapture(0) at 640×480")
        else:
            cap.release()
            cap = None
            logger.info("Camera fallback: synthetic frame generator (no physical camera)")

    _camera_running.set()

    try:
        while not _stop_event.is_set():
            frame_bgr = None

            if cam is not None:
                try:
                    # Exact picamera2 capture pattern (preserved from project)
                    rgb_array = cam.capture_array("main")
                    frame_bgr = cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)
                except Exception as e:
                    logger.error(f"picamera2 capture error: {e}")
                    frame_bgr = _generate_synthetic_frame()

            elif cap is not None:
                ret, frame_bgr = cap.read()
                if not ret:
                    frame_bgr = _generate_synthetic_frame()
            else:
                frame_bgr = _generate_synthetic_frame()
                time.sleep(0.033)   # ~30 FPS cap for synthetic frames

            if frame_bgr is not None:
                _, jpeg = cv2.imencode(".jpg", frame_bgr,
                                       [cv2.IMWRITE_JPEG_QUALITY, 80])
                with _frame_lock:
                    _latest_frame = jpeg.tobytes()

    finally:
        if cam is not None:
            try:
                cam.stop()
            except Exception:
                pass
        if cap is not None:
            cap.release()
        logger.info("Camera loop exited")


def _capture_frame_now(cam_ref=None) -> np.ndarray | None:
    """
    Capture a single frame for inspection (called by the inspection thread).
    Uses the most recent frame from the MJPEG buffer decoded back to BGR.
    This avoids re-initialising the camera object inside the inspection thread.
    """
    with _frame_lock:
        raw = _latest_frame

    if raw is None:
        logger.warning("capture_frame_now: no frame available")
        return None

    try:
        arr = np.frombuffer(raw, dtype=np.uint8)
        frame_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        return frame_bgr
    except Exception as e:
        logger.error(f"Frame decode error: {e}")
        return None


def _frame_to_b64(frame_bgr: np.ndarray) -> str:
    """Encode a BGR frame to a base64 JPEG data URI for the dashboard thumbnail gallery."""
    _, jpeg = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return "data:image/jpeg;base64," + base64.b64encode(jpeg.tobytes()).decode("ascii")


# ══════════════════════════════════════════════════════════════════════════════
#  INSPECTION STATE MACHINE
# ══════════════════════════════════════════════════════════════════════════════

_stop_event = threading.Event()


def _set_status(status: str, error: str | None = None):
    with _state_lock:
        _inspection_state["status"] = status
        if error is not None:
            _inspection_state["error"] = error
        logger.info(f"Inspection status → {status}" + (f" [{error}]" if error else ""))


def _inspection_cycle():
    """
    Full inspection cycle executed in a background thread:
      1. Motor ON  (GPIO 17 HIGH)
      2. Capture 5 frames over 3 seconds
      3. Motor OFF (GPIO 17 LOW)
      4. ONNX inference on all 5 frames
      5. Aggregate grade (A / B / C)
      6. Transmit grade byte over serial to ESP32
      7. Servo eject (0° → 90° → 0°)
      8. Emit JSON result / reset to IDLE

    Hard timeout: if the cycle takes > INSPECTION_TIMEOUT_S seconds,
    the state is forcibly reset to IDLE.
    """
    cycle_start = time.monotonic()

    def _check_timeout():
        if (time.monotonic() - cycle_start) > INSPECTION_TIMEOUT_S:
            logger.error("Inspection cycle TIMEOUT — forcing IDLE reset")
            hw.motor_off()
            _set_status("IDLE", error="timeout")
            return True
        return False

    try:
        # ── 1. INSPECTING — motor on ──────────────────────────────────────────
        _set_status("INSPECTING")
        hw.motor_on()

        # ── 2. Capture 5 frames over given time ──────────────────────────────
        NUM_FRAMES      = 5
        with _state_lock:
            CAPTURE_SPAN_S = _inspection_state.get("capture_span", 3.0)
            
        interval        = CAPTURE_SPAN_S / NUM_FRAMES
        captured_frames = []
        thumbnails_b64  = []

        for i in range(NUM_FRAMES):
            if _check_timeout():
                return
            time.sleep(interval)
            frame = _capture_frame_now()
            if frame is not None:
                captured_frames.append(frame)
                thumbnails_b64.append(_frame_to_b64(frame))
                logger.info(f"Captured frame {i + 1}/{NUM_FRAMES}")
            else:
                logger.warning(f"Frame {i + 1} capture returned None — using synthetic")
                synth = _generate_synthetic_frame()
                captured_frames.append(synth)
                thumbnails_b64.append(_frame_to_b64(synth))

        # ── 3. Motor OFF ──────────────────────────────────────────────────────
        hw.motor_off()

        # ── 4. EJECTING — run inference ───────────────────────────────────────
        _set_status("EJECTING")
        if _check_timeout():
            return

        predictions = []
        for idx, frame in enumerate(captured_frames):
            if _check_timeout():
                return
            pred = engine.predict_frame(frame)
            predictions.append(pred)
            logger.info(f"Frame {idx + 1} inference: {pred[0]} ({pred[1]:.3f})")

        # ── 5. Aggregate grade ────────────────────────────────────────────────
        result = engine.aggregate_grade(predictions)
        grade  = result["grade"]

        # ── 6. Serial transmission → ESP32 ───────────────────────────────────
        if _check_timeout():
            return
        tx_ok = serial.send_grade(grade)
        logger.info(f"Serial TX grade '{grade}': {'ok' if tx_ok else 'failed'}")

        # ── 7. Servo eject ────────────────────────────────────────────────────
        if _check_timeout():
            return

        # Run servo eject in the same thread (blocking ~800 ms total)
        hw.servo_eject(eject_angle=90, home_angle=0, hold_ms=400)

        # ── 8. Finalise ───────────────────────────────────────────────────────
        with _state_lock:
            _inspection_state["last_grade"]  = grade
            _inspection_state["last_result"] = result
            _inspection_state["session_count"] += 1
            _inspection_state["grade_counts"][grade] = (
                _inspection_state["grade_counts"].get(grade, 0) + 1
            )
            _inspection_state["finished_at"] = datetime.utcnow().isoformat() + "Z"
            _inspection_state["thumbnails"]   = thumbnails_b64
            _inspection_state["error"]        = None
            _inspection_state["status"]       = "IDLE"

        logger.info(f"Inspection cycle complete — Grade {grade}")

    except Exception as exc:
        logger.exception(f"Inspection cycle unhandled exception: {exc}")
        hw.motor_off()   # Safety: always ensure motor is off on error
        _set_status("ERROR", error=str(exc))
        # Auto-recover to IDLE after a short delay
        time.sleep(2.0)
        _set_status("IDLE")


# ══════════════════════════════════════════════════════════════════════════════
#  FLASK ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    """Serve the dashboard HTML template."""
    return render_template("index.html")


@app.route("/video_feed")
def video_feed():
    """
    MJPEG camera stream.
    Embed in HTML as: <img src="/video_feed">
    """
    def _generate():
        while True:
            with _frame_lock:
                frame = _latest_frame
            if frame:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                )
            time.sleep(0.033)   # ~30 FPS

    return Response(
        _generate(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/api/status")
def api_status():
    """Full JSON state snapshot — polled by the dashboard every second."""
    with _state_lock:
        snap = dict(_inspection_state)
        # Don't send thumbnail b64 strings in the status poll (heavy)
        snap["thumbnails"] = [f"frame_{i + 1}" for i in range(len(snap["thumbnails"]))]
    snap["hw"]     = hw.status()
    snap["serial"] = serial.status()
    snap["engine"] = engine.status()
    snap["ts"]     = datetime.utcnow().isoformat() + "Z"
    return jsonify(snap)


@app.route("/api/settings/capture-span", methods=["POST"])
def api_update_capture_span():
    """Update the time taken to capture 5 frames."""
    with _state_lock:
        if _inspection_state["status"] != "IDLE":
            return jsonify({"error": "Cannot change speed during inspection"}), 409
            
    data = request.get_json() or {}
    new_span = float(data.get("capture_span", 3.0))
    
    with _state_lock:
        _inspection_state["capture_span"] = max(0.5, min(new_span, 10.0))
        span_val = _inspection_state["capture_span"]
        
    logger.info(f"Capture span updated to {span_val}s")
    return jsonify({"capture_span": span_val})


@app.route("/api/run-inspection", methods=["POST"])
def api_run_inspection():
    """
    Trigger a full inspection cycle.
    Returns 409 if a cycle is already running.
    """
    global _inspection_thread

    with _state_lock:
        current_status = _inspection_state["status"]

    if current_status != "IDLE":
        return jsonify({
            "error": f"Inspection already running (status={current_status}). Wait for IDLE."
        }), 409

    # Record start time
    with _state_lock:
        _inspection_state["started_at"] = datetime.utcnow().isoformat() + "Z"
        _inspection_state["thumbnails"] = []
        _inspection_state["error"]      = None

    _inspection_thread = threading.Thread(
        target=_inspection_cycle,
        daemon=True,
        name="InspectionCycle",
    )
    _inspection_thread.start()

    # Also register a watchdog to enforce the hard timeout
    def _watchdog():
        time.sleep(INSPECTION_TIMEOUT_S + 1)
        with _state_lock:
            if _inspection_state["status"] not in ("IDLE", "ERROR"):
                logger.error("Watchdog: inspection did not finish — forcing IDLE")
                hw.motor_off()
                _inspection_state["status"] = "IDLE"
                _inspection_state["error"]  = "watchdog_timeout"

    threading.Thread(target=_watchdog, daemon=True, name="InspectionWatchdog").start()

    return jsonify({"status": "started", "ts": _inspection_state["started_at"]})


@app.route("/api/result")
def api_result():
    """Return the last completed inspection result including frame thumbnails."""
    with _state_lock:
        result = {
            "grade":         _inspection_state.get("last_grade"),
            "result":        _inspection_state.get("last_result"),
            "thumbnails":    _inspection_state.get("thumbnails", []),
            "session_count": _inspection_state.get("session_count", 0),
            "grade_counts":  _inspection_state.get("grade_counts", {}),
            "finished_at":   _inspection_state.get("finished_at"),
        }
    return jsonify(result)


@app.route("/api/motor/toggle", methods=["POST"])
def api_motor_toggle():
    """Toggle DC motor on/off for manual testing."""
    with _state_lock:
        if _inspection_state["status"] != "IDLE":
            return jsonify({"error": "Cannot toggle motor during inspection"}), 409

    if hw.motor_is_on():
        hw.motor_off()
        state_str = "off"
    else:
        hw.motor_on()
        state_str = "on"

    logger.info(f"Manual motor toggle → {state_str}")
    return jsonify({"motor": state_str})


@app.route("/api/servo/eject", methods=["POST"])
def api_servo_eject():
    """Trigger a single servo eject pulse for manual testing."""
    with _state_lock:
        if _inspection_state["status"] != "IDLE":
            return jsonify({"error": "Cannot trigger servo during inspection"}), 409

    def _run():
        hw.servo_eject(eject_angle=90, home_angle=0, hold_ms=400)

    threading.Thread(target=_run, daemon=True, name="ManualServoEject").start()
    logger.info("Manual servo eject triggered")
    return jsonify({"servo": "ejecting"})


@app.route("/api/health")
def api_health():
    """Lightweight health check — used by setup verification scripts."""
    return jsonify({
        "status":   "ok",
        "ts":       datetime.utcnow().isoformat() + "Z",
        "platform": sys.platform,
        "pi":       IS_PI,
        "camera":   PICAMERA_AVAILABLE,
        "sim_mode": engine.simulation_mode,
    })


# ══════════════════════════════════════════════════════════════════════════════
#  STARTUP / SHUTDOWN
# ══════════════════════════════════════════════════════════════════════════════

def startup():
    """Initialise all subsystems before serving requests."""
    logger.info("PotatoSort AI — starting subsystems")

    hw.setup()
    serial.start()

    # Log engine status
    eng_status = engine.status()
    if eng_status["sim_mode"]:
        logger.warning(
            "Inference engine in SIMULATION MODE — "
            f"model not found at '{eng_status['model_path']}'"
        )

    # Start camera background thread
    global _camera_thread
    _stop_event.clear()
    _camera_thread = threading.Thread(
        target=_camera_loop, daemon=True, name="CameraLoop"
    )
    _camera_thread.start()
    # Wait for the camera to produce its first frame (max 5s)
    _camera_running.wait(timeout=5.0)
    logger.info("Camera loop started")

    logger.info("All subsystems running — Flask ready on http://0.0.0.0:5000")


def shutdown():
    """Cleanly stop all subsystems on exit."""
    logger.info("PotatoSort AI — shutting down")
    _stop_event.set()
    hw.motor_off()
    hw.cleanup()
    serial.stop()
    if _camera_thread:
        _camera_thread.join(timeout=5)
    logger.info("Shutdown complete")


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    startup()
    try:
        app.run(
            host="0.0.0.0",
            port=5000,
            debug=False,        # Never True in production on Pi
            threaded=True,
            use_reloader=False, # Reloader would double-start subsystems
        )
    finally:
        shutdown()
