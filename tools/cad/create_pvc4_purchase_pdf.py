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
OUT = ROOT / 'output/pdf/Warirak_PVC4_Full_Three_Rounds_A4.pdf'
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
    label(f'{num:02d} / 04', R, 822, 9, bold=True, color=TEAL, align='right')
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


def part(name, detail, qty, price, url, kind='ค้นหา'):
    return Part(name, detail, qty, price, price, url, kind)


r1 = [
 part('เหล็กกล่อง 20 × 20 × 1.2 มม.', 'ใช้ 2.24 ม. ซื้อเศษตรงขนาดอย่างน้อย 2.5 ม. เผื่อใบตัด', '2.5 ม.', 200, search('เหล็กกล่อง 20x20 1.2 มม')),
 part('เหล็กแผ่น F04, F05E และ F06', 'ใช้เศษแผ่นหนา 2 และ 3 มม. ขนาดตามแบบเฟรมแยก', '1 ชุด', 100, search('เหล็กแผ่นดำ 2 มม 3 มม ตัดตามขนาด')),
 part('ชุดยึดทุ่นพร้อมอานและยาง', 'U-bolt M6 จำนวน 4 ชุด ระยะขา 124 มม. ต้องทาบของจริง', '4 ชุด', 250, search('ยูโบลท์ M6 ท่อ 4 นิ้ว ยางรอง อาน')),
 part('ลวดเชื่อมและสีรองพื้นกันสนิม', 'ใช้เครื่องเชื่อมและเครื่องเจียรของคณะ รวมค่าแรงทำเอง', '1 ชุด', 120, search('ลวดเชื่อมเหล็กบาง สีรองพื้นกันสนิม')),
 part('เผื่อใบตัดและดอกสว่าน', 'ยืมเครื่องมือหลัก ซื้อเฉพาะวัสดุสิ้นเปลืองที่ขาด', '1 ชุด', 30, search('ใบตัดเหล็กบาง ดอกสว่าน 7 มม')),
]
r2 = [
 part('ท่อ PVC 4 นิ้ว ชั้น 5', 'ซื้อเส้น 4 ม. ตัด 600 มม. 2 ท่อน เหลือใช้ทำงานอื่น', '1 เส้น', 435, 'https://www.torpvc.com/4inch-pvc', 'อ้างอิง'),
 part('ฝาครอบบาง PVC 4 นิ้ว', 'ราคาหน้าร้านอ้างอิง 60 บาท/ชิ้น ลองสวมกับท่อก่อน', '4 ฝา', 240, 'https://www.homepro.co.th/p/1206328', 'สินค้า'),
 part('น้ำยาประสานท่อ PVC', 'ใช้ผลิตภัณฑ์สำหรับ PVC และรอให้แห้งตามฉลาก', '1 กระป๋อง', 80, 'https://www.homepro.co.th/p/1136719', 'ตัวอย่าง'),
 part('เชือกกู้เรือ', 'เชือกยาว 5-10 ม. สำหรับทดสอบลอยในบ่อน้ำสงบ', '1 เส้น', 50, search('เชือก PP 10 เมตร')),
]
drive = [
 part('มอเตอร์เรือ BM70 แปรงถ่าน', 'CW และ CCW อย่างละตัว ใช้ 2S สูงสุด 8.4 V ห้ามจ่าย 12 V', '2 ตัว', 690, 'https://www.underwaterthruster.com/products/apisqueen-2s-lipo-8-4v-28w-bm70-brushed-thruster-for-rov-toy-boats', 'สินค้า'),
 part('ไดรเวอร์ BTS7960 สำหรับเรือ', 'แยก 1 บอร์ดต่อมอเตอร์ ตรวจลอจิกและกระแสจริง', '2 บอร์ด', 290, old_links[11], 'สินค้า'),
 part('แบตเตอรี่ LiPo 2S 2200 mAh', '7.4 V หัว XT60 และหัวบาลานซ์ ตัวอย่าง ManiaX 30C', '1 ก้อน', 450, 'https://www.udshobby.com/category/26/battery-อุปกรณ์/2s-7-4v', 'หมวด'),
 part('เครื่องชาร์จบาลานซ์ 2S', 'ตัวอย่าง iMaxRC B3 AC 20W สำหรับ LiPo 2S', '1 เครื่อง', 350, old_links[23], 'หมวด'),
 part('สายไฟ ฟิวส์ สวิตช์ และตัดไฟต่ำ', 'รวม XT60 อุปกรณ์ป้องกัน 2S และชุดจ่าย 5 V ให้ ESP32', '1 ชุด', 250, old_links[27]),
 part('วงจรแปลงลอจิกและแผ่นปริ้น', 'Echo ลง 3.3 V และสัญญาณควบคุมไดรเวอร์ตามวงจร', '1 ชุด', 60, old_links[16], 'ตัวอย่าง'),
 part('กล่องมีปะเก็นและเคเบิลแกลนด์', 'กล่องแบตและกล่องควบคุม ตรวจพื้นที่และการระบายความร้อน', '1 ชุด', 180, old_links[25]),
 part('ชุดไฟ Pi 5 บนเรือ', 'วงเงิน 5 V / 5 A และสาย ต้องออกแบบขั้วต่อและทดสอบโหลด', '1 ชุด', 550, 'https://www.udshobby.com/product/741/hobbywing-ubec-5-amp-2-8s-out-5v-6v-7-4v', 'ตัวอย่าง'),
 part('เซนเซอร์หน้าเรือ JSN-SR04T', 'เป็นเซนเซอร์ทดลองด้านหน้า ไม่ยืนยันการหลบชนรอบลำ', '1 ชุด', 240, old_links[20], 'สินค้า'),
 part('กล้อง USB สำหรับ Raspberry Pi', 'รุ่นอ้างอิง A1570 ภาพ 640 × 480 ต้องลองแสงและระยะจริง', '1 ตัว', 140, 'https://www.allnewstep.com/product/1598/กล้อง-usb-camera-for-raspberry-pi', 'สินค้า'),
 part('ชุดระบายความร้อน Pi 5', 'วงเงิน Active Cooler ถ้ามีอยู่แล้วตัดรายการนี้ออกได้', '1 ชุด', 325, 'https://www.arduitronics.com/product/6000/official-heat-sinks-raspberry-pi-5-active-cooler', 'ตัวอย่าง'),
 part('ขายึดและครอบใบพัด', 'ทำตามขนาดมอเตอร์ที่ซื้อ ไม่ใช้แบบตัวแทนเจาะรูถาวร', '2 ชุด', 100, old_links[12]),
 part('เผื่อขนส่ง อัตราแลกเปลี่ยน และนำเข้า', 'สำรองเบื้องต้น หากยอดชำระจริงเกินต้องปรับวงเงินก่อนสั่ง', '1 กอง', 300, '', 'งบเผื่อ'),
]
conveyor = [
 part('แผ่น HDPE สำหรับรางและเด็ค', 'ใช้เศษแผ่นหนา 5-6 มม. ทาบรางและเด็คจากแบบ', '1 ชุด', 250, old_links[3]),
 part('ตาข่าย PE', 'กว้าง 190 มม. ยาวเผื่อ 900 มม. รู 3-5 มม.', '1 ชุด', 100, old_links[4]),
 part('เพลา ลูกกลิ้ง บูช และดุม', 'เพลา Ø6 ยาว 244 และ 217 มม. ลูกกลิ้ง Ø32 × 198 มม.', '1 ชุด', 280, old_links[6]),
 part('คัปปลิงเพลา', '6 × 6 มม. เมื่อเพลาที่ซื้อทั้งสองด้านมีขนาดตรงกัน', '1 ตัว', 49, old_links[7], 'สินค้า'),
 part('มอเตอร์สายพาน JGY-370', 'DCM030 12 V 30 RPM จ่าย 2S จะช้าลง ต้องทดสอบยกขวด', '1 ตัว', 260, 'https://www.mechashop.com/product/detail/DCM030', 'สินค้า'),
 part('ไดรเวอร์ BTS7960 ของสายพาน', 'บอร์ดที่ 3 แยกจากมอเตอร์เรือ', '1 บอร์ด', 145, old_links[11], 'สินค้า'),
 part('ครีบตัก นอต และวัสดุยึดราง', 'ครีบสูง 20 มม. 8 ชิ้น ใช้เศษ PP ทำเองได้', '1 ชุด', 100, old_links[29]),
 part('กระบะรับขยะ', 'ประมาณ 4 ลิตร ฐานต้องพอดีช่องหลังสายพาน', '1 ใบ', 60, old_links[9]),
]
solar = [
 part('แผงโซลาร์ Hopesun 5W 18V', '215 × 180 × 17 มม. น้ำหนักอ้างอิง 0.53 กก.', '1 แผง', 350, 'https://www.solar-thailand.co.th/TH/Product.asp?Data1=MONO-5W-HPSM', 'สินค้า'),
 part('วงจรชาร์จโซลาร์สำหรับ LiPo 2S', 'เผื่อรุ่น CC/CV 8.4 V รับแผง 18 V มีการคุมกระแสและอุณหภูมิ', '1 ชุด', 350, old_links[31], 'ตรวจรุ่น'),
 part('เสา ขายึด และอุปกรณ์ตัดอุณหภูมิ', 'ใช้เศษอะลูมิเนียม เสา 4 ต้น คาน 2 ชิ้น ตรวจความแข็งแรง', '1 ชุด', 150, old_links[32]),
]
r3=drive+conveyor+solar
assert budget(r1)==(700,700) and budget(r2)==(805,805)
total=budget(r1+r2+r3)[0]
assert total==7524 and budget(r3)[0]==6019

