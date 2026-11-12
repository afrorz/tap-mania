"""タップマニアのサイトを作る。data/products/*.yaml + content/**/*.md → public/

python scripts/build.py           # public/ を作り直す
python scripts/build.py --serve   # 作ったあと http://localhost:8791 で確認
python scripts/build.py --drafts  # draft: true の記事も作る(手元で見るとき。push 前は付けずに作り直す)

仕組みは Cozy Desk(afrorz/cozy-desk)の build.py を借りている(紹介リンク・ページの枠・GA4・sitemap・CNAME)。
ページの中身はタップマニア用に書き直した。製品は記事ではなくデータとして持ち、図鑑・比べ表・計算機はそこから作る。
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import quote

import markdown
import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "public"
CFG = yaml.safe_load((ROOT / "config" / "site.yaml").read_text(encoding="utf-8"))
SITE = CFG["site"]
CATS = CFG["categories"]
CAT = {c["slug"]: c for c in CATS}
TODAY = dt.date.today()
CSS_VER = int((ROOT / "assets" / "tap.css").stat().st_mtime)  # 直したら古い見た目が残らないように
# 見出しは丸ゴシック、本文と表は読みやすさ優先で Noto Sans JP(2026-11-12 本人「フォントが読みづらい」)
FONTS = "https://fonts.googleapis.com/css2?family=M+PLUS+Rounded+1c:wght@800&family=Noto+Sans+JP:wght@400;700&display=swap"

PSE = {  # 仕様書 第3章の3段階
    "confirmed": ("確認済", "メーカー公式ページか取扱説明書で、PSE の表示を確認しました"),
    "image": ("公式画像で確認", "公式の製品画像で、本体の PSE の表示が読めました"),
    "unconfirmed": ("未確認", "PSE の表示を公式の情報で確かめられていません。このため買うボタンを出していません"),
}
# PSE マークの形。ひし形(特定電気用品: タップ・充電器)は登録検査機関名まで要る。丸形(モバイルバッテリー)は要らない
# (法律の説明なので、サイトに書く前に経産省の原文で確かめる。docs/WRITING.md)
PSE_MARK = {"diamond": "ひし形", "round": "丸形"}
TAP_CATS = ("tap", "extension", "usb-tap")


def pse_mark(p: dict) -> str:
    return (p.get("pse") or {}).get("mark") or ("round" if p.get("category") == "battery" else "diamond")
FACES = ["futsu", "shinpai", "odoroki", "majime", "ureshii"]


def e(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def die(msg: str) -> None:
    sys.exit("ビルドを止めました: " + msg)


# ── 製品データを読む ─────────────────────────────────────────

def load_products() -> list[dict]:
    items = []
    for path in sorted((ROOT / "data" / "products").glob("*.yaml")):
        p = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        where = path.name
        for k in ("id", "maker", "model", "name", "category", "official_url", "checked", "pse"):
            if not p.get(k):
                die(f"{where}: {k} がありません")
        if p["id"] != path.stem:
            die(f"{where}: id({p['id']})とファイル名を同じにしてください")
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", p["id"]):
            die(f"{where}: id は英小文字・数字・ハイフンだけにしてください")
        if p["category"] not in CAT:
            die(f"{where}: category {p['category']} は config/site.yaml の categories にありません")
        st = (p["pse"] or {}).get("status")
        if st not in PSE:
            die(f"{where}: pse.status は confirmed / image / unconfirmed のどれかです")
        if pse_mark(p) not in PSE_MARK:
            die(f"{where}: pse.mark は diamond / round のどちらかです")
        if st != "unconfirmed":
            need = ("how", "notifier", "date") + (("inspector",) if pse_mark(p) == "diamond" else ())
            for k in need:
                if not p["pse"].get(k):
                    die(f"{where}: pse.status が {st} なのに pse.{k} がありません(確かめた方法と日付を残す決まり)")
        usb = p.get("usb") or {}
        if len(usb.get("ports") or []) >= 2 and not usb.get("sharing"):
            print(f"  注意 {where}: USB ポートが2つ以上なのに sharing(同時に使ったときの配り方)がありません。取説で確かめて書く")
        for k in ("checked", "recall_checked"):
            if isinstance(p.get(k), str):
                p[k] = dt.date.fromisoformat(p[k])
        p["url"] = f"/t/{p['id']}/"
        items.append(p)
    return items


def stale(products: list[dict]) -> list[dict]:
    lim = int(SITE.get("stale_days") or 180)
    return [p for p in products if (TODAY - p["checked"]).days > lim]


# ── 記事(疑問記事・固定ページ)を読む ─────────────────────────

def split_fm(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        die(f"{path.name}: front matter(--- で囲んだ頭の部分)がありません")
    _, fm, body = text.split("---", 2)
    return yaml.safe_load(fm) or {}, body


def load_articles(products: list[dict]) -> list[dict]:
    ids = {p["id"] for p in products}
    arts = []
    for path in sorted((ROOT / "content" / "q").glob("*.md")):
        fm, body = split_fm(path)
        for k in ("title", "date", "summary"):
            if not fm.get(k):
                die(f"{path.name}: {k} がありません")
        if fm.get("draft") and "--drafts" not in sys.argv:  # 手元で下書きも見るときは --drafts
            continue
        for pid in fm.get("products") or []:
            if pid not in ids:
                die(f"{path.name}: products の {pid} が data/products にありません")
        fm["slug"] = path.stem
        fm["url"] = f"/q/{path.stem}/"
        fm["body"] = body
        arts.append(fm)
    arts.sort(key=lambda a: str(a["date"]), reverse=True)
    return arts


# ── 紹介リンク(Cozy Desk の store_buttons と同じ作り) ───────────

STORES = [
    ("rakuten", "楽天で見る", "https://search.rakuten.co.jp/search/mall/{q}/"),
    ("amazon", "Amazon で見る", "https://www.amazon.co.jp/s?k={q}"),
    ("yahoo", "Yahoo!ショッピングで見る", "https://shopping.yahoo.co.jp/search?p={q}"),
]
AFF = CFG.get("affiliate") or {}
HAS_AFF = any(AFF.get(k) for k, _, _ in STORES)
AFF_SHOPS = "・".join(n for k, n in (("amazon", "Amazon"), ("rakuten", "楽天"), ("yahoo", "Yahoo!ショッピング")) if AFF.get(k))
AD_NOTE = '<p class="adnote">広告を含みます</p>'


def store_buttons(p: dict, where: str) -> str:
    """買うボタン。PSE 未確認の物には出さない(仕様書 第3章)"""
    if p["pse"]["status"] == "unconfirmed":
        return '<p class="nobuy">PSE の表示を公式の情報で確かめられていないため、買うボタンを出していません。</p>'
    only = p.get("stores") or [k for k, _, _ in STORES]
    bad = [s for s in only if s not in {k for k, _, _ in STORES}]
    if bad:
        die(f"{p['id']}: stores の名前が違います {bad}(rakuten / amazon / yahoo)")
    q = p.get("q") or f"{p['maker']} {p['model']}"
    out = []
    for i, (key, label, base) in enumerate(s for s in STORES if s[0] in only):
        url = base.replace("{q}", quote(q, safe=""))
        tmpl = AFF.get(key) or ""
        attrs = ""
        if tmpl:
            url = tmpl.replace("{url}", quote(url, safe=""))
            attrs = ' rel="sponsored noopener"'
        out.append(f'<a class="btn{" buy" if i == 0 else ""}" href="{e(url)}" target="_blank"{attrs} '
                   f'data-store="{key}" data-where="{e(where)}">{label}</a>')
    # 冒頭だけでは足りない場合がある(消費者庁のステマ規制 Q&A)ので、リンクの近くにも出す
    return (AD_NOTE if HAS_AFF else "") + '<div class="btns">' + "".join(out) + "</div>"


# ── ページの枠 ──────────────────────────────────────────────

def asset_exists(rel: str) -> bool:
    return (ROOT / "assets" / rel).exists()


def face(name: str, size: int = 64) -> str:
    """タプ夫の顔。画像がまだ無いときはオレンジの丸で代わりにする"""
    if name not in FACES:
        die(f"タプ夫の表情 {name} はありません({' / '.join(FACES)})")
    if asset_exists(f"chara/face-{name}.png"):
        return f'<img class="face" src="/assets/chara/face-{name}.png" alt="タプ夫" width="{size}" height="{size}" loading="lazy">'
    return f'<span class="face face-ph" style="width:{size}px;height:{size}px" aria-label="タプ夫"></span>'


def bubble(name: str, text: str) -> str:
    return f'<div class="bubble {e(name)}">{face(name)}<p><b>タプ夫</b>{e(text)}</p></div>'


def nav(current: str = "") -> str:
    items = [("usbc", "/usb-c/", "USB-C の配り方"), ("compare", "/compare/", "比べ表"), ("q", "/q/", "疑問に答える"),
             ("tools", "/tools/watt/", "計算機"), ("about", "/about/", "確かめ方")]
    cur = ' aria-current="page"'
    return '<nav class="gnav" aria-label="サイト内">' + "".join(
        f'<a href="{u}"{cur if k == current else ""}>{n}</a>' for k, u, n in items) + "</nav>"


def page(*, title: str, desc: str, path: str, body: str, current: str = "", image: str = "",
         pr: bool = False, ld: list | None = None, noindex: bool = False) -> str:
    full = f"{title}｜{SITE['title']}" if title else f"{SITE['title']}｜{SITE['tagline']}"
    base = SITE["base_url"].rstrip("/")
    url = base + path
    og = image or (base + "/assets/ogp-1200x630.png" if asset_exists("ogp-1200x630.png") else "")
    extra = ""
    if noindex:
        extra += '<meta name="robots" content="noindex">\n'
    if og:
        extra += f'<meta property="og:image" content="{e(og)}">\n<meta name="twitter:card" content="summary_large_image">\n'
    if SITE.get("x_account"):
        extra += f'<meta name="twitter:site" content="@{e(SITE["x_account"])}">\n'
    if SITE.get("search_console_verification"):
        extra += f'<meta name="google-site-verification" content="{e(SITE["search_console_verification"])}">\n'
    if SITE.get("cf_analytics_token"):
        extra += ("<script defer src='https://static.cloudflareinsights.com/beacon.min.js' "
                  f"data-cf-beacon='{{\"token\": \"{e(SITE['cf_analytics_token'])}\"}}'></script>\n")
    if SITE.get("analytics_id"):
        gid = e(SITE["analytics_id"])
        extra += (f'<script async src="https://www.googletagmanager.com/gtag/js?id={gid}"></script>\n'
                  "<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}"
                  f"gtag('js',new Date());gtag('config','{gid}');</script>\n")
    for block in ld or []:
        extra += '<script type="application/ld+json">' + json.dumps(block, ensure_ascii=False).replace("</", "<\\/") + "</script>\n"
    if asset_exists("favicon.ico"):
        extra += '<link rel="icon" href="/assets/favicon.ico" sizes="any">\n'
    if asset_exists("favicon-32.png"):
        extra += '<link rel="icon" href="/assets/favicon-32.png" type="image/png" sizes="32x32">\n'
    if asset_exists("apple-touch-icon.png"):
        extra += '<link rel="apple-touch-icon" href="/assets/apple-touch-icon.png">\n'
    year = TODAY.year
    years = f"{SITE['copyright_from']}" + (f"–{year}" if year > SITE["copyright_from"] else "")
    ad_line = f"このサイトはアフィリエイト広告({AFF_SHOPS})を含みます" if HAS_AFF else "Gadget Terminal の姉妹サイト"
    top_ad = f'<div class="wrap">{AD_NOTE}</div>' if (pr and HAS_AFF) else ""
    if asset_exists("logo.png"):
        logo = f'<img src="/assets/logo.png" alt="{e(SITE["title"])}" height="44">'
    else:
        logo = f'<b>{e(SITE["title"])}</b><span>{e(SITE["tagline"])}</span>'
    x = (f' ・ <a href="https://x.com/{e(SITE["x_account"])}">X @{e(SITE["x_account"])}</a>' if SITE.get("x_account") else "")
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(full)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(url)}">
<meta property="og:type" content="{'article' if path.startswith('/q/') else 'website'}">
<meta property="og:site_name" content="{e(SITE['title'])}">
<meta property="og:title" content="{e(title or SITE['title'])}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{e(url)}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{FONTS}" rel="stylesheet">
<link rel="stylesheet" href="/assets/tap.css?v={CSS_VER}">
{extra}</head>
<body>
<header class="top">
  <div class="wrap">
    <a class="logo" href="/">{logo}</a>
    {nav(current)}
  </div>
</header>
{top_ad}
{body}
<footer>
  <div class="wrap">
    <span>© {years} {e(SITE['title'])}(運営 {e(SITE['author'])}) ・ <a href="/about/">確かめ方</a> ・ <a href="/fixes/">直した履歴</a> ・ <a href="/privacy/">プライバシー</a>{x}</span>
    <span>{ad_line}</span>
  </div>
</footer>
</body>
</html>
"""


