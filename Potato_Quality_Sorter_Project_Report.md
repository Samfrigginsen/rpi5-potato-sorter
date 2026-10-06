
# AI-Powered Potato Quality Sorter
## Department of Computer Science and Engineering
### Microcontroller Lab — Project Report

---

**Group Members**

| Name   | Role / Primary Contribution |
|--------|------------------------------|
| Sameer | AI Model, Raspberry Pi 5 Software, 360° Rotating Platform, Feed Servo Arm |
| Fahim  | Web UI / Physical UI, Button Mechanism Design, Conveyor Belt Integration |
| Saker  | Conveyor Belt Subsystem, Structural Frame Assembly |
| Ador   | Sorting Servo Arms, ESP32 Firmware |
| Rokon  | Sorting Mechanism Calibration, ESP32 Support, Power Distribution, Power System Diagnostics |

**Date of Submission:** October 2026

---

## Abstract

This report presents the design, implementation, and evaluation of an AI-powered Potato Quality Sorter — an embedded system built for the Microcontroller Laboratory course. The system combines a Raspberry Pi 5 single-board computer, a Sony IMX219 camera module, an ESP32 microcontroller, a custom 360° rotating scanning platform, a motorized conveyor belt, and a set of sorting servo arms to automatically grade incoming potatoes into three quality tiers — Grade A, Grade B, and Grade C — using an on-device YOLOv8n image classifier exported to the ONNX format. A Flask-based web dashboard provides the operator with a live camera feed, a running grading history, and manual test controls for every electromechanical subsystem.

The project faced persistent engineering, logistical, and teamwork challenges: a defective switched-mode power supply that died out of the box, structural integrity and speed-control problems in the conveyor belt, slow and only partially operational sorting servos, missing environmental and weight sensors, quality issues in the downloaded image dataset, and the ever-present difficulty of coordinating five geographically dispersed team members whose prior hands-on experience with embedded systems was uneven. Despite these headwinds, the team delivered a working end-to-end demonstration on the final day. A potato enters the scanning chamber, the rotating stage spins it through a full 360° while the Pi captures and classifies five frames across the rotation, aggregates the results into a single grade, and triggers a push arm that reliably delivers the tuber onto the output conveyor. This report documents both the engineering of the system that finally ran, and the honest lessons learned from the process of trying to get it working under real resource and time constraints.

---

## Table of Contents

1.  Introduction
2.  System Architecture
3.  Hardware Construction
4.  Power System
5.  AI Pipeline and Sensing Logic
6.  Software and User Interface
7.  Budget and Bill of Materials
8.  Team Contributions and Division of Work
9.  Challenges, Problem Solving, and Lessons Learned
10. Results — What Worked and What Did Not
11. Future Development
12. Conclusion

---

## 1. Introduction

Post-harvest quality grading is still one of the least digitalized stages of the agricultural supply chain in our context. A farmer or wholesaler today sorts potatoes — and most other tubers and fruits — by hand. Hand sorting is slow, it is subjective, and it is inconsistent. Two experienced workers standing next to each other will rarely agree exactly on where the line between "premium marketable" and "lower grade" falls, and by the end of a long day on a sorting table fatigue makes even the best sorter less reliable. An automated visual grading machine removes that subjectivity, keeps the same standard on the first potato of the day and the ten thousandth, and frees up people for work that cannot be automated.

### 1.1 Project Objectives

The original project scope, written up in the merged produce sorter initial plan at the start of the semester, was deliberately ambitious. The group wanted to build a multi-crop produce sorter that could handle tomatoes, apples, oranges, and potatoes; grade each item both by visual quality and by weight using a load cell; monitor the temperature and humidity inside every storage bin with environmental sensors; give the farmer both a physical pushbutton-and-LCD control panel on the machine itself and a browser-based dashboard on the local network; and log a complete, queryable history of every single item that passed through the machine in an SQLite audit database. The concrete subsystems planned from day one were:

- A **scanning chamber** with 360° rotation so that the camera could see all sides of each tuber, not just the top face.
- An **AI vision pipeline** of camera capture, five-frame aggregation across the rotation, YOLOv8 classification, and a final Grade A / B / C output.
- An **output handling subsystem**: a servo push arm to eject the scanned item onto a conveyor belt, followed by three sorting servo arms at the end of the belt to divert each item into the correct bin.
- **Environmental sensors** of the DHT or BME family, mounted in each storage bin, with readings logged alongside each classification record.
- **Weight sensing** using a load cell and an HX711 amplifier, so that underweight or oversized items could be flagged independently of visual grade.
- **Position tracking** with IR proximity sensors or micro-limit switches at key points along the conveyor, so the system always knew where a given tuber was in the pipeline.
- **Dual user interface**: a physical panel on the machine with an LCD character display, rotary encoder, and hardwired START and EMERGENCY STOP buttons, paired with a browser dashboard on the local Wi-Fi network.
- **Data persistence**: every scan, with timestamp, grade, confidence, and weight, written to a relational database table.

Circumstance, resource limits, and plain realism pared this scope down substantially between the first planning meeting and demo day. What was actually demonstrated was a single-commodity visual grader: a potato-only machine that sorts based on appearance alone, with one operational output sorting arm, no weight sensor, no environmental sensors, no panel-mounted physical buttons — but with a functional web dashboard and a working SQLite audit log.

