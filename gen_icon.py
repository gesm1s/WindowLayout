#!/usr/bin/env python3
"""Generate an .icns app icon: two overlapping windows with traffic lights."""
import os
import subprocess
import shutil
import tempfile
from PIL import Image, ImageDraw

SIZES = [16, 32, 64, 128, 256, 512, 1024]
OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "WindowLayout.icns")


def render_icon(size):
    """Draw two overlapping window rectangles into a PIL Image."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    s = size
    pad = int(s * 0.08)
    r = max(1, int(s * 0.06))
    titlebar_h = max(2, int(s * 0.13))

    # Back window (upper-left) — note: PIL y=0 is top
    bx, by = pad, pad
    bw, bh = int(s * 0.65), int(s * 0.65)
    draw.rounded_rectangle(
        [bx, by, bx + bw, by + bh],
        radius=r, fill=(140, 165, 215), outline=(75, 100, 180), width=max(1, s // 40)
    )
    # Back titlebar
    draw.rectangle([bx, by, bx + bw, by + titlebar_h], fill=(100, 130, 190))

    # Front window (lower-right, overlapping)
    fx, fy = int(s * 0.28), int(s * 0.28)
    fw, fh = int(s * 0.65), int(s * 0.65)
    draw.rounded_rectangle(
        [fx, fy, fx + fw, fy + fh],
        radius=r, fill=(242, 242, 247), outline=(75, 100, 180), width=max(1, s // 40)
    )
    # Front titlebar
    draw.rectangle([fx, fy, fx + fw, fy + titlebar_h], fill=(90, 130, 215))

    # Traffic light dots
    dot_r = max(1, int(s * 0.022))
    dot_cy = fy + titlebar_h // 2
    colors = [(240, 75, 75), (240, 190, 65), (90, 200, 90)]
    for i, color in enumerate(colors):
        cx = fx + int(s * 0.06) + i * int(s * 0.05)
        draw.ellipse([cx - dot_r, dot_cy - dot_r, cx + dot_r, dot_cy + dot_r], fill=color)

    return img


def main():
    tmpdir = tempfile.mkdtemp()
    iconset = os.path.join(tmpdir, "WindowLayout.iconset")
    os.makedirs(iconset)

    size_map = {
        16: ["16x16"], 32: ["16x16@2x", "32x32"],
        64: ["32x32@2x"], 128: ["128x128"],
        256: ["128x128@2x", "256x256"],
        512: ["256x256@2x", "512x512"],
        1024: ["512x512@2x"],
    }

    for size in SIZES:
        img = render_icon(size)
        for name in size_map.get(size, []):
            img.save(os.path.join(iconset, f"icon_{name}.png"))

    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", OUTPUT], check=True)
    shutil.rmtree(tmpdir)
    print(f"Icon saved to {OUTPUT}")


if __name__ == "__main__":
    main()
