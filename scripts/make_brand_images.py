"""充電沼のロゴ(assets/logo-juden.png)と共有用の画像(assets/ogp-juden-1200x630.png)を作る。

タプ夫の画像(assets/chara/)に文字を重ねるだけ。名前やキャッチコピーを変えたら作り直す:
python scripts/make_brand_images.py
2026-11-14 サイトを白地の「仕様書」風にしたので、白地用(本人「黒背景より白背景がいい」)。「充電沼」の右に英語の「Charge Mania」(本人)。
書体は Cozy Desk の Zen Maru Gothic(OFL)を借りる(media\\CozyDesk\\scripts\\fonts)。英字は Windows の Consolas。
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT.parent / "CozyDesk" / "scripts" / "fonts"
BLACK = FONTS / "ZenMaruGothic-Black.ttf"
BOLD = FONTS / "ZenMaruGothic-Bold.ttf"
MONO = Path(r"C:\Windows\Fonts\consolab.ttf")
if not MONO.exists():
    MONO = BOLD
ORANGE, INK, SUB = (248, 132, 37, 255), (22, 25, 30, 255), (89, 99, 111, 255)
BG, TILE, GRID = (245, 246, 248, 255), (243, 238, 231, 255), (20, 30, 45, 16)
NAME = [("充電", ORANGE), ("沼", INK)]
EN = "Charge Mania"
TAG = "充電まわりを、取説まで読む。"
SUB_TEXT = "2台目を挿すと何Wになるか、全機種で。"


def font(path, size):
    return ImageFont.truetype(str(path), size)


def trim(im):
    return im.crop(im.getbbox())


def tile(im, pad):
    """線画のタプ夫を、角丸のクリームの台に載せる"""
    w, h = im.width + pad * 2, im.height + pad * 2
    t = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(t).rounded_rectangle((0, 0, w - 1, h - 1), radius=pad * 2, fill=TILE)
    t.alpha_composite(im, (pad, pad))
    return t


def draw_name(d, x, y, size, en_size):
    """「充電沼」を描き、その右に英語名を下そろえで置く。右端の x を返す"""
    f = font(BLACK, size)
    top, bottom = d.textbbox((0, 0), "充電沼", font=f)[1::2]
    for text, color in NAME:
        d.text((x, y - top), text, font=f, fill=color)
        x += d.textlength(text, font=f)
    ef = font(MONO, en_size)
    etop, ebottom = d.textbbox((0, 0), EN, font=ef)[1::2]
    x += en_size * 0.5
    d.text((x, y + (bottom - top) - ebottom), EN, font=ef, fill=SUB)
    return x + d.textlength(EN, font=ef), bottom - top


def grid(im, step):
    """方眼を薄く重ねる(別の層に描いて重ねないと、線が透けずに真っ白になる)"""
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for x in range(0, im.width, step):
        d.line((x, 0, x, im.height), fill=GRID)
    for y in range(0, im.height, step):
        d.line((0, y, im.width, y), fill=GRID)
    im.alpha_composite(layer)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")

    # ロゴ(背景透明、高さ120。サイトの頭では 40px で出る)
    face = trim(Image.open(ROOT / "assets/chara/face-futsu.png").convert("RGBA"))
    face = face.resize((round(face.width * 96 / face.height), 96), Image.LANCZOS)
    face = tile(face, 12)
    logo = Image.new("RGBA", (1000, 120), (0, 0, 0, 0))
    logo.alpha_composite(face, (0, 0))
    d = ImageDraw.Draw(logo)
    x0 = face.width + 22
    end, nh = draw_name(d, x0, 6, 74, 30)
    tf = font(BOLD, 24)
    ttop = d.textbbox((0, 0), TAG, font=tf)[1]
    d.text((x0, 6 + nh + 14 - ttop), TAG, font=tf, fill=SUB)
    end2 = x0 + d.textlength(TAG, font=tf)
    logo = logo.crop((0, 0, int(max(end, end2)) + 6, 120))
    logo.save(ROOT / "assets/logo-juden.png")

    # 共有用(1200x630、白い方眼の地、下にオレンジの線)
    og = Image.new("RGBA", (1200, 630), BG)
    grid(og, 30)
    body = trim(Image.open(ROOT / "assets/chara/tapuo-futsu.png").convert("RGBA"))
    body = body.resize((round(body.width * 430 / body.height), 430), Image.LANCZOS)
    card = tile(body, 26)
    og.alpha_composite(card, (1200 - card.width - 56, (630 - card.height) // 2 - 6))
    d = ImageDraw.Draw(og)
    d.text((76, 150), "CHARGE MANIA · SPEC SHEET", font=font(MONO, 22), fill=(181, 78, 0, 255))
    draw_name(d, 72, 200, 120, 32)
    d.text((76, 380), TAG, font=font(BOLD, 38), fill=INK)
    d.text((76, 440), SUB_TEXT, font=font(BOLD, 30), fill=SUB)
    d.rectangle((0, 622, 1200, 630), fill=ORANGE)
    og.convert("RGB").save(ROOT / "assets/ogp-juden-1200x630.png")
    print("作った:", logo.size, og.size)


if __name__ == "__main__":
    main()