### 1.2 Why Potatoes?

Potatoes were chosen as the practical demonstration commodity for three straightforward reasons. First, they are roughly uniform in shape and therefore easy to rotate mechanically on a flat turntable. Second, a labeled image dataset for visual defects on potatoes already existed in a published IEEE paper the team had found, lowering the barrier to getting a classifier trained. Third, and most pragmatically, potatoes are cheap and available everywhere locally — the team could walk to any kitchen market, buy two dozen sample tubers in three different conditions, and run test after test without worrying about wasting expensive or perishable fruit.

---

## 2. System Architecture

The overall system is a two-controller architecture with a clean separation of concerns. The computationally heavy work — camera capture, neural network inference, web serving, database logging, and decision aggregation — lives on the Raspberry Pi 5. Real-time, low-level motor and servo control lives on the ESP32. The two talk to each other over a USB serial link.

### 2.1 High-Level Block Diagram

From a data-flow perspective, a single sorting cycle looks like this:

```
OPERATOR presses Start on web dashboard
          │
          ▼
RASPBERRY PI 5 (main host)
 ├─ Flask Web App    ← serves dashboard page, MJPEG stream, audit table
 ├─ Inference Engine  ← ONNX Runtime classifies each 224×224 frame
 ├─ Database Layer    ← writes every completed scan to SQLite
 ├─ Hardware Ctrl     ← toggles stepper GPIO pulses for rotating stage
 └─ Serial Bridge     ← sends ASCII commands over USB-serial at 115200 baud
          │
          ├─── IMX219 Camera  (MJPEG stream + still captures)
          ├─── Stepper Motor  (rotating scanning platform)
          └─── USB UART ───────► ESP32 (slave controller)
                                  │
                                  ├── SERVO_PUSH  → MG996R push arm
                                  ├── CONVEYOR_FWD/RVS → L298N DC motor
                                  └── SORT_BIN_A/B/C  → three sorting flaps
```

### 2.2 Serial Communication Protocol