# ── 製品の表示 ──────────────────────────────────────────────

NOT_LISTED = '<span class="nl">記載なし</span>'


def yesno(v) -> str:
    if v is None:
        return NOT_LISTED
    return "あり" if v else "なし"


def num(v, unit: str = "") -> str:
    if v is None or v == "":
        return NOT_LISTED
    if isinstance(v, (int, float)):
        s = f"{v:,}" if isinstance(v, int) else f"{v:g}"
        return f"{s}{unit}"
    return e(v)


def txt(v) -> str:
    return NOT_LISTED if v in (None, "", []) else e(v)


SWITCH = {"none": "なし", "all": "一括スイッチ", "individual": "個別スイッチ"}


def usb_c_ports(p: dict) -> list[dict]:
    return [x for x in ((p.get("usb") or {}).get("ports") or []) if str(x.get("type")).upper() == "C"]


def usb_summary(p: dict) -> str:
    usb = p.get("usb")
    if not usb:
        return "なし" if p["category"] in ("tap", "extension") else NOT_LISTED
    ports = usb.get("ports") or []
    parts = [f"{e(x.get('name') or x.get('type'))} 最大{num(x.get('max_w'), 'W')}" for x in ports]
    return " / ".join(parts) or NOT_LISTED


def sharing_list(p: dict) -> list[dict]:
    """同時に使ったときの配り方。[{use, out}] の形にそろえる(古い1行の書き方も読む)"""
    s = (p.get("usb") or {}).get("sharing")
    if not s:
        return []
    if isinstance(s, str):
        rows = []
        for part in s.split(" / "):
            use, _, out = part.partition(":")
            rows.append({"use": use.strip(), "out": out.strip()} if out else {"use": "", "out": part.strip()})
        return rows
    return [{"use": str(x.get("use", "")), "out": str(x.get("out", ""))} for x in s]


