"""Generates the banner artwork and logo in assets/. Run: python tools/make_art.py
All art is drawn from scratch (no brand photos), so it's free to use."""
import os
import random
from PIL import Image, ImageDraw, ImageFilter

S = 2                      # draw at 2x then shrink for smooth edges
H = 200
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
random.seed(7)


def rgb(h, a=255):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (a,)


def vgrad(w, h, top, bot):
    g = Image.new("RGBA", (w, h))
    d = ImageDraw.Draw(g)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(4)))
    return g


def hgrad(w, h, left, mid, right):
    g = Image.new("RGBA", (w, h))
    d = ImageDraw.Draw(g)
    for x in range(w):
        t = x / max(1, w - 1)
        a, b, tt = (left, mid, t * 2) if t < .5 else (mid, right, (t - .5) * 2)
        d.line([(x, 0), (x, h)], fill=tuple(int(a[i] + (b[i] - a[i]) * tt) for i in range(4)))
    return g


def fill_shape(img, draw_fn, grad):
    """Paste gradient image `grad` (full canvas size) through a mask drawn by draw_fn."""
    mask = Image.new("L", img.size, 0)
    draw_fn(ImageDraw.Draw(mask))
    img.paste(Image.alpha_composite(img, grad), (0, 0), mask)


def shadow(img, box, alpha=150, blur=10):
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([v * S for v in box], fill=(0, 0, 0, alpha))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(blur * S)))


