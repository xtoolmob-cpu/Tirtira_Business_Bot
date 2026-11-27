#!/usr/bin/env python3
"""Promotional poster for Tirtira Business Studio, styled after the user's
EZA-MOBILE poster: bold blue/yellow/red commercial layout, exact text."""
from PIL import Image, ImageDraw, ImageFont

W = H = 1600
BLUE = (10, 60, 160)
DARK_BLUE = (6, 38, 110)
YELLOW = (255, 205, 0)
RED = (225, 25, 35)
WHITE = (255, 255, 255)
LIGHT = (235, 243, 255)
INK = (15, 25, 60)

img = Image.new("RGB", (W, H), LIGHT)
d = ImageDraw.Draw(img)

BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
ETH = "/home/hatch/workspace/fayda_id_printer/assets/NotoSansEthiopic-Regular.ttf"

def font(path, size):
    return ImageFont.truetype(path, size)

def centered(text, y, fnt, fill, stroke=0):
    tw = d.textlength(text, font=fnt)
    d.text(((W - tw) / 2, y), text, font=fnt, fill=fill, stroke_width=stroke)

def rounded(box, r, **kw):
    d.rounded_rectangle(box, radius=r, **kw)

# ---- header band ----
d.rectangle([0, 0, W, 372], fill=DARK_BLUE)
d.polygon([(0, 372), (W, 292), (W, 372)], fill=BLUE)
d.rectangle([0, 344, W, 372], fill=YELLOW)
centered("TIRTIRA", 28, font(BOLD, 150), YELLOW)
centered("BUSINESS STUDIO", 185, font(BOLD, 92), WHITE)
centered("Telegram AI Business Assistant", 288, font(BOLD, 44), WHITE)

# ---- Amharic tagline ----
centered("የቢዝነስዎ AI ረዳት — ፈጣን, ጥራት ያለው, ተመጣጣኝ!", 388, font(ETH, 52), DARK_BLUE)

# ---- red banner ----
rounded([70, 472, W - 70, 572], 40, fill=RED)
centered("20 FREE Credits for New Users!", 495, font(BOLD, 56), WHITE)

# ---- services grid ----
services = [
    ("AI Chat & Writing", "የ AI ጽሑፍ ረዳት"),
    ("Advertisement Poster", "የማስታወቂያ ፖስተር"),
    ("AI Image Design", "የ AI ምስል ዲዛይን"),
    ("Text → PDF", "ጽሑፍ ወደ PDF"),
    ("Photo → PDF", "ፎቶ ወደ PDF"),
    ("PDF → Text", "PDF ወደ ጽሑፍ"),
    ("PDF OCR", "የተቃኘ PDF ንባብ"),
    ("Amharic Support", "የአማርኛ ድጋፍ"),
]
gx, gy = 70, 612
cw, ch, gap = 715, 128, 20
for i, (en, am) in enumerate(services):
    x = gx + (i % 2) * (cw + gap)
    y = gy + (i // 2) * (ch + gap)
    rounded([x, y, x + cw, y + ch], 26, fill=WHITE, outline=BLUE, width=4)
    d.ellipse([x + 26, y + 36, x + 82, y + 92], fill=BLUE)
    ck = font(BOLD, 44)
    tw = d.textlength("✓", font=ck)
    d.text((x + 54 - tw / 2, y + 40), "✓", font=ck, fill=WHITE)
    d.text((x + 105, y + 16), en, font=font(BOLD, 43), fill=INK)
    d.text((x + 105, y + 70), am, font=font(ETH, 40), fill=BLUE)

# ---- packages band ----
py = gy + 4 * (ch + gap) + 10
d.rectangle([0, py, W, py + 150], fill=YELLOW)
centered("Credit Packages", py + 10, font(BOLD, 46), DARK_BLUE)
centered("100 – 50 ብር  •  500 – 200 ብር  •  1,000 – 350 ብር  •  3,000 – 900 ብር",
         py + 72, font(ETH, 47), INK)

# ---- bottom contact band ----
by = py + 150
d.rectangle([0, by, W, H], fill=DARK_BLUE)
centered("Telebirr / CBE — ክፍያ ይቀበላል", by + 18, font(ETH, 46), YELLOW)
centered("☎  0920210606   •   0912416068", by + 82, font(BOLD, 74), WHITE)
centered("Tirtira Business Studio — ስራዎን ያሳድጉ!", by + 178, font(ETH, 44), WHITE)

img.save("/home/hatch/workspace/tirtira_studio/poster.png")
print("poster saved", img.size)