The Raspberry Pi 5 is the bus master; the ESP32 only speaks when spoken to. The message envelope is deliberately simple ASCII lines, defined in [serial_bridge.py](file:///d:/Programming/Arduino%20Stuff/rpi5%20potato%20sorter/serial_bridge.py). A human can read every byte on the wire with nothing more than a `screen` session into the COM port, which made debugging substantially easier than a packed binary protocol would have been.

Commands from the Pi take the form:

```
ACTION:<command>\n
```

Replies from the ESP32 follow:

```
STATUS:<ok|err>:<freeform detail>\n
```

The full command vocabulary implemented by demo day included `MOTOR_SPIN start/stop`, `SERVO_PUSH`, `CONVEYOR_START`, `CONVEYOR_STOP`, `SORT_BIN_A`, `SORT_BIN_B`, `SORT_BIN_C`, `ESTOP`, and `PING`. The `PING` command in particular was useful during bring-up because it let the web dashboard show a green or red status indicator before a user ever pressed Start.

### 2.3 AI Decision Pipeline — Five-Frame Aggregation

The classifier does not make a one-shot decision. A single picture taken from directly above will reliably miss a scab or a rotten patch on the underside or the far side of a round potato. To compensate, the team implemented a five-frame aggregation policy inside the scan handler in [app.py](file:///d:/Programming/Arduino%20Stuff/rpi5%20potato%20sorter/app.py):

1.  The rotating platform begins a full turn.
2.  One 224×224 frame is captured every roughly 100 milliseconds, giving five frames evenly distributed across the 360° rotation.
3.  Each frame is run individually through the ONNX Runtime inference engine, producing a 5-element softmax vector.
4.  The five softmax vectors are averaged element-wise, giving a single per-class confidence across the whole rotation.
5.  The class index of the highest average confidence is read off.
6.  The class name is mapped to a letter grade using the table below.

```
Class Index    Class Name         Final Grade
-----------    ----------         -----------
     0         Good               Grade A
     1         Lower Quality      Grade B
     2         Rotten             Grade C
     3         Scabs              Grade C
     4         Damaged            Grade C
```

Combining visual evidence from five different angles makes the final grade dramatically more stable than any single-frame judgment. A single unlucky capture with a shadow or a glare is outweighed by the other four.

### 2.4 Web UI Architecture

The operator dashboard, implemented in [index.html](file:///d:/Programming/Arduino%20Stuff/rpi5%20potato%20sorter/templates/index.html), is a self-contained single-page application served by Flask from the Raspberry Pi 5 on TCP port 5000. The live camera feed uses a Motion JPEG stream over HTTP from the `/video_feed` endpoint, which OpenCV on the Pi feeds from the `libcamera` stack; no extra browser plugin or WebRTC complexity is needed. Interaction between the page and the back end is straightforward `fetch()` POST calls, and the audit log table refreshes automatically every few seconds. Every completed scan is persisted to the `scans` table in `logs/sorter_logs.db` via the `SorterLogger` class in `database.py`.

---

## 3. Hardware Construction

Physically, the finished machine looks like a slightly oversize white desktop PC tower. A cutout on the left side of the front face forms the loading chute — this is where a potato goes in. A second opening on the right side is the exit, where the graded potato leaves the scanning chamber and falls onto the head of the conveyor belt. The Raspberry Pi 5, the USB-serial adapter, the camera, and the rotating stage stepper all live inside the enclosure; the ESP32, the motor drivers, and the power distribution wiring are mounted on a perfboard strip bolted to the back wall of the case.

### 3.1 Scanning Chamber and 360° Rotating Platform

The rotating scanning platform was the single most mechanically iterative piece of the entire project. It went through three full design cycles — two dead ends, then a winner — and the process of getting it right is a good illustration of how a complicated-looking idea very often loses to a simple one that a team can actually build with the tools on hand.

**Iteration 1: Rolling-pin rollers.** The first concept, drawn on paper early, called for a set of smooth parallel rollers under the potato, all driven in sync, whose axes were perpendicular to the direction of travel. The geometry looked fine in a 2D sketch. The team could not, however, get a clean FreeCAD model of the mounting brackets to line up without binding, and the exact-size smooth metal pins the design required were not available from the shop the group normally used. Rather than burn a week chasing custom parts for a subsystem that might not work anyway, the team scrapped it before a single bracket was cut.

**Iteration 2: Twin diagonal belts.** The second design tried to avoid custom machined pins entirely by using two rubber belts running in the same direction but offset at opposing angles. The theory was that a potato sitting between them would roll like a planet between two suns and naturally show every face to the overhead camera. The team mocked this design up in cardboard and hot glue to test before ordering any real parts. The potato did not precess. It simply slid sideways across both belts, or if pressed down firmly enough to catch the rubber, it sat in one spot spinning on a single axis and still showed only half its surface to the camera. Two full afternoons of adjusting belt tension, angle, and center distance did not save it. Rejected.

**Iteration 3: Flat rotating disc.** The third and final approach was deliberately boring. A single flat circular disc, the underside of which was press-fit directly onto the output shaft of a geared stepper motor. The top surface of the disc was covered with a thin layer of closed-cell foam rubber glued down with contact cement to give just enough grip that the potato would not skid when the disc began to turn. The whole assembly was raised by four plastic standoffs to the correct height inside the chamber. This version worked on the first try. Every size of potato the team threw at it — from small new potatoes to large baking potatoes — spun cleanly in place for as many full revolutions as the stepper was told to run. The rotating platform design that won the project was the one that a first-year engineering student could have sketched on a napkin in five minutes. The team's consensus after the fact: simple wins. For a 360° view, a single turntable beat two clever mechanisms that nobody on the team could actually machine to tolerance.

### 3.2 Turntable Drive

The disc itself is turned by a 28BYJ-48 unipolar stepper mated to a ULN2003 Darlington driver module. The team had originally wanted a NEMA 17 for the extra torque, but the budget for that motor and a proper A4988 carrier board was eaten up by other surprises. The 28BYJ-48 is a 64:1 gear-reduced unit rated at 2048 full steps per output revolution. The motion profile in [hardware_controller.py](file:///d:/Programming/Arduino%20Stuff/rpi5%20potato%20sorter/hardware_controller.py) runs it at roughly 15 rpm for one full turn per scan — slow enough that the camera gets five sharp frames, fast enough that the operator is not waiting around.

### 3.3 Conveyor Belt Subsystem

The conveyor belt was Saker's primary deliverable, and Fahim stepped in to help rework it during the last week before the demo. The belt itself ran over two plastic pulleys on a light-gauge metal frame, with a brushed 12 V DC motor driving the head pulley through an L298N H-bridge module. Two issues followed the subsystem from first power-on to demo day:

1.  **No closed-loop speed control.** There was no encoder anywhere on the motor shaft or the pulley, so speed was a raw PWM duty cycle written to the L298N. The actual belt speed therefore varied with the charge state of whatever battery pack was powering the machine at that moment. Tuning the sorting-flap timing for a consistent travel time from camera to bin was guesswork.
2.  **Structural integrity.** The thin sheet-metal frame that held the two pulleys flexed under hand pressure, and the idler axle had a habit of walking slightly out of its slot, which made the belt drift to one side and occasionally ride up over the edge of the pulley. A combination of extra hot-glue gussets, a small spring on the idler, and Fahim's last-hour rework of the frame corners made it run well enough for the demo, but nobody on the team would call the final build robust.

### 3.4 Feed Push Arm

The small hinged paddle that ejects a graded potato off the rotating disc and onto the head of the conveyor was the single most reliable electromechanical subsystem on the whole machine. Sameer designed it as a 10 cm wide flat paddle on the output shaft of a metal-gear MG996R servo. A single `SERVO_PUSH` command over the serial bus raises the paddle from its parked vertical position, sweeps roughly 110° across the face of the disc, and returns. On demo day this arm worked every single time, without exception, across every test run the group did for the evaluators. If any single part of the machine deserved a perfect score, it was this one.

### 3.5 ESP32 Sorting Servo Arms

Three more MG996R servos — one for Grade A, one for Grade B, one for Grade C — were mounted at the tail end of the conveyor belt, each driving a small diverter flap that could push a passing potato off the belt and into the corresponding storage bin. Ador wrote the ESP32 firmware for them and built the mechanical mounts. In practice, only the Grade A arm moved reliably during testing, and it moved slowly. A full sweep took roughly a second and a half, which under the open-loop conveyor timing was right on the edge of being too slow for the potatoes as they arrived. The other two arms were wired and could be driven manually from the test buttons on the web dashboard, but their motion was inconsistent and their timing relative to the conveyor travel was not trustworthy. They were treated as non-operational for the final demo.

---

## 4. Power System

The power system is worth a dedicated chapter because it absorbed more collective troubleshooting hours than any single software module, and it was the root cause of more apparently unrelated subsystem failures than anything else. The short version: buy a good power supply, and load-test it before you solder anything to it.

### 4.1 Original Design Intent

The power architecture drawn up at the start of the project was textbook and perfectly reasonable on paper:

- A 220 V AC input to an enclosed 12 V, 5 A switched-mode power supply mounted on the back of the case.
- A 12 V to 5 V / 3 A buck converter feeding the Raspberry Pi 5, the camera module, and the USB-serial chip.
- The raw 12 V rail feeding the L298N H-bridge for the conveyor DC motor.
- A separate 5 V / 2 A battery elimination circuit (BEC) tapped from the 12 V input to power the bank of MG996R servos, keeping the noisy servo current away from the Pi's 5 V rail.
- A single star ground at the SMPS output terminal, with every subsystem's ground wire running back to that one point to avoid ground loops.

None of this survived first contact with the actual hardware.

### 4.2 The DOA SMPS

The 12 V / 5 A SMPS the team bought was defective out of its plastic bag. It produced a solid 12.0 V on the multimeter with no load connected, which is the only test anyone thought to run at the shop. Once connected to even the 1.5 A of the Raspberry Pi 5, camera, and ESP32 combined, the output collapsed down to about 6 V and the Pi threw undervoltage lightning bolts on the debug monitor. The team spent the better part of two weeks chasing ghosts before diagnosing it. The ESP32 would brown out and watchdog-reset mid-sort for no obvious reason. The servos would twitch randomly when the stepper turned on. The conveyor motor would barely spin. Every subsystem looked individually broken. It was only when Rokon disconnected the SMPS and ran the Pi alone off a phone charger that everything suddenly stabilized — at which point the group realized the supply itself was the problem.

### 4.3 The LiPo Workaround

A replacement SMPS was not easily obtainable in time, so the team fell back on the only 12 V-class energy source they had available: three older 3-cell, 11.1 V, 2200 mAh lithium-polymer packs that Rokon had left over from previous hobby builds. These packs kept the project alive, but they introduced their own list of constraints:

- **Low capacity.** A 2200 mAh 3S pack stores roughly 26 watt-hours of energy. With the full system drawing somewhere between 1.5 and 2.5 A at peak depending on what was running at that instant, a fully charged pack would last only 30 to 40 minutes of real testing time. A typical lab work session therefore followed a rhythm: test for half an hour, pack dies, swap in the next one, wait.
- **One balance charger.** The team owned exactly one hobby-grade balance charger for the LiPo packs. So only one of the three packs could be recharging at any given time. For most of the build period the group was effectively running on one-and-a-half packs, not three. There was never a moment when two fully charged spares sat waiting.
- **Voltage sag under load.** The packs were old and not particularly high-discharge rated. When the 28BYJ-48 stepper accelerated and all five servos were drawing their stall currents simultaneously, the pack voltage sagged enough that the Pi's undervoltage detector would still occasionally fire. The software had to derate the stepper's acceleration profile by about 40% just to keep the whole system above the brownout line.
- **Grounding discipline when swapping packs.** Every swap was an opportunity to miswire something. The team accidentally back-powered the USB-serial chip twice while fumbling with XT60 connectors in a hurry, and each incident cost an hour of panicked "is the ESP32 dead?" debugging before they realized what had happened.

### 4.4 The Takeaway

Power is the first subsystem to test and double-test. An SMPS is not known-good until you have loaded it with a dummy resistor on the bench and watched the output voltage stay put. Everyone on this team will know that for the rest of their careers.

---

## 5. AI Pipeline and Sensing Logic

### 5.1 Dataset and Model Training

The original plan laid out in [plan for dataset.txt](file:///d:/Programming/Arduino%20Stuff/rpi5%20potato%20sorter/plan%20for%20dataset.txt) called for a richer and more multi-modal AI pipeline than what eventually shipped: visual classification layered on top of load-cell weight data, possibly combined with an object-detection step to first crop the potato ROI out of the frame before classifying it, and support for multiple crop types beyond potatoes alone. Reality was messier.

Sameer downloaded the five-class potato dataset from the IEEE Xplore paper referenced in the plan (document 1009916), which came as raw image folders organized by class name. The dataset was usable but had real quality problems: a noticeable fraction of the images were visibly mislabeled, the per-class counts were heavily skewed, and the photographs had been taken under a mix of natural and artificial lighting that did not match the flat, diffused, indoor LED lighting inside the team's white plastic chamber. The first two training runs of YOLOv8n-cls on Sameer's home GPU produced garbage — models that confidently classified everything as "Lower Quality" regardless of what was in the frame. The third run, after a manual pass to drop the obviously mislabeled images and augment the rest with rotations and color jitter in the training pipeline, finally produced a working checkpoint.

That checkpoint was exported to ONNX at 224×224 input size with the `simplify=True` flag per the instructions in [the models README](file:///d:/Programming/Arduino%20Stuff/rpi5%20potato%20sorter/models/README.md), yielding `potato_yolov8n_cls.onnx`. That ONNX file is the one piece of deliverable software that is not physically present in this project folder — it lived on the Raspberry Pi 5's SD card for the demo — but it is the core model that actually ran on the device.

The multi-model, multi-crop plan was abandoned early. Two heavier model variants that the team benchmarked on the Pi 5 CPU — a larger YOLOv8s-cls and an ensemble of two onnx files — ran at roughly 2 to 3 frames per second end-to-end, which would have made the five-frame aggregation window take over two seconds per potato and destroyed the throughput of the machine. The group kept the single lightweight model that hit about 14 FPS on the Pi 5, accepted that it would sort potatoes only, and moved on.

### 5.2 Inference Engine

The inference wrapper in [inference_engine.py](file:///d:/Programming/Arduino%20Stuff/rpi5%20potato%20sorter/inference_engine.py) loads the ONNX file with `onnxruntime` for CPU execution. A deliberate and very useful feature of this wrapper is the simulation mode. If the `.onnx` file is missing from the `models/` folder, the engine does not crash. Instead it returns randomized but class-plausible classifications with realistic-looking confidence values. This turned out to be an enormous time saver during the weeks when the model training was still being worked on, because the rest of the pipeline — stepper, serial bridge, servo push, conveyor, database logging, and web dashboard — could all be exercised and debugged without requiring a working neural network.

### 5.3 Sensors That Never Got Integrated

Three sensor subsystems made it onto the merged initial plan and were crossed off one by one as the semester ran out:

- **Temperature and humidity sensors.** The plan had called for DHT22 or BME280 sensors mounted inside each of the three storage bins, with readings polled once a minute and written to a separate history table. These were cut purely for lack of time in the final week, not for lack of parts — the sensors were sitting in a bag on the workbench, unused, on demo day.
- **Load cell and HX711 amplifier.** The specific load cell the team bought was faulty. When Sameer wired it up on a breadboard with an Arduino Nano and a known-good HX711 library, the raw readings drifted wildly with no weight on the cell and could not be tared or calibrated even with known calibration weights. The whole weight-sorting feature was therefore removed from the design document entirely rather than delay the rest of the machine waiting for a replacement.
- **Potato position sensors (IR or limit switches).** The team never got around to wiring IR photo-interrupters or micro-switches along the conveyor, so there was no hardware feedback about when a potato had actually left the push arm, reached the sorting flaps, or dropped into a bin. Every timing decision was a software-estimated delay, which is a big part of why the sorting flaps never synced up reliably.

---

## 6. Software and User Interface

### 6.1 Raspberry Pi 5 Main Software Stack

| Layer          | Component                        | Primary Location |
|----------------|----------------------------------|------------------|
| Operating Sys  | Raspberry Pi OS 64-bit Bookworm  | —                |
| Language       | CPython 3.11                     | —                |
| Web framework  | Flask 3.x                        | `app.py`         |
| Inference      | ONNX Runtime 1.17                | `inference_engine.py` |
| Serial I/O     | `pyserial` wrapper               | `serial_bridge.py` |
| GPIO control   | `gpiozero` + `RPi.GPIO`          | `hardware_controller.py` |
| Database       | `sqlite3` standard library       | `database.py`    |
| Camera capture | `libcamera` + OpenCV `VideoCapture` | `app.py` MJPEG generator |

The install script in [setup.sh](file:///d:/Programming/Arduino%20Stuff/rpi5%20potato%20sorter/setup.sh) documents the full apt and pip dependency chain needed to get from a fresh Bookworm image to a running application.

### 6.2 Web Dashboard

The browser dashboard is Fahim's main contribution to the software side of the project. The page layout is intentionally operator-friendly, with the live video feed front and center:

- The top of the page has a banner with the project title and a serial-connection status LED on the far right (green when `/api/ping` round-trips cleanly, red otherwise).
- The left column holds the 320×240 MJPEG camera preview from `/video_feed`, with a large blue **Start Scan** button directly underneath, and a row of smaller hardware test buttons below that for the rotating motor, the push arm, the conveyor forward/stop, each of the three sorting flaps individually, and an E-Stop.
- The right column shows the **Last Scan** widget — detected class, confidence percentage, letter grade, and timestamp. Below that widget is an auto-refreshing audit table of the twenty most recent scans pulled from the SQLite database.

All styling is hand-written CSS in [style.css](file:///d:/Programming/Arduino%20Stuff/rpi5%20potato%20sorter/static/css/style.css) with a clean blue-on-white palette, and the client-side interactivity is plain vanilla JavaScript in [main.js](file:///d:/Programming/Arduino%20Stuff/rpi5%20potato%20sorter/static/js/main.js) using `fetch()` against the Flask routes. No React, no build step, no npm install required on the Pi.

The sibling folder `WEB UI, physical UI, Database` also contains a second, more ambitious alternative design for a physical operator panel — a 20×4 LCD over I²C, a rotary encoder, and 4-digit seven-segment bin counters — with schematics and a working breadboard sketch. That panel was never soldered into the final machine for lack of time, but all the design work for it is in that folder.

### 6.3 Database Layer

The `SorterLogger` class in `database.py` creates, on first use, a SQLite file at `logs/sorter_logs.db` with a single table:

```sql
CREATE TABLE IF NOT EXISTS scans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
    top_class   TEXT,
    confidence  REAL,
    grade       TEXT,
    notes       TEXT
);
```

Every completed scan is inserted into this table before the dashboard ever renders it back to the user. This was a working feature on demo day — the evaluators were able to scroll back through the history table and see every classification from the test runs, including timestamps.

### 6.4 Physical Buttons

The white plastic case of the machine does have two rectangular cutouts for panel-mount buttons — one START button near the entry chute and one STOP/E-STOP near the exit. Those buttons were never wired in. A panel-mount cable gland for a 20×4 LCD was also drawn on the case blueprint and never cut. The operator interface that actually made it to the demo was purely the web page.

---

## 7. Budget and Bill of Materials

The Raspberry Pi 5 was provided by the university department for the semester. The remaining components were purchased out of pocket by the team and totaled approximately **8,000 Bangladeshi taka (BDT)**. The table below breaks this down by line item; prices are rounded to the nearest 50 taka at local electronics market rates at the time of purchase.

| Qty | Item                                               | Unit Price (TK) | Line Total (TK) |
|-----|----------------------------------------------------|-----------------|-----------------|
| 1   | ESP32 DevKit V1 (38-pin, WROOM-32)                 | 750             | 750             |
| 1   | Sony IMX219 8 MP camera module for Raspberry Pi    | 550             | 550             |
| 5   | MG996R metal-gear servo (TowerPro clone)           | 350             | 1,750           |
| 1   | 28BYJ-48 geared stepper + ULN2003 driver board     | 400             | 400             |
| 1   | 12 V brushed DC gearmotor + L298N dual H-bridge    | 500             | 500             |
| 1   | Conveyor belt kit (rubber belt, 2 pulleys, axles)  | 900             | 900             |
| 1   | White ABS plastic project enclosure (PC-tower form) | 700             | 700             |
| 1   | 12 V / 5 A enclosed SMPS (defective, eventually unused) | 800         | 800             |
| 3   | 3S 11.1 V 2200 mAh LiPo (from Rokon's hobby stock) | 0               | 0               |
| 1   | Single-channel LiPo balance charger (shared gear)  | 600             | 600             |
| 2   | Full-size breadboard, assorted dupont jumper wires | 250             | 500             |
| 1   | Strip perfboard, solder, male/female header pins   | 300             | 300             |
| —   | Acrylic sheet, hot-glue sticks, standoffs, screws, 3D-printed brackets and pulleys | — | 800 |
| —   | USB cables, XT60 connectors, power distribution wiring | 150         | 150             |
|     | **Grand total (excl. Raspberry Pi 5)**             |                 | **≈ 7,900**     |

The rounding on consumables and the few small incidentals not listed bring the actual out-of-pocket spend to the 8,000 taka figure the team reported.

---

## 8. Team Contributions and Division of Work

The project was divided into four major work areas among the five-person team, with a small amount of overlap and cross-support during the final push.

### 8.1 Sameer — AI, Raspberry Pi 5, Rotating Platform, Push Arm

Sameer was the de facto integration lead for the project:

- He located and downloaded the IEEE potato dataset, ran three full training runs on his home GPU until he got a usable checkpoint, exported the model to ONNX, and wrote the inference engine wrapper and the five-frame aggregation logic.
- He wrote the Flask application skeleton in `app.py`, the camera MJPEG stream generator, the GPIO stepper tuning in `hardware_controller.py`, and the database glue that writes each scan to SQLite.
- He personally designed and iterated through all three rotating-platform concepts, and built the final foam-covered disc that worked on demo day.
- He also designed and mounted the feed push arm — the single subsystem that worked 100% of the time on presentation day.

### 8.2 Fahim — Web UI, Physical UI Design, Conveyor Rework

- Fahim designed and built the browser dashboard that the evaluators actually used: the HTML layout, the custom CSS, the vanilla JavaScript interaction layer, and the integration of the test buttons with the serial API endpoints.
- He also produced a complete second design for a physical operator panel (LCD 2004, rotary encoder, seven-segment bin counters) including schematics and a working breadboard sketch, which lives in the `WEB UI, physical UI, Database` folder. The panel-mount button mechanism itself — the START/STOP buttons on the case — was planned and drawn up but never soldered in.
- During the last week before the demo, when the conveyor belt frame was threatening to come apart entirely, Fahim helped Saker re-brace and re-tension it.

### 8.3 Saker — Conveyor Belt Subsystem

- Saker was the primary owner of the conveyor belt from first concept to final assembly. He selected the belt and pulley kit, built the first sheet-metal frame, mounted the DC motor and the L298N driver, and got the first version of the belt moving under its own power.
- Structural integrity problems and the lack of closed-loop speed control plagued the subsystem throughout, but with Fahim's help in the final week he produced a version that ran continuously through the demo without throwing the belt.

### 8.4 Ador — Sorting Servo Arms, ESP32 Firmware

- Ador wrote the ESP32 firmware that receives serial commands from the Pi and drives the L298N and the three sorting servos over LEDC PWM channels.
- He designed and built the mechanical diverter flaps and servo mounts for all three bin arms.
- In practice, only the Grade A flap moved reliably during testing, and it moved slowly; the other two arms were wired and testable from the dashboard but inconsistent enough that the team did not trust them during the live demo.

### 8.5 Rokon — Sorting Calibration, ESP32 Support, Power System

- Rokon supported Ador on the ESP32 side during bring-up, helped tune the servo PWM ranges and the sweep timing for the flaps, and reworked the soldering on the perfboard several times as the wiring changed.
- He was also the person who finally diagnosed the faulty SMPS after a week and a half of confusing subsystem failures, and who supplied the three LiPo packs and the single balance charger that kept the project testable for the rest of the semester.
- He owned the power-distribution harness layout and spent several evenings re-doing XT60 connectors and star-ground wiring as the architecture shifted from SMPS to battery power.

### 8.6 Cross-Cutting Team Issues

Three cross-cutting issues affected everyone's productivity across the entire semester:

- **Geographic dispersion.** Four of the five team members lived well outside easy walking or commuting distance from the campus workshop, and some had two-hour one-way trips. Getting all five people in the same room on the same day was a scheduling victory. A large fraction of the build happened on days with only two or three members physically present, which slowed integration work.
- **Uneven prior experience.** Nobody on the team came into the course having done ONNX Runtime inference on a Raspberry Pi 5 before. Nobody had built a working conveyor belt. Nobody had soldered a multi-rail power harness. The learning curve was real, and it consumed weeks that the original Gantt chart had assumed would be spent building.
- **Tools and materials spread out.** A working multimeter lived at one person's house. A good temperature-controlled soldering station lived at another's. A hot-glue gun and a supply of glue sticks lived at a third. Swapping a part or re-soldering a joint sometimes meant half a day of coordinating pickup and drop-off instead of actually working on the machine.

---

## 9. Challenges, Problem Solving, and Lessons Learned

### 9.1 Material Sourcing

Finding the right material at the right time was a constant low-grade friction. A bracket would be designed around a specific diameter of shaft; the shop would not have it, and the only alternatives were a weekend trip to a different part of the city or a redesign. A 3D-printed pulley would crack on first use, and the only printer available on campus would have a two-day queue. The cumulative delay from dozens of small sourcing problems was more than the delay from any single big failure.

### 9.2 Tools Were Spread Out

As noted above, the team's tools were geographically distributed along with the team members. A trivial soldering fix that should have taken three minutes could take half a day if the soldering station happened to be in a different part of the city than the machine. By the end of the project, the group had consolidated the most-used tools into a single plastic toolbox that lived with the machine itself; this was one of the most underrated process improvements the team made.

### 9.3 Trial and Error Beat Clever Design

The rotating platform is the canonical example. Two clever, paper-perfect designs failed in cardboard mockups or early assembly. The third design — a boring, flat disc on a motor shaft — won on the first try. The lesson the whole team took away is that if you are building with hobbyist-grade tools and hobbyist-grade skills, the boring solution that you can actually build today is better than the clever solution that requires a week of custom parts you cannot reliably source.

### 9.4 Aggressive Scope Cuts Were the Right Call

The original merged initial plan was beautiful on paper and impossible for five overloaded students to deliver in a single semester. Cutting the multi-crop classifier, the weight sensor, the environmental sensors, the physical pushbutton panel, and the IR position sensors one by one was painful, but every one of those cuts bought time that was needed to get the core pipeline actually working. A small working demo beats a grand non-working plan every time.

### 9.5 Teamwork Took Practice

The first few team meetings were long, loud, and not especially productive: five people with five opinions and no clear owner for each subsystem. Once the group agreed on the four work-area split described in Section 8, with a single accountable owner for each area and Sameer as the final integration tiebreaker, meetings got shorter and progress got faster. Learning to work together was, in many ways, the real deliverable of the course.

---

## 10. Results — What Worked and What Did Not

### 10.1 Subsystems That Were Working on Demo Day

| Subsystem                              | Status           | Notes |
|----------------------------------------|------------------|-------|
| 360° rotating disc (Iteration 3)       | Fully working    | 100% reliable across all test runs. |
| Feed push arm on MG996R                | Fully working    | Every potato was ejected cleanly. |
| IMX219 camera + MJPEG live stream      | Working          | Live preview visible in dashboard with no visible lag. |
| ONNX potato classifier (5 classes)     | Working          | Classified consistently under the chamber's lighting. |
| 5-frame grade aggregation              | Working          | Clearly more stable than any single-frame judgement. |
| Web dashboard UI                       | Working          | Start button, live video, Last Scan widget, audit history, all test buttons responsive. |
| SQLite audit log                       | Working          | Every scan written to `scans` table, visible in dashboard. |
| Serial protocol RPi 5 ↔ ESP32          | Working          | PING, MOTOR, PUSH, CONVEYOR, SORT, ESTOP all round-tripped cleanly. |
| Conveyor belt movement                 | Barely working   | Moved forward continuously for the demo, but drifted in speed and needed manual adjustment between runs. |
| Sorting arm — Grade A only             | Barely working   | Moved reliably but slowly; the other two arms were not used in the live demo. |

### 10.2 Subsystems That Did Not Work, Were Cut, or Were Never Delivered

| Subsystem                                       | Final Status        | Primary Root Cause |
|-------------------------------------------------|---------------------|--------------------|
| Sorting arms — Grade B and Grade C              | Non-operational     | Inconsistent motion, timing drift vs. open-loop conveyor. |
| Conveyor closed-loop speed control              | Never implemented   | No encoder was fitted; no time to add PID tuning. |
| Conveyor structural frame                       | Marginal            | Thin sheet metal flexed; idler axle walked. |
| Panel-mount physical START / STOP buttons       | Not delivered       | Cutouts in the case were made; never wired. |
| Physical LCD 20×4 + rotary encoder panel        | Designed only       | Schematics and breadboard proof done in UI folder; not soldered in. |
| Temperature / humidity sensors (storage bins)   | Cut                 | Parts purchased; time ran out before integration. |
| Load cell + HX711 weight measurement            | Cut                 | The purchased load cell was defective out of the bag. |
| IR / limit-switch potato position tracking      | Cut                 | Ran out of both GPIO headroom and time. |
| Multi-crop classifier (potato + tomato + etc.)  | Cut                 | Dataset quality, GPU training time, and Pi FPS constraints. |
| Multi-model / ensemble inference                | Cut                 | Heavier models were too slow on the Pi 5 CPU. |
| 12 V / 5 A SMPS power supply                    | DOA / unused        | Output collapsed under load; replaced with LiPo packs. |

### 10.3 The Demo Run

What the evaluators actually saw on demo day was this: a potato is placed in the entry chute and rolls onto the stationary rotating disc inside the white case. The operator clicks Start on the web dashboard. The disc spins through one full revolution; the live feed shows the five captures happening; the Last Scan widget updates with the class, confidence, and Grade A/B/C within about one second of the rotation finishing; the push arm sweeps and the potato cleanly exits onto the head of the moving conveyor belt; the belt carries it past the three sorting flaps, and the Grade A flap (the only one trusted) dips to guide a Grade A tuber into its bin. The pipeline ran end to end, which was the bar the team had set for themselves once the scope cuts were accepted.

---

## 11. Future Development

A v2 of this machine built on what was learned would fix the weakest links first, in roughly this order:

1.  **Power supply, done right.** A name-brand 12 V / 10 A enclosed industrial SMPS, load-tested on the bench with a 1 ohm power resistor before any other subsystem is connected. A separate 5 V / 6 A rated BEC for the servo bank, star-grounded at one terminal block. No more LiPo workarounds.
2.  **Closed-loop, rigid conveyor.** Replace the 12 V brushed DC motor with a gearmotor that has a quadrature encoder on the output shaft. Move the conveyor drive to the ESP32 with a simple PID loop on the encoder feedback so belt speed is actually constant regardless of battery or mains sag. Replace the sheet-metal frame with 2020-series aluminum extrusion — cheap, rigid, and infinitely adjustable.
3.  **All three sorting flaps working properly.** Use short, stiff servo horns and a 4-bar linkage so that 60° of servo motion produces a full 90° flap travel, cutting the sweep time roughly in half. Calibrate each flap against the real encoder-based travel time of the belt, not a guessed delay.
4.  **Environmental sensors done simply.** I²C BME280 modules (one per bin) instead of DHTs for better long-term stability. Add a second SQLite table for timestamped bin-environment history, and a tab in the web dashboard to graph it.
5.  **Working weight sensor.** A new, known-good 5 kg load cell with a fresh HX711, tared on a precision weight set, and the `scans` table extended with a `weight_g` column.
6.  **Potato position sensing.** One IR photo-interrupter at each of three key points: immediately after the push arm, at the first sorting flap, and past the last sorting flap. This turns every timing guess into a hardware event and makes the sort cycle deterministic.
7.  **Physical operator buttons finished.** The two panel-mount cutouts are already in the case; soldering in real switches and wiring them to GPIOs or the ESP32 is a weekend job.
8.  **In-domain dataset refresh.** Re-label and re-train the classifier on a few hundred photos actually taken inside the machine's own chamber lighting, instead of relying entirely on a public dataset shot in different conditions. A few rounds of active learning would boost accuracy more than any model-size increase.
9.  **Re-introduce multi-crop support one crop at a time.** Start with tomatoes as the second class now that the basic conveyor-and-sorter skeleton is proven.
10. **UPS / battery backup.** A small enclosed lead-acid battery and a charger module so the machine can keep logging and keep sorting through short power cuts, which are a fact of life for any rural deployment the team would eventually want to target.

---

## 12. Conclusion

This project was, in the end, as much an education in real-world engineering teamwork as it was a deliverable for a microcontroller laboratory course. Five people with uneven prior skills, living far apart, handed a defective power supply and an initial plan that wanted too much from a single semester, converged over the final month on a set of aggressive scope cuts and a simplified mechanical design that actually ran.

What survived to demo day is a coherent machine: an ONNX-powered vision system running locally on a Raspberry Pi 5, grading real potatoes into three quality tiers using visual evidence from five camera captures distributed across a full 360° rotation; a rotating scanning platform that won the project on its third, deliberately simple mechanical iteration; a push arm that never misfired once; a web dashboard that the evaluators could actually use to run the machine; and a SQLite database that recorded every scan.

What did not survive is a long list too: two of the three sorting flaps, closed-loop conveyor speed, environmental sensors, weight measurement, panel-mounted operator buttons, multi-crop support, and the original SMPS that died on day one.

By the end of the semester, every one of the five team members could produce a longer list of things they would do differently on the next machine than things they already knew how to do going in. That outcome is arguably the real point of a project-based microcontroller laboratory course. A perfect machine would have taught them less.

---

*End of Report*
