
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import copy

SRC = r"d:\Programming\Arduino Stuff\rpi5 potato sorter\Micro Final Project Report.docx"
OUT = r"d:\Programming\Arduino Stuff\rpi5 potato sorter\Micro Final Project Report.docx"

doc = Document(SRC)

FONT_H2 = ("Arial", 17)
FONT_H3 = ("Arial", 13)
FONT_BODY = ("Arial", 12)
FONT_COVER = ("Bodoni", 18)
FONT_COVER_LARGE = ("Bodoni", 20)

KEEP_UNTIL_PARA_IDX = 13  # paragraphs[13] is "1. Introduction" heading (KEEP) + its body paragraphs[14] KEEP, so after intro we start inserting
# Actually paragraphs 0..13 are:
# 0-9 cover lines
# 10 empty, 11 empty heading2, 12 heading2 = "1. Introduction" (empty text?) wait no. check again
# From inspect: [012] style=Heading 2 text='1. Introduction'  (index 12)
# [013] style=Normal body intro text (index 13)   -> KEEP THIS, it IS the intro body.
# [014] style=Heading 2 text='2. Hardware Construction'  -> THIS IS OLD Cane content, REMOVE.

# So keep paragraphs 0..13 inclusive (14 paragraphs). Remove everything >= 14, remove tables >= 1 (keep Table 0 = "Submitted by")

KEEP_PARAS = 14  # indices 0..13
KEEP_TABLES = 1  # keep Table 0 only (submitted-by); Table 1 is old cane BOM


def clear_paragraphs_from(doc, start_idx):
    # Remove elements in reverse
    paras = list(doc.paragraphs)
    for p in paras[start_idx:]:
        p._element.getparent().remove(p._element)


def clear_tables_from(doc, start_idx):
    tables = list(doc.tables)
    for t in tables[start_idx:]:
        tbl = t._tbl
        tbl.getparent().remove(tbl)


# ============ 1. CLEAN OUT OLD CONTENT ============
clear_paragraphs_from(doc, KEEP_PARAS)
clear_tables_from(doc, KEEP_TABLES)


def add_heading2(doc, text):
    p = doc.add_paragraph(style="Heading 2")
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    run = p.add_run(text)
    run.font.name = FONT_H2[0]
    run.font.size = Pt(FONT_H2[1])
    # Ensure east-asian font name too
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = OxmlElement('w:rFonts')
        rPr.insert(0, rFonts)
    rFonts.set(qn('w:ascii'), FONT_H2[0])
    rFonts.set(qn('w:hAnsi'), FONT_H2[0])
    return p


def add_heading3(doc, text):
    p = doc.add_paragraph(style="Heading 3")
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    run = p.add_run(text)
    run.font.name = FONT_H3[0]
    run.font.size = Pt(FONT_H3[1])
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = OxmlElement('w:rFonts')
        rPr.insert(0, rFonts)
    rFonts.set(qn('w:ascii'), FONT_H3[0])
    rFonts.set(qn('w:hAnsi'), FONT_H3[0])
    return p


def add_body(doc, text, bold_prefix_pairs=None):
    """Add a justified normal paragraph.
    bold_prefix_pairs: list of (bold_prefix_string, rest_string). If None, plain text."""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    if bold_prefix_pairs is None:
        run = p.add_run(text)
        run.font.name = FONT_BODY[0]
        run.font.size = Pt(FONT_BODY[1])
        rPr = run._element.get_or_add_rPr()
        rFonts = rPr.find(qn('w:rFonts'))
        if rFonts is None:
            rFonts = OxmlElement('w:rFonts')
            rPr.insert(0, rFonts)
        rFonts.set(qn('w:ascii'), FONT_BODY[0])
        rFonts.set(qn('w:hAnsi'), FONT_BODY[0])
    else:
        for prefix, rest in bold_prefix_pairs:
            if prefix:
                rb = p.add_run(prefix)
                rb.bold = True
                rb.font.name = FONT_BODY[0]
                rb.font.size = Pt(FONT_BODY[1])
                rPr = rb._element.get_or_add_rPr()
                rFonts = rPr.find(qn('w:rFonts'))
                if rFonts is None:
                    rFonts = OxmlElement('w:rFonts')
                    rPr.insert(0, rFonts)
                rFonts.set(qn('w:ascii'), FONT_BODY[0])
                rFonts.set(qn('w:hAnsi'), FONT_BODY[0])
            if rest:
                rn = p.add_run(rest)
                rn.font.name = FONT_BODY[0]
                rn.font.size = Pt(FONT_BODY[1])
                rPr = rn._element.get_or_add_rPr()
                rFonts = rPr.find(qn('w:rFonts'))
                if rFonts is None:
                    rFonts = OxmlElement('w:rFonts')
                    rPr.insert(0, rFonts)
                rFonts.set(qn('w:ascii'), FONT_BODY[0])
                rFonts.set(qn('w:hAnsi'), FONT_BODY[0])
    return p


def add_bullet(doc, prefix_bold, rest):
    p = doc.add_paragraph(style="List Bullet")
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    if prefix_bold:
        rb = p.add_run(prefix_bold)
        rb.bold = True
        rb.font.name = FONT_BODY[0]
        rb.font.size = Pt(FONT_BODY[1])
    rn = p.add_run(rest)
    rn.font.name = FONT_BODY[0]
    rn.font.size = Pt(FONT_BODY[1])
    return p


