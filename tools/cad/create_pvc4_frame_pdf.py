from dataclasses import dataclass
import json
from pathlib import Path
import sys
from urllib.parse import quote

sys.path.insert(0, str(Path.cwd()/'tmp/pdfs/warirak-pdf-deps'))
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.pdfgen.textobject import bidiShapedText


ROOT = Path.cwd()
OUT = ROOT / 'output/pdf/Warirak_PVC4_Frame_A4.pdf'
PREV = Path('C:/Users/Administrator/Documents/Codex/2026-10-22/solid-mini-prototype-scale-model-350')
old_bom = PREV / 'outputs/Warirak_Pi4_PVC2inch_5W/BOM_with_purchase_links.json'
old_links = {r['id']: r['url'] for r in json.loads(old_bom.read_text(encoding='utf-8'))['rows']}


def search(term):
    return 'https://shopee.co.th/search?keyword=' + quote(term)


@dataclass(frozen=True)
class Part:
    name: str
    detail: str
    qty: str
    low: int
    high: int
    url: str
    kind: str = 'ค้นหา'


def budget(parts):
    return sum(p.low for p in parts), sum(p.high for p in parts)


def number(low, high):
    return f'{low:,}' if low == high else f'{low:,}-{high:,}'


pdfmetrics.registerFont(TTFont('Thai', 'C:/Windows/Fonts/tahoma.ttf'))
pdfmetrics.registerFont(TTFont('ThaiBold', 'C:/Windows/Fonts/tahomabd.ttf'))
OUT.parent.mkdir(parents=True, exist_ok=True)
c = Canvas(str(OUT), pagesize=A4, pageCompression=1)
c.setTitle('วารีรักษ์ | PVC 4 นิ้ว สายพานและโซลาร์ แผนซื้อ 3 รอบ')
c.setAuthor('วารีรักษ์ • มหาวิทยาลัยทักษิณ')
W, H = A4
M, R = 38, W - 38
INK, MUTED, TEAL = map(HexColor, ['#142C36', '#455B62', '#08675E'])
LIGHT, LINE, PALE, GOLD = map(HexColor, ['#F3F8F7', '#CDDCD9', '#E3F1EC', '#FFF3D7'])


def label(value, x, y, size=11, *, bold=False, color=INK, align='left', limit=None):
    font = 'ThaiBold' if bold else 'Thai'
    _, width = bidiShapedText(value, direction='LTR', fontName=font, fontSize=size, shaping=True)
    if limit is not None and width > limit:
        raise ValueError(f'Line too wide {width:.1f} > {limit}: {value}')
    if align == 'right':
        x -= width
    if align == 'center':
        x -= width / 2
    c.setFillColor(color)
    c.setFont(font, size)
    c.drawString(x, H-y, value, direction='LTR', shaping=True)
    return width


def rect(x, y, w, h, fill, stroke=None, radius=0):
    c.setFillColor(fill)
    c.setStrokeColor(stroke or fill)
    c.roundRect(x, H-y-h, w, h, radius, fill=1, stroke=bool(stroke))


def rule(y):
    c.setStrokeColor(LINE)
    c.setLineWidth(.55)
    c.line(M, H-y, R, H-y)


def page(kicker, title, subtitle):
    rect(0, 0, W, 8, TEAL)
    label(kicker, M, 38, 10, bold=True, color=TEAL)
    label('อัปเดต 7 พ.ย. 2569', R, 38, 10, color=MUTED, align='right')
    label(title, M, 75, 26, bold=True)
    label(subtitle, M, 100, 11, color=MUTED, limit=R-M)


def footer(num):
    rule(805)
    label('วารีรักษ์ / แบบต้นแบบ • คณะวิศวกรรมศาสตร์ มหาวิทยาลัยทักษิณ', M, 822, 9, color=MUTED)
    label(f'{num:02d} / 02', R, 822, 9, bold=True, color=TEAL, align='right')
    c.showPage()


def note(y, title, lines, fill=LIGHT):
    h = 34 + 15 * len(lines)
    rect(M, y, R-M, h, fill, radius=7)
    label(title, M+13, y+20, 11, bold=True, color=TEAL, limit=R-M-26)
    for i, line in enumerate(lines):
        label(line, M+13, y+39+i*15, 10, color=INK, limit=R-M-26)
    return y+h


