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
    # 英語名は黒い札にオレンジの文字(2026-11-18 本人「Charge Mania をもっと目立たせたい」→ B 案)
    ef = font(MONO, en_size)
    l, t, r, b = d.textbbox((0, 0), EN, font=ef)
    pad = round(en_size * 0.32)
    nh = bottom - top
    x += en_size * 0.55
    lift = round(en_size * 0.1)  # 札の下を漢字の下より少しだけ下げる
    box = (x, y + nh - (b - t) - pad * 2 + lift, x + (r - l) + pad * 2, y + nh + lift)
    d.rounded_rectangle(box, radius=round(en_size * 0.22), fill=INK)
    d.text((x + pad - l, box[1] + pad - t), EN, font=ef, fill=ORANGE)
    return box[2], nh


BOLT = [(22.5, 6), (11, 22.5), (19, 22.5), (16.5, 34), (29, 16.5), (20.8, 16.5)]


def bolt_icon(size):
    """黒い角丸の四角にオレンジの稲妻(2026-11-21 本人「タイトルの左に充電をイメージするアイコン」→ A 案)。
    4倍で描いて縮め、ふちを滑らかにする"""
    k = size * 4 / 40
    big = Image.new("RGBA", (size * 4, size * 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.rounded_rectangle((0, 0, size * 4 - 1, size * 4 - 1), radius=round(10 * k), fill=INK)
    d.polygon([(x * k, y * k) for x, y in BOLT], fill=ORANGE)
    return big.resize((size, size), Image.LANCZOS)


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

    # ロゴ(背景透明。サイトの頭では 40px の高さで出る)
    # 2026-11-18 本人「キャラのアイコンはなくていい」「Charge Mania をもう少し大きく」「キャッチコピーは右に」
    # → 顔を外し、名前だけの1行にした。キャッチコピーは画像に入れず、build.py が右に文字で出す
    logo = Image.new("RGBA", (1000, 120), (0, 0, 0, 0))
    d = ImageDraw.Draw(logo)
    end, nh = draw_name(d, 4, 20, 80, 42)
    logo = logo.crop(logo.getbbox())
    ic = bolt_icon(logo.height)
    gap = round(logo.height * 0.22)
    pad = Image.new("RGBA", (ic.width + gap + logo.width + 8, logo.height + 8), (0, 0, 0, 0))
    pad.alpha_composite(ic, (4, 4))
    pad.alpha_composite(logo, (4 + ic.width + gap, 4))
    pad.save(ROOT / "assets/logo-juden.png")
    logo = pad

    # 共有用(1200x630、白い方眼の地、下にオレンジの線)
    og = Image.new("RGBA", (1200, 630), BG)
    grid(og, 30)
    body = trim(Image.open(ROOT / "assets/chara/tapuo-futsu.png").convert("RGBA"))
    body = body.resize((round(body.width * 430 / body.height), 430), Image.LANCZOS)
    card = tile(body, 26)
    og.alpha_composite(card, (1200 - card.width - 56, (630 - card.height) // 2 - 6))
    d = ImageDraw.Draw(og)
    d.text((76, 150), "CHARGE MANIA · SPEC SHEET", font=font(MONO, 22), fill=(181, 78, 0, 255))
    draw_name(d, 72, 200, 120, 40)
    d.text((76, 380), TAG, font=font(BOLD, 38), fill=INK)
    d.text((76, 440), SUB_TEXT, font=font(BOLD, 30), fill=SUB)
    d.rectangle((0, 622, 1200, 630), fill=ORANGE)
    og.convert("RGB").save(ROOT / "assets/ogp-juden-1200x630.png")
    # ブラウザのタブ・ホーム画面のアイコンも稲妻にそろえる(それまではタプ夫の顔)
    for n in (32, 48, 192):
        bolt_icon(n).save(ROOT / f"assets/favicon-{n}.png")
    bolt_icon(180).save(ROOT / "assets/apple-touch-icon.png")
    bolt_icon(256).save(ROOT / "assets/favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    print("作った:", logo.size, og.size)


if __name__ == "__main__":
    main()
