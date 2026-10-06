"""
inference_engine.py — ONNX Runtime inference for potato quality classification

Model:   models/potato_yolov8n_cls.onnx  (YOLOv8n-cls export)
Input:   224×224 RGB float32, normalised to [0, 1]
Classes: Good | Lower Quality | Rotten | Scabs | Damaged  (indices 0–4)

5-Frame Aggregation Rules:
  Grade A — all 5 frames classified as Good
  Grade B — no Rotten/Scabs/Damaged, ≥1 Lower Quality
  Grade C — any frame classified as Rotten, Scabs, or Damaged

Simulation mode (no ONNX model on disk):
  Returns randomised valid classifications + confidence scores.
"""

import os
import logging
import time
import random
from typing import Optional, Tuple

import numpy as np
import cv2

logger = logging.getLogger(__name__)

# ── Model & class config ───────────────────────────────────────────────────────
MODEL_PATH   = os.path.join(os.path.dirname(__file__), "models", "potato_yolov8n_cls.onnx")
INPUT_SIZE   = (224, 224)          # H × W expected by cls model
CLASS_NAMES  = ["Good", "Lower Quality", "Rotten", "Scabs", "Damaged"]
NUM_CLASSES  = len(CLASS_NAMES)

# Grade-C trigger classes (any occurrence → Grade C)
GRADE_C_CLASSES = {"Rotten", "Scabs", "Damaged"}
# Grade-B trigger classes (at least one, and no Grade-C → Grade B)
GRADE_B_CLASSES = {"Lower Quality"}

# ── ONNX Runtime availability ─────────────────────────────────────────────────
try:
    import onnxruntime as ort
    ORT_AVAILABLE = True
    logger.info(f"ONNX Runtime {ort.__version__} loaded")
except ImportError:
    ORT_AVAILABLE = False
    logger.warning("onnxruntime not installed — inference will use simulation mode")


def _softmax(x: np.ndarray) -> np.ndarray:
    """Numerically stable softmax over last axis."""
    e = np.exp(x - np.max(x, axis=-1, keepdims=True))
    return e / e.sum(axis=-1, keepdims=True)


def _preprocess(frame_bgr: np.ndarray) -> np.ndarray:
    """
    Resize and normalise a BGR OpenCV frame to the model's expected input tensor.

    Returns: float32 array of shape (1, 3, H, W) in RGB channel order.
    """
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    resized = cv2.resize(rgb, INPUT_SIZE, interpolation=cv2.INTER_LINEAR)
    tensor = resized.astype(np.float32) / 255.0          # → [0, 1]
    tensor = np.transpose(tensor, (2, 0, 1))              # HWC → CHW
    tensor = np.expand_dims(tensor, 0)                    # → (1, 3, H, W)
    return tensor


