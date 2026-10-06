#!/usr/bin/env python3
"""
test_camera.py — Standalone IMX219 camera verification script

Tests:
  1. picamera2 initialisation (640×480 Video configuration)
  2. Frame capture using capture_array('main')
  3. RGB → BGR conversion
  4. Frame rate measurement (30-frame test)
  5. Optional display window (if a display is available)

Run on the Raspberry Pi:
    python3 test_camera.py
    python3 test_camera.py --no-display   (headless / SSH)
    python3 test_camera.py --frames 60    (capture 60 frames)
"""

import sys
import time
import argparse
import logging

import cv2
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── Platform check ─────────────────────────────────────────────────────────────
IS_PI = sys.platform.startswith("linux") and any(
    p in open("/proc/cpuinfo", "r", errors="ignore").read()
    for p in ("Raspberry", "BCM2")
) if sys.platform.startswith("linux") else False

# ── picamera2 import ───────────────────────────────────────────────────────────
PICAMERA_AVAILABLE = False
Picamera2 = None

if IS_PI:
    try:
        from picamera2 import Picamera2 as _Picam
        Picamera2 = _Picam
        PICAMERA_AVAILABLE = True
        logger.info("picamera2 loaded successfully")
    except ImportError as e:
        logger.error(f"picamera2 not available: {e}")
else:
    logger.warning(f"Not running on Raspberry Pi (platform='{sys.platform}') — using OpenCV fallback")


# ══════════════════════════════════════════════════════════════════════════════
#  INITIALISATION
# ══════════════════════════════════════════════════════════════════════════════

def init_picamera2():
    """
    Initialise IMX219 via picamera2.

    Uses the exact working configuration:
      - create_video_configuration with 640×480 main stream
      - RGB888 pixel format
      - capture_array('main') for frame capture
    """
    logger.info("── Test 1: picamera2 initialisation ──────────────────────")

    if not PICAMERA_AVAILABLE:
        logger.error("FAIL: picamera2 not available on this system")
        return None

    try:
        cam = Picamera2()
        logger.info(f"  Camera instance created: {cam}")

        cfg = cam.create_video_configuration(
            main={"size": (640, 480), "format": "RGB888"}
        )
        cam.configure(cfg)
        logger.info(f"  Video configuration applied: {cfg}")

        cam.start()
        logger.info("  Camera started — allowing 0.5s for AEC/AWB to settle")
        time.sleep(0.5)

        logger.info("  ✓ picamera2 initialisation: PASS")
        return cam

    except Exception as e:
        logger.error(f"  FAIL: picamera2 init raised: {e}")
        return None


def init_opencv_fallback():
    """
    Fallback: open a standard webcam via OpenCV VideoCapture.
    Used when picamera2 is unavailable.
    """
    logger.info("── Fallback: OpenCV VideoCapture(0) ─────────────────────")
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        logger.error("  FAIL: Cannot open VideoCapture(0) — no camera found")
        return None, "opencv"
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)
    logger.info(f"  OpenCV camera opened at {cap.get(cv2.CAP_PROP_FRAME_WIDTH):.0f}"
                f"×{cap.get(cv2.CAP_PROP_FRAME_HEIGHT):.0f}")
    return cap, "opencv"


# ══════════════════════════════════════════════════════════════════════════════
#  TESTS
# ══════════════════════════════════════════════════════════════════════════════

def test_single_capture(cam_obj, mode: str) -> np.ndarray | None:
    """Test 2 & 3: single frame capture + RGB→BGR conversion."""
    logger.info("── Test 2: Single frame capture ──────────────────────────")

    try:
        if mode == "picamera2":
            # Exact capture pattern preserved from project
            rgb_array = cam_obj.capture_array("main")
            logger.info(f"  capture_array('main') shape: {rgb_array.shape}  dtype: {rgb_array.dtype}")
            assert rgb_array.ndim == 3, f"Expected 3D array, got {rgb_array.ndim}D"
            assert rgb_array.shape[2] == 3, f"Expected 3 channels, got {rgb_array.shape[2]}"

            logger.info("── Test 3: RGB → BGR conversion ──────────────────────")
            bgr = cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)
            logger.info(f"  Converted BGR shape: {bgr.shape}")

        else:
            ret, bgr = cam_obj.read()
            if not ret or bgr is None:
                logger.error("  FAIL: VideoCapture.read() returned no frame")
                return None
            logger.info(f"  OpenCV frame shape: {bgr.shape}  dtype: {bgr.dtype}")
            logger.info("  (OpenCV already returns BGR — no conversion needed)")

        # Sanity checks
        h, w, c = bgr.shape
        assert w == 640, f"Expected width 640, got {w}"
        assert h == 480, f"Expected height 480, got {h}"
        assert bgr.mean() > 0, "Frame appears to be all-black — camera may not be ready"

        logger.info(f"  Frame stats — mean: {bgr.mean():.1f}  min: {bgr.min()}  max: {bgr.max()}")
        logger.info("  ✓ Frame capture + colour conversion: PASS")
        return bgr

    except Exception as e:
        logger.error(f"  FAIL: capture raised: {e}")
        return None


