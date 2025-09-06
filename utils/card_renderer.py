# utils/card_renderer.py
from __future__ import annotations
import io, os, math, random
from typing import Tuple
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

# ===== دعم العربية =====
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    _HAS_AR = True
except Exception:
    _HAS_AR = False

# ================== خطوط ==================
def _font_paths():
    return {
        "ar_regular": os.getenv("APP_AR_FONT",       r"C:\Windows\Fonts\tahoma.ttf"),
        "ar_bold":    os.getenv("APP_AR_FONT_BOLD",  r"C:\Windows\Fonts\tahomabd.ttf"),
        "en_regular": os.getenv("APP_EN_FONT",       r"C:\Windows\Fonts\segoeui.ttf"),
        "en_bold":    os.getenv("APP_EN_FONT_BOLD",  r"C:\Windows\Fonts\segoeuib.ttf"),
    }

def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size=size)
    except Exception:
        return ImageFont.load_default()

def _font(lang: str, size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    P = _font_paths()
    if lang == "ar":
        return _load_font(P["ar_bold" if bold else "ar_regular"], size)
    return _load_font(P["en_bold" if bold else "en_regular"], size)

# ================== أدوات نص ==================
from functools import lru_cache

@lru_cache(maxsize=512)
def _shape(text: str, lang: str) -> str:
    if lang != "ar" or not _HAS_AR:
        return text
    lines = []
    for ln in str(text).split("\n"):
        lines.append(get_display(arabic_reshaper.reshape(ln)))
    return "\n".join(lines)

def _text_w(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    return int(draw.textlength(text, font=font))

def _wrap(draw: ImageDraw.ImageDraw, raw_text: str, font: ImageFont.ImageFont, max_w: int, lang: str) -> list[str]:
    text = _shape(raw_text, lang)
    out: list[str] = []
    for src in text.split("\n"):
        if not src:
            out.append("")
            continue
        words = src.split(" ")
        cur = words[0]
        for w in words[1:]:
            test = f"{cur} {w}"
            if _text_w(draw, test, font) <= max_w:
                cur = test
            else:
                out.append(cur)
                cur = w
        out.append(cur)
    return out

# ================== أشكال/تأثيرات ==================
def _rounded_mask(size, radius: int):
    w, h = size
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle((0, 0, w-1, h-1), radius=radius, fill=255)
    return m

def _draw_round_rect(img: Image.Image, xy, r: int, fill=None, outline=None, width: int = 1):
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(xy, radius=r, fill=fill, outline=outline, width=width)

def _linear_gradient(size, start, end, vertical=True):
    w, h = size
    base = Image.new("RGBA", size, 0)
    grad = Image.new("L", (1, h if vertical else w), color=0)
    gdraw = ImageDraw.Draw(grad)
    length = h if vertical else w
    for i in range(length):
        gdraw.line(((0, i) if vertical else (i, 0),
                    (0, i) if vertical else (i, 0)), fill=int(255 * (i / max(1, length-1))))
    grad = grad.resize(size)
    top = Image.new("RGBA", size, start)
    bottom = Image.new("RGBA", size, end)
    base = Image.composite(bottom, top, grad)
    return base

def _rounded_gradient(size, r: int, start, end, vertical=True):
    g = _linear_gradient(size, start, end, vertical)
    mask = _rounded_mask(size, r)
    out = Image.new("RGBA", size, 0)
    out.paste(g, (0, 0), mask)
    return out

def _rounded_shadow(size, r: int, blur: int, offset: tuple[int,int]=(0,0), color=(0,0,0,130)):
    base = Image.new("RGBA", (size[0]+abs(offset[0])*2, size[1]+abs(offset[1])*2), 0)
    box  = Image.new("RGBA", size, color)
    mask = _rounded_mask(size, r)
    tmp  = Image.new("RGBA", size, 0)
    tmp.paste(box, (0,0), mask)
    tmp = tmp.filter(ImageFilter.GaussianBlur(blur))
    base.paste(tmp, (abs(offset[0])+offset[0], abs(offset[1])+offset[1]), tmp)
    return base

def _inner_glow(img: Image.Image, xy, r: int, glow_color=(38, 198, 166, 60), glow_width=10):
    x0,y0,x1,y1 = xy
    w = x1-x0; h = y1-y0
    mask = _rounded_mask((w, h), r)
    glow = Image.new("RGBA", (w, h), 0)
    d = ImageDraw.Draw(glow)
    for i in range(glow_width, 0, -1):
        alpha = int(glow_color[3] * (i/glow_width))
        d.rounded_rectangle((i, i, w-1-i, h-1-i), r, outline=(glow_color[0],glow_color[1],glow_color[2], alpha), width=1)
    img.alpha_composite(glow, (x0, y0))

def _vignette(size, intensity=0.55):
    w, h = size
    rad = int(max(w, h) * 0.65)
    mask = Image.new("L", (w, h), 0)
    grad = Image.new("L", (rad*2, rad*2), 0)
    d = ImageDraw.Draw(grad)
    for r in range(rad, 0, -1):
        a = int(255 * (1 - (r / rad)) * intensity)
        d.ellipse((rad-r, rad-r, rad+r, rad+r), outline=a, width=2)
    grad = grad.filter(ImageFilter.GaussianBlur(60))
    mask.paste(grad, (w//2-rad, h//2-rad))
    vign = Image.new("RGBA", size, (0,0,0,180))
    return Image.composite(vign, Image.new("RGBA", size, 0), mask)

def _grain(size, alpha=18):
    # حبيبات فيلم خفيفة جداً
    w,h = size
    # effect_noise قد لا تكون متاحة بكل الإصدارات؛ fallback يدوي
    try:
        g = Image.effect_noise((w, h), 16)  # grayscale
    except Exception:
        import random
        g = Image.new("L", (w,h), 0)
        px = g.load()
        for y in range(h):
            for x in range(w):
                px[x,y] = random.randint(0, 30)
    g = ImageOps.autocontrast(g)
    return Image.merge("RGBA", (g,g,g, Image.new("L", (w,h), alpha)))

def _light_streak(size, angle_deg=24, width_ratio=0.42, color=(255,255,255,80)):
    w,h = size
    lw = int(w * width_ratio)
    stripe = Image.new("RGBA", (lw, h), 0)
    grad = _linear_gradient((lw, h), (255,255,255,0), color, vertical=False)
    stripe.alpha_composite(grad)
    stripe = stripe.rotate(angle_deg, resample=Image.BICUBIC, expand=True, fillcolor=(0,0,0,0))
    # ضعها من أعلى يسار تقريباً
    canvas = Image.new("RGBA", (w,h), 0)
    canvas.alpha_composite(stripe, (-int(w*0.2), -int(h*0.15)))
    return canvas

# ===== أيقونات بسيطة للفقـرات =====
def _icon_circle(draw: ImageDraw.ImageDraw, cx, cy, r, fill, outline=(255,255,255,140)):
    draw.ellipse((cx-r, cy-r, cx+r, cy+r), fill=fill, outline=outline, width=2)

def _icon_shield(img: Image.Image, cx, cy, s, color=(80,220,190,230)):
    # درع بسيط
    d = ImageDraw.Draw(img)
    w = s; h = int(s*1.2)
    x0, y0 = cx - w//2, cy - h//2
    poly = [
        (x0, y0),
        (x0+w, y0),
        (x0+w-int(w*0.12), y0+int(h*0.45)),
        (cx, y0+h),
        (x0+int(w*0.12), y0+int(h*0.45)),
    ]
    d.polygon(poly, fill=color, outline=(255,255,255,180))

# ================== البطاقة الاحترافية ==================
def render_welcome_card(
    *,
    lang: str,
    title: str,
    hello: str,
    status_line: str,
    pitch: str,
    safety: str,
    cta: str,
    size: Tuple[int, int] | None = None,
    dpr: float = 2.0,
) -> bytes:
    # مقاس / دقّة
    if size is None:
        W = int(os.getenv("WELCOME_WIDTH", "1400"))
        H = int(os.getenv("WELCOME_HEIGHT", "760"))
    else:
        W, H = size
    scale = max(1.0, float(dpr))
    cw, ch = int(W*scale), int(H*scale)

    # ألوان أساسية (متحيّزة للأزرق المخضر)
    ACCENT   = (38, 198, 166, 230)
    ACCENT_D = (22, 120, 100, 230)
    BG_TOP   = (8, 28, 42, 255)
    BG_BOT   = (12, 16, 30, 255)
    CARD_T1  = (24, 30, 48, 235)
    CARD_T2  = (18, 24, 42, 235)
    TXT_MAIN = (236, 244, 255, 255)
    TXT_DIM  = (188, 204, 226, 255)

    # خلفية + مؤثرات
    bg = _linear_gradient((cw, ch), BG_TOP, BG_BOT, vertical=True)
    bg.alpha_composite(_light_streak((cw, ch), angle_deg=28, width_ratio=0.55, color=(255,255,255,70)))
    bg.alpha_composite(_grain((cw, ch), alpha=16))
    bg.alpha_composite(_vignette((cw, ch), intensity=0.55))

    # بطاقة زجاجية مع ظل
    pad    = int(30*scale)
    radius = int(26*scale)
    inner  = (pad, pad, cw-pad, ch-pad)
    card_size = (cw-2*pad, ch-2*pad)

    shadow = _rounded_shadow(card_size, radius, blur=int(34*scale), offset=(0, 10), color=(0,0,0,150))
    bg.alpha_composite(shadow, (pad, pad-6))

    card = _rounded_gradient(card_size, radius, CARD_T1, CARD_T2, vertical=True)
    # لمعان زجاجي مائل خفي
    gloss = Image.new("RGBA", card_size, (255,255,255,0))
    gd = ImageDraw.Draw(gloss)
    gd.polygon([(0,int(card_size[1]*0.12)), (card_size[0],0), (card_size[0],int(card_size[1]*0.35))],
               fill=(255,255,255,22))
    gloss = gloss.filter(ImageFilter.GaussianBlur(int(30*scale)))
    card.alpha_composite(gloss)

    bg.alpha_composite(card, (pad, pad))
    # حدّ وتوهج داخلي
    _draw_round_rect(bg, inner, r=radius, outline=ACCENT, width=int(2*scale))
    _inner_glow(bg, inner, r=radius, glow_color=(ACCENT[0],ACCENT[1],ACCENT[2],80), glow_width=int(16*scale))

    d = ImageDraw.Draw(bg)
    inset = pad + int(28*scale)
    x0, x1 = inset, cw - inset
    y = inset

    # خطوط
    f_title = _font(lang, int(64*scale), bold=True)
    f_sub   = _font(lang, int(30*scale))
    f_body  = _font(lang, int(40*scale))
    f_small = _font(lang, int(32*scale))

    anchor = "ra" if lang == "ar" else "la"
    # عنوان + ظل خفيف
    title_shaped = _shape(title, lang)
    off = int(3*scale)
    pos = (x1 if lang=="ar" else x0, y)
    d.text((pos[0] + (-off if lang=="ar" else off), pos[1] + off), title_shaped, font=f_title, fill=(0,0,0,120), anchor=anchor)
    d.text(pos, title_shaped, font=f_title, fill=TXT_MAIN, anchor=anchor,
           stroke_width=int(1*scale), stroke_fill=(255,255,255,35))
    y += int(f_title.size*1.55)

    # سطر ترحيب صغير
    d.text((x1 if lang=="ar" else x0, y), _shape(hello, lang), font=f_sub, fill=TXT_DIM, anchor=anchor)
    y += int(f_sub.size*1.5)

    # كبسولة الحالة (زجاج)
    pill_h = int(56*scale)
    pill_pad = int(22*scale)
    pill_txt = _shape(status_line, lang)
    pill_w = _text_w(d, pill_txt, f_small) + pill_pad*2
    pill_bbox = (x1-pill_w, y, x1, y+pill_h) if lang=="ar" else (x0, y, x0+pill_w, y+pill_h)

    # ظل الكبسولة
    bg.alpha_composite(_rounded_shadow((pill_w, pill_h), int(pill_h/2), blur=int(18*scale), offset=(0,6), color=(0,0,0,120)),
                       (pill_bbox[0], pill_bbox[1]-int(2*scale)))
    # جسم زجاجي متدرّج
    pill = _rounded_gradient((pill_w, pill_h), int(pill_h/2), (255,255,255,35), (120,200,170,90), vertical=False)
    bg.alpha_composite(pill, (pill_bbox[0], pill_bbox[1]))
    # حد داخلي
    d.rounded_rectangle(pill_bbox, radius=int(pill_h/2), outline=(255,255,255,95), width=int(1*scale))
    # نص الكبسولة
    d.text((pill_bbox[2]-pill_pad if lang=="ar" else pill_bbox[0]+pill_pad, pill_bbox[1]+pill_h//2),
           pill_txt, font=f_small, fill=(255,255,255,240), anchor=("rm" if lang=="ar" else "lm"))
    y = pill_bbox[3] + int(26*scale)

    # فقرة 1 (أيقونة دائرة مضيئة)
    max_w = (x1-x0) - int(28*scale)
    line_h = int(f_body.size*1.45)
    icon_r = int(10*scale)

    # أيقونة الفقرة الأولى (دائرة متدرّجة)
    cx = (x1 + int(18*scale)) if lang=="ar" else (x0 - int(18*scale))
    cy = y + f_body.size//2
    _icon_circle(d, cx, cy, icon_r, fill=(255,255,255,230))
    lines = _wrap(d, pitch, f_body, max_w, lang)
    for i, ln in enumerate(lines):
        d.text((x1 if lang=="ar" else x0, y + i*line_h), ln, font=f_body, fill=TXT_MAIN, anchor=anchor)
    y += len(lines)*line_h + int(10*scale)

    # فقرة 2 (درع)
    lines2 = _wrap(d, safety, f_body, max_w, lang)
    cy2 = y + f_body.size//2
    _icon_shield(bg, (x1 + int(18*scale)) if lang=="ar" else (x0 - int(18*scale)), cy2, int(22*scale),
                 color=(ACCENT[0],ACCENT[1],ACCENT[2],230))
    for i, ln in enumerate(lines2):
        d.text((x1 if lang=="ar" else x0, y + i*line_h), ln, font=f_body, fill=TXT_MAIN, anchor=anchor)
    y += len(lines2)*line_h + int(16*scale)

    # زر CTA زجاجي (يضفي إحساس واقعي)
    btn_h  = int(64*scale)
    btn_pad = int(26*scale)
    btn_txt = _shape(cta, lang)
    btn_w = max(int(_text_w(d, btn_txt, f_small) + btn_pad*2), int(cw*0.36))
    btn_x0 = (x1-btn_w) if lang=="ar" else x0
    btn_box = (btn_x0, y, btn_x0+btn_w, y+btn_h)

    # ظل + جسم زجاجي
    bg.alpha_composite(_rounded_shadow((btn_w, btn_h), int(btn_h/2), blur=int(20*scale), offset=(0,7), color=(0,0,0,120)),
                       (btn_box[0], btn_box[1]-int(2*scale)))
    btn = _rounded_gradient((btn_w, btn_h), int(btn_h/2), (255,255,255,40), (ACCENT[0],ACCENT[1],ACCENT[2],85), vertical=False)
    bg.alpha_composite(btn, (btn_box[0], btn_box[1]))
    d.rounded_rectangle(btn_box, radius=int(btn_h/2), outline=(255,255,255,100), width=int(1*scale))

    # نص الزر + سهم اتجاه
    d.text((btn_box[2]-btn_pad if lang=="ar" else btn_box[0]+btn_pad, btn_box[1]+btn_h//2),
           btn_txt, font=f_small, fill=(255,255,255,250), anchor=("rm" if lang=="ar" else "lm"))
    # سهم
    tri_w = int(16*scale); tri_h = int(14*scale)
    if lang == "ar":
        tri = [(btn_box[0]+btn_pad, btn_box[1]+btn_h//2),
               (btn_box[0]+btn_pad+tri_w, btn_box[1]+btn_h//2-tri_h//2),
               (btn_box[0]+btn_pad+tri_w, btn_box[1]+btn_h//2+tri_h//2)]
    else:
        tri = [(btn_box[2]-btn_pad, btn_box[1]+btn_h//2),
               (btn_box[2]-btn_pad-tri_w, btn_box[1]+btn_h//2-tri_h//2),
               (btn_box[2]-btn_pad-tri_w, btn_box[1]+btn_h//2+tri_h//2)]
    ImageDraw.Draw(bg).polygon(tri, fill=(255,255,255,230))

    # تصغير لحيوية الخطوط
    if scale != 1.0:
        bg = bg.resize((W, H), Image.LANCZOS)

    buf = io.BytesIO()
    bg.save(buf, format="PNG", optimize=True, compress_level=9)
    return buf.getvalue()
