# handwriter_v2.py
import io
import random
import logging
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import config

logger = logging.getLogger(__name__)
FONTS_DIR = config.FONTS_DIR

LIGATURES = ["ff", "fi", "fl", "ffi", "ffl", "st", "ct"]


class HandwriterV2:
    def __init__(self):
        self.fonts = {}
        self.user_fonts = {}
        self._load_system()
        self._load_user()

    def _load_system(self):
        candidates = {
            "cursive": [
                "C:/Windows/Fonts/Georgia.ttf",
                "C:/Windows/Fonts/Times.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
                str(FONTS_DIR / "LiberationSerif-Regular.ttf"),
            ],
            "print": [
                "C:/Windows/Fonts/Arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                str(FONTS_DIR / "DejaVuSans.ttf"),
            ],
            "handwritten": [
                "C:/Windows/Fonts/ComicSansMS.ttf",
                str(FONTS_DIR / "DejaVuSans.ttf"),
            ],
            "elegant": [
                "C:/Windows/Fonts/Georgia.ttf",
                str(FONTS_DIR / "LiberationSerif-Regular.ttf"),
            ],
        }
        for style, paths in candidates.items():
            for p in paths:
                if Path(p).exists():
                    try:
                        self.fonts[style] = {
                            "font": ImageFont.truetype(p, 32),
                            "title": ImageFont.truetype(p, 40),
                            "small": ImageFont.truetype(p, 24),
                        }
                        logger.info(f"Handwriter: загружен {style} из {p}")
                        break
                    except Exception as e:
                        logger.warning(f"Шрифт {p}: {e}")
        if not self.fonts:
            d = ImageFont.load_default()
            self.fonts["default"] = {"font": d, "title": d, "small": d}

    def _load_user(self):
        if not FONTS_DIR.exists():
            return
        for f in FONTS_DIR.glob("user_*.ttf"):
            try:
                uid = int(f.stem.replace("user_", ""))
                self.load_user(uid, str(f))
            except Exception as e:
                logger.error(f"Ошибка загрузки {f}: {e}")

    def load_user(self, uid: int, path: str) -> bool:
        try:
            self.user_fonts[str(uid)] = {
                "font": ImageFont.truetype(path, 32),
                "title": ImageFont.truetype(path, 40),
                "small": ImageFont.truetype(path, 24),
            }
            return True
        except Exception as e:
            logger.error(f"Ошибка загрузки пользовательского шрифта: {e}")
            return False

    def get(self, uid: int, style: str = None):
        if style == "user":
            uf = self.user_fonts.get(str(uid))
            if uf:
                return uf
            style = "cursive"
        return self.fonts.get(style, next(iter(self.fonts.values())))

    def generate(self, text: str, uid: int = None, style: str = "cursive") -> bytes:
        fd = self.get(uid, style)
        font = fd["font"]
        margin = 60
        line_h = 50
        max_w = 800 - margin * 2

        lines = self._wrap(text, font, max_w)
        if len(lines) > 35:
            lines = lines[:35]
            lines.append("... (текст обрезан)")

        h = margin * 2 + len(lines) * line_h + 100
        img = Image.new("RGB", (800, h), color="white")
        draw = ImageDraw.Draw(img)

        for i in range(len(lines) + 1):
            y = margin + i * line_h
            draw.line([(margin, y), (800 - margin, y)], fill=(200, 220, 255), width=1)
        draw.line(
            [(margin + 20, margin), (margin + 20, margin + len(lines) * line_h)],
            fill=(255, 200, 200),
            width=1,
        )

        x0 = margin + 30
        for i, line in enumerate(lines):
            y_base = margin + i * line_h + 10
            x = x0
            words = line.split(" ")
            for wi, word in enumerate(words):
                x = self._draw_word(img, font, word, x, y_base)
                if wi < len(words) - 1:
                    sp = self._char_width(font, " ") * random.uniform(0.9, 1.3)
                    x += int(sp)

        buf = io.BytesIO()
        img.save(buf, format="PNG", quality=95)
        buf.seek(0)
        return buf.getvalue()

    def _wrap(self, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list:
        lines = []
        for paragraph in text.split("\n"):
            words = paragraph.split()
            cur = ""
            for w in words:
                test = cur + " " + w if cur else w
                if self._text_width(font, test) <= max_w:
                    cur = test
                else:
                    if cur:
                        lines.append(cur)
                    cur = w
            if cur:
                lines.append(cur)
        return lines if lines else [text]

    def _text_width(self, font, text: str) -> int:
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0] if bbox else len(text) * 15

    def _char_width(self, font, char: str) -> int:
        bbox = font.getbbox(char)
        return bbox[2] - bbox[0] if bbox else 15

    def _draw_word(self, img: Image.Image, font, word: str, x: int, y_base: int) -> int:
        chars = list(word)
        ci = 0
        while ci < len(chars):
            lig = None
            for lig_candidate in LIGATURES:
                end = ci + len(lig_candidate)
                if end <= len(chars) and "".join(chars[ci:end]) == lig_candidate:
                    lig = lig_candidate
                    break
            if lig:
                x = self._draw_glyph(img, font, lig, x, y_base)
                ci += len(lig)
            else:
                x = self._draw_glyph(img, font, chars[ci], x, y_base)
                ci += 1
        return x

    def _draw_glyph(self, img: Image.Image, font, chars: str, x: int, y_base: int) -> int:
        bbox = font.getbbox(chars)
        gw = (bbox[2] - bbox[0]) if bbox else len(chars) * 15
        gh = (bbox[3] - bbox[1]) if bbox else 24
        pad = 8
        tmp = Image.new("RGBA", (gw + pad * 2, gh + pad * 2), (255, 255, 255, 0))
        tdraw = ImageDraw.Draw(tmp)
        tdraw.text((pad, pad), chars, font=font, fill=(30, 30, 30))
        angle = random.uniform(-3.0, 3.0)
        tmp = tmp.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=(255, 255, 255, 0))
        y_off = random.randint(-2, 2)
        img.paste(tmp, (x, y_base + y_off), tmp)
        spacing = gw * random.uniform(0.8, 1.2)
        return x + int(spacing)