"""充電沼のロゴ(assets/logo-juden.png)と共有用の画像(assets/ogp-juden-1200x630.png)を作る。

タプ夫の画像(assets/chara/)に文字を重ねるだけ。名前やキャッチコピーを変えたら作り直す:
python scripts/make_brand_images.py
書体は Cozy Desk の Zen Maru Gothic(OFL)を借りる(media\\CozyDesk\\scripts\\fonts)。
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT.parent / "CozyDesk" / "scripts" / "fonts"
BLACK = FONTS / "ZenMaruGothic-Black.ttf"
MED = FONTS / "ZenMaruGothic-Bold.ttf"
ORANGE, INK, CREAM = (248, 132, 37, 255), (31, 31, 31, 255), (255, 246, 236, 255)
NAME = [("充電", ORANGE), ("沼", INK)]
TAG = "充電まわりを、取説まで読む。"
SUB = "2台目を挿すと何Wになるか、全機種で。"


def draw_name(d, x, y, size):
    f = ImageFont.truetype(str(BLACK), size)
    for text, color in NAME:
        d.text((x, y), text, font=f, fill=color)
        x += d.textlength(text, font=f)
    return x


def trim(im):
    return im.crop(im.getbbox())


def main() -> None:
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    # ロゴ(背景透明、高さ170)
    face = trim(Image.open(ROOT / "assets/chara/face-futsu.png").convert("RGBA"))
    fh = 160
    face = face.resize((round(face.width * fh / face.height), fh), Image.LANCZOS)
    logo = Image.new("RGBA", (900, 170), (0, 0, 0, 0))
    logo.alpha_composite(face, (5, 5))
    d = ImageDraw.Draw(logo)
    x0 = face.width + 30
    nf = ImageFont.truetype(str(BLACK), 104)
    top, bottom = d.textbbox((0, 0), "".join(t for t, _ in NAME), font=nf)[1::2]
    end = draw_name(d, x0, 8 - top, 104)  # 文字の上端を 8px に
    tf = ImageFont.truetype(str(MED), 30)
    ttop = d.textbbox((0, 0), TAG, font=tf)[1]
    end2 = x0 + d.textlength(TAG, font=tf)
    d.text((x0, 8 + (bottom - top) + 14 - ttop), TAG, font=tf, fill=INK)  # 名前の下に 14px あけて置く
    logo = logo.crop((0, 0, int(max(end, end2)) + 10, 170))
    logo.save(ROOT / "assets/logo-juden.png")

    # 共有用(1200x630、クリーム地、下にオレンジの帯)
    og = Image.new("RGBA", (1200, 630), CREAM)
    body = trim(Image.open(ROOT / "assets/chara/tapuo-futsu.png").convert("RGBA"))
    bh = 500
    body = body.resize((round(body.width * bh / body.height), bh), Image.LANCZOS)
    og.alpha_composite(body, (1200 - body.width - 50, 630 - 24 - bh))
    d = ImageDraw.Draw(og)
    draw_name(d, 72, 170, 150)
    d.text((76, 360), TAG, font=ImageFont.truetype(str(MED), 40), fill=INK)
    d.text((76, 425), SUB, font=ImageFont.truetype(str(MED), 32), fill=(92, 82, 72, 255))
    d.rectangle((0, 606, 1200, 630), fill=ORANGE)
    og.convert("RGB").save(ROOT / "assets/ogp-juden-1200x630.png")
    print("作った:", logo.size, og.size)


if __name__ == "__main__":
    main()