def sharing_html(p: dict) -> str:
    rows = sharing_list(p)
    if not rows:
        return NOT_LISTED
    src = (p.get("usb") or {}).get("sharing_source")
    trs = "".join(f"<tr><th>{e(r['use'])}</th><td>{e(r['out'])}</td></tr>" for r in rows)
    return (f'<table class="share"><thead><tr><th>挿すポート</th><th>それぞれの出力</th></tr></thead><tbody>{trs}</tbody></table>'
            + (f'<small>出典: {e(src)}</small>' if src else ""))


def spec_rows(p: dict) -> list[tuple[str, str]]:
    if p["category"] not in TAP_CATS:
        return gadget_rows(p)
    r = p.get("rating") or {}
    cord = p.get("cord") or {}
    o = p.get("outlets") or {}
    s = p.get("surge") or {}
    usb = p.get("usb")
    rows = [
        ("定格", (f"{num(r.get('volt'), 'V')}・{num(r.get('amp'), 'A')}" if r else NOT_LISTED)),
        ("合計の最大", num(r.get("watt_max"), "W")),
        ("差し込み口(AC)", num(o.get("ac"), "個")),
        ("コードの長さ", num(cord.get("length_m"), "m")),
        ("コードの種類", txt(cord.get("type"))),
        ("ほこりシャッター", yesno(o.get("shutter"))),
        ("トラッキング防止プラグ", yesno(o.get("tracking_plug"))),
        ("スイッチ", SWITCH.get(o.get("switch"), NOT_LISTED) if o.get("switch") else NOT_LISTED),
        ("3ピン(アース付き)", yesno(o.get("three_pin"))),
        ("回転プラグ", yesno(o.get("rotating_plug"))),
        ("マグネット", yesno(o.get("magnet"))),
        ("雷サージ", yesno(s.get("has")) if s else NOT_LISTED),
    ]
    if s.get("spec"):
        rows.append(("雷サージの公式記載", e(s["spec"])))
    if usb:
        rows += [
            ("USB ポート", usb_summary(p)),
            ("USB の合計", num(usb.get("total_w"), "W")),
            ("同時に使ったときの配り方", sharing_html(p)),
            ("USB PD", yesno(usb.get("pd"))),
            ("PPS", yesno(usb.get("pps"))),
        ]
        if usb.get("gan") is not None:
            rows.append(("GaN(窒化ガリウム)", yesno(usb.get("gan"))))
    else:
        rows.append(("USB ポート", usb_summary(p)))
    rows += [
        ("難燃性", txt(p.get("flame"))),
        ("色", txt("・".join(p.get("colors") or []))),
        ("保証", txt(p.get("warranty"))),
        ("国内の販売者", txt(p.get("seller_jp"))),
        ("値段(掲載時点)", txt(p.get("price"))),
    ]
    return rows


def usb_rows(p: dict) -> list[tuple[str, str]]:
    usb = p.get("usb") or {}
    rows = [
        ("USB ポート", usb_summary(p)),
        ("USB の合計", num(usb.get("total_w"), "W")),
        ("同時に使ったときの配り方", sharing_html(p)),
        ("USB PD", yesno(usb.get("pd"))),
        ("PPS", yesno(usb.get("pps"))),
    ]
    if usb.get("gan") is not None:
        rows.append(("GaN(窒化ガリウム)", yesno(usb.get("gan"))))
    return rows


def gadget_rows(p: dict) -> list[tuple[str, str]]:
    """充電器・モバイルバッテリーの表"""
    rows: list[tuple[str, str]] = []
    if p["category"] == "battery":
        b = p.get("battery") or {}
        rows += [
            ("容量", num(b.get("mah"), "mAh")),
            ("電力量", num(b.get("wh"), "Wh")),
            ("定格容量", num(b.get("rated_mah"), "mAh")),
            ("電池の種類", txt(b.get("cell"))),
            ("本体への充電(入力)", num(b.get("input_w"), "W")),
            ("本体の充電時間", txt(b.get("recharge_time"))),
            ("パススルー充電", yesno(b.get("passthrough"))),
            ("安全の機能(公式の記載)", txt(b.get("safety"))),
        ]
    else:
        rows += [("入力", txt(p.get("input"))), ("折りたたみプラグ", yesno(p.get("foldable_plug")))]
    rows += usb_rows(p)
    rows += [
        ("大きさ", txt(p.get("size"))),
        ("重さ", num(p.get("weight_g"), "g")),
        ("色", txt("・".join(p.get("colors") or []))),
        ("保証", txt(p.get("warranty"))),
        ("国内の販売者", txt(p.get("seller_jp"))),
        ("値段(掲載時点)", txt(p.get("price"))),
    ]
    return rows