def compact(y, rows, h=31):
    rect(M,y,R-M,23,TEAL,radius=4)
    label('รายการ / จุดตรวจสอบ',M+8,y+15,10,bold=True,color=white)
    label('จำนวน',383,y+15,10,bold=True,color=white,align='center')
    label('บาท',484,y+15,10,bold=True,color=white,align='right')
    label('ลิงก์',527,y+15,10,bold=True,color=white,align='center')
    y+=23
    for i,p in enumerate(rows):
        if not i%2:rect(M,y,R-M,h,LIGHT)
        label(p.name,M+8,y+12,10,bold=True,limit=310)
        label(p.detail,M+8,y+25,8.5,color=MUTED,limit=310)
        label(p.qty,383,y+18,9,align='center',limit=63)
        label(f'{p.low:,}',484,y+18,10,bold=True,align='right')
        if p.url:
            label(p.kind,527,y+18,9,color=TEAL,align='center',limit=56)
            c.linkURL(p.url,(497,H-y-28,556,H-y-3),relative=0,thickness=0)
        y+=h
    rule(y)
    return y

page('WARIRAK / PVC 4 INCH', 'เฟรมเดิม สายพาน และโซลาร์', 'แบบอ้างอิงประกอบต้นแบบ / หน่วยมิลลิเมตร / แกน X กว้าง Y สูง Z ไปหัวเรือ')
model=ROOT/'outputs/Warirak_PVC4_RevF_Full'
c.drawImage(str(model/'images/assembled.png'),M,H-411,width=R-M,height=294,preserveAspectRatio=True,anchor='c',mask='auto')
label('ขนาดหลักและรายการตัดเฟรม',M,429,16,bold=True)
for i,(a,b) in enumerate([
 ('ฐานเหล็กกล่อง 20 × 20 × 1.2 มม.','กว้าง 480 × ยาว 500; ตัดคานปลายฉาก 90° ทั้งสองด้าน'),
 ('F01 คานข้าง / F02 คานขวาง','500 มม. × 2 ชิ้น / 440 มม. × 2 ชิ้น'),
 ('F03 คานรองกระบะ / F04 กัสเซต','180 มม. × 2 ชิ้น / สามเหลี่ยม 20 × 20 หนา 2 มม. × 4'),
 ('F05E แผ่นยึดทุ่น 4 ชิ้น','160 × 30 × 3; รู Ø7 สองรู ระยะศูนย์ 124; ห่างขอบ 18'),
 ('ทุ่น PVC 4 นิ้ว 2 ท่อน','OD 114; ผนังสมมติ 3.2; ตัดยาว 600; ฝาเป็นขนาดตัวแทน'),
 ('สายพานและหลังคา','กว้าง 190; ศูนย์เพลา 350; เอียง 32° / แผง 215 × 180 × 17'),
]):
 y=451+i*36
 label(a,M,y,10.6,bold=True)
 label(b,M,y+15,10,color=MUTED,limit=R-M)
