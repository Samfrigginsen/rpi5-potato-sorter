"""
vision_worker.py — YOLOv8 + OpenCV vision pipeline for PotatoSort AI
Runs in a dedicated daemon thread; reads camera, detects & classifies potatoes,
updates SharedState, and fires solenoid signals via GPIO manager.
"""

import time
import threading
import logging
from typing import Optional

import cv2
import numpy as np

# ── Import conditionally so the module loads on dev machines without YOLO
try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    logging.warning("ultralytics not installed — vision will run in DEMO mode")

from shared_state import sorter_state, SharedState
from gpio_manager import GPIOManager

logger = logging.getLogger(__name__)

# ── Pixel-to-mm calibration constant (calibrate against known reference object)
# At 30cm camera height, 1px ≈ 0.18mm for a 1280×720 frame
PX_TO_MM: float = 0.18

# ── YOLO model path — use a custom-trained potato model or fine-tuned yolov8n
MODEL_PATH = "models/potato_sorter_yolov8n.pt"

# ── Confidence threshold
CONF_THRESHOLD = 0.60

# ── Size thresholds (mm) — these define bin boundaries.
# FIX (calibration gap): these used to be hardcoded module constants,
# which is exactly why the Tier-2 rotary encoder's "calibration" screens
# had nothing real to adjust. They now live as mutable state on
# sorter_state (sorter_state.size_threshold_medium_mm / _large_mm) and
# are only kept here as the STARTUP defaults, applied once in __init__.
SIZE_LARGE_MM_DEFAULT = 75.0
SIZE_MEDIUM_MM_DEFAULT = 50.0

# ── FIX (bug #1): Reject/blight is a YOLO CLASS, not a size bucket.
# The model's box.cls[0] index must be mapped to a class *name* (via
# results[0].names) and checked against this set. Add/adjust names to
# match exactly what your trained model's data.yaml uses.
REJECT_CLASS_NAMES = {"blight", "diseased", "rotten", "reject", "defect"}


