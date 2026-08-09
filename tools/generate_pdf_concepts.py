from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader

W, H = A4
OUT = Path("output/pdf/concepts")
OUT.mkdir(parents=True, exist_ok=True)
logo = ImageReader("frontend/public/assets/brand/apex-logo.png")
font = "C:/Windows/Fonts/arial.ttf"
bold = "C:/Windows/Fonts/arialbd.ttf"
pdfmetrics.registerFont(TTFont("UI", font))
pdfmetrics.registerFont(TTFont("UIB", bold))

YELLOW = "#FFD600"
BLACK = "#080D12"
PANEL = "#111A23"
SOFT = "#182431"
LINE = "#2A3846"
WHITE = "#F7FAFC"
MUTED = "#93A3B5"
RED = "#FF5661"
AMBER = "#FFBD2E"

issues = [
    ("Передняя подвеска", "Шаровая опора, левая", "Неисправно", "Люфт. Рекомендуется замена", "4 500 ₽"),
    ("Тормозная система", "Передние тормозные колодки", "Внимание", "Остаток 20%. Замена на следующем ТО", ""),
    ("Двигатель", "Подтекание масла", "Внимание", "Очистить и выполнить повторный осмотр", "1 500 ₽"),
]

def col(c, value): c.setFillColor(value)
def line(c, value): c.setStrokeColor(value)
def text(c, x, y, value, size=10, color=WHITE, face="UI"):
    col(c, color); c.setFont(face, size); c.drawString(x, y, value)
def right(c, x, y, value, size=10, color=WHITE, face="UI"):
    col(c, color); c.setFont(face, size); c.drawRightString(x, y, value)
def roundbox(c, x, y, w, h, fill=PANEL, stroke=LINE, radius=12):
    col(c, fill); line(c, stroke); c.roundRect(x, y, w, h, radius, fill=1, stroke=1)
def brand(c, x, y, compact=False):
    size = 42 if compact else 58
    c.drawImage(logo, x, y-size, size, size, mask="auto")
    text(c, x+size+12, y-20, "APEX AUTO", 18 if compact else 23, WHITE, "UIB")
    text(c, x+size+12, y-37, "ДИАГНОСТИЧЕСКАЯ КАРТА", 8.5, YELLOW, "UIB")
def issue_rows(c, x, y, w, card=True, numbered=False):
    for i, (section, title, status, note, price) in enumerate(issues, 1):
        h = 76
        if card: roundbox(c, x, y-h, w, h-8, SOFT, LINE, 10)
        color = RED if status == "Неисправно" else AMBER
        if numbered:
            roundbox(c, x+12, y-46, 34, 34, color, color, 9); text(c, x+23, y-35, str(i), 13, BLACK, "UIB")
            tx = x+58
        else:
            col(c, color); c.roundRect(x+14, y-51, 5, 38, 2, fill=1, stroke=0); tx=x+30
        text(c, tx, y-22, section.upper(), 7.5, MUTED, "UIB")
        text(c, tx, y-40, title, 11.5, WHITE, "UIB")
        text(c, tx, y-56, note, 8.5, MUTED)
        right(c, x+w-16, y-26, status, 8.5, color, "UIB")
        if price: right(c, x+w-16, y-53, price, 10, YELLOW, "UIB")
        y -= h

def base(c, title):
    col(c, BLACK); c.rect(0, 0, W, H, fill=1, stroke=0)
    text(c, 35, 24, f"КОНЦЕПЦИЯ · {title}", 7.5, MUTED, "UIB")
    right(c, W-35, 24, "Apex Auto · стр. 1", 7.5, MUTED)

def concept_1(path):
    c=canvas.Canvas(str(path), pagesize=A4); base(c,"ПАНЕЛЬ CRM")
    brand(c,35,H-35); roundbox(c,35,H-190,W-70,82,SOFT,LINE,14)
    text(c,55,H-137,"NISSAN QASHQAI",24,WHITE,"UIB"); text(c,55,H-160,"В987КХ126  ·  SJNFAAJ10U2155739",9,MUTED)
    right(c,W-55,H-140,"3 ЗАМЕЧАНИЯ",12,YELLOW,"UIB"); right(c,W-55,H-160,"Заказ-наряд #15",9,MUTED)
    text(c,35,H-220,"ВЫЯВЛЕННЫЕ ЗАМЕЧАНИЯ",12,WHITE,"UIB"); issue_rows(c,35,H-238,W-70)
    c.save()

def concept_2(path):
    c=canvas.Canvas(str(path), pagesize=A4); base(c,"ЖЁЛТАЯ ШАПКА")
    col(c,YELLOW); c.rect(0,H-150,W,150,fill=1,stroke=0); c.drawImage(logo,35,H-125,82,82,mask="auto")
    text(c,135,H-75,"NISSAN QASHQAI",27,BLACK,"UIB"); text(c,135,H-101,"ДИАГНОСТИЧЕСКАЯ КАРТА #15",10,BLACK,"UIB")
    text(c,35,H-190,"КЛИЕНТСКИЙ ОТЧЁТ",9,YELLOW,"UIB"); text(c,35,H-218,"Обнаружено 3 замечания",20,WHITE,"UIB")
    issue_rows(c,35,H-245,W-70,card=False,numbered=True); c.save()

