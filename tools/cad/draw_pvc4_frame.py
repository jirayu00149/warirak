"""Geometry-derived top layout, cut list and DXF for the unchanged steel base."""
from pathlib import Path
import json, sys, html
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'outputs/Warirak_PVC4_RevF_Full'
data=json.loads((OUT/'CAD_parameters.json').read_text(encoding='utf-8'))
parts=[p for p in data['parts'] if p['group']=='welded_frame']
def profile(p):
    pts=sorted(set((round(v[0],5),round(v[2],5)) for v in p['mesh']['vertices']))
    def cross(o,a,b):return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
    lower=[];upper=[]
    for v in pts:
        while len(lower)>=2 and cross(lower[-2],lower[-1],v)<=0:lower.pop()
        lower.append(v)
    for v in reversed(pts):
        while len(upper)>=2 and cross(upper[-2],upper[-1],v)<=0:upper.pop()
        upper.append(v)
    return lower[:-1]+upper[:-1]
frame=OUT/'Frame_Only'; frame.mkdir(exist_ok=True)
S=2
im=Image.new('RGB',(1000*S,960*S),'white'); d=ImageDraw.Draw(im)
svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="960" viewBox="0 0 1000 960"><rect width="1000" height="960" fill="white"/>']
def line(x1,y1,x2,y2,color='#274c56',w=1):
    d.line((x1*S,y1*S,x2*S,y2*S),fill=color,width=max(1,round(w*S)))
    svg.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{w}"/>')
def text(x,y,value,size=16,color='#15363e',anchor='mm'):
    font=ImageFont.truetype('C:/Windows/Fonts/tahoma.ttf',size*S)
    d.text((x*S,y*S),value,font=font,fill=color,anchor=anchor)
    ta={'mm':'middle','lm':'start','rm':'end'}[anchor]
    svg.append(f'<text x="{x}" y="{y+size*.35}" text-anchor="{ta}" font-family="Arial" font-size="{size}" fill="{color}">{html.escape(value)}</text>')
def rect(x,y,w,h,fill='#dce7e9'):
    d.rectangle((x*S,y*S,(x+w)*S,(y+h)*S),fill=fill,outline='#274c56',width=2)
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="#274c56"/>')
def hdim(x1,x2,y,object_y,label):
    for x in (x1,x2):
        line(x,object_y,x,y+8,'#68838b');line(x-4,y+4,x+4,y-4)
    line(x1,y,x2,y);text((x1+x2)/2,y-13,label,15)
def vdim(y1,y2,x,object_x,label):
    for y in (y1,y2):
        line(object_x,y,x+8,y,'#68838b');line(x-4,y+4,x+4,y-4)
    line(x,y1,x,y2);text(x+12,(y1+y2)/2,label,15,anchor='lm')
text(40,36,'WARIRAK | STEEL FRAME ONLY | PVC 4 INCH',25,anchor='lm')
text(40,68,'TOP VIEW / X across, +Z bow / dimensions in mm / measure bought clamps before drilling',15,anchor='lm')
ox,oy=500,420
for p in parts:
    x0,y0,z0,x1,y1,z1=p['bounds_mm']
    if p['code'].startswith('F04'):
        points=[(ox+x,oy-z) for x,z in profile(p)]
        d.polygon([(x*S,y*S) for x,y in points],fill='#e3ebed',outline='#274c56',width=2)
        svg.append('<polygon points="'+' '.join(f'{x},{y}' for x,y in points)+'" fill="#e3ebed" stroke="#274c56"/>')
    else:rect(ox+x0,oy-z1,x1-x0,z1-z0,'#b6cbd0' if p['code'].startswith('F05') else '#e3ebed')
    if p['code'].startswith('F05'):
        for x in [(x0+x1)/2-62,(x0+x1)/2+62]:
            xx,yy=ox+x,oy-(z0+z1)/2
            d.ellipse(((xx-3.5)*S,(yy-3.5)*S,(xx+3.5)*S,(yy+3.5)*S),outline='#15363e',width=2)
            svg.append(f'<circle cx="{xx}" cy="{yy}" r="3.5" fill="white" stroke="#15363e"/>')
    if p['code'].startswith('F06'):
        for x in [(x0+x1)/2-5,(x0+x1)/2+5]:
            xx,yy=ox+x,oy+55
            d.ellipse(((xx-2.25)*S,(yy-2.25)*S,(xx+2.25)*S,(yy+2.25)*S),outline='#15363e',width=2)
            svg.append(f'<circle cx="{xx}" cy="{yy}" r="2.25" fill="white" stroke="#15363e"/>')