def set_cell_borders(cell, sz="4", color="auto"):
    """Set cell borders directly via XML. sz is in eighths of a point; 4 => 0.5pt."""
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    old = tcPr.find(qn('w:tcBorders'))
    if old is not None:
        tcPr.remove(old)
    tcBorders = OxmlElement('w:tcBorders')
    for edge in ('top', 'left', 'bottom', 'right'):
        b = OxmlElement('w:' + edge)
        b.set(qn('w:val'), 'single')
        b.set(qn('w:sz'), sz)
        b.set(qn('w:space'), '0')
        b.set(qn('w:color'), color)
        tcBorders.append(b)
    tcPr.append(tcBorders)


def set_cell_font(cell, text, bold=False, size=FONT_BODY[1], font=FONT_BODY[0], align_center=False):
    cell.text = ""
    p = cell.paragraphs[0]
    if align_center:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    else:
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = p.add_run(text)
    run.bold = bold
    run.font.name = font
    run.font.size = Pt(size)
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = OxmlElement('w:rFonts')
        rPr.insert(0, rFonts)
    rFonts.set(qn('w:ascii'), font)
    rFonts.set(qn('w:hAnsi'), font)


def style_table_borders(table):
    for row in table.rows:
        for cell in row.cells:
            set_cell_borders(cell)


# ============ 2. APPEND NEW CONTENT (POTATO SORTER) ============

# --- 2. System Architecture ---
add_heading2(doc, "2. System Architecture")
add_body(doc, "The overall sorting system is a two-controller architecture with a clean separation of concerns. Computationally heavy work — camera capture, neural network inference, web serving, database logging, and decision aggregation — runs on a Raspberry Pi 5. Real-time motor and servo control lives on an ESP32 microcontroller. The two boards communicate over USB serial at 115,200 baud.")

add_heading3(doc, "2.1 High-Level Data Flow")
add_body(doc, "A single sorting cycle proceeds as follows. The operator clicks Start on the web dashboard. The RPi 5 begins a full turn of the rotating platform and simultaneously captures five still frames from the IMX219 camera spaced across the 360° rotation. Each frame is classified locally on the Pi using ONNX Runtime, the five resulting softmax vectors are averaged, and the winning class is mapped to Grade A, B, or C. The grade is written to the SQLite audit log, the dashboard Last Scan widget is updated, and a serial command is dispatched to the ESP32: first SERVO_PUSH to eject the potato onto the conveyor belt, then CONVEYOR_START, then SORT_BIN_{A,B,C} to trigger the appropriate flap when the tuber is estimated to reach the end of the belt.")

add_heading3(doc, "2.2 Serial Communication Protocol")
add_body(doc, "The RPi 5 is the bus master; the ESP32 only responds when addressed. The command envelope is plain ASCII lines for easy debugging with nothing more than a serial terminal. Commands follow ACTION:<cmd>\\n, and replies follow STATUS:<ok|err>:<detail>\\n. The vocabulary implemented by demo day included MOTOR_SPIN start/stop, SERVO_PUSH, CONVEYOR_START, CONVEYOR_STOP, SORT_BIN_A, SORT_BIN_B, SORT_BIN_C, ESTOP, and PING, which the dashboard uses to show its green/red serial-connection LED.")

add_heading3(doc, "2.3 Five-Frame Aggregation Policy")
add_body(doc, "The system does not make a one-shot classification from a single top-down photo, because a round potato reliably hides roughly half its surface from any one viewpoint. Instead, five 224×224 frames are captured at regular angles during one full revolution and each is classified independently. Their per-class softmax scores are averaged element-wise, and the highest-average class index is read off as the final class, then mapped to a letter grade: Good → Grade A, Lower Quality → Grade B, Rotten/Scabs/Damaged → Grade C. Aggregating evidence from five angles eliminates single-frame glares and shadows and dramatically stabilizes the final grade.")

# --- 3. Hardware Construction ---
add_heading2(doc, "3. Hardware Construction")
add_body(doc, "The finished machine is housed in a white plastic enclosure roughly the size and shape of a small desktop PC tower. A cutout on the left front is the entry chute, where a potato is loaded and rolls onto the scanning platform. A second cutout on the right side is the exit chute, where the push arm ejects the graded tuber onto the head of the conveyor belt. The Raspberry Pi 5, camera module, USB-serial adapter, and stepper driver live inside the enclosure; the ESP32, L298N motor driver, and servo power wiring are bolted to a perfboard strip on the inner back wall.")

add_heading3(doc, "3.1 360° Rotating Scanning Platform — Three Iterations")
add_body(doc, "The rotating platform was the single most mechanically iterative piece of the project. It went through three full design cycles before reaching a build that actually worked, and the process illustrates how clever paper designs very often lose to simple ones when real material, tolerance, and tooling constraints apply.")
add_body(doc, None, [("Iteration 1 – Rolling-pin rollers.  ", "The first concept called for a set of smooth parallel metal rollers under the potato, all driven in sync, whose axes were perpendicular to the direction of travel. The geometry looked fine in a 2D sketch but the team could not produce a clean FreeCAD model of the mounting brackets without binding, and the exact-size smooth pins the design required were not available locally. The design was scrapped before a single bracket was cut.")])
add_body(doc, None, [("Iteration 2 – Twin diagonal belts.  ", "The second concept tried to avoid custom pins entirely by using two rubber belts running in the same direction but offset at opposing angles. The theory was that a potato wedged between them would precess like a planet and naturally present every face to the overhead camera. A cardboard and hot-glue mockup told a different story: the potato either slid sideways across both belts without rotating, or if pressed down firmly enough to catch the rubber, it spun on a single fixed axis and still hid half its surface. Two afternoons of adjusting belt tension, angle, and center distance did not save it. Rejected.")])
add_body(doc, None, [("Iteration 3 – Flat rotating disc.  ", "The final design was deliberately unexciting: a single flat circular disc, press-fit directly onto the output shaft of a geared stepper motor, with a thin layer of closed-cell foam rubber glued to the top surface for grip. This version worked on the very first try. Every potato size the team tested — from small new potatoes to large baking potatoes — spun cleanly in place for as many revolutions as the stepper was commanded. Simple won. For a 360° view, a single turntable beat two clever mechanisms that nobody on the team could actually machine to tolerance.")])

