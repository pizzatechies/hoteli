"""Generate the official Hoteli logo set as clean SVG (wordmark outlined from Poppins, OFL)."""

import sys
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
FONTS = Path(__file__).parent / "fonts"  # Poppins-500.ttf, Poppins-600.ttf (OFL, from Google Fonts)

TEAL_LIGHT, TEAL, TEAL_DARK = "#14b8a6", "#0f766e", "#115e59"
AMBER = "#f59e0b"
INK = "#0f172a"
WHITE = "#ffffff"


class Font:
    def __init__(self, path):
        self.tt = TTFont(path)
        self.glyphs = self.tt.getGlyphSet()
        self.cmap = self.tt.getBestCmap()
        self.upem = self.tt["head"].unitsPerEm

    def name(self, ch):
        return self.cmap[ord(ch)]

    def advance(self, glyph):
        return self.tt["hmtx"][glyph][0]

    def path(self, glyph, x, baseline, scale):
        pen = SVGPathPen(self.glyphs)
        self.glyphs[glyph].draw(TransformPen(pen, (scale, 0, 0, -scale, x, baseline)))
        return pen.getCommands()

    def bounds(self, glyph):
        pen = BoundsPen(self.glyphs)
        self.glyphs[glyph].draw(pen)
        return pen.bounds

    def i_dot(self):
        """Centre and radius (font units) of the dot on the lowercase i."""
        rec = RecordingPen()
        self.glyphs[self.name("i")].draw(rec)
        contours, current = [], []
        for op, args in rec.value:
            current.append((op, args))
            if op in ("closePath", "endPath"):
                contours.append(current)
                current = []
        best = None
        for contour in contours:
            pts = [p for _op, args in contour for p in args]
            if not pts:
                continue
            ys = [p[1] for p in pts]
            xs = [p[0] for p in pts]
            box = (min(xs), min(ys), max(xs), max(ys))
            if best is None or box[3] > best[3]:
                best = box
        x0, y0, x1, y1 = best
        return (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0) / 2


SEMIBOLD = Font(FONTS / "Poppins-600.ttf")
MEDIUM = Font(FONTS / "Poppins-500.ttf")


