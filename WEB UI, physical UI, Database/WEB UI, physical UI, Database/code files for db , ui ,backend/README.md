# PotatoSort AI — Industrial Vision Sorter
## Raspberry Pi 5 · YOLOv8 · Flask · SQLite

---

## File Structure

```
potato_sorter_backend/
├── app.py                  # Flask server — REST API + SSE + MJPEG
├── shared_state.py         # Thread-safe shared state (GPIO ↔ Flask bridge)
├── gpio_manager.py         # All hardware I/O — buttons, LEDs, solenoids
├── vision_worker.py        # YOLOv8 + OpenCV detection thread
├── database.py             # SQLite batch history + daily summaries
├── lcd_display.py          # 20x4 character LCD for Tier-2 interface
├── telemetry_monitor.py    # CPU%, temperature, health thresholds
├── static/
│   └── index.html          # Dashboard Web UI (dark camera + light analytics)
├── models/
│   └── potato_sorter_yolov8n.pt   # Your trained YOLO model
├── requirements.txt
└── README.md
```

---

## Hardware Requirements

### Core
| Component | Spec |
|---|---|
| SBC | Raspberry Pi 5 (4GB or 8GB) |
| Camera | Raspberry Pi Camera Module 3 or USB camera (1280×720 @ 30fps) |
| Storage | 32GB+ microSD (Class 10) or NVMe via PCIe hat |

### Tier 1 — Field Panel
| Component | Qty | GPIO Pin (BCM) |
|---|---|---|
| Heavy-duty push button (Start) | 1 | GPIO 17 |
| Heavy-duty push button (Stop) | 1 | GPIO 27 |
| Heavy-duty push button (Reset) | 1 | GPIO 22 |
| Green LED + 330Ω resistor (Power) | 1 | GPIO 5 |
| Blue LED + 330Ω resistor (Run) | 1 | GPIO 6 |
| Amber LED + 330Ω resistor (Warn) | 1 | GPIO 13 |
| Red LED + 330Ω resistor (Bin Full) | 1 | GPIO 19 |

### Tier 2 — Cold Storage Panel
| Component | Qty | GPIO Pin (BCM) |
|---|---|---|
| 20x4 Character LCD (I²C, PCF8574 backpack) | 1 | SDA=GPIO2, SCL=GPIO3 |
| Rotary encoder with switch | 1 | CLK=GPIO23, DT=GPIO24, SW=GPIO25 |
| SPDT speed toggle switch | 1 | GPIO 12 |
| Quick purge push button | 1 | GPIO 16 |
| Batch save push button | 1 | GPIO 20 |

### Solenoid Gates
| Bin | Pin | Description |
|---|---|---|
| Bin A — Large | GPIO 26 | Deflector for >75mm potatoes |
| Bin B — Medium | GPIO 21 | Deflector for 50–75mm potatoes |
| Bin C — Small | GPIO 7 | Deflector for <50mm potatoes |
| Bin D — Reject | GPIO 8 | Deflector for blight/reject potatoes |

> **Driver circuit**: Use an NPN transistor (2N2222 or TIP120) or relay module.
> Pi GPIO outputs 3.3V / ~16mA — never connect solenoids directly to GPIO pins.

---

## Wiring Diagram (ASCII)

```
Raspberry Pi 5                         Field Panel
──────────────────           ─────────────────────────────
GPIO17 ── [330Ω] ──┐         [BTN_START]──────────── GND
GPIO27 ── [330Ω] ──┤         [BTN_STOP] ──────────── GND
GPIO22 ── [330Ω] ──┤         [BTN_RESET]──────────── GND
GPIO5  ──────────[LED_PWR]── GND   (Green)
GPIO6  ──────────[LED_RUN]── GND   (Blue)
GPIO13 ──────────[LED_WRN]── GND   (Amber)
GPIO19 ──────────[LED_FUL]── GND   (Red)

GPIO26 ─── [NPN] ─── SOL_LARGE  (12V coil)
GPIO21 ─── [NPN] ─── SOL_MEDIUM
GPIO7  ─── [NPN] ─── SOL_SMALL
GPIO8  ─── [NPN] ─── SOL_REJECT

GPIO2 (SDA) ─── LCD SDA
GPIO3 (SCL) ─── LCD SCL
5V          ─── LCD VCC   (most 20x4 I2C backpacks need 5V, not 3.3V)
GND         ─── LCD GND
```