def test_frame_rate(cam_obj, mode: str, n_frames: int = 30) -> float:
    """Test 4: measure sustained frame rate over n_frames captures."""
    logger.info(f"── Test 4: Frame rate ({n_frames} frames) ────────────────")

    t_start = time.perf_counter()
    frames_captured = 0

    for i in range(n_frames):
        try:
            if mode == "picamera2":
                rgb = cam_obj.capture_array("main")
                _ = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            else:
                ret, _ = cam_obj.read()
                if not ret:
                    logger.warning(f"  Frame {i + 1}: read() failed")
                    continue
            frames_captured += 1
        except Exception as e:
            logger.warning(f"  Frame {i + 1} error: {e}")

    elapsed = time.perf_counter() - t_start
    fps = frames_captured / elapsed if elapsed > 0 else 0

    logger.info(f"  Captured {frames_captured}/{n_frames} frames in {elapsed:.2f}s")
    logger.info(f"  Measured FPS: {fps:.1f}")

    if fps >= 20:
        logger.info("  ✓ Frame rate test: PASS (≥20 FPS)")
    elif fps >= 10:
        logger.warning(f"  ⚠ Frame rate test: MARGINAL ({fps:.1f} FPS — expected ≥20)")
    else:
        logger.error(f"  FAIL: Frame rate too low ({fps:.1f} FPS)")

    return fps


def test_display(bgr_frame: np.ndarray, duration_s: float = 3.0):
    """Test 5 (optional): display frame in an OpenCV window."""
    logger.info("── Test 5: Display window ────────────────────────────────")
    try:
        cv2.namedWindow("IMX219 Test Frame", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("IMX219 Test Frame", 640, 480)

        # Add test overlay
        display = bgr_frame.copy()
        cv2.putText(display, "IMX219 CAMERA TEST", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 100), 2)
        cv2.putText(display, "Press any key to close", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        cv2.imshow("IMX219 Test Frame", display)

        key = cv2.waitKey(int(duration_s * 1000))
        cv2.destroyAllWindows()
        logger.info("  ✓ Display test: PASS")
    except Exception as e:
        logger.warning(f"  Display test skipped (no display available): {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Standalone IMX219 camera verification for Raspberry Pi 5"
    )
    parser.add_argument(
        "--no-display", action="store_true",
        help="Skip the OpenCV display window (headless/SSH mode)"
    )
    parser.add_argument(
        "--frames", type=int, default=30,
        help="Number of frames to capture for the frame-rate test (default: 30)"
    )
    args = parser.parse_args()

    logger.info("══════════════════════════════════════════")
    logger.info("  IMX219 Camera Verification — Potato Sorter")
    logger.info(f"  Platform: {'Raspberry Pi' if IS_PI else sys.platform}")
    logger.info("══════════════════════════════════════════")

    cam_obj = None
    mode    = "picamera2"
    passed  = 0
    failed  = 0

    # ── Init ──────────────────────────────────────────────────────────────────
    if PICAMERA_AVAILABLE:
        cam_obj = init_picamera2()
        mode    = "picamera2"
        if cam_obj:
            passed += 1
        else:
            failed += 1
    
    if cam_obj is None:
        cam_obj, mode = init_opencv_fallback()
        if cam_obj:
            logger.info("  Using OpenCV fallback (picamera2 unavailable)")
            passed += 1
        else:
            failed += 1
            logger.error("No camera available — aborting tests")
            sys.exit(1)

    # ── Tests ─────────────────────────────────────────────────────────────────
    bgr_frame = test_single_capture(cam_obj, mode)
    if bgr_frame is not None:
        passed += 1
    else:
        failed += 1

    fps = test_frame_rate(cam_obj, mode, n_frames=args.frames)
    if fps >= 20:
        passed += 1
    else:
        failed += 1

    if bgr_frame is not None and not args.no_display:
        test_display(bgr_frame)
    elif args.no_display:
        logger.info("── Test 5: Display skipped (--no-display flag) ──────────")

    # ── Cleanup ───────────────────────────────────────────────────────────────
    if mode == "picamera2" and cam_obj is not None:
        try:
            cam_obj.stop()
        except Exception:
            pass
    elif cam_obj is not None:
        cam_obj.release()

    # ── Summary ───────────────────────────────────────────────────────────────
    total = passed + failed
    logger.info("══════════════════════════════════════════")
    logger.info(f"  Results: {passed}/{total} tests passed")
    logger.info(f"  FPS:     {fps:.1f}")
    if failed == 0:
        logger.info("  STATUS:  ✓ ALL TESTS PASSED — camera ready")
        sys.exit(0)
    else:
        logger.error(f"  STATUS:  ✗ {failed} test(s) FAILED — check wiring / driver")
        sys.exit(1)


if __name__ == "__main__":
    main()