def pse_badge(p: dict) -> str:
    st = p["pse"]["status"]
    return f'<span class="pse pse-{st}" title="{e(PSE[st][1])}">PSE {e(PSE[st][0])}</span>'


def img(p: dict, cls: str = "pimg") -> str:
    if not p.get("image"):
        return f'<div class="{cls} noimg">{e(p["maker"])}</div>'
    return (f'<figure class="{cls}"><img src="{e(p["image"])}" alt="{e(p["name"])}" loading="lazy" referrerpolicy="no-referrer">'
            f'<figcaption>画像: {e(p.get("image_credit") or p["maker"] + " 公式サイト")}</figcaption></figure>')


def pcard(p: dict) -> str:
    r = p.get("rating") or {}
    o = p.get("outlets") or {}
    b = p.get("battery") or {}
    usb = p.get("usb") or {}
    cmax = max([x.get("max_w") or 0 for x in usb_c_ports(p)] or [0])
    if p["category"] in TAP_CATS:
        bits = [f"{o['ac']}個口" if o.get("ac") else "", f"{r['watt_max']:,}W" if r.get("watt_max") else "",
                f"USB-C {cmax}W" if cmax else "", "雷サージ" if (p.get("surge") or {}).get("has") else ""]
    else:
        bits = [f"{b['mah']:,}mAh" if b.get("mah") else "", f"USB-C {cmax}W" if cmax else "",
                f"合計 {usb['total_w']}W" if usb.get("total_w") else "", "GaN" if usb.get("gan") else ""]
    return (f'<a class="pcard" href="{p["url"]}">{img(p, "pthumb")}'
            f'<span class="maker">{e(p["maker"])}</span><b>{e(p["model"])}</b>'
            f'<span class="tags">{" ".join(f"<i>{b}</i>" for b in bits if b)}</span>{pse_badge(p)}</a>')


def build_product(p: dict, products: list[dict], arts: list[dict]) -> str:
    st = p["pse"]["status"]
    rows = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in spec_rows(p))
    pse = p["pse"]
    insp = (f'<tr><th>登録検査機関名</th><td>{e(pse.get("inspector"))}</td></tr>' if pse_mark(p) == "diamond" else "")
    pse_html = (f'<p>{pse_badge(p)} {e(PSE[st][1])}。この製品で確かめる PSE マークの形: {PSE_MARK[pse_mark(p)]}。</p>'
                + (f'<table class="spec"><tr><th>届出事業者名</th><td>{e(pse["notifier"])}</td></tr>{insp}'
                   f'<tr><th>確かめた方法</th><td>{e(pse["how"])}</td></tr>'
                   f'<tr><th>確かめた日</th><td>{e(pse["date"])}</td></tr></table>' if st != "unconfirmed" else ""))
    rc = p.get("recall")
    if p.get("recall_checked"):
        rc_html = (f"消費者庁リコール情報サイトと NITE で型番「{e(p['model'])}」を引いた結果、該当するリコールは見つかりませんでした({e(p['recall_checked'])} 時点)。"
                   if rc in (None, "none") else
                   f'型番が一致するリコールがあります: <a href="{e(rc)}">{e(rc)}</a>({e(p["recall_checked"])} 時点)')
    else:
        rc_html = "リコール情報はまだ引いていません。"
    srcs = [f'<li><a href="{e(p["official_url"])}">{e(p["maker"])} 公式の製品ページ</a></li>']
    if p.get("manual_url"):
        srcs.append(f'<li><a href="{e(p["manual_url"])}">取扱説明書(PDF)</a></li>')
    same = [x for x in products if x["id"] != p["id"] and x["category"] == p["category"]][:6]
    rel_arts = [a for a in arts if p["id"] in (a.get("products") or [])]
    note = f'<div class="note">{markdown.markdown(e(p["note"]))}</div>' if p.get("note") else ""
    ld = [{"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": SITE["title"], "item": SITE["base_url"] + "/"},
        {"@type": "ListItem", "position": 2, "name": "比べ表", "item": SITE["base_url"] + "/compare/"},
        {"@type": "ListItem", "position": 3, "name": f'{p["maker"]} {p["model"]}'}]}]
    r = p.get("rating") or {}
    desc = (f'{p["maker"]}「{p["model"]}」の定格' + (f'(最大{r["watt_max"]:,}W)' if r.get("watt_max") else "")
            + "・口数・コード・雷サージ・USB の出力と PSE の表示を、公式ページと取扱説明書から並べました。")
    body = f"""<main class="article"><div class="wrap">
<p class="crumb"><a href="/">トップ</a> › <a href="/compare/">比べ表</a> › {e(CAT[p['category']]['name'])}</p>
<div class="phead">
  {img(p)}
  <div>
    <p class="maker">{e(p['maker'])} ・ {e(CAT[p['category']]['name'])}</p>
    <h1>{e(p['model'])}<small>{e(p['name'])}</small></h1>
    {pse_badge(p)}
    <p class="checked">公式情報を見た日: {e(p['checked'])}</p>
    {store_buttons(p, 'product-top')}
  </div>
</div>
<h2>仕様(公式の数字だけ)</h2>
<p class="small">メーカー公式ページと取扱説明書に書かれている値だけを載せています。書かれていない項目は「記載なし」です。</p>
<table class="spec">{rows}</table>
{note}
<h2>PSE の表示</h2>
{pse_html}
<h2>リコール</h2>
<p>{rc_html}</p>
<h2>出典</h2>
<ul class="src">{''.join(srcs)}</ul>
{store_buttons(p, 'product-bottom')}
{('<h2>この製品にかかわる疑問</h2><ul>' + ''.join(f'<li><a href="{a["url"]}">{e(a["title"])}</a></li>' for a in rel_arts) + '</ul>') if rel_arts else ''}
{('<h2>同じ区分のほかの機種</h2><div class="pgrid">' + ''.join(pcard(x) for x in same) + '</div>') if same else ''}
</div></main>"""
    return page(title=f'{p["maker"]} {p["model"]} の仕様', desc=desc, path=p["url"], body=body, current="compare",
                image=p.get("image") or "", pr=st != "unconfirmed", ld=ld)


# ── 比べ表 ──────────────────────────────────────────────────