add_heading3(doc, "3.2 Turntable Drive")
add_body(doc, "The disc is driven by a 28BYJ-48 unipolar stepper motor through a ULN2003 Darlington driver module. The team had originally planned a NEMA 17 with an A4988 carrier board for extra torque, but the budget for that was consumed by other surprises and the 28BYJ-48 is what was actually installed. At 2048 full steps per output revolution, the motion profile in hardware_controller.py runs the platform at roughly 15 rpm — slow enough that the camera gets five sharp frames, fast enough that the operator is not kept waiting.")

add_heading3(doc, "3.3 Conveyor Belt Subsystem")
add_body(doc, "The conveyor belt was Saker's primary deliverable, with Fahim pitching in to rework it during the final week. The belt ran over two plastic pulleys on a thin sheet-metal frame, driven by a brushed 12 V DC gearmotor through an L298N H-bridge. Two problems followed it to demo day. First, there was no closed-loop speed control — no encoder anywhere on the motor or pulley, just a raw PWM duty cycle written to the L298N, so belt speed drifted with the charge state of whichever battery pack was in use. Second, the frame flexed visibly under hand pressure and the idler axle had a habit of walking in its slot, which made the belt drift sideways and occasionally ride up over the pulley flange. Extra hot-glue gussets, a small spring on the idler, and Fahim's last-hour corner rework made it run continuously for the duration of the demo, but nobody on the team would call the final build robust.")

add_heading3(doc, "3.4 Feed Push Arm")
add_body(doc, "The small hinged paddle that ejects a graded potato off the rotating disc and onto the head of the conveyor was the single most reliable electromechanical subsystem on the whole machine. Sameer designed it as a 10 cm flat paddle on the output shaft of a metal-gear MG996R servo. A single SERVO_PUSH serial command raises the paddle from its parked vertical position, sweeps roughly 110° across the face of the disc, and returns. On demo day this arm worked every single time, without exception, across every test run for the evaluators.")

add_heading3(doc, "3.5 Sorting Servo Arms (Bin Diversion Flaps)")
add_body(doc, "Three more MG996R servos — one each for Grade A, B, and C — were mounted at the tail end of the conveyor belt, each driving a small diverter flap that could push a passing potato off the belt and into its corresponding storage bin. Ador wrote the ESP32 firmware for them and built the mechanical mounts. In practice, only the Grade A flap (the one closest to the head of the belt) moved reliably, and it moved slowly: a full sweep took about 1.5 seconds, which under the open-loop conveyor timing was right on the edge of being too slow for a normal-sized potato. The other two arms were wired and could be driven individually from the dashboard test buttons, but their motion was inconsistent and their timing relative to the conveyor travel was not trustworthy; they were treated as non-operational for the final live demo.")

# --- 4. Power System ---
add_heading2(doc, "4. Power System")
add_body(doc, "The power system is worth a dedicated chapter because it absorbed more collective troubleshooting hours than any single software module, and it was the root cause of more apparently-unrelated subsystem failures than anything else on the project. The short version: buy a good supply, and load-test it on the bench before you solder anything else to it.")

add_heading3(doc, "4.1 Original Design Intent")
add_body(doc, "The power architecture drawn up at the start of the semester was textbook and perfectly reasonable on paper. A 220 V AC input fed an enclosed 12 V 5 A switched-mode power supply (SMPS) mounted on the back of the case. A 12 V → 5 V 3 A buck converter fed the Raspberry Pi 5, the camera module, and the USB-serial chip. The raw 12 V rail fed the L298N H-bridge for the conveyor DC motor. A separate 5 V 2 A BEC tapped from the 12 V input powered the bank of MG996R servos, keeping the noisy servo currents off the Pi's clean 5 V rail. A single star-ground point at the SMPS output terminal, with every subsystem's ground wire returning to that one point, was supposed to prevent ground loops. None of that survived first contact with the actual hardware.")

add_heading3(doc, "4.2 The Dead-on-Arrival SMPS")
add_body(doc, "The 12 V 5 A SMPS the team bought was defective straight out of its plastic bag. It produced a solid 12.0 V on the multimeter with no load connected — which is the only test anyone thought to run at the shop. Once connected to just the 1.5 A baseline load of Raspberry Pi 5 + camera + ESP32, the output collapsed to roughly 6 V and the Pi threw undervoltage lightning bolts on its debug monitor. The team spent the better part of two weeks chasing ghosts before diagnosing it. The ESP32 would brown out and watchdog-reset mid-sort for no visible reason. The servos twitched randomly whenever the stepper turned on. The conveyor DC motor barely spun. Every subsystem individually looked broken. It was only when Rokon disconnected the SMPS and ran the Pi alone off a phone charger that everything suddenly stabilized — at which point the group realized the supply itself was the problem.")

