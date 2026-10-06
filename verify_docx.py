
from docx import Document

d = Document(r"d:\Programming\Arduino Stuff\rpi5 potato sorter\Micro Final Project Report.docx")

out = []
out.append(f"Total paragraphs: {len(d.paragraphs)}")
out.append(f"Total tables: {len(d.tables)}")
out.append("")
out.append("=== PARAGRAPH HEADERS / KEY STRUCTURE ===")
for i, p in enumerate(d.paragraphs):
    text = p.text.strip()
    if not text:
        continue
    style = p.style.name if p.style else "None"
    size_hint = ""
    first_run = next((r for r in p.runs if r.text.strip()), None)
    if first_run is not None and first_run.font.size:
        size_hint = f" [font {first_run.font.name} {first_run.font.size.pt}pt bold={first_run.bold}]"
    # Only print headings + first 40 chars of body to spot-check
    if style.startswith("Heading") or style.lower().startswith("heading") or (len(text) < 120):
        out.append(f"[{i:03d}] {style:<12s} {text[:150]!r}{size_hint}")
    else:
        out.append(f"[{i:03d}] {style:<12s} {text[:90]!r}...{size_hint}")

out.append("")
out.append("=== TABLES SUMMARY ===")
for ti, t in enumerate(d.tables):
    out.append(f"Table {ti}: {len(t.rows)} rows x {len(t.columns)} cols")
    # Print header + first two rows
    for ri, row in enumerate(t.rows[:3]):
        cells = [c.text[:40] for c in row.cells]
        out.append(f"  Row {ri}: {cells}")

with open(r"d:\Programming\Arduino Stuff\rpi5 potato sorter\docx_verify_output.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("VERIFY OK")