class VisionWorker:
    """
    Grabs frames from the camera, runs YOLO inference, classifies detections,
    updates shared state, and triggers GPIO solenoids.
    """

    def __init__(self, gpio: GPIOManager, camera_index: int = 0):
        self.gpio = gpio
        self.camera_index = camera_index

        self._cap: Optional[cv2.VideoCapture] = None
        self._model = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Frame buffer for MJPEG stream
        self._frame_lock = threading.Lock()
        self._latest_frame: Optional[bytes] = None

        # FPS tracking
        self._frame_times: list[float] = []

    # ─────────────────────────────────────────────────────────── Lifecycle

    def start(self):
        if self._thread and self._thread.is_alive():
            logger.warning("VisionWorker already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="VisionWorker")
        self._thread.start()
        logger.info("VisionWorker started")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self._cap and self._cap.isOpened():
            self._cap.release()
        logger.info("VisionWorker stopped")

    # ─────────────────────────────────────────────────────────── Main loop

    def _run(self):
        self._init_model()
        self._init_camera()

        while not self._stop_event.is_set():
            ret, frame = self._cap.read()
            if not ret:
                logger.error("Camera read failed — retrying in 1s")
                time.sleep(1)
                self._init_camera()
                continue

            t0 = time.perf_counter()

            if sorter_state.is_running:
                annotated, detections = self._process_frame(frame)
                for det in detections:
                    self._dispatch(det)
            else:
                annotated = frame

            # FPS
            t1 = time.perf_counter()
            self._frame_times.append(t1)
            self._frame_times = [t for t in self._frame_times if t > t1 - 1.0]
            fps = len(self._frame_times)
            sorter_state.telemetry.fps = fps

            # Encode for MJPEG stream
            _, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
            with self._frame_lock:
                self._latest_frame = buf.tobytes()

            # Approx 30 FPS cap
            elapsed_ms = (t1 - t0) * 1000
            sleep_ms = max(0, 33 - elapsed_ms)
            time.sleep(sleep_ms / 1000)

    # ─────────────────────────────────────────────────────────── Frame processing

    def _process_frame(self, frame: np.ndarray) -> tuple[np.ndarray, list[dict]]:
        """Run YOLO on frame, return annotated frame and list of detections."""
        t0 = time.perf_counter()
        detections = []

        if YOLO_AVAILABLE and self._model:
            results = self._model.predict(
                frame,
                conf=CONF_THRESHOLD,
                verbose=False,
                imgsz=640,
            )
            t1 = time.perf_counter()
            inference_ms = (t1 - t0) * 1000
            sorter_state.telemetry.inference_ms = inference_ms

            annotated = results[0].plot()

            for box in results[0].boxes:
                cls_idx = int(box.cls[0])
                conf = float(box.conf[0])
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                width_px = x2 - x1
                height_px = y2 - y1
                size_mm = max(width_px, height_px) * PX_TO_MM

                # FIX (bug #1): previously `cls_idx` was extracted but never
                # used, so a potato was ALWAYS bucketed by size only and
                # could never land in "reject" from real YOLO detections —
                # only DEMO mode's fake data ever produced "reject".
                # Now: look up the class name for this box and check it
                # against REJECT_CLASS_NAMES *before* falling back to the
                # size-based large/medium/small split, matching the README's
                # documented rule: "YOLO blight class detected (regardless
                # of size) → BIN D (Reject)".
                class_name = results[0].names.get(cls_idx, "").lower()
                if class_name in REJECT_CLASS_NAMES:
                    category = "reject"
                else:
                    category = self._classify_by_size(size_mm)

                detections.append({
                    "category": category,
                    "confidence": conf,
                    "size_mm": size_mm,
                    "bbox": (x1, y1, x2, y2),
                })
        else:
            # DEMO mode: simulate detections
            annotated = self._draw_demo_overlay(frame)
            detections = self._fake_detection()
            sorter_state.telemetry.inference_ms = 35.0

        return annotated, detections

    def _classify_by_size(self, size_mm: float) -> str:
        """
        Map diameter to bin category — Large / Medium / Small.
        Called ONLY for boxes whose YOLO class is not in REJECT_CLASS_NAMES
        (see _process_frame). Reject/blight is decided by class name first.

        FIX (calibration gap): thresholds are read LIVE from sorter_state
        on every call (not a module constant), so adjusting them via the
        Tier-2 rotary-encoder CALIBRATE_MEDIUM/CALIBRATE_LARGE screens
        takes effect on the very next frame — no restart needed.
        """
        if size_mm >= sorter_state.size_threshold_large_mm:
            return "large"
        elif size_mm >= sorter_state.size_threshold_medium_mm:
            return "medium"
        else:
            return "small"

    # ─────────────────────────────────────────────────────────── Dispatch

    def _dispatch(self, detection: dict):
        """Update state and fire the correct solenoid gate."""
        category = detection["category"]
        conf = detection["confidence"]
        size_mm = detection["size_mm"]

        sorter_state.increment(category, confidence=conf, size_mm=size_mm)
        self.gpio.fire_solenoid(category)

    # ─────────────────────────────────────────────────────────── Helpers

    def _init_model(self):
        if not YOLO_AVAILABLE:
            return
        try:
            self._model = YOLO(MODEL_PATH)
            logger.info(f"YOLO model loaded: {MODEL_PATH}")
        except Exception as e:
            logger.error(f"Failed to load YOLO model: {e} — falling back to DEMO mode")
            self._model = None

    def _init_camera(self):
        if self._cap and self._cap.isOpened():
            self._cap.release()
        self._cap = cv2.VideoCapture(self.camera_index)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        self._cap.set(cv2.CAP_PROP_FPS, 30)
        if not self._cap.isOpened():
            logger.error(f"Cannot open camera {self.camera_index}")

    def _draw_demo_overlay(self, frame: np.ndarray) -> np.ndarray:
        """Draws a 'DEMO MODE' banner on frame."""
        out = frame.copy()
        cv2.putText(out, "DEMO MODE — No YOLO model", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)
        return out

    def _fake_detection(self) -> list[dict]:
        """Returns a random detection for demo/testing."""
        import random
        if random.random() < 0.3:  # 30% chance of a detection per frame
            cats = ["large", "large", "medium", "medium", "small", "reject"]
            cat = random.choice(cats)
            size = {"large": 80, "medium": 62, "small": 38, "reject": 55}[cat]
            return [{"category": cat, "confidence": random.uniform(0.7, 0.97), "size_mm": size, "bbox": (0,0,0,0)}]
        return []

    # ─────────────────────────────────────────────────────────── Stream

    def get_frame(self) -> Optional[bytes]:
        """Returns the latest JPEG frame (bytes) for MJPEG streaming."""
        with self._frame_lock:
            return self._latest_frame

    def generate_mjpeg(self):
        """Generator for Flask MJPEG response."""
        while True:
            frame = self.get_frame()
            if frame:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                )
            time.sleep(0.033)