def table(y, rows, h=37):
    rect(M, y, R-M, 25, TEAL, radius=5)
    label('รายการ / สิ่งที่ต้องเช็ก', M+28, y+16, 10, bold=True, color=white)
    label('จำนวน', 383, y+16, 10, bold=True, color=white, align='center')
    label('รวม (บาท)', 484, y+16, 10, bold=True, color=white, align='right')
    label('ลิงก์', 527, y+16, 10, bold=True, color=white, align='center')
    y += 25
    for i, p in enumerate(rows):
        if i % 2 == 0:
            rect(M, y, R-M, h, LIGHT)
        c.setStrokeColor(TEAL)
        c.setLineWidth(.7)
        c.rect(M+9, H-y-19, 8, 8, fill=0)
        label(p.name, M+28, y+14, 10.8, bold=True, limit=288)
        label(p.detail, M+28, y+28, 9.25, color=MUTED, limit=290)
        label(p.qty, 383, y+19, 9.6, align='center', limit=61)
        label(number(p.low, p.high), 484, y+19, 10.3, bold=True, align='right', limit=73)
        rect(497, y+7, 59, 20, PALE, radius=5)
        label(p.kind, 526.5, y+20, 9.15, color=TEAL, align='center', limit=54)
        c.linkURL(p.url, (497, H-y-27, 556, H-y-7), relative=0, thickness=0)
        y += h
    rule(y)
    return y


def sumline(y, title, rows):
    label(title, M+2, y, 11, bold=True, color=TEAL)
    label(number(*budget(rows))+' บาท', R, y, 13, bold=True, color=TEAL, align='right')



model=ROOT/'outputs/Warirak_PVC4_RevF_Full'
page('WARIRAK / FRAME ONLY','เฟรมเหล็กแยกประกอบ','คงฐานเดิม 480 × 500 มม. / แผ่นยึดทุ่นสำหรับ PVC 4 นิ้ว / หน่วยมิลลิเมตร')
c.drawImage(str(model/'images/frame_reference.png'),M,H-443,width=R-M,height=324,preserveAspectRatio=True,anchor='c')
label('รายการตัดและองศา',M,463,16,bold=True)
for i,(code,detail) in enumerate([
 ('F01 : 2 ชิ้น','เหล็กกล่อง 20 × 20 × 1.2 ยาว 500 มม. ปลายตัดฉาก 90°/90°'),
 ('F02 : 2 ชิ้น','เหล็กกล่อง 20 × 20 × 1.2 ยาว 440 มม. ปลายตัดฉาก 90°/90°'),
 ('F03 : 2 ชิ้น','เหล็กกล่อง 20 × 20 × 1.2 ยาว 180 มม. ปลายตัดฉาก 90°/90°'),
 ('F04 : 4 ชิ้น','เหล็กแผ่นหนา 2 สามเหลี่ยมขา 20 × 20 มม. มุม 90°/45°/45°'),
 ('F05E : 4 ชิ้น','เหล็กแผ่น 160 × 30 × 3 มม. รู Ø7 จำนวน 2 รู ระยะศูนย์ 124 มม.'),
 ('F06 : 2 ชิ้น','เหล็กแผ่น 50 × 45 × 3 มม. รู Ø4.5 จำนวน 2 รู ระยะศูนย์ 10 มม.'),
]):
 y=489+i*32
 label(code,M,y,11,bold=True)
 label(detail,M,y+16,10.4,color=MUTED,limit=R-M)
note(679,'ก่อนเชื่อมจริง',[
 'เหล็กกล่องใช้สุทธิ 2.24 ม. เตรียมอย่างน้อย 2.5 ม. เผื่อใบตัดและแต่งปลาย',
 'เชื่อมแต้ม ตรวจแนวฉากและระยะทแยง ทาบท่อ อาน และ U-bolt จริงก่อนเจาะรู',
 'ถอด PVC และอุปกรณ์ไฟออกก่อนเชื่อม แบบนี้ยังไม่ผ่านการรับรองรอยเชื่อมหรือบรรทุก',
],GOLD)
footer(1)

page('WARIRAK / FRAME DIMENSIONS','แบบมองบนและตำแหน่งยึด','แกน X ตามความกว้าง; แกน +Z ไปหัวเรือ / รูปย่อเพื่อพิมพ์ A4 ให้ยึดค่าตัวเลข')
c.drawImage(str(model/'Frame_Only/Frame_Top_mm.png'),M,H-624,width=R-M,height=498,preserveAspectRatio=True,anchor='c')
note(641,'ตำแหน่งที่ต้องตรวจ',[
 'คานขวางศูนย์ Z = -240 และ -40 ระยะศูนย์ 200 มม.; คานรอง X = -80 และ +80',
 'แผ่น F05E ศูนย์ X = -230 และ +230; Z = -180 และ +120 ระยะหน้า-หลัง 300 มม.',
 'ศูนย์รู F05E ห่างหัวท้าย 18 มม. ห่างขอบด้านยาว 15 มม. ต้องตรง U-bolt ของจริง',
 'F06 รูห่างขอบซ้าย 20 และ 30 มม. ห่างขอบท้าย 7.5 มม. ทาบฐานขายึดจริงก่อนเจาะ',
],PALE)
footer(2)
c.save()
print(OUT)