add_heading3(doc, "4.3 The LiPo Workaround")
add_body(doc, "A replacement SMPS was not easily obtainable in time, so the team fell back on the only 12 V-class energy source they had available: three older 3-cell, 11.1 V, 2200 mAh lithium-polymer packs that Rokon had left over from previous hobby builds. These packs kept the project testable, but they introduced their own list of constraints.")
add_body(doc, None, [("Low capacity.  ", "A 2200 mAh 3S pack stores roughly 26 Wh. With the full system drawing between 1.5 and 2.5 A peak depending on what was running, a fully charged pack lasted only 30 to 40 minutes of real testing time. A typical lab work session therefore followed a rhythm of test for half an hour, pack dies, swap packs, wait.")])
add_body(doc, None, [("Single balance charger.  ", "The team owned exactly one hobby-grade balance charger for the LiPo packs, so only one of the three packs could be recharging at any moment. For most of the build period the group was effectively running on one-and-a-half packs, not three. There was never a moment when two fully charged spares sat waiting.")])
add_body(doc, None, [("Voltage sag under load.  ", "The packs were old and not particularly high-discharge rated. When the 28BYJ-48 stepper accelerated and all five MG996R servos drew their stall currents at the same instant, the pack voltage sagged enough that the Pi's undervoltage detector would still occasionally fire. The software had to derate the stepper's acceleration profile by roughly 40% just to keep the whole system above the brownout line.")])
add_body(doc, None, [("Grounding discipline while swapping packs.  ", "Every pack swap was an opportunity to miswire something. The team accidentally back-powered the USB-serial chip twice while fumbling with XT60 connectors in a hurry, and each incident cost an hour of panicked is-the-ESP32-dead debugging before they realized what had happened.")])

# --- 5. AI Pipeline and Sensor Logic ---
add_heading2(doc, "5. AI Pipeline and Sensor Logic")

add_heading3(doc, "5.1 Dataset and Model Training")
add_body(doc, "Sameer located and downloaded the five-class potato image dataset from the IEEE Xplore paper referenced in the original plan (document 1009916), which came as raw image folders organized by class name. The dataset was usable but had real quality problems: a noticeable fraction of the images were visibly mislabeled, per-class counts were heavily skewed, and the photographs had been taken under a mix of natural and artificial lighting that did not match the flat indoor LED lighting inside the team's white plastic chamber. The first two training runs of YOLOv8n-cls on Sameer's home GPU produced garbage — models that confidently classified everything as Lower Quality regardless of what was in the frame. The third run, after a manual pass to drop obviously mislabeled images and augment the rest with rotations and color jitter in the training pipeline, finally produced a working checkpoint. That checkpoint was exported to ONNX at 224×224 with the simplify=True flag, yielding potato_yolov8n_cls.onnx, which is the model that actually ran on the Raspberry Pi 5 during the demo. (The ONNX binary itself lived on the Pi's SD card and is not present in this project folder.)")

add_heading3(doc, "5.2 Model Selection and Scope Cuts")
add_body(doc, "The original merged plan called for a richer pipeline — layered visual classification + load cell weight data + a YOLO object-detection step to first crop the potato ROI + multi-crop support for potatoes, tomatoes, apples, and oranges. Most of that plan was abandoned early for concrete, measurable reasons. Two heavier model variants benchmarked on the Pi 5 CPU (a larger YOLOv8s-cls and a small ensemble of two ONNX files) ran at roughly 2 to 3 frames per second end-to-end, which would have stretched the five-frame aggregation window past two seconds per potato and destroyed throughput. The group kept the single lightweight YOLOv8n-cls that hit roughly 14 FPS on the Pi 5, accepted that it would only sort potatoes for the demo, and moved on.")

add_heading3(doc, "5.3 Inference Engine and Simulation Mode")
add_body(doc, "The inference_engine.py wrapper loads the ONNX file with onnxruntime for CPU execution. A deliberate and very useful feature of this wrapper is the simulation fallback. If the .onnx file is missing from the models/ folder, the engine does not crash. Instead it returns randomized but class-plausible classifications with realistic-looking confidence values. This turned out to be an enormous time saver during the weeks when the model training was still being worked on, because the rest of the pipeline — stepper, serial bridge, servo push, conveyor, database logging, and web dashboard — could all be exercised and debugged independently of whether a working neural network was present.")

add_heading3(doc, "5.4 Sensors That Never Got Integrated")
add_body(doc, "Three sensor subsystems made it onto the merged initial plan and were crossed off one by one as the semester ran out.")
add_body(doc, None, [("Temperature and humidity sensors.  ", "The plan called for DHT22 or BME280 sensors inside each of the three storage bins, with readings polled once a minute and written to a separate history table. These were cut purely for lack of time in the final week, not for lack of parts — the sensors were sitting in a bag on the workbench, unused, on demo day.")])
add_body(doc, None, [("Load cell and HX711 amplifier.  ", "The specific load cell the team bought was defective. When Sameer wired it up on a breadboard with an Arduino Nano and a known-good HX711 library, the raw readings drifted wildly with no weight on the cell and could not be tared or calibrated even with known calibration weights. The whole weight-sorting feature was therefore removed from the design document entirely rather than delay the rest of the machine waiting for a replacement.")])
add_body(doc, None, [("Potato position sensors (IR or limit switches).  ", "The team never got around to wiring IR photo-interrupters or micro-limit switches along the conveyor, so there was no hardware feedback about when a potato had actually left the push arm, reached the sorting flaps, or dropped into a bin. Every timing decision was a software-estimated delay, which is a major reason the sorting flaps never synced up reliably.")])

# --- 6. Software and User Interface ---
add_heading2(doc, "6. Software and User Interface")