def match(p: dict, where: dict) -> bool:
    if where.get("usb_c") and not usb_c_ports(p):
        return False
    if where.get("surge") and not (p.get("surge") or {}).get("has"):
        return False
    if where.get("min_ac") and ((p.get("outlets") or {}).get("ac") or 0) < where["min_ac"]:
        return False
    if where.get("category") and p["category"] != where["category"]:
        return False
    return True


def ctable(products: list[dict]) -> str:
    def b(v):
        return "" if v is None else ("1" if v else "0")
    trs = []
    for p in products:
        r = p.get("rating") or {}
        o = p.get("outlets") or {}
        s = p.get("surge") or {}
        cmax = max([x.get("max_w") or 0 for x in usb_c_ports(p)] or [0])
        cord = (p.get("cord") or {}).get("length_m")
        colors = p.get("colors") or []
        trs.append(
            f'<tr data-ac="{o.get("ac") or 0}" data-w="{r.get("watt_max") or 0}" data-usbc="{cmax}" '
            f'data-magnet="{b(o.get("magnet"))}" data-shutter="{b(o.get("shutter"))}" data-surge="{b(s.get("has"))}" '
            f'data-cord="{cord or 0}" data-colors="{e("|".join(colors))}">'
            f'<th><a href="{p["url"]}">{e(p["model"])}</a><small>{e(p["maker"])}</small>{pse_badge(p)}</th>'
            f'<td>{num(o.get("ac"), "個")}</td><td>{num(r.get("watt_max"), "W")}</td>'
            f'<td>{usb_summary(p) if usb_c_ports(p) else ("なし" if not p.get("usb") else usb_summary(p))}</td>'
            f'<td>{yesno(o.get("magnet"))}</td><td>{yesno(o.get("shutter"))}</td><td>{yesno(s.get("has")) if s else NOT_LISTED}</td>'
            f'<td>{num(cord, "m")}</td><td>{txt("・".join(colors))}</td></tr>')
    all_colors = sorted({c for p in products for c in (p.get("colors") or [])})
    copts = "".join(f'<option>{e(c)}</option>' for c in all_colors)
    return f"""<form class="filters" data-filter>
<label>口数 <select name="ac"><option value="0">こだわらない</option><option value="3">3個以上</option><option value="4">4個以上</option><option value="6">6個以上</option></select></label>
<label>合計の最大 <select name="w"><option value="0">こだわらない</option><option value="1500">1,500W 以上</option></select></label>
<label>USB-C <select name="usbc"><option value="-1">こだわらない</option><option value="1">あり</option><option value="30">1ポート30W以上</option><option value="65">1ポート65W以上</option></select></label>
<label>コード <select name="cord"><option value="0">こだわらない</option><option value="1">1m 以上</option><option value="2">2m 以上</option><option value="3">3m 以上</option></select></label>
<label>色 <select name="color"><option value="">こだわらない</option>{copts}</select></label>
<label class="chk"><input type="checkbox" name="magnet"> マグネット</label>
<label class="chk"><input type="checkbox" name="shutter"> ほこりシャッター</label>
<label class="chk"><input type="checkbox" name="surge"> 雷サージ</label>
<output data-count></output>
</form>
<div class="tscroll"><table class="ctable">
<thead><tr><th>製品</th><th>口数</th><th>合計の最大</th><th>USB-C</th><th>マグネット</th><th>ほこりシャッター</th><th>雷サージ</th><th>コード</th><th>色</th></tr></thead>
<tbody>{''.join(trs)}</tbody></table></div>
<p class="small">公式に記載のある項目だけを埋めています。「記載なし」は、公式ページと取扱説明書に書かれていなかった項目です。</p>
<script src="/assets/filter.js" defer></script>"""


def gtable(products: list[dict], kind: str) -> str:
    """充電器・モバイルバッテリーの比べ表(絞り込みは機種が増えてから)"""
    trs = []
    for p in products:
        usb = p.get("usb") or {}
        b = p.get("battery") or {}
        cmax = max([x.get("max_w") or 0 for x in usb_c_ports(p)] or [0])
        first = (f'<td>{num(b.get("mah"), "mAh")}</td><td>{num(b.get("wh"), "Wh")}</td>' if kind == "battery"
                 else f'<td>{yesno(usb.get("gan"))}</td><td>{yesno(p.get("foldable_plug"))}</td>')
        trs.append(f'<tr><th><a href="{p["url"]}">{e(p["model"])}</a><small>{e(p["maker"])}</small>{pse_badge(p)}</th>'
                   f'{first}<td>{num(cmax or None, "W")}</td><td>{two_c(p)}</td><td>{num(usb.get("total_w"), "W")}</td>'
                   f'<td>{num(p.get("weight_g"), "g")}</td></tr>')
    head = "<th>容量</th><th>電力量</th>" if kind == "battery" else "<th>GaN</th><th>折りたたみプラグ</th>"
    return (f'<div class="tscroll"><table class="ctable"><thead><tr><th>製品</th>{head}<th>USB-C 1ポートの最大</th>'
            f'<th>USB-C を2本挿したとき</th><th>USB の合計</th><th>重さ</th></tr></thead><tbody>{"".join(trs)}</tbody></table></div>'
            '<p class="small">公式に記載のある項目だけを埋めています。</p>')


GADGET_COMPARE = {"chargers": ("charger", "USB-C 充電器 比べ表", "USB-C・GaN 充電器の、ポートごとの最大と同時に挿したときの出力を、公式の数字で並べました。"),
                  "batteries": ("battery", "モバイルバッテリー 比べ表", "モバイルバッテリーの容量・電力量・出力を、公式の数字で並べました。")}


def compare_nav() -> str:
    views = "".join(f'<a href="/compare/{v["slug"]}/">{e(v["name"])}</a>' for v in CFG.get("compare_views") or [])
    g = "".join(f'<a href="/compare/{k}/">{e(t.split(" 比べ表")[0])}</a>' for k, (_, t, _) in GADGET_COMPARE.items())
    return f'<nav class="views" aria-label="種類・用途で絞る"><a href="/compare/">電源タップ</a>{views}{g}</nav>'


def build_gadget_compare(products: list[dict], key: str) -> str:
    cat, title, lead = GADGET_COMPARE[key]
    items = [p for p in products if p["category"] == cat]
    body = f"""<main class="article wide"><div class="wrap">
<p class="crumb"><a href="/">トップ</a> › <a href="/compare/">比べ表</a></p>
<h1>{e(title)}</h1>
<p>{e(lead)}</p>
{compare_nav()}
{gtable(items, cat)}
</div></main>"""
    return page(title=title, desc=lead, path=f"/compare/{key}/", body=body, current="compare")