---

## Software Setup

### 1. OS & System deps
```bash
# Raspberry Pi OS (64-bit) recommended
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv git i2c-tools
sudo raspi-config  # Enable: Camera, I2C, SSH
```

### 2. Python environment
```bash
cd ~
git clone <your-repo> potato_sorter
cd potato_sorter
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Install requirements.txt
```
flask>=3.0
RPi.GPIO>=0.7.1
opencv-python-headless>=4.9
ultralytics>=8.2
psutil>=5.9
RPLCD>=1.3.1
```

### 4. Train / obtain YOLO model
```bash
# Option A: Fine-tune YOLOv8n on your potato dataset
yolo train model=yolov8n.pt data=potato_dataset.yaml epochs=60 imgsz=640

# Option B: Use pre-labelled open-source potato disease dataset from Roboflow
# Export as YOLOv8 format, place .pt file at models/potato_sorter_yolov8n.pt
```

### 5. Run
```bash
source venv/bin/activate
python app.py
# Web UI: http://<pi-ip>:5000
```

### 6. Run as systemd service (production)
```ini
# /etc/systemd/system/potato_sorter.service
[Unit]
Description=PotatoSort AI Vision Sorter
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/potato_sorter
ExecStart=/home/pi/potato_sorter/venv/bin/python app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable potato_sorter
sudo systemctl start potato_sorter
sudo journalctl -u potato_sorter -f
```

---

## API Reference

| Method | Endpoint | Body / Params | Response |
|---|---|---|---|
| GET | `/` | — | Dashboard HTML |
| GET | `/video_feed` | — | MJPEG stream |
| POST | `/api/command` | `{"action":"start"}` | `{"status":"started","batch_id":"..."}` |
| POST | `/api/command` | `{"action":"stop"}` | `{"status":"stopped"}` |
| POST | `/api/command` | `{"action":"reset"}` | `{"status":"reset"}` |
| POST | `/api/command` | `{"action":"purge"}` | `{"status":"purge_requested"}` |
| POST | `/api/command` | `{"action":"save"}` | `{"status":"saved"}` |
| POST | `/api/speed` | `{"speed":"HIGH"}` | `{"status":"ok","speed":"HIGH"}` |
| GET | `/api/state` | — | Full state JSON |
| GET | `/api/state/stream` | — | SSE event stream |
| GET | `/api/history?n=20` | — | Last N batch rows |
| GET | `/api/health` | — | `{"status":"ok"}` |

---

## Database Schema (SQLite)

```sql
-- batches: one row per sorting session
batch_id TEXT, started_at TEXT, ended_at TEXT, duration_s REAL,
speed TEXT, cnt_large INT, cnt_medium INT, cnt_small INT,
cnt_reject INT, cnt_total INT, reject_rate REAL

-- daily_summary: rolled-up daily totals
summary_date TEXT PK, batches_run INT, cnt_total INT, avg_reject_pct REAL
```

---

## Calibration

To calibrate the pixel-to-mm constant (`PX_TO_MM` in `vision_worker.py`):
1. Place a reference object of known width (e.g., 50mm wooden block) on the belt
2. Measure its pixel width in the camera frame
3. `PX_TO_MM = known_width_mm / pixel_width`
4. Update `vision_worker.py` and restart

---

## Size Classification Logic

```
Detected pixel bounding box → max(width, height) × PX_TO_MM = size_mm

size_mm ≥ 75 → BIN A (Large)
size_mm ≥ 50 → BIN B (Medium)
size_mm < 50 → BIN C (Small)
YOLO blight class detected (regardless of size) → BIN D (Reject)
```
