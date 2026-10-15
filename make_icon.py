#!/usr/bin/env python3
"""生成应用图标：assets/icon.png（1024）+ assets/app.ico（Windows）"""
import os
from PIL import Image, ImageDraw, ImageFont

SIZE = 1024
BRAND_A = (0, 180, 170)   # #00B4AA
BRAND_B = (45, 121, 228)  # #2D79E4
WHITE = (255, 255, 255)

out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
os.makedirs(out_dir, exist_ok=True)

# 1) 对角渐变背景（小图放大避免逐像素循环）
grad = Image.new("RGB", (256, 256))
for y in range(256):
    t = y / 255.0
    r = int(BRAND_A[0] + (BRAND_B[0] - BRAND_A[0]) * t)
    g = int(BRAND_A[1] + (BRAND_B[1] - BRAND_A[1]) * t)
    b = int(BRAND_A[2] + (BRAND_B[2] - BRAND_A[2]) * t)
    for x in range(256):
        grad.putpixel((x, y), (r, g, b))
grad = grad.resize((SIZE, SIZE), Image.BICUBIC)

# 2) 圆角遮罩
mask = Image.new("L", (SIZE, SIZE), 0)
d = ImageDraw.Draw(mask)
radius = int(SIZE * 0.22)
d.rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=radius, fill=255)

# 3) 合成
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
img.paste(grad, (0, 0), mask)

# 4) 画"抢"字
draw = ImageDraw.Draw(img)
font_path = "/System/Library/Fonts/PingFang.ttc"
font = ImageFont.truetype(font_path, int(SIZE * 0.52)) if os.path.exists(font_path) else None
bbox = draw.textbbox((0, 0), "抢", font=font)
tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
draw.text(
    ((SIZE - tw) / 2 - bbox[0], (SIZE - th) / 2 - bbox[1]),
    "抢", font=font, fill=WHITE,
)

png_path = os.path.join(out_dir, "icon.png")
img.save(png_path, "PNG")
print("icon.png ->", png_path)

# 5) Windows .ico
ico_path = os.path.join(out_dir, "app.ico")
img.save(ico_path, "ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                 (64, 64), (128, 128), (256, 256)])
print("app.ico ->", ico_path)

# 6) mac .icns（需 iconutil 转换 iconset）
iconset = os.path.join(out_dir, "app.iconset")
os.makedirs(iconset, exist_ok=True)
for s in (16, 32, 64, 128, 256, 512):
    im = img.resize((s, s), Image.LANCZOS)
    im.save(os.path.join(iconset, f"icon_{s}x{s}.png"))
    im2 = img.resize((s * 2, s * 2), Image.LANCZOS)
    im2.save(os.path.join(iconset, f"icon_{s}x{s}@2x.png"))
os.system(f"iconutil -c icns {iconset} -o {os.path.join(out_dir, 'app.icns')}")
print("app.icns ->", os.path.join(out_dir, "app.icns"))