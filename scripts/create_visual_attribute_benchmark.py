from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests" / "assets" / "visual_attribute_benchmark.png"

COLORS = [
    ("black", (20, 20, 20)), ("white", (245, 245, 245)),
    ("gray", (125, 125, 125)), ("red", (220, 25, 25)),
    ("orange", (245, 120, 10)), ("yellow", (220, 235, 15)),
    ("green", (20, 150, 45)), ("cyan", (15, 190, 190)),
    ("blue", (30, 70, 220)), ("purple", (130, 45, 180)),
    ("pink", (245, 105, 170)), ("brown", (125, 70, 30)),
]


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1200, 600), (225, 225, 225))
    draw = ImageDraw.Draw(image)
    for index, (name, rgb) in enumerate(COLORS):
        column, row = index % 6, index // 6
        x0, y0 = 40 + column * 195, 40 + row * 280
        size = 80 if column < 2 else 130 if column < 4 else 180
        draw.rectangle((x0, y0, x0 + size, y0 + size), fill=rgb, outline=(0, 0, 0), width=3)
        draw.text((x0, y0 + size + 8), name, fill=(0, 0, 0))
    image.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    main()