def build_compare(products: list[dict], view: dict | None = None) -> str:
    taps = [p for p in products if p["category"] in TAP_CATS]
    items = [p for p in taps if match(p, view["where"])] if view else taps
    title = f"{view['name']}の電源タップ 比べ表" if view else "電源タップ 比べ表(全機種)"
    lead = view["lead"] if view else "載せている電源タップ全機種の、公式の数字の比べ表です。条件で絞り込めます。"
    body = f"""<main class="article wide"><div class="wrap">
<p class="crumb"><a href="/">トップ</a> › <a href="/compare/">比べ表</a></p>
<h1>{e(title)}</h1>
<p>{e(lead)}</p>
{compare_nav()}
{ctable(items)}
</div></main>"""
    path = f"/compare/{view['slug']}/" if view else "/compare/"
    return page(title=title, desc=lead, path=path, body=body, current="compare")


# ── USB-C の配り方の全機種表(看板。2026-11-12 本人「ガジェット好きに絞る」) ─────────

def two_c(p: dict) -> str:
    """USB-C を2本挿したときの出力(配り方の表から拾う)"""
    for r in sharing_list(p):
        # 「C1+C2」「USB-C1+C2(Cable)」「C1(ケーブル)+C2(ポート)」のような書き方を拾う
        if re.fullmatch(r"\s*(USB-)?C\d?(\([^)]*\))?\s*\+\s*C\d?(\([^)]*\))?\s*", r["use"]):
            return e(r["out"])
    return NOT_LISTED if len(usb_c_ports(p)) >= 2 else '<span class="nl">C は1ポート</span>'


def build_usbc(products: list[dict]) -> str:
    items = sorted([p for p in products if usb_c_ports(p)],
                   key=lambda p: -max(x.get("max_w") or 0 for x in usb_c_ports(p)))
    rows = "".join(
        f'<tr><th><a href="{p["url"]}">{e(p["model"])}</a><small>{e(p["maker"])}</small>{pse_badge(p)}</th>'
        f'<td>{len(usb_c_ports(p))}</td><td>{num(max(x.get("max_w") or 0 for x in usb_c_ports(p)), "W")}</td>'
        f'<td>{two_c(p)}</td><td>{num((p.get("usb") or {}).get("total_w"), "W")}</td>'
        f'<td>{num((p.get("outlets") or {}).get("ac"), "個") if p["category"] in TAP_CATS else "なし"}</td></tr>' for p in items)
    cards = "".join(
        f'<section class="usbcard" id="{p["id"]}"><h2><a href="{p["url"]}">{e(p["maker"])} {e(p["model"])}</a></h2>'
        f'<p>{pse_badge(p)} ポート: {usb_summary(p)} ・ USB の合計 {num((p.get("usb") or {}).get("total_w"), "W")}</p>'
        f'{sharing_html(p)}{store_buttons(p, "usbc")}</section>' for p in items)
    body = f"""<main class="article"><div class="wrap">
<p class="crumb"><a href="/">トップ</a> › USB-C の配り方</p>
<h1>USB-C の充電器・タップ・モバイルバッテリー、2台目を挿すと何Wになるか 全機種表</h1>
{bubble("odoroki", "箱に「65W」って書いてあっても、2台挿すと 45W と 20W に分かれたりするんだよね。取説の表を、載せてる機種ぶん全部並べてみた。")}
<p>USB-C の充電器・電源タップ・モバイルバッテリーは、1ポートだけ使ったときの最大の出力が大きく書かれます。ノートPCとスマホを同時に挿すと、出力はポートに分けて配られます。どう配られるかは機種ごとに違い、取扱説明書の表にしか載っていないことがあります。このページは、メーカー公式ページと取扱説明書に書かれた配り方を、そのまま並べたものです。</p>
<div class="tscroll"><table class="ctable usbc">
<thead><tr><th>製品</th><th>USB-C の数</th><th>1ポートの最大</th><th>USB-C を2本挿したとき</th><th>USB の合計</th><th>AC 口数</th></tr></thead>
<tbody>{rows}</tbody></table></div>
<p class="small">「記載なし」は、公式ページと取扱説明書に書かれていなかった組み合わせです。ポートの名前(C1・C2 など)はメーカーの呼び方です。</p>
{cards}
</div></main>"""
    return page(title="USB-C の出力の配り方 全機種表(充電器・タップ・モバイルバッテリー)",
                desc="USB-C の充電器・電源タップ・モバイルバッテリーに2台・3台を同時に挿したとき、出力がどう配られるかを、メーカー公式ページと取扱説明書から全機種ぶん並べました。",
                path="/usb-c/", body=body, current="usbc", pr=any(p["pse"]["status"] != "unconfirmed" for p in items))


# ── 疑問記事 ────────────────────────────────────────────────

def appliances() -> list[dict]:
    path = ROOT / "data" / "appliances.yaml"
    if not path.exists():
        return []
    d = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    srcs = {s["id"]: s for s in d.get("sources") or []}
    rows = d.get("items") or []
    for a in rows:
        if a.get("source") not in srcs:
            die(f"data/appliances.yaml: {a.get('name')} の source {a.get('source')} が sources にありません")
        a["src"] = srcs[a["source"]]
    return rows


def appliance_table() -> str:
    rows = appliances()
    if not rows:
        return ""
    trs = "".join(f'<tr><th>{e(a["name"])}</th><td>{e(a["label"])}</td><td><a href="{e(a["src"]["url"])}">{e(a["src"]["name"])}</a></td></tr>' for a in rows)
    return ('<div class="tscroll"><table class="spec wtable"><thead><tr><th>家電</th><th>消費電力の目安</th><th>出典</th></tr></thead>'
            f'<tbody>{trs}</tbody></table></div><p class="small">目安です。お使いの家電の本体の表示(銘板)か取扱説明書の消費電力を見てください。</p>')


def tool_card(name: str) -> str:
    if name == "watt":
        return (f'<a class="toolcard" href="/tools/watt/">{face("futsu", 56)}<span><b>消費電力の計算機</b>'
                '挿したい家電を選ぶと、合計のWと、タップの定格に収まるかが出ます。</span></a>')
    die(f"道具 {name} はありません")
    return ""