class InferenceEngine:
    """
    Wraps the ONNX classification session.

    If the model file is missing or onnxruntime is unavailable, the engine
    enters simulation mode and produces randomised but plausible outputs.
    """

    def __init__(self, model_path: str = MODEL_PATH):
        self._model_path = model_path
        self._session: Optional["ort.InferenceSession"] = None
        self._input_name: Optional[str] = None
        self._sim_mode = False
        self._load()

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def _load(self):
        """Attempt to load the ONNX model; fall back to simulation on failure."""
        if not ORT_AVAILABLE:
            logger.warning("InferenceEngine: ONNX Runtime unavailable — simulation mode")
            self._sim_mode = True
            return

        if not os.path.isfile(self._model_path):
            logger.warning(
                f"InferenceEngine: model not found at '{self._model_path}' — simulation mode"
            )
            self._sim_mode = True
            return

        try:
            providers = ["CPUExecutionProvider"]
            opts = ort.SessionOptions()
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            opts.intra_op_num_threads = 4
            self._session = ort.InferenceSession(
                self._model_path, sess_options=opts, providers=providers
            )
            self._input_name = self._session.get_inputs()[0].name
            logger.info(
                f"ONNX model loaded: '{self._model_path}'  "
                f"input='{self._input_name}'  providers={providers}"
            )
            self._sim_mode = False
        except Exception as e:
            logger.error(f"Failed to load ONNX model: {e} — falling back to simulation mode")
            self._sim_mode = True

    # ── Per-frame inference ────────────────────────────────────────────────────

    def predict_frame(self, frame_bgr: np.ndarray) -> Tuple[str, float, list]:
        """
        Run inference on a single BGR frame.

        Returns:
            (class_name, confidence, all_probabilities_list)
            e.g. ("Good", 0.9532, [0.9532, 0.0241, 0.0112, 0.0072, 0.0043])
        """
        t0 = time.perf_counter()

        if self._sim_mode:
            return self._simulate_prediction()

        try:
            tensor = _preprocess(frame_bgr)
            outputs = self._session.run(None, {self._input_name: tensor})
            # outputs[0] shape: (1, NUM_CLASSES) — raw logits or softmax scores
            logits = outputs[0][0]
            probs = _softmax(logits) if logits.max() > 1.0 else logits
            idx = int(np.argmax(probs))
            conf = float(probs[idx])
            cls_name = CLASS_NAMES[idx] if idx < NUM_CLASSES else "Unknown"

            dt_ms = (time.perf_counter() - t0) * 1000
            logger.debug(f"Inference: {cls_name} ({conf:.3f}) in {dt_ms:.1f} ms")
            return cls_name, conf, probs.tolist()

        except Exception as e:
            logger.error(f"Inference error: {e} — returning simulation prediction")
            return self._simulate_prediction()

    # ── 5-frame aggregation ────────────────────────────────────────────────────

    def aggregate_grade(self, predictions: list[Tuple[str, float, list]]) -> dict:
        """
        Apply the 5-frame grading rules to a list of predictions.

        Args:
            predictions: list of (class_name, confidence, probs) tuples.

        Returns:
            dict with keys: grade, frame_classes, avg_confidence, per_class_counts,
                            sim_mode, frame_detail
        """
        if not predictions:
            return {"grade": "C", "error": "no predictions provided",
                    "sim_mode": self._sim_mode}

        frame_classes = [p[0] for p in predictions]
        confs         = [p[1] for p in predictions]

        # Count per-class occurrences
        per_class = {c: frame_classes.count(c) for c in CLASS_NAMES}

        # Grade determination ──────────────────────────────
        has_grade_c = any(c in GRADE_C_CLASSES for c in frame_classes)
        has_grade_b = any(c in GRADE_B_CLASSES for c in frame_classes)
        all_good    = all(c == "Good" for c in frame_classes)

        if all_good:
            grade = "A"
        elif not has_grade_c and has_grade_b:
            grade = "B"
        else:
            grade = "C"

        avg_conf = sum(confs) / len(confs) if confs else 0.0

        logger.info(
            f"Grade {grade} — frames={frame_classes}  avg_conf={avg_conf:.3f}  "
            f"sim_mode={self._sim_mode}"
        )

        return {
            "grade":           grade,
            "frame_classes":   frame_classes,
            "per_class_counts": per_class,
            "avg_confidence":  round(avg_conf, 4),
            "sim_mode":        self._sim_mode,
            "frame_detail": [
                {
                    "frame":      i + 1,
                    "class":      predictions[i][0],
                    "confidence": round(predictions[i][1], 4),
                    "all_probs":  [round(v, 4) for v in predictions[i][2]],
                }
                for i in range(len(predictions))
            ],
        }

    # ── Simulation mode ────────────────────────────────────────────────────────

    def _simulate_prediction(self) -> Tuple[str, float, list]:
        """
        Produce a randomised-but-realistic classification for demo/dev.
        Weighted distribution: 45% Good, 25% Lower Quality, 15% Rotten,
                               10% Scabs, 5% Damaged.
        """
        weights = [0.45, 0.25, 0.15, 0.10, 0.05]
        cls_name = random.choices(CLASS_NAMES, weights=weights, k=1)[0]
        idx = CLASS_NAMES.index(cls_name)

        # Build a realistic softmax-looking probability vector
        raw = [random.uniform(0.01, 0.05) for _ in CLASS_NAMES]
        raw[idx] = random.uniform(0.65, 0.97)
        total = sum(raw)
        probs = [v / total for v in raw]
        conf = probs[idx]

        time.sleep(random.uniform(0.008, 0.020))   # simulate latency
        return cls_name, conf, probs

    # ── Status ────────────────────────────────────────────────────────────────

    @property
    def simulation_mode(self) -> bool:
        return self._sim_mode

    def status(self) -> dict:
        return {
            "model_path":  self._model_path,
            "model_loaded": not self._sim_mode,
            "sim_mode":    self._sim_mode,
            "ort_available": ORT_AVAILABLE,
            "class_names": CLASS_NAMES,
        }