add_heading3(doc, "6.1 Raspberry Pi 5 Software Stack")
add_body(doc, "The main controller runs Raspberry Pi OS 64-bit Bookworm on CPython 3.11. The web layer is Flask 3.x in app.py, which serves the dashboard page, the Motion JPEG camera stream from /video_feed, and the REST endpoints for scan, serial commands, and audit-log queries. Neural inference runs on the ONNX Runtime 1.17 CPU build inside inference_engine.py. Serial I/O to the ESP32 is handled by a thin pyserial wrapper in serial_bridge.py. GPIO control for the rotating platform stepper uses gpiozero and RPi.GPIO in hardware_controller.py. The scan history is persisted to SQLite via the SorterLogger class in database.py using the standard-library sqlite3 module. Camera capture goes through OpenCV VideoCapture on top of the libcamera stack. The full apt and pip dependency chain from a fresh Bookworm image to a running application is documented in setup.sh.")

add_heading3(doc, "6.2 Web Dashboard")
add_body(doc, "The browser dashboard is Fahim's main contribution to the software side of the project. The page layout is deliberately operator-friendly, with the live video feed front and center. The top banner holds the project title and a serial-connection status LED on the far right (green when /api/ping round-trips cleanly, red otherwise). The left column shows the 320×240 MJPEG camera preview, with a large blue Start Scan button directly underneath and a row of smaller hardware test buttons below that for the rotating motor, push arm, conveyor forward/stop, each of the three sorting flaps individually, and an E-Stop. The right column displays the Last Scan widget (detected class, confidence percentage, letter grade, and timestamp) and an auto-refreshing audit table of the twenty most recent scans pulled from the SQLite database. All styling is hand-written CSS with a clean blue-on-white palette, and client-side interactivity is plain vanilla JavaScript using fetch() against the Flask routes — no React, no build step, no npm install required on the Pi.")

add_heading3(doc, "6.3 Physical UI and Panel Buttons")
add_body(doc, "The WEB UI, physical UI, Database folder in the project repository contains a complete second design for a physical operator panel: a 20×4 character LCD over I²C, a rotary encoder for menu navigation, and 4-digit seven-segment bin counters, complete with schematics and a working breadboard sketch. The panel-mount button mechanism itself (START / STOP buttons on the case) was drawn up and rectangular cutouts for them were made in the white enclosure, but this physical panel was never soldered into the final machine for lack of time. The operator interface that actually made it to the final demo was purely the browser dashboard.")

add_heading3(doc, "6.4 Database Layer")
add_body(doc, "The SorterLogger class in database.py creates, on first use, a SQLite file at logs/sorter_logs.db with a single scans table containing id, timestamp, top_class, confidence, grade, and notes columns. Every completed scan is inserted into this table before the dashboard ever renders it back to the user, so the audit log is never lost even if the browser window is closed. On demo day the evaluators were able to scroll back through the history table and see every classification from the test runs, including their timestamps.")

# --- 7. Budget and Bill of Materials ---
add_heading2(doc, "7. Budget and Bill of Materials")
add_body(doc, "The Raspberry Pi 5 was provided by the university department for the semester. The remaining components were purchased out of pocket by the team and totaled approximately 8,000 Bangladeshi taka. The table below breaks this down by line item, with prices rounded to the nearest 50 taka at local electronics market rates at the time of purchase.")

bom_rows = [
    ["1", "ESP32 DevKit V1 (WROOM-32, 38-pin)", "1", "Slave motor/servo controller", "Dual-core, Wi-Fi + BLE"],
    ["2", "Sony IMX219 8 MP camera module", "1", "Visual grading input", "Raspberry Pi MIPI CSI-2"],
    ["3", "MG996R metal-gear servo", "5", "Push arm + 3 sorting flaps + spare", "Metal gears, 10 kg·cm stall torque"],
    ["4", "28BYJ-48 stepper + ULN2003 driver board", "1", "Rotating platform drive", "64:1 gear reduction, 5 V"],
    ["5", "12 V brushed DC gearmotor + L298N H-bridge", "1", "Conveyor belt drive", "Open-loop PWM speed control"],
    ["6", "Conveyor belt kit (rubber belt + 2 pulleys + axles)", "1", "Grade-A/B/C transport", "20 mm wide belt"],
    ["7", "White ABS plastic enclosure (PC-tower form)", "1", "Main case, scanning chamber housing", "Cutouts for entry/exit chutes"],
    ["8", "12 V 5 A enclosed SMPS", "1", "Main power (defective, unused)", "Output collapsed under load"],
    ["9", "3S 11.1 V 2200 mAh LiPo pack", "3", "Temporary replacement power", "From Rokon's hobby stock (no cost)"],
    ["10", "Single-channel LiPo balance charger", "1", "LiPo recharging", "Shared hobby equipment"],
    ["11", "Breadboard + dupont jumper wires (assorted)", "2", "Prototyping and bring-up", "Full-size, M-F, M-M, F-F"],
    ["12", "Strip perfboard + solder + header pins", "1", "ESP32 and power distribution", "Glass-epoxy, 2.54 mm pitch"],
    ["13", "Acrylic sheet, hot-glue sticks, standoffs, screws, 3D-printed brackets/pulleys", "Lot", "Structural and fasteners", "Consumables"],
    ["14", "USB cables, XT60 connectors, power distribution wiring", "Lot", "Harness", "Consumables"],
]

tbl = doc.add_table(rows=1 + len(bom_rows), cols=5)
style_table_borders(tbl)
# Header row
header = ["Item #", "Component", "Qty", "Function", "Specs / Notes"]
for ci, htext in enumerate(header):
    set_cell_font(tbl.rows[0].cells[ci], htext, bold=True, size=12, align_center=True)