def bubbles(d, x0, x1, y0, y1, n):
    for _ in range(n):
        x, y, r = random.uniform(x0, x1), random.uniform(y0, y1), random.uniform(.8, 2.2)
        d.ellipse([(x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S], fill=(255, 245, 210, random.randint(90, 170)))


def foam(d, x0, x1, ytop, h, spill=0):
    d.rounded_rectangle([x0 * S, ytop * S, x1 * S, (ytop + h) * S], radius=6 * S, fill=rgb("#fbf3df"))
    x = x0 - spill
    while x < x1 + spill:
        r = random.uniform(6, 10)
        d.ellipse([(x - r) * S, (ytop - r * .6) * S, (x + r) * S, (ytop + r * 1.2) * S], fill=rgb("#fffaf0"))
        x += r * 1.1
    d.rounded_rectangle([x0 * S, (ytop + h - 5) * S, x1 * S, (ytop + h) * S], radius=2 * S, fill=rgb("#efe0bb"))


def pint(img, cx, bottom, h=128, wt=62, wb=46):
    top = bottom - h
    shadow(img, (cx - wb, bottom - 6, cx + wb, bottom + 8))
    poly = [((cx - wt / 2) * S, top * S), ((cx + wt / 2) * S, top * S),
            ((cx + wb / 2) * S, bottom * S), ((cx - wb / 2) * S, bottom * S)]
    beer = vgrad(img.width, img.height, rgb("#f7b733"), rgb("#b8620a"))
    fill_shape(img, lambda m: m.polygon(poly, fill=255), beer)
    lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    bubbles(d, cx - wb / 2 + 5, cx + wb / 2 - 5, top + 30, bottom - 12, 40)
    d.polygon([((cx - wb / 2) * S, (bottom - 9) * S), ((cx + wb / 2) * S, (bottom - 9) * S),
               ((cx + wb / 2) * S, bottom * S), ((cx - wb / 2) * S, bottom * S)], fill=rgb("#ffd98a", 200))
    hl = [((cx - wt / 2 + 7) * S, (top + 26) * S), ((cx - wt / 2 + 14) * S, (top + 26) * S),
          ((cx - wb / 2 + 12) * S, (bottom - 14) * S), ((cx - wb / 2 + 6) * S, (bottom - 14) * S)]
    d.polygon(hl, fill=(255, 255, 255, 70))
    foam(d, cx - wt / 2, cx + wt / 2, top - 4, 26, 2)
    d.polygon(poly, outline=(255, 255, 255, 90), width=2 * S)
    img.alpha_composite(lay)


def mug(img, cx, bottom, w=82, h=112):
    x0, x1, top = cx - w / 2, cx + w / 2, bottom - h
    shadow(img, (x0 - 6, bottom - 6, x1 + 26, bottom + 8))
    hl = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(hl).ellipse([(x1 - 14) * S, (top + 24) * S, (x1 + 30) * S, (bottom - 18) * S], outline=rgb("#f3d9a0", 230), width=11 * S)
    img.alpha_composite(hl)
    beer = vgrad(img.width, img.height, rgb("#ffc247"), rgb("#a9560a"))
    fill_shape(img, lambda m: m.rounded_rectangle([x0 * S, top * S, x1 * S, bottom * S], radius=9 * S, fill=255), beer)
    lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    bubbles(d, x0 + 6, x1 - 6, top + 26, bottom - 14, 45)
    for i in range(4):                                   # glass dimples
        xx = x0 + 12 + i * (w - 24) / 3
        d.rounded_rectangle([(xx - 4) * S, (top + 34) * S, (xx + 4) * S, (bottom - 18) * S], radius=4 * S, fill=(255, 235, 180, 55))
    d.rounded_rectangle([x0 * S, (bottom - 10) * S, x1 * S, bottom * S], radius=4 * S, fill=rgb("#ffdf9a", 210))
    foam(d, x0 - 2, x1 + 2, top - 6, 28, 4)
    for dx in (-22, 8, 26):                              # drips
        d.rounded_rectangle([(cx + dx) * S, (top + 16) * S, (cx + dx + 7) * S, (top + 16 + random.randint(12, 26)) * S],
                            radius=4 * S, fill=rgb("#fffaf0"))
    d.rounded_rectangle([x0 * S, top * S, x1 * S, bottom * S], radius=9 * S, outline=(255, 255, 255, 110), width=2 * S)
    img.alpha_composite(lay)


def hops(img, cx, cy, scale=1.0):
    d = ImageDraw.Draw(img)
    d.line([(cx - 30 * scale) * S, (cy - 26 * scale) * S, cx * S, cy * S], fill=rgb("#4c7a26"), width=int(3 * S))
    for row in range(5):
        n = 2 + (row % 2)
        for i in range(n):
            x = cx + (i - (n - 1) / 2) * 9 * scale
            y = cy + row * 7 * scale
            r = (8 - row * .6) * scale
            d.ellipse([(x - r) * S, (y - r * .8) * S, (x + r) * S, (y + r * .9) * S],
                      fill=rgb("#8cc63f" if (row + i) % 2 else "#6fa832"), outline=rgb("#3f6b1f"), width=S)
    lx, ly = cx + 10 * scale, cy - 10 * scale
    pts = [(0, 0), (8, -10), (14, -6), (20, -16), (26, -8), (34, -12), (28, 0), (34, 8), (22, 6), (16, 14), (10, 4)]
    d.polygon([((lx + px * scale) * S, (ly + py * scale) * S) for px, py in pts], fill=rgb("#5d9b2c"), outline=rgb("#3f6b1f"))
    d.line([lx * S, ly * S, (lx + 26 * scale) * S, (ly - 2 * scale) * S], fill=rgb("#3f6b1f"), width=S)


def bottle(img, cx, bottom, w, h, neck_w, neck_h, top_col, bot_col, cap, label=True, square=False):
    body_top = bottom - h + neck_h + 20
    x0, x1 = cx - w / 2, cx + w / 2
    shadow(img, (x0 - 4, bottom - 6, x1 + 4, bottom + 8))
    glass = vgrad(img.width, img.height, top_col, bot_col)

    def shape(m):
        m.rounded_rectangle([x0 * S, body_top * S, x1 * S, bottom * S], radius=(6 if square else w / 2.6) * S, fill=255)
        m.polygon([(x0 * S, (body_top + 10) * S), ((cx - neck_w / 2) * S, (body_top - 22) * S),
                   ((cx + neck_w / 2) * S, (body_top - 22) * S), (x1 * S, (body_top + 10) * S)], fill=255)
        m.rectangle([(cx - neck_w / 2) * S, (bottom - h) * S, (cx + neck_w / 2) * S, (body_top - 18) * S], fill=255)
    fill_shape(img, shape, glass)
    lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    d.rounded_rectangle([(cx - neck_w / 2 - 2) * S, (bottom - h - 14) * S, (cx + neck_w / 2 + 2) * S, (bottom - h + 4) * S],
                        radius=3 * S, fill=cap)
    if label:
        ly0, ly1 = body_top + 30, bottom - 22
        d.rounded_rectangle([(x0 + 6) * S, ly0 * S, (x1 - 6) * S, ly1 * S], radius=3 * S, fill=rgb("#f4e9d0"))
        d.rectangle([(x0 + 10) * S, (ly0 + 4) * S, (x1 - 10) * S, (ly1 - 4) * S], outline=rgb("#b08a4a"), width=S)
        for k, frac in enumerate((.3, .5, .62)):
            yy = ly0 + (ly1 - ly0) * frac
            ww = (w - 30) * (1 if k == 1 else .6)
            d.line([(cx - ww / 2) * S, yy * S, (cx + ww / 2) * S, yy * S], fill=rgb("#7a5a2c"), width=(3 if k == 1 else 1) * S)
    d.rounded_rectangle([(x0 + 5) * S, (body_top + 4) * S, (x0 + 11) * S, (bottom - 10) * S], radius=3 * S, fill=(255, 255, 255, 60))
    img.alpha_composite(lay)


def rocks_glass(img, cx, bottom, w=74, h=58):
    x0, x1, top = cx - w / 2, cx + w / 2, bottom - h
    shadow(img, (x0 - 4, bottom - 5, x1 + 4, bottom + 7))
    base = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(base).rounded_rectangle([x0 * S, top * S, x1 * S, bottom * S], radius=5 * S, fill=(255, 255, 255, 40))
    img.alpha_composite(base)
    liquor = vgrad(img.width, img.height, rgb("#e08a1e"), rgb("#7a3a07"))
    fill_shape(img, lambda m: m.rounded_rectangle([(x0 + 3) * S, (top + 24) * S, (x1 - 3) * S, (bottom - 8) * S], radius=4 * S, fill=255), liquor)
    lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    for ix, iy in ((cx - 18, top + 12), (cx + 6, top + 18), (cx - 4, top + 30)):
        d.rounded_rectangle([(ix - 11) * S, (iy - 10) * S, (ix + 11) * S, (iy + 10) * S], radius=4 * S,
                            fill=(235, 248, 255, 150), outline=(255, 255, 255, 200), width=S)
    d.rounded_rectangle([x0 * S, (bottom - 9) * S, x1 * S, bottom * S], radius=3 * S, fill=(255, 255, 255, 90))
    d.rounded_rectangle([x0 * S, top * S, x1 * S, bottom * S], radius=5 * S, outline=(255, 255, 255, 150), width=2 * S)
    img.alpha_composite(lay)


def finish(img, w):
    return img.resize((w, H), Image.LANCZOS)


def background():
    w = 2600
    img = vgrad(w * S, H * S, rgb("#3a200c"), rgb("#140b05"))
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for _ in range(60):                                 # bar lights (bokeh)
        x, y, r = random.uniform(0, w), random.uniform(0, H * .7), random.uniform(6, 22)
        gd.ellipse([(x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S],
                   fill=random.choice([rgb("#ffb347", 70), rgb("#ffd27a", 55), rgb("#ff8c2a", 50)]))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(5 * S)))
    shelf = Image.new("RGBA", img.size, (0, 0, 0, 0))   # back-bar bottle silhouettes
    sd = ImageDraw.Draw(shelf)
    for row_y in (70, 140):
        sd.rectangle([0, row_y * S, w * S, (row_y + 4) * S], fill=(90, 55, 25, 160))
        x = 10
        while x < w:
            bw, bh = random.uniform(12, 22), random.uniform(32, 52)
            col = random.choice([(60, 30, 10, 120), (30, 50, 30, 110), (80, 50, 15, 120), (40, 40, 50, 110)])
            sd.rounded_rectangle([x * S, (row_y - bh + 12) * S, (x + bw) * S, row_y * S], radius=4 * S, fill=col)
            sd.rectangle([(x + bw / 2 - 3) * S, (row_y - bh) * S, (x + bw / 2 + 3) * S, (row_y - bh + 14) * S], fill=col)
            x += bw + random.uniform(4, 14)
    img.alpha_composite(shelf.filter(ImageFilter.GaussianBlur(1.5 * S)))
    wood = vgrad(img.width, 34 * S, rgb("#8a5428"), rgb("#4a2a12"))
    wd = ImageDraw.Draw(wood)
    for _ in range(40):
        y = random.uniform(4, 32)
        wd.line([(random.uniform(0, w) * S, y * S), (random.uniform(0, w) * S, y * S)], fill=(40, 20, 8, 50), width=S)
    img.alpha_composite(wood, (0, (H - 34) * S))
    ImageDraw.Draw(img).line([(0, (H - 34) * S), (w * S, (H - 34) * S)], fill=rgb("#c08850", 200), width=2 * S)
    vign = hgrad(img.width, img.height, (0, 0, 0, 30), (0, 0, 0, 120), (0, 0, 0, 30))
    img.alpha_composite(vign)
    return finish(img, w)