hdim(260,740,125,170,'480 base')
vdim(170,670,850,740,'500')
hdim(190,810,732,670,'620 including mount tabs')
vdim(300,600,115,190,'300 tab centres')
vdim(460,660,825,740,'200 beam centres')
hdim(420,580,548,560,'160 runner centres')
line(500,112,500,92);line(495,100,500,92);line(505,100,500,92)
text(520,99,'+Z BOW',13,anchor='lm')
text(280,400,'F01',14);text(720,400,'F01',14)
text(500,659,'F02 440',14);text(500,459,'F02 440',14)
text(395,570,'F03',13);text(605,570,'F03',13)
text(310,285,'F05E',13);text(690,285,'F05E',13)
text(500,695,'F01=500 x2  |  F02=440 x2  |  F03=180 x2; all ends square 90 deg',15)
text(40,778,'F04: 4 right triangles, legs20 x20, t2; angles90/45/45. Fit at four rear beam corners.',16,anchor='lm')
text(40,808,'F05E: 4 plates160 x30 x3; two holesD7, pitch124; centres18 from either end,15 from side.',16,anchor='lm')
text(40,838,'Tab centres: X=+/-230; Z=-180,+120. Rear beam Z=-240; mid beam Z=-40. Datum at base centre.',15,anchor='lm')
text(40,868,'SHS20 x20 x1.2: net2240 mm; buy >=2500 mm allowing saw kerf. Borrow tools and verify steel wall.',15,anchor='lm')
text(40,898,'F06: 2 plates50 x45 x3; holesD4.5 at20,30 from left and7.5 from rear; pitch10. Trial-fit conveyor mount.',15,anchor='lm')
text(40,930,'REFERENCE FIT DRAWING / gusset orientation and all joints: see 3D solid files / weld strength and flotation pending',14,anchor='lm')
svg.append('</svg>')
(frame/'Frame_Top_mm.svg').write_text('\n'.join(svg),encoding='utf-8')
im.save(frame/'Frame_Top_mm.png')

sys.path.insert(0,'C:/Users/Administrator/Documents/Codex/2026-10-22/solid-mini-prototype-scale-model-350/work/cad_runtime_b')
import ezdxf
doc=ezdxf.new('R2010');doc.units=4;ms=doc.modelspace()
for p in parts:
    a,b,z,c,e,w=p['bounds_mm']
    ms.add_lwpolyline(profile(p) if p['code'].startswith('F04') else [(a,z),(c,z),(c,w),(a,w)],close=True)
    if p['code'].startswith('F05'):
        for x in [(a+c)/2-62,(a+c)/2+62]:ms.add_circle((x,(z+w)/2),3.5)
    if p['code'].startswith('F06'):
        for x in [(a+c)/2-5,(a+c)/2+5]:ms.add_circle((x,-55),2.25)
for base,p1,p2,ang in [((0,300),(-240,250),(240,250),0),((350,0),(240,-250),(240,250),90),((0,-310),(-310,-250),(310,-250),0)]:
    ms.add_linear_dim(base=base,p1=p1,p2=p2,angle=ang,override={'dimtxt':8,'dimasz':5,'dimexo':2,'dimexe':3,'dimtad':1}).render()
ms.add_text('TOP LAYOUT ONLY / mm / individual gusset profile in STEP / actual U-bolt fit before drilling',dxfattribs={'height':8,'insert':(-310,-350)})
doc.saveas(frame/'Frame_Top_Reference_mm.dxf')
print('FRAME TOP PNG SVG DXF WRITTEN',flush=True)