note(674,'แบบเฟรมแยกอยู่ในโฟลเดอร์ Frame_Only',[
 'มีชิ้นส่วน STEP, SolidWorks, ภาพแยกประกอบ และรายการตัด พร้อมแบบมองบนระบุระยะ',
 'คงคานฐานเดิม 480 × 500 มม. แผ่นยึดทุ่น F05E เป็นชิ้นเฉพาะสำหรับท่อ 4 นิ้ว',
 'เป็นแบบอ้างอิง ยังไม่มีผลทดสอบลอย รอยเชื่อม กำลังขับ และน้ำหนักบรรทุกที่รับรองแล้ว',
],GOLD)
footer(1)

page('01-03 / CASH PLAN', 'เก็บเงินคนละ 100 บาทต่อรอบ', '7 คน × 100 บาท = 700 บาทต่อรอบ / 3 รอบ รวม 2,100 บาท')
label('รอบที่ 1 : ซื้อเฟรมก่อน',M,128,15,bold=True)
y=compact(141,r1,31)
sumline(y+21,'รวมรอบที่ 1',r1)
label('รอบที่ 2 : ซื้อท่อและทดสอบลอย',M,y+53,15,bold=True)
y=compact(y+65,r2,31)
sumline(y+21,'รวมรอบที่ 2 / เกินเงินรอบนี้ 105 บาท',r2)
y=note(y+38,'สมมติได้รับเงินอาจารย์ก่อนซื้อรอบที่ 2',[
 'ถ้าอาจารย์ช่วย 3,000 บาท : หลังรอบ 2 เหลือ 2,895; บวกรอบ 3 อีก 700 = 3,595 บาท',
 'ถ้าอาจารย์ช่วย 2,000 บาท : หลังรอบ 2 เหลือ 1,895; บวกรอบ 3 อีก 700 = 2,595 บาท',
 'รอบ 3 ชุดครบตามหน้า 3-4 ใช้ 6,019 บาท จึงยังต้องหาเพิ่ม 2,424 หรือ 3,424 บาท',
],PALE)
note(y+12,'ซื้อเท่าที่เงินเข้าจริง',[
 'ถ้าเงินอาจารย์ยังไม่เข้า รอบ 2 ซื้อท่อกับฝา 675 บาทก่อน เก็บ 25 บาท รอกาวและเชือก',
 'งบชุดครบ 7,524 บาท เป็นวงเงินวางแผน รวมค่าส่งเผื่อ 300 บาท ไม่ใช่ใบเสนอราคา',
 'รอบ 3 เริ่มจากชุดขับเรือและทดสอบโหลดก่อน เลื่อนสายพานกับโซลาร์จนมีงบครบ',
],GOLD)
footer(2)