def beer_group():
    w = 400
    img = Image.new("RGBA", (w * S, H * S), (0, 0, 0, 0))
    floor = H - 22
    pint(img, 80, floor, h=124)
    mug(img, 198, floor, w=86, h=110)
    pint(img, 312, floor, h=104, wt=54, wb=40)
    hops(img, 362, 128, .9)
    return finish(img, w)


def liquor_group():
    w = 400
    img = Image.new("RGBA", (w * S, H * S), (0, 0, 0, 0))
    floor = H - 22
    bottle(img, 70, floor, 58, 150, 18, 48, rgb("#2c4a2a", 235), rgb("#0f2010", 245), rgb("#b5893c"))   # green gin
    bottle(img, 150, floor, 70, 140, 20, 44, rgb("#e19a3a", 235), rgb("#7a3d0b", 245), rgb("#2b1a0e"), square=True)  # whiskey
    bottle(img, 236, floor, 56, 166, 16, 60, rgb("#d9eef7", 150), rgb("#a7c7d6", 170), rgb("#c0c0c0"))  # clear vodka
    rocks_glass(img, 330, floor)
    return finish(img, w)


def logo():
    size = 120
    img = Image.new("RGBA", (size * S, size * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([88 * S, 40 * S, 116 * S, 88 * S], outline=rgb("#ffc247"), width=8 * S)
    d.rounded_rectangle([30 * S, 34 * S, 94 * S, 108 * S], radius=10 * S, fill=rgb("#ffc247"))
    d.rounded_rectangle([30 * S, 98 * S, 94 * S, 108 * S], radius=4 * S, fill=rgb("#ffe39a"))
    for x in (44, 62, 80):
        d.rounded_rectangle([(x - 3) * S, 50 * S, (x + 3) * S, 92 * S], radius=3 * S, fill=rgb("#ffe08a"))
    for x, r in ((32, 12), (48, 14), (66, 13), (84, 12), (94, 9)):
        d.ellipse([(x - r) * S, (32 - r) * S, (x + r) * S, (32 + r) * S], fill=rgb("#ffffff"))
    hops(img, 22, 70, .9)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    background().convert("RGB").save(os.path.join(OUT, "banner_bg.png"), optimize=True)
    beer_group().save(os.path.join(OUT, "banner_beer.png"), optimize=True)
    liquor_group().save(os.path.join(OUT, "banner_liquor.png"), optimize=True)
    pill = Image.new("RGBA", (300 * S, 56 * S), (0, 0, 0, 0))
    ImageDraw.Draw(pill).rounded_rectangle([0, 0, 300 * S - 1, 56 * S - 1], radius=12 * S, fill=(8, 22, 42, 185),
                                           outline=(255, 255, 255, 60), width=S)
    pill.resize((300, 56), Image.LANCZOS).save(os.path.join(OUT, "badge_bg.png"))
    lg = logo()
    lg.save(os.path.join(OUT, "logo.png"))
    ico = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    ImageDraw.Draw(ico).rounded_rectangle((6, 6, 250, 250), 48, fill=rgb("#0d2f57"))
    ico.alpha_composite(lg.resize((210, 210), Image.LANCZOS), (22, 24))
    ico.save(os.path.join(OUT, "app.ico"), sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    for name in ("banner_bg", "banner_beer", "banner_liquor"):      # smaller set for laptop screens
        im = Image.open(os.path.join(OUT, name + ".png"))
        im.resize((int(im.width * .72), int(im.height * .72)), Image.LANCZOS).save(os.path.join(OUT, name + "_sm.png"), optimize=True)
    print("art written to", OUT)
