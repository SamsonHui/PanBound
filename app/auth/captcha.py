"""图形验证码。

使用 Pillow 生成 4 位字母数字混编的 PNG,验证码原文存 Redis,TTL 由配置决定。
调用方用 /auth/captcha/<captcha_key>.png 取图片,登录时再以同样 captcha_key 提交答案。
"""

from __future__ import annotations

import io
import random
import string
from pathlib import Path

from flask import current_app
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..extensions import get_redis

_CAPTCHA_PREFIX = "captcha:"

# 默认字符集:去掉易混淆的 0/O/1/l/I
_CHARS = "23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz"

# 字体回退顺序
_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def _load_font(size: int) -> ImageFont.ImageFont:
    for p in _FONT_CANDIDATES:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _rand_color(min_v: int = 0, max_v: int = 200) -> tuple[int, int, int]:
    return (
        random.randint(min_v, max_v),
        random.randint(min_v, max_v),
        random.randint(min_v, max_v),
    )


def generate_captcha() -> tuple[str, bytes]:
    """生成一对 (captcha_key, png_bytes)。"""
    length = current_app.config["CAPTCHA_LENGTH"]
    width = current_app.config["CAPTCHA_WIDTH"]
    height = current_app.config["CAPTCHA_HEIGHT"]
    font_size = current_app.config["CAPTCHA_FONT_SIZE"]
    ttl = current_app.config["CAPTCHA_TTL_SECONDS"]

    text = "".join(random.choice(_CHARS) for _ in range(length))

    img = Image.new("RGB", (width, height), (245, 246, 250))
    draw = ImageDraw.Draw(img)
    font = _load_font(font_size)

    # 干扰线
    for _ in range(4):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        draw.line(((x1, y1), (x2, y2)), fill=_rand_color(160, 220), width=1)

    # 噪点
    for _ in range(int(width * height * 0.02)):
        draw.point((random.randint(0, width), random.randint(0, height)), fill=_rand_color(120, 220))

    # 文本:逐字符偏移
    char_w = width // (length + 1)
    for i, ch in enumerate(text):
        x = char_w * (i + 1) - char_w // 2
        y = (height - font_size) // 2 + random.randint(-3, 3)
        draw.text((x, y), ch, font=font, fill=_rand_color(20, 100))

    img = img.filter(ImageFilter.SMOOTH)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    png_bytes = buf.getvalue()

    # 写 Redis
    key = "".join(random.choice(string.ascii_letters + string.digits) for _ in range(24))
    try:
        get_redis().setex(f"{_CAPTCHA_PREFIX}{key}", ttl, text.lower())
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning("captcha 写 Redis 失败:%s", exc)

    return key, png_bytes


class CaptchaError(Exception):
    pass


def verify_captcha(captcha_key: str, answer: str, *, consume: bool = True) -> bool:
    """校验验证码并消耗。

    answer 会被 strip+lower 后与存储值比对。
    失败时总是消耗掉 (防暴力枚举)。
    """
    if not captcha_key or not answer:
        return False
    key = f"{_CAPTCHA_PREFIX}{captcha_key}"
    try:
        r = get_redis()
        stored = r.get(key)
        if consume:
            r.delete(key)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning("captcha 读 Redis 失败:%s", exc)
        return False
    if not stored:
        return False
    return stored == answer.strip().lower()