page('03 / PROPULSION & CONVEYOR', 'ของรอบที่ 3 : ชุดขับและสายพาน', 'ซื้อหลังทุ่นและเฟรมผ่านการทดสอบลอยด้วยน้ำหนักจำลองของอุปกรณ์ทั้งหมด')
y=compact(119,drive,26)
sumline(y+20,'ชุดขับเรือ กล้อง และไฟเลี้ยง',drive)
label('สายพานและกระบะรับขยะ',M,y+50,15,bold=True)
y=compact(y+62,conveyor,26)
sumline(y+17,'รวมสายพานและกระบะ',conveyor)
footer(3)

page('03 / SOLAR & TOTAL', 'โซลาร์ขนาดเล็กแบบประหยัด', 'โซลาร์ช่วยเติมแบตเตอรี่ตอนจอด / ไม่เพียงพอให้ Pi 5 และมอเตอร์ทำงานต่อเนื่อง')
y=compact(120,solar,38)
sumline(y+23,'รวมชุดโซลาร์',solar)
y=note(y+40,'วิธีใช้แผง 5W กับแบตเตอรี่ 2S',[
 'แผง 18 V → วงจรชาร์จที่ตั้งสำหรับ LiPo 2S 8.4 V → แบตเตอรี่พร้อมระบบป้องกัน',
 'เลือกแยกชาร์จตอนจอด ปิดโหลดและเฝ้าดูการชาร์จ ไม่ต่อแผงเข้าก้อนแบตโดยตรง',
 'ลิงก์วงจรชาร์จเป็นตัวเลือกหลายรุ่น ให้ร้านยืนยันรุ่น 2S กระแส และการคุมอุณหภูมิก่อนซื้อ',
 'ไม่ใช้คอนโทรลเลอร์ 12 V สำหรับแบตตะกั่วแทนวงจรชาร์จ LiPo 2S',
],GOLD)
label('ยอดรวมตามแบบครบ',M,y+35,17,bold=True)
for i,(name,value) in enumerate([('รอบ 1 : เฟรม',700),('รอบ 2 : ทุ่น',805),('รอบ 3 : ชุดขับ สายพาน และโซลาร์',6019),('รวม',7524)]):
 yy=y+61+i*25
 label(name,M+6,yy,11,bold=i==3)
 label(f'{value:,} บาท',R-6,yy,12,bold=True,align='right',color=TEAL)