def concept_3(path):
    c=canvas.Canvas(str(path), pagesize=A4); base(c,"БОКОВАЯ МАРКА")
    col(c,YELLOW); c.rect(0,0,145,H,fill=1,stroke=0); c.drawImage(logo,28,H-125,88,88,mask="auto")
    text(c,23,H-165,"APEX AUTO",19,BLACK,"UIB"); text(c,23,H-190,"ДИАГНОСТИКА",10,BLACK,"UIB")
    text(c,23,H-250,"АВТОМОБИЛЬ",7.5,BLACK,"UIB"); text(c,23,H-275,"Nissan",15,BLACK,"UIB"); text(c,23,H-295,"Qashqai",15,BLACK,"UIB")
    text(c,170,H-65,"РЕЗУЛЬТАТ ОСМОТРА",9,YELLOW,"UIB"); text(c,170,H-98,"Требует внимания",25,WHITE,"UIB")
    text(c,170,H-124,"3 замечания · заказ-наряд #15",9,MUTED)
    issue_rows(c,170,H-165,W-205); c.save()

def concept_4(path):
    c=canvas.Canvas(str(path), pagesize=A4); base(c,"КАРТОЧКА КЛИЕНТА")
    brand(c,35,H-35,True); roundbox(c,35,H-250,W-70,142,SOFT,LINE,18)
    text(c,58,H-145,"Nissan Qashqai",26,WHITE,"UIB"); text(c,58,H-171,"В987КХ126",11,MUTED)
    roundbox(c,58,H-223,125,34,"#2A151B",RED,9); text(c,75,H-202,"1 НЕИСПРАВНО",9,RED,"UIB")
    roundbox(c,195,H-223,145,34,"#292414",AMBER,9); text(c,212,H-202,"2 ВНИМАНИЕ",9,AMBER,"UIB")
    text(c,35,H-285,"РЕКОМЕНДАЦИИ СЕРВИСА",11,YELLOW,"UIB"); issue_rows(c,35,H-305,W-70); c.save()

def concept_5(path):
    c=canvas.Canvas(str(path), pagesize=A4); base(c,"ТЕХНИЧЕСКИЙ")
    text(c,35,H-55,"APEX",32,WHITE,"UIB"); text(c,131,H-55,"AUTO",32,YELLOW,"UIB")
    line(c,YELLOW); c.setLineWidth(4); c.line(35,H-70,W-35,H-70)
    text(c,35,H-110,"ДИАГНОСТИЧЕСКАЯ КАРТА / 015",9,MUTED,"UIB"); right(c,W-35,H-110,"09.08.2026",9,MUTED)
    text(c,35,H-150,"NISSAN QASHQAI",25,WHITE,"UIB"); text(c,35,H-174,"VIN  SJNFAAJ10U2155739",9,MUTED)
    issue_rows(c,35,H-220,W-70,card=False); c.save()

def concept_6(path):
    c=canvas.Canvas(str(path), pagesize=A4); base(c,"МИНИМАЛЬНЫЙ")
    brand(c,35,H-38,True); right(c,W-35,H-70,"ОТЧЁТ #15",10,YELLOW,"UIB")
    text(c,35,H-140,"Nissan Qashqai",31,WHITE,"UIB"); text(c,35,H-169,"В987КХ126 · клиент Иван Петров",10,MUTED)
    col(c,YELLOW); c.roundRect(35,H-215,W-70,7,3,fill=1,stroke=0)
    text(c,35,H-255,"ТОЛЬКО ВАЖНОЕ",9,YELLOW,"UIB"); text(c,35,H-286,"3 выявленных замечания",22,WHITE,"UIB")
    issue_rows(c,35,H-315,W-70,card=False); c.save()

def concept_7(path):
    c=canvas.Canvas(str(path), pagesize=A4); base(c,"ПРЕМИУМ")
    roundbox(c,25,H-225,W-50,190,PANEL,LINE,22); brand(c,48,H-58,True)
    text(c,48,H-145,"NISSAN QASHQAI",29,WHITE,"UIB"); text(c,48,H-174,"Диагностическая карта #15",10,MUTED)
    right(c,W-48,H-145,"3",34,YELLOW,"UIB"); right(c,W-48,H-169,"ЗАМЕЧАНИЯ",9,YELLOW,"UIB")
    text(c,35,H-265,"ПРИОРИТЕТНЫЕ РАБОТЫ",11,WHITE,"UIB"); issue_rows(c,35,H-286,W-70,card=True,numbered=True); c.save()

for i, fn in enumerate([concept_1,concept_2,concept_3,concept_4,concept_5,concept_6,concept_7],1):
    fn(OUT / f"concept-{i}.pdf")
print(OUT)