def render_md(a: dict, products: dict[str, dict]) -> str:
    html_ = markdown.markdown(a["body"], extensions=["tables", "fenced_code"])

    def sc(m):
        key, _, arg = m.group(1).partition(":")
        if key == "tool":
            return tool_card(arg)
        if key == "appliances":
            return appliance_table()
        if key == "products":
            ids = [x.strip() for x in arg.split(",") if x.strip()] or (a.get("products") or [])
            return '<div class="pgrid">' + "".join(pcard(products[i]) for i in ids) + "</div>"
        if key == "tapuo":
            name, _, text = arg.partition("|")
            return bubble(name.strip(), text.strip())
        die(f"{a['slug']}: 知らない札 {{{{{m.group(1)}}}}}")
        return ""
    return re.sub(r"<p>\{\{(.+?)\}\}</p>", sc, html_)


def build_article(a: dict, products: dict[str, dict]) -> str:
    srcs = a.get("sources") or []
    src_html = ("<h2>出典</h2><ol class=\"src\">" + "".join(
        f'<li><a href="{e(s["url"])}">{e(s["name"])}</a>(取得 {e(s.get("date", ""))})</li>' for s in srcs) + "</ol>") if srcs else ""
    upd = f' ・ 更新 {e(a["updated"])}' if a.get("updated") else ""
    intro = bubble(a.get("face", "futsu"), a["intro"]) if a.get("intro") else ""
    has_buy = any(products[i]["pse"]["status"] != "unconfirmed" for i in a.get("products") or [])
    body = f"""<main class="article"><div class="wrap">
<p class="crumb"><a href="/">トップ</a> › <a href="/q/">疑問に答える</a></p>
<h1>{e(a['title'])}</h1>
<p class="meta">{e(a['date'])}{upd}</p>
{intro}
<div class="prose">{render_md(a, products)}</div>
{src_html}
</div></main>"""
    ld = [{"@context": "https://schema.org", "@type": "Article", "headline": a["title"], "datePublished": str(a["date"]),
           "dateModified": str(a.get("updated") or a["date"]),
           "author": {"@type": "Organization", "name": SITE["title"]},
           "publisher": {"@type": "Organization", "name": SITE["author"]}}]
    return page(title=a["title"], desc=a["summary"], path=a["url"], body=body, current="q", pr=has_buy, ld=ld)


def build_q_index(arts: list[dict]) -> str:
    lis = "".join(f'<li><a href="{a["url"]}"><b>{e(a["title"])}</b><span>{e(a["summary"])}</span></a></li>' for a in arts)
    body = f"""<main class="article"><div class="wrap">
<h1>疑問に答える</h1>
<p>電源タップについてよく調べられている疑問に、NITE・経済産業省・メーカーの一次情報で答えます。</p>
<ul class="qlist">{lis}</ul>
</div></main>"""
    return page(title="疑問に答える", desc="電源タップの疑問に、一次情報で答える記事の一覧", path="/q/", body=body, current="q")


# ── 道具: 消費電力の計算機 ───────────────────────────────────

def build_watt_tool(products: list[dict], arts: list[dict]) -> str:
    rows = appliances()
    taps = [p for p in products if p["category"] in TAP_CATS and (p.get("rating") or {}).get("watt_max")]
    art =next((a for a in arts if a["slug"] == "1500w"), None)  # 下書きのあいだはリンクしない
    see = (f'(出典は<a href="{art["url"]}">何Wまで使えるかの記事</a>の表)' if art else
           "(出典: NITE「無頓着は火事の元！」別紙3、2024-01-25)")
    data = {
        "article": art["url"] if art else "",
        "appliances": [{"name": a["name"], "w": a["watt"], "src": a["src"]["name"]} for a in rows],
        "taps": [{"id": p["id"], "name": f'{p["maker"]} {p["model"]}', "w": p["rating"]["watt_max"], "url": p["url"]} for p in taps],
    }
    opts = "".join(f'<option value="{e(t["id"])}">{e(t["name"])}(定格 {t["w"]:,}W)</option>' for t in data["taps"])
    body = f"""<main class="article"><div class="wrap">
<p class="crumb"><a href="/">トップ</a> › 道具</p>
<h1>消費電力の計算機</h1>
{bubble("futsu", "同じタップに挿したい家電を選んでみて。合計のWと、タップの定格に収まるかが出るんだよね。数字は目安だから、最後は家電の本体の表示を見てほしいな。")}
<div class="calc" data-calc>
  <label class="tapsel">使うタップ <select name="tap"><option value="generic">一般的な 15A・125V のタップ(1,500W)</option>{opts}</select></label>
  <ul class="alist" data-list></ul>
  <div class="result" data-result aria-live="polite"></div>
</div>
<p class="small">家電の消費電力は、公的機関・電力会社・メーカーが出している目安です{see}。同じ家電でも機種や使い方で大きく変わります。</p>
<script id="calc-data" type="application/json">{json.dumps(data, ensure_ascii=False).replace("</", "<\\/")}</script>
<script src="/assets/calc.js" defer></script>
</div></main>"""
    return page(title="消費電力の計算機", desc="電源タップに挿したい家電を選ぶと、合計の消費電力と、タップの定格に収まるかが出ます。",
                path="/tools/watt/", body=body, current="tools")


# ── トップ・固定ページ ───────────────────────────────────────

def build_index(products: list[dict], arts: list[dict]) -> str:
    hero_img = ('<img class="hero-chara" src="/assets/chara/tapuo-futsu.png" alt="タプ夫" width="220" height="220">'
                if asset_exists("chara/tapuo-futsu.png") else face("futsu", 160))
    qs = "".join(f'<li><a href="{a["url"]}"><b>{e(a["title"])}</b><span>{e(a["summary"])}</span></a></li>' for a in arts[:8])
    newest = sorted(products, key=lambda p: p["checked"], reverse=True)[:6]
    usbs = [p for p in products if usb_c_ports(p)]
    usb_rows = "".join(f'<li><a href="/usb-c/#{p["id"]}"><b>{e(p["maker"])} {e(p["model"])}</b>'
                       f'<span>1ポート最大 {num(max(x.get("max_w") or 0 for x in usb_c_ports(p)), "W")} → USB-C 2本なら {two_c(p)}</span></a></li>'
                       for p in usbs[:6])
    body = f"""<main>
<section class="hero"><div class="wrap">
  {hero_img}
  <div>
    <h1>{e(SITE['tagline'])}</h1>
    <p>{e(SITE['description'])}</p>
    <p class="hero-q">「取説、最後まで読んだ？」 ── タプ夫</p>
  </div>
</div></section>
<section class="band"><div class="wrap">
  <h2>2台目を挿すと何Wになるか</h2>
  <p>USB-C 付きタップの「最大◯W」は、1ポートだけ使ったときの数字です。同時に挿したときの配り方を、取扱説明書の表から全機種ぶん並べています。</p>
  <ul class="qlist">{usb_rows}</ul>
  <p><a class="btn buy" href="/usb-c/">USB-C の配り方の全機種表を見る</a></p>
</div></section>
{f'''<section class="band"><div class="wrap">
  <h2>疑問に答える</h2>
  <ul class="qlist">{qs}</ul>
  <p><a href="/q/">疑問の記事をすべて見る</a></p>
</div></section>''' if arts else ''}
<section class="band alt"><div class="wrap">
  <h2>道具</h2>
  {tool_card("watt")}
</div></section>
<section class="band"><div class="wrap">
  <h2>新しく載せた機種</h2>
  <div class="pgrid">{''.join(pcard(p) for p in newest)}</div>
  <p><a href="/compare/">全機種の比べ表を見る</a></p>
</div></section>
</main>"""
    ld = [{"@context": "https://schema.org", "@type": "WebSite", "name": SITE["title"], "url": SITE["base_url"] + "/"}]
    return page(title="", desc=SITE["description"], path="/", body=body, ld=ld)