y=note(y+155,'สิ่งที่มีแล้วและเงื่อนไขการลดงบ',[
 'ไม่ซื้อ Pi 5, ESP32 DevKit, ESP8266MOD และ microSD ใหม่ ใช้ของที่มีอยู่',
 'รวมกล้อง USB 140 บาท และชุดระบายความร้อน 325 บาทแล้ว ถ้ามีครบลดได้ 465 บาท',
 'ยืมเครื่องมือและทำเอง ใช้เศษ HDPE/อะลูมิเนียมตามงบ หากต้องซื้อเต็มแผ่นจะสูงขึ้น',
 'มอเตอร์ BM70 คิดคู่ละ US$19.60 ที่สมมติ 35 บาท/US$ ปัดวงเงินเป็น 690 บาท',
],PALE)
label('ข้อจำกัดก่อนประกอบระบบไฟ',M,y+27,13,bold=True)
for i,line in enumerate([
 'UBEC 5 A เป็นตัวเลือกภาคจ่ายไฟ ไม่ใช่ชุด USB-PD ของ Pi 5 สำเร็จรูป ต้องออกแบบขั้วต่อและทดสอบ',
 'JGY-370 ระบุ 12 V เมื่อใช้ 2S รอบและแรงบิดอาจไม่พอ ต้องลองยกขวดจริงก่อนยึดรางถาวร',
 'กล้อง USB ราคาประหยัดเหมาะทดลองใกล้ ๆ การตรวจฝาขวดและแสงสะท้อนยังต้องทดสอบจริง',
]):label(line,M,y+47+i*16,9.5,color=MUTED,limit=R-M)
footer(4)
c.save()

manifest={'date':'2026-11-07','currency':'THB','contribution_per_person_per_round':100,'people':7,
 'group_total':2100,'teacher_grants_are_unconfirmed':[2000,3000],
 'round_totals':[700,805,6019],'total':total,'short_if_teacher_2000':3424,'short_if_teacher_3000':2424,
 'owned_excluded':['Raspberry Pi 5','ESP32 DevKit','ESP8266MOD','microSD'],
 'rows':[dict(round=r,**p.__dict__) for r,parts in [(1,r1),(2,r2),(3,r3)] for p in parts],
 'status':'Planning allowances, not confirmed quotations. Actual checkout, fit and physical tests pending.'}
(model/'Purchase_Plan.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(OUT, 'TOTAL',total, 'DRIVE',budget(drive)[0],'CONVEYOR',budget(conveyor)[0],flush=True)