for ri, row in enumerate(bom_rows, start=1):
    for ci, ctext in enumerate(row):
        align_center = (ci in (0, 2))
        set_cell_font(tbl.rows[ri].cells[ci], ctext, bold=False, size=11, align_center=align_center)

add_body(doc, "The small rounding on consumables and the few incidental parts not itemized bring the actual out-of-pocket spend to the ~8,000 taka figure the team reported.")

# --- 8. Team Contributions ---
add_heading2(doc, "8. Team Contributions and Division of Work")
add_body(doc, "The project was divided into four major work areas among the five-person team, with a small amount of overlap and cross-support during the final push.")

add_heading3(doc, "8.1 Sameer Hossain — AI Model, RPi 5 Software, Rotating Platform, Feed Arm")
add_body(doc, "Sameer was the de facto integration lead for the project. He located and downloaded the IEEE potato dataset, ran three full training runs on his home GPU until he got a usable checkpoint, exported the model to ONNX, and wrote both the inference engine wrapper and the five-frame aggregation logic. He also authored the Flask application skeleton in app.py, the camera MJPEG stream generator, the GPIO stepper tuning in hardware_controller.py, and the database glue that writes each scan to SQLite. On the mechanical side he personally designed and iterated through all three rotating-platform concepts and built the final foam-covered disc that worked on demo day, as well as designing and mounting the feed push arm that scored a perfect 100% reliability record on presentation day.")

add_heading3(doc, "8.2 Md. Thansirul Hoque Fahim — Web UI, Physical UI Design, Conveyor Rework")
add_body(doc, "Fahim designed and built the browser dashboard that the evaluators actually used on demo day: the HTML layout, the custom CSS, the vanilla JavaScript interaction layer, and the integration of the manual test buttons with the serial API endpoints. He also produced a complete second design for a physical operator panel — LCD 2004, rotary encoder, seven-segment bin counters — including schematics and a working breadboard sketch, which lives in the WEB UI, physical UI, Database folder. (The panel-mount button mechanism itself was planned and drawn up but never soldered in.) During the last week before the demo, when the conveyor belt frame threatened to come apart entirely, Fahim helped Saker re-brace and re-tension it.")

add_heading3(doc, "8.3 Saker Munshi — Conveyor Belt Subsystem")
add_body(doc, "Saker was the primary owner of the conveyor belt from first concept to final assembly. He selected the belt and pulley kit, built the first sheet-metal frame, mounted the DC gearmotor and the L298N driver, and got the first version of the belt moving under its own power. Structural integrity problems and the lack of closed-loop speed control plagued the subsystem throughout the build, but with Fahim's help in the final week he produced a version that ran continuously through the entire demo without throwing the belt.")

add_heading3(doc, "8.4 Romim Ahmed Ador — Sorting Servo Arms, ESP32 Firmware")
add_body(doc, "Ador wrote the ESP32 firmware that receives serial commands from the Raspberry Pi 5 and drives the L298N DC motor and the three sorting servos over LEDC PWM channels. He also designed and built the mechanical diverter flaps and servo mounts for all three bin arms. In practice, only the Grade A flap moved reliably during testing, and it moved slowly; the other two arms were wired and individually testable from the dashboard but inconsistent enough that the team did not trust them during the live demo.")

add_heading3(doc, "8.5 Md. Rokonuzzaman — Sorting Calibration, ESP32 Support, Power System")
add_body(doc, "Rokon supported Ador on the ESP32 side during bring-up, helped tune the servo PWM ranges and sweep timing for the three sorting flaps, and reworked the soldering on the perfboard several times as the wiring changed. He was also the person who finally diagnosed the faulty SMPS after a week and a half of confusing subsystem failures, and who supplied the three LiPo packs and the single balance charger that kept the project testable for the rest of the semester. He owned the power-distribution harness layout and spent several evenings re-doing XT60 connectors and star-ground wiring as the architecture shifted from SMPS to battery power.")

add_heading3(doc, "8.6 Cross-Cutting Team Issues")
add_body(doc, "Three cross-cutting issues affected everyone's productivity across the entire semester.")
add_body(doc, None, [("Geographic dispersion.  ", "Four of the five team members lived well outside easy walking or commuting distance from the campus workshop, and some had two-hour one-way trips. Getting all five people in the same room on the same day was a scheduling victory. A large fraction of the build happened on days with only two or three members physically present, which naturally slowed integration work.")])
add_body(doc, None, [("Uneven prior experience.  ", "Nobody on the team came into the course having done ONNX Runtime inference on a Raspberry Pi 5 before. Nobody had built a working conveyor belt. Nobody had soldered a multi-rail power harness. The learning curve was real, and it consumed weeks that the original Gantt chart had optimistically assumed would be spent building rather than learning.")])
add_body(doc, None, [("Tools and materials spread out.  ", "A working multimeter lived at one person's house. A good temperature-controlled soldering station lived at another's. A hot-glue gun and a supply of glue sticks lived at a third. Swapping a part or re-soldering a joint sometimes meant half a day of coordinating pickup and drop-off instead of actually working on the machine. By the end of the project the group had consolidated the most-used tools into a single plastic toolbox that lived with the machine itself — one of the most underrated process improvements the team made.")])

# --- 9. Challenges, Problem Solving, Lessons ---
add_heading2(doc, "9. Challenges, Problem Solving, and Lessons Learned")