def build_static(name: str, title: str, desc: str) -> str:
    fm, body = split_fm(ROOT / "content" / "pages" / f"{name}.md")
    analytics = ("## アクセス解析について\n\nサイトの利用状況を知るため、Google社のアクセス解析(Google アナリティクス)を使っています。"
                 "Google アナリティクスは Cookie を使ってアクセス状況を集計します。氏名やメールアドレスなど個人を特定する情報は含まれません。"
                 "ブラウザの設定で Cookie を無効にすると、収集を拒否できます。"
                 "詳しくは[Google のポリシー](https://policies.google.com/technologies/partner-sites?hl=ja)をご覧ください。\n"
                 if SITE.get("analytics_id") else "")
    ads = ("紹介しているストアへのリンクの一部はアフィリエイトリンク(もしもアフィリエイト経由の " + AFF_SHOPS + ")です。"
           "リンクから買い物をされると、運営者に紹介料が入ることがあります。紹介料の有無で、載せる製品や書く内容は変えません。"
           if HAS_AFF else "いまはストアへのリンクに紹介料はついていません。紹介料がつくようになったら、このページと各ページに表示します。")
    body = (body.replace("{{analytics}}", analytics).replace("{{ads}}", ads)
            .replace("{{author}}", SITE["author"]).replace("{{contact}}", SITE["contact_email"]))
    html_ = markdown.markdown(body, extensions=["tables"])
    main = f'<main class="article"><div class="wrap"><h1>{e(fm.get("title", title))}</h1><div class="prose">{html_}</div></div></main>'
    return page(title=fm.get("title", title), desc=fm.get("summary", desc), path=f"/{name}/", body=main,
                current="about" if name == "about" else "")


# ── 書き出し ────────────────────────────────────────────────

def write(rel: str, text: str) -> None:
    path = OUT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")  # 止まったときの文が Windows で化けないように
    products = load_products()
    by_id = {p["id"]: p for p in products}
    arts = load_articles(products)
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(ROOT / "assets", OUT / "assets")
    urls = ["/", "/q/", "/compare/", "/tools/watt/", "/about/", "/privacy/", "/fixes/"]
    write("index.html", build_index(products, arts))
    for p in products:
        write(f"t/{p['id']}/index.html", build_product(p, products, arts))
        urls.append(p["url"])
    write("usb-c/index.html", build_usbc(products))
    urls.append("/usb-c/")
    write("compare/index.html", build_compare(products))
    for key, (cat, _, _) in GADGET_COMPARE.items():
        if any(p["category"] == cat for p in products):
            write(f"compare/{key}/index.html", build_gadget_compare(products, key))
            urls.append(f"/compare/{key}/")
    for v in CFG.get("compare_views") or []:
        if not any(match(p, v["where"]) for p in products if p["category"] in TAP_CATS):
            continue  # 当てはまる機種が無い用途のページは作らない(中身の無いページを検索に出さない)
        write(f"compare/{v['slug']}/index.html", build_compare(products, v))
        urls.append(f"/compare/{v['slug']}/")
    write("q/index.html", build_q_index(arts))
    for a in arts:
        write(f"q/{a['slug']}/index.html", build_article(a, by_id))
        urls.append(a["url"])
    write("tools/watt/index.html", build_watt_tool(products, arts))
    write("about/index.html", build_static("about", "このサイトの確かめ方", "タップマニアの確かめ方"))
    write("privacy/index.html", build_static("privacy", "プライバシー", "プライバシーと広告について"))
    write("fixes/index.html", build_static("fixes", "直した履歴", "誤りを直した履歴"))
    write("404.html", page(title="ページが見つかりません", desc="", path="/404.html", noindex=True,
                           body='<main class="article"><div class="wrap"><h1>ページが見つかりません</h1>'
                                '<p><a href="/">トップへ戻る</a></p></div></main>'))
    base = SITE["base_url"].rstrip("/")
    write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
          + "".join(f"<url><loc>{base}{u}</loc></url>\n" for u in urls) + "</urlset>\n")
    write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n")
    write("CNAME", base.split("://", 1)[1] + "\n")

    old = stale(products)
    if old:
        print(f"警告: 公式情報を見てから {SITE.get('stale_days', 180)} 日を過ぎた製品(値段と仕様を見直す)")
        for p in old:
            print(f"  - {p['id']}(checked {p['checked']})")
    nobuy = [p["id"] for p in products if p["pse"]["status"] == "unconfirmed"]
    if nobuy:
        print(f"PSE 未確認のため買うボタンを出していない製品: {', '.join(nobuy)}")
    missing = [f for f in FACES if not asset_exists(f"chara/face-{f}.png")]
    if missing:
        print(f"注意: タプ夫の顔の画像がまだありません({', '.join(missing)})。オレンジの丸で代わりにしています")
    print(f"製品 {len(products)} 件・疑問記事 {len(arts)} 本・ページ {len(urls)} 枚(sitemap)・ public/ に書き出した")

    if "--serve" in sys.argv:
        import functools
        import http.server
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(OUT))
        print("http://localhost:8791")
        http.server.ThreadingHTTPServer(("127.0.0.1", 8791), handler).serve_forever()


if __name__ == "__main__":
    main()