def wordmark(x, baseline, size, color, dot_color, tracking=-12):
    """'hoteli' with the i's dot replaced by a round sun. Returns (svg, width)."""
    f = SEMIBOLD
    scale = size / f.upem
    parts, cursor = [], x
    for ch in "hotel":
        g = f.name(ch)
        parts.append(f.path(g, cursor, baseline, scale))
        cursor += (f.advance(g) + tracking) * scale
    dotless = "dotlessi"
    i_x = cursor
    parts.append(f.path(dotless, cursor, baseline, scale))
    # centre the sun over the dotless stem
    bx0, _by0, bx1, _by1 = f.bounds(dotless)
    _dx, dy, r = f.i_dot()
    cx = i_x + (bx0 + bx1) / 2 * scale
    cy = baseline - dy * scale
    radius = r * scale * 1.05
    cursor += f.advance(dotless) * scale
    svg = (f'<path fill="{color}" d="{" ".join(parts)}"/>'
           f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{radius:.2f}" fill="{dot_color}"/>')
    return svg, cursor - x


def caps(text, x, baseline, size, color, tracking=140):
    f = MEDIUM
    scale = size / f.upem
    parts, cursor = [], x
    for ch in text:
        g = f.name(ch)
        parts.append(f.path(g, cursor, baseline, scale))
        cursor += (f.advance(g) + tracking) * scale
    width = cursor - x - tracking * scale
    return f'<path fill="{color}" d="{" ".join(parts)}"/>', width


def mark(x=0, y=0, size=64, mono=None, uid="m", tile=None, corner=15):
    """The app mark: rounded square, H formed by two towers, sun rising between them."""
    s = size / 64
    if tile:  # white tile for busy or coloured backgrounds
        bg, fg, sun, defs = tile, TEAL, AMBER, ""
    elif mono:
        bg, fg, sun, defs = mono, WHITE, WHITE, ""
    else:
        bg = f"url(#{uid}g)"
        fg, sun = WHITE, AMBER
        defs = (f'<defs><linearGradient id="{uid}g" x1="0" y1="0" x2="1" y2="1">'
                f'<stop offset="0" stop-color="{TEAL_LIGHT}"/><stop offset=".55" stop-color="{TEAL}"/>'
                f'<stop offset="1" stop-color="{TEAL_DARK}"/></linearGradient></defs>')
    # Two towers (stems) and a low crossbar; the sun rises in the gap between the towers.
    left, right, stem, top, bottom, bar_top, bar_h, r = 15.0, 49.0, 8.0, 14.0, 50.0, 34.0, 6.0, 2.4
    lx1, rx0 = left + stem, right - stem
    h = (f"M{left + r} {top}H{lx1 - r}a{r} {r} 0 0 1 {r} {r}V{bar_top}H{rx0}V{top + r}"
         f"a{r} {r} 0 0 1 {r}-{r}H{right - r}a{r} {r} 0 0 1 {r} {r}V{bottom - r}a{r} {r} 0 0 1-{r} {r}"
         f"H{rx0 + r}a{r} {r} 0 0 1-{r}-{r}V{bar_top + bar_h}H{lx1}V{bottom - r}a{r} {r} 0 0 1-{r} {r}"
         f"H{left + r}a{r} {r} 0 0 1-{r}-{r}V{top + r}a{r} {r} 0 0 1 {r}-{r}Z")
    return (f'{defs}<g transform="translate({x} {y}) scale({s:g})">'
            f'<rect width="64" height="64" rx="{corner}" fill="{bg}"/>'
            f'<path fill="{fg}" d="{h}"/>'
            f'<circle cx="32" cy="24.5" r="4.6" fill="{sun}"/></g>')


def svg(width, height, body, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" '
            f'width="{width:.0f}" height="{height:.0f}" role="img" aria-label="{title}">'
            f'<title>{title}</title>{body}</svg>\n')


def horizontal(text_color, dot_color, mono=None, uid="h"):
    size, gap = 54, 16
    word, width = wordmark(64 + gap, 50, size, text_color, dot_color)
    return svg(64 + gap + width + 2, 64, mark(mono=mono, uid=uid) + word, "Hoteli")


def tagline(text_color, sub_color, uid="t"):
    word, width = wordmark(80, 44, 50, text_color, AMBER)
    sub, sub_w = caps("HOTEL MANAGEMENT SYSTEM", 82, 60.5, 9.6, sub_color)
    total = max(80 + width, 82 + sub_w) + 2
    return svg(total, 64, mark(uid=uid) + word + sub, "Hoteli – hotel management system")


def stacked(text_color, uid="s"):
    word, width = wordmark(0, 0, 60, text_color, AMBER)
    w = max(width, 128) + 8
    body = mark(x=(w - 128) / 2, y=0, size=128, uid=uid)
    word, _ = wordmark((w - width) / 2, 128 + 62, 60, text_color, AMBER)
    return svg(w, 128 + 78, body + word, "Hoteli")


def social():
    w, h = 1280, 640
    bg = ('<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0f172a"/>'
          '<stop offset="1" stop-color="#134e4a"/></linearGradient>'
          '<radialGradient id="glow" cx=".5" cy=".38" r=".5"><stop offset="0" stop-color="#f59e0b" stop-opacity=".18"/>'
          '<stop offset="1" stop-color="#f59e0b" stop-opacity="0"/></radialGradient></defs>'
          f'<rect width="{w}" height="{h}" fill="url(#bg)"/><rect width="{w}" height="{h}" fill="url(#glow)"/>')
    word, ww = wordmark(0, 0, 120, WHITE, AMBER)
    total = 160 + 36 + ww
    x0 = (w - total) / 2
    body = bg + mark(x=x0, y=170, size=160, uid="sp")
    word, _ = wordmark(x0 + 196, 170 + 126, 120, WHITE, AMBER)
    line1, l1 = caps("HOTEL MANAGEMENT SYSTEM", 0, 0, 26, "#5eead4", tracking=180)
    line1, _ = caps("HOTEL MANAGEMENT SYSTEM", (w - l1) / 2, 420, 26, "#5eead4", tracking=180)
    line2, l2 = caps("BOOKINGS · FRONT DESK · BILLING · M-PESA · POS · WEBSITE", 0, 0, 17, "#cbd5e1", tracking=120)
    line2, _ = caps("BOOKINGS · FRONT DESK · BILLING · M-PESA · POS · WEBSITE", (w - l2) / 2, 470, 17,
                    "#cbd5e1", tracking=120)
    credit, cw = caps("CRAFTED BY PIZZA TECHNOLOGIES", 0, 0, 13, "#94a3b8", tracking=160)
    credit, _ = caps("CRAFTED BY PIZZA TECHNOLOGIES", (w - cw) / 2, 590, 13, "#94a3b8", tracking=160)
    return svg(w, h, body + word + line1 + line2 + credit, "Hoteli – hotel management system")


files = {
    "hoteli-mark.svg": svg(64, 64, mark(uid="mk"), "Hoteli"),
    "hoteli-app-icon.svg": svg(64, 64, mark(uid="ai", corner=0), "Hoteli"),
    "hoteli-mark-mono.svg": svg(64, 64, mark(mono=INK), "Hoteli"),
    "hoteli-mark-white.svg": svg(64, 64, mark(tile=WHITE), "Hoteli"),
    "hoteli-logo.svg": horizontal(INK, AMBER, uid="lg"),
    "hoteli-logo-light.svg": horizontal(WHITE, AMBER, uid="ll"),
    "hoteli-logo-mono.svg": horizontal(INK, INK, mono=INK, uid="lm"),
    "hoteli-logo-tagline.svg": tagline(INK, TEAL, uid="tg"),
    "hoteli-logo-tagline-light.svg": tagline(WHITE, "#5eead4", uid="tl"),
    "hoteli-logo-stacked.svg": stacked(INK, uid="st"),
    "hoteli-logo-stacked-light.svg": stacked(WHITE, uid="sl"),
    "social-preview.svg": social(),
}
for name, content in files.items():
    (OUT / name).write_text(content, encoding="utf-8")
    print(f"{name:34s} {len(content):6d} bytes")