add_heading3(doc, "9.1 Material Sourcing Friction")
add_body(doc, "Finding the right material at the right time was a constant low-grade drag on momentum. A bracket would be designed around a specific diameter of shaft; the local shop would not have it, and the only alternatives were a weekend trip to a different part of the city or a full redesign. A 3D-printed pulley would crack on first use, and the only printer available on campus would have a two-day queue. The cumulative delay from dozens of small sourcing problems was arguably larger than the delay from any single big failure.")

add_heading3(doc, "9.2 Trial and Error Beats Clever Design")
add_body(doc, "The rotating platform is the canonical example. Two clever, paper-perfect designs failed in cardboard mockups or early assembly. The third design — a boring, flat disc on a motor shaft, with a foam sheet glued on top — won on the very first try. The lesson the whole team took away is that if you are building with hobbyist-grade tools and hobbyist-grade skills, the boring solution you can actually build today is better than the clever solution that requires a week of custom parts you cannot reliably source.")

add_heading3(doc, "9.3 Aggressive Scope Cuts Were the Right Call")
add_body(doc, "The original merged initial plan was beautiful on paper and impossible for five overloaded students to deliver in a single semester. Cutting the multi-crop classifier, the weight sensor, the environmental sensors, the physical pushbutton panel, and the IR position sensors one by one was painful at each step, but every one of those cuts bought time that was needed to get the core pipeline actually working. A small working demo beats a grand non-working plan every time, and by the end of the project the team was genuinely glad they had swallowed those cuts early rather than trying to hang on to the full scope and ending up with nothing that ran.")

add_heading3(doc, "9.4 Teamwork Took Practice")
add_body(doc, "The first few team meetings were long, loud, and not especially productive: five people with five opinions and no clear single owner for each subsystem. Once the group agreed on the four-area split documented in Section 8, with a single accountable owner for each area and Sameer as the final integration tiebreaker, meetings got shorter and progress got faster. Learning to divide work cleanly and to trust each owner's judgment on their area was, in many ways, the real deliverable of the course.")

# --- 10. Results ---
add_heading2(doc, "10. Results — What Worked and What Did Not")

add_heading3(doc, "10.1 Subsystems That Were Working on Demo Day")
res_working = [
    ["360° rotating disc (Iteration 3)", "Fully working", "100% reliable across every test run."],
    ["Feed push arm (MG996R)", "Fully working", "Every potato ejected cleanly onto the conveyor."],
    ["IMX219 camera + MJPEG live stream", "Working", "Live preview visible in dashboard with no noticeable lag."],
    ["ONNX potato classifier (5 classes)", "Working", "Classified consistently under the chamber's lighting."],
    ["5-frame grade aggregation", "Working", "Clearly more stable than any single-frame judgment."],
    ["Web dashboard UI", "Working", "Start button, live video, Last Scan widget, audit history, and all test buttons were responsive."],
    ["SQLite audit log", "Working", "Every scan written to the scans table and visible in the dashboard."],
    ["Serial protocol (RPi 5 ↔ ESP32)", "Working", "PING, MOTOR, PUSH, CONVEYOR, SORT, and ESTOP all round-tripped cleanly."],
    ["Conveyor belt movement", "Barely working", "Moved forward continuously for the demo, but drifted in speed and needed manual adjustment between runs."],
    ["Sorting arm — Grade A flap only", "Barely working", "Moved reliably but slowly; the other two flaps were not used during the live demo."],
]
tbl2 = doc.add_table(rows=1 + len(res_working), cols=3)
style_table_borders(tbl2)
h2 = ["Subsystem", "Status", "Notes"]
for ci, htext in enumerate(h2):
    set_cell_font(tbl2.rows[0].cells[ci], htext, bold=True, align_center=True)
for ri, row in enumerate(res_working, start=1):
    for ci, ctext in enumerate(row):
        set_cell_font(tbl2.rows[ri].cells[ci], ctext, align_center=(ci == 1))

add_heading3(doc, "10.2 Subsystems That Did Not Work, Were Cut, or Were Never Delivered")
res_failed = [
    ["Sorting arms — Grade B and Grade C flaps", "Non-operational", "Inconsistent motion, timing drift vs. open-loop conveyor."],
    ["Conveyor closed-loop speed control", "Never implemented", "No encoder was fitted; no time to add PID tuning."],
    ["Conveyor structural frame", "Marginal", "Thin sheet metal flexed visibly; idler axle walked in its slot."],
    ["Panel-mount START / STOP physical buttons", "Not delivered", "Cutouts in the case were made; the switches were never wired in."],
    ["Physical LCD 20×4 + rotary encoder panel", "Designed only", "Schematics and breadboard proof done in the UI folder; not soldered."],
    ["Temperature / humidity sensors (storage bins)", "Cut", "Parts purchased; time ran out before integration."],
    ["Load cell + HX711 weight measurement", "Cut", "The purchased load cell was defective out of the bag."],
    ["IR / limit-switch potato position tracking", "Cut", "Ran out of both GPIO headroom and integration time."],
    ["Multi-crop classifier (potato + tomato + apple + orange)", "Cut", "Dataset quality issues, GPU training time, and Pi FPS constraints."],
    ["Multi-model / ensemble inference", "Cut", "Heavier models were too slow on the Pi 5 CPU."],
    ["12 V 5 A SMPS power supply", "DOA / unused", "Output collapsed under load; replaced with LiPo packs."],
]
tbl3 = doc.add_table(rows=1 + len(res_failed), cols=3)
style_table_borders(tbl3)
for ci, htext in enumerate(h2):
    set_cell_font(tbl3.rows[0].cells[ci], htext, bold=True, align_center=True)
for ri, row in enumerate(res_failed, start=1):
    for ci, ctext in enumerate(row):
        set_cell_font(tbl3.rows[ri].cells[ci], ctext, align_center=(ci == 1))

