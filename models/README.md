# Model Directory

Place your exported YOLOv8n classification ONNX model here:

    models/potato_yolov8n_cls.onnx

## How to Export

From Ultralytics (on a machine with GPU/CUDA recommended):

```bash
pip install ultralytics
python - <<'EOF'
from ultralytics import YOLO
model = YOLO("yolov8n-cls.pt")                          # or your custom .pt
model.export(format="onnx", imgsz=224, simplify=True)   # → yolov8n-cls.onnx
EOF
mv yolov8n-cls.onnx models/potato_yolov8n_cls.onnx
```

If the model file is **absent**, the inference engine enters **simulation mode**
and returns randomised-but-plausible classifications so the full pipeline
(motor, serial, servo) continues to operate for testing.

## Class Index Mapping

| Index | Class         | Grade trigger |
|-------|---------------|---------------|
| 0     | Good          | A             |
| 1     | Lower Quality | B             |
| 2     | Rotten        | C             |
| 3     | Scabs         | C             |
| 4     | Damaged       | C             |
