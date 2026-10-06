
from docx import Document
from docx.enum.style import WD_STYLE_TYPE

d = Document(r"d:\Programming\Arduino Stuff\rpi5 potato sorter\Micro Final Project Report.docx")
print("=== AVAILABLE TABLE STYLES ===")
for s in d.styles:
    if s.type == WD_STYLE_TYPE.TABLE:
        print(f"  - name={s.name!r}  style_id={s.style_id!r}")

print("\n=== PARA STYLES ===")
for s in list(d.styles)[:30]:
    try:
        if s.type == WD_STYLE_TYPE.PARAGRAPH:
            print(f"  - {s.name!r}")
    except:
        pass