add_heading3(doc, "10.3 The Demo Run")
add_body(doc, "What the evaluators actually saw on demo day was this: a potato is placed in the entry chute and rolls onto the stationary rotating disc inside the white case. The operator clicks Start on the web dashboard. The disc spins through one full revolution; the live feed shows the five captures happening; the Last Scan widget updates with the class, confidence, and Grade A/B/C within about one second of the rotation finishing; the push arm sweeps and the potato cleanly exits onto the head of the moving conveyor belt; the belt carries it past the three sorting flaps, and the Grade A flap (the only one trusted) dips to guide a Grade A tuber into its bin. The pipeline ran end to end, which was the bar the team had set for themselves once the scope cuts were accepted.")

# --- 11. Future Development ---
add_heading2(doc, "11. Future Development Roadmap")
add_body(doc, "A v2 of this machine built on what was learned would fix the weakest links first, in roughly the following order:")
future_points = [
    ("Power supply, done right.  ", "A name-brand 12 V 10 A enclosed industrial SMPS, load-tested on the bench with a power resistor before any other subsystem is connected. A separate 5 V 6 A rated BEC for the servo bank, star-grounded at a single terminal block. No more LiPo workarounds."),
    ("Closed-loop, rigid conveyor.  ", "Replace the 12 V brushed DC motor with a gearmotor that has a quadrature encoder on the output shaft. Move the conveyor drive to the ESP32 with a simple PID loop on the encoder feedback so belt speed is genuinely constant regardless of supply voltage or line sag. Replace the sheet-metal frame with 2020-series aluminum extrusion — cheap, rigid, and infinitely adjustable."),
    ("All three sorting flaps working properly.  ", "Use short, stiff servo horns and a four-bar linkage so 60° of servo motion produces a full 90° flap travel, cutting sweep time roughly in half. Calibrate each flap against the real encoder-based travel time of the belt, not a guessed software delay."),
    ("Environmental sensors done simply.  ", "I²C BME280 modules (one per bin) instead of DHTs for better long-term stability. Add a second SQLite table for timestamped bin-environment history, and a new tab in the web dashboard to graph it."),
    ("Working weight sensor.  ", "A new, known-good 5 kg load cell with a fresh HX711, tared on a precision calibration weight set, and the scans table extended with a weight_g column so weight and visual grade can be correlated."),
    ("Potato position sensing.  ", "One IR photo-interrupter at each of three key points: immediately after the push arm, at the first sorting flap, and past the last sorting flap. This turns every timing guess into a hardware event and makes the sort cycle deterministic."),
    ("Physical operator buttons finished.  ", "The two panel-mount cutouts are already in the case; soldering in real switches and wiring them either to RPi GPIOs or to ESP32 inputs is roughly a weekend job."),
    ("In-domain dataset refresh.  ", "Re-label and re-train the classifier on a few hundred photos actually taken inside the machine's own chamber lighting, instead of relying entirely on a public dataset shot under different conditions. A few rounds of active learning would boost accuracy more than any model-size increase."),
    ("Re-introduce multi-crop support one crop at a time.  ", "Start with tomatoes as the second commodity now that the basic conveyor-and-sorter skeleton is proven, rather than trying to support four crops from day one."),
    ("UPS / battery backup.  ", "A small enclosed lead-acid battery and a charger module so the machine can keep logging and keep sorting through short power cuts, which are a fact of life for any rural deployment the team would eventually want to target."),
]
for bold_prefix, rest in future_points:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    num_run = p.add_run(str(future_points.index((bold_prefix, rest)) + 1) + ".  ")
    num_run.font.name = FONT_BODY[0]
    num_run.font.size = Pt(FONT_BODY[1])
    rb = p.add_run(bold_prefix)
    rb.bold = True
    rb.font.name = FONT_BODY[0]
    rb.font.size = Pt(FONT_BODY[1])
    rn = p.add_run(rest)
    rn.font.name = FONT_BODY[0]
    rn.font.size = Pt(FONT_BODY[1])

# --- 12. Conclusion ---
add_heading2(doc, "12. Conclusion")
add_body(doc, "This project was, in the end, as much an education in real-world engineering teamwork as it was a deliverable for the Microprocessors and Microcontrollers Laboratory course. Five people with uneven prior embedded experience, living far apart, handed a defective power supply and an initial plan that wanted too much from a single semester, converged over the final month on a set of aggressive scope cuts and a simplified mechanical design that actually ran.")
add_body(doc, "What survived to demo day is a coherent end-to-end machine: an ONNX-powered vision system running locally on a Raspberry Pi 5, grading real potatoes into three quality tiers using visual evidence from five camera captures distributed across a full 360° rotation; a rotating scanning platform that won the project on its third, deliberately simple mechanical iteration; a push arm that never misfired once; a web dashboard that the evaluators could actually use to operate the machine; and a SQLite database that faithfully recorded every scan.")
add_body(doc, "What did not survive is a long list too: two of the three sorting flaps, closed-loop conveyor speed control, environmental sensors, weight measurement, panel-mounted operator buttons, multi-crop support, and the original SMPS that died on day one.")
add_body(doc, "By the end of the semester every one of the five team members could produce a longer list of things they would do differently on the next machine than things they already knew how to do going in. That outcome is arguably the real point of a project-based microcontroller laboratory course. A perfect machine would have taught them less.")

# Save
doc.save(OUT)
print("DOCX SAVED OK to", OUT)
print("Final paragraph count:", len(doc.paragraphs))
print("Final table count:", len(doc.tables))
