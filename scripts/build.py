"""充電沼のサイトを作る。data/products/*.yaml + content/**/*.md → public/

python scripts/build.py           # public/ を作り直す
python scripts/build.py --serve   # 作ったあと http://localhost:8791 で確認
python scripts/build.py --drafts  # draft: true の記事も作る(手元で見るとき。push 前は付けずに作り直す)

仕組みは Cozy Desk(afrorz/cozy-desk)の build.py を借りている(紹介リンク・ページの枠・GA4・sitemap・CNAME)。
ページの中身は充電沼用に書き直した。製品は記事ではなくデータとして持ち、図鑑・比べ表・計算機はそこから作る。
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
JS_VER = {f.stem: int(f.stat().st_mtime) for f in (ROOT / "assets").glob("*.js")}
CSS_VER = int((ROOT / "assets" / "tap.css").stat().st_mtime)  # 直したら古い見た目が残らないように
# 見出しは丸ゴシック、本文と表は読みやすさ優先で Noto Sans JP(2026-11-12 本人「フォントが読みづらい」)
FONTS = ("https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@125,800&family=DotGothic16&family=JetBrains+Mono:wght@400;700"
         "&family=Noto+Sans+JP:wght@400;700;900&family=Zen+Kaku+Gothic+New:wght@700;900&display=swap")  # 2026-11-21 READOUT

PSE = {  # 仕様書 第3章の3段階
    "confirmed": ("確認済", "メーカー公式ページか取扱説明書で、PSE の表示を確認しました"),
    "image": ("公式画像で確認", "公式の製品画像で、本体の PSE の表示が読めました"),
    "unconfirmed": ("未確認", "PSE の表示を、公式の情報ではまだ確かめられていません"),
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


def shop_list(p: dict) -> list:
    """買うボタンを出す店。stores が無ければ全部、空 [] なら無し(大手の通販で売っていない物)。
    PSE の確認の有無では止めない(2026-11-15 本人「売っていてアフィできるなら絶対にボタンをつける」)"""
    if "stores" not in p:
        return [k for k, _, _ in STORES]
    return list(p.get("stores") or [])


def has_buy(p: dict) -> bool:
    return bool(shop_list(p))


def store_buttons(p: dict, where: str) -> str:
    """買うボタン"""
    only = shop_list(p)
    if not only:
        return '<p class="nobuy">楽天・Amazon・Yahoo!ショッピングでは、まだ売っていません。</p>'

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
    items = [("posts", "/p/", "新製品"), ("features", "/f/", "特集"), ("usbc", "/usb-c/", "USB-C の配り方"), ("compare", "/compare/", "比べ表"),
             ("about", "/about/", "確かめ方")]
    cur = ' aria-current="page"'
    return '<nav class="gnav" aria-label="サイト内">' + "".join(
        f'<a href="{u}"{cur if k == current else ""}>{n}</a>' for k, u, n in items) + "</nav>"


def page(*, title: str, desc: str, path: str, body: str, current: str = "", image: str = "",
         pr: bool = False, ld: list | None = None, noindex: bool = False) -> str:
    # スクリプトも直したら古いのが残らないように、ファイルの更新時刻を付ける
    body = re.sub(r'src="/assets/([\w-]+)\.js"', lambda m: f'src="/assets/{m[1]}.js?v={JS_VER.get(m[1], 0)}"', body)
    full = f"{title}｜{SITE['title']}" if title else f"{SITE['title']}｜{SITE['tagline']}"
    base = SITE["base_url"].rstrip("/")
    url = base + path
    ogp = SITE.get("ogp_image") or ""  # 名前入りの画像は site.yaml で指定したときだけ使う(改名で古い名前が出ないように)
    og = image or (f"{base}/assets/{ogp}" if ogp and asset_exists(ogp) else "")
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
                  f"gtag('js',new Date());gtag('config','{gid}');"
                  # 買うボタンが押されたら、どの店・どのページのどの位置かを送る(紹介料につながる動きを数える)
                  "document.addEventListener('click',function(ev){var a=ev.target.closest&&ev.target.closest('a[data-store]');"
                  "if(a)gtag('event','buy_click',{store:a.dataset.store,where:a.dataset.where,page:location.pathname});});"
                  "</script>\n")
    for block in ld or []:
        extra += '<script type="application/ld+json">' + json.dumps(block, ensure_ascii=False).replace("</", "<\\/") + "</script>\n"
    if asset_exists("favicon.ico"):
        extra += '<link rel="icon" href="/assets/favicon.ico?v=4" sizes="any">\n'
    if asset_exists("favicon-32.png"):
        extra += '<link rel="icon" href="/assets/favicon-32.png?v=4" type="image/png" sizes="32x32">\n'
    if asset_exists("apple-touch-icon.png"):
        extra += '<link rel="apple-touch-icon" href="/assets/apple-touch-icon.png">\n'
    year = TODAY.year
    years = f"{SITE['copyright_from']}" + (f"–{year}" if year > SITE["copyright_from"] else "")
    ad_line = f"このサイトはアフィリエイト広告({AFF_SHOPS})を含みます" if HAS_AFF else "Gadget Terminal の姉妹サイト"
    top_ad = f'<div class="wrap adwrap">{AD_NOTE}</div>' if (pr and HAS_AFF) else ""
    # ヘッダはモックの形(2026-11-21 本人「ヘッダもモックと同じに」)。稲妻のアイコン(本人 A 案)＋文字の名前＋英字
    # アイコンは 11/21 本人「バッテリーアイコンにしよう」、英字は「改行してみて」で2行
    en = e((SITE.get("title_en") or "Charge Mania").upper()).replace(" ", "<br>")
    logo = ('<svg class="bolt" viewBox="4.5 10.5 31 19" aria-hidden="true">'
            '<rect x="7.3" y="13.3" width="22.4" height="13.4" rx="2.4" fill="none" stroke="#F88425" stroke-width="2.6"/>'
            '<rect x="32.5" y="17" width="2.5" height="6" rx="1" fill="#F88425"/>'
            '<rect x="9.5" y="15.5" width="18" height="9" rx="1.5" fill="#F88425"/>'
            '<path d="M20 14.5 14.5 21H18l-1.5 4.5 6-6.5H19z" fill="#0E1013"/></svg>'
            f'<b>{e(SITE["title"])}</b><span>{en}</span>')
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
    <a class="brand" href="/" aria-label="{e(SITE['title'])} トップ">{logo}</a>
    {nav(current)}
  </div>
</header>
{top_ad}
{body}
<footer>
  <div class="wrap">
    <span>© {years} {e(SITE['title'])}(運営 {e(SITE['author'])}) ・ <a href="/about/">確かめ方</a> ・ <a href="/tools/watt/">消費電力の計算機</a> ・ <a href="/q/">疑問に答える</a> ・ <a href="/fixes/">直した履歴</a> ・ <a href="/privacy/">プライバシー</a>{x}</span>
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
    if not ports:
        return NOT_LISTED
    return '<span class="ports">' + "".join(port_chip(x) for x in ports) + "</span>"


def port_kind(t: str) -> str:
    t = str(t or "").upper()
    return "wireless" if ("WIRELESS" in t or "ワイヤレス" in t) else ("a" if t == "A" else "c")


def port_chip(x: dict) -> str:
    """差し込み口の形をした札。左にポート名、右に最大W"""
    w = x.get("max_w")
    wtxt = f"{w:g}W" if isinstance(w, (int, float)) else "記載なし"
    return f'<span class="port {port_kind(x.get("type"))}"><i>{e(x.get("name") or x.get("type"))}</i><b>{wtxt}</b></span>'


def _watts(token: str) -> list[float] | None:
    """「45W」「5V2.4A」「5V2.4A×2(24W)」から、ポートごとの W を取り出す"""
    n = 1
    m = re.search(r"[×x]\s*(\d+)", token)
    if m:
        n = int(m.group(1))
    va = re.search(r"(\d+(?:\.\d+)?)\s*V\s*(\d+(?:\.\d+)?)\s*A", token)
    if va:
        w = float(va.group(1)) * float(va.group(2))
    else:
        mw = re.search(r"(\d+(?:\.\d+)?)\s*W", token)
        if not mw:
            return None
        w = float(mw.group(1))
    return [w] * n


def split_bar(p: dict, use: str, out: str) -> str:
    """配り方を帯グラフにする。帯の全幅はその機種の1ポートの最大(か USB の合計)。
    「合計」「or」など、ポートごとの値に分けられない書き方は文字だけ出す"""
    text = f'<span class="txt">{e(out)}</span>'
    if "合計" not in out and re.search(r"\s(/|or)\s", out):
        # 「45W+20W / 20W+45W / 30W+30W(65W Max)」のような選択肢は、帯を選択肢の数だけ並べる
        opts = [o for o in re.split(r"\s+(?:/|or)\s+", re.sub(r"\([^)]*\)$", "", out.strip())) if o]
        bars = [split_bar(p, use, o) for o in opts]
        if all('class="bars"' in b for b in bars):
            inner = "".join(re.search(r'<div class="bars".*?</div>', b).group(0) for b in bars)
            return f'<div class="split">{inner}{text}</div>'
    if re.search(r"合計|or|/", out):
        return f'<div class="split">{text}</div>'
    vals: list[float] = []
    for tok in re.split(r"\s*\+\s*", re.sub(r"\([^)]*\)$", "", out.strip())):
        got = _watts(tok)
        if got is None:
            return f'<div class="split">{text}</div>'
        vals += got
    if not vals:
        return f'<div class="split">{text}</div>'
    usb = p.get("usb") or {}
    full = max([x.get("max_w") or 0 for x in usb.get("ports") or []] + [usb.get("total_w") or 0, sum(vals)])
    names = [t for t in re.split(r"\s*\+\s*", use) if t]
    kinds = [("wireless" if "ワイヤレス" in t else "a" if re.search(r"(^|[^-])A\d?", t) and "C" not in t else "c") for t in names]
    if len(kinds) != len(vals):
        kinds = ["c"] * len(vals)
    segs = "".join(f'<span class="seg-{k}" style="width:{v / full * 100:.1f}%" title="{v:g}W">{v:g}W</span>' for v, k in zip(vals, kinds))
    return f'<div class="split"><div class="bars" aria-hidden="true">{segs}</div>{text}</div>'


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
    trs = "".join(f"<tr><th>{e(r['use'])}</th><td>{split_bar(p, r['use'], r['out'])}</td></tr>" for r in rows)
    return (f'<div class="tscroll"><table class="share"><thead><tr><th>挿すポート</th><th>それぞれの出力(帯の全幅 = 1ポートの最大)</th></tr></thead><tbody>{trs}</tbody></table></div>'
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
    if p["category"] == "cable":  # 2026-11-21 本人がケーブルも扱う範囲に足した
        c = p.get("cable") or {}
        return [
            ("コネクター", txt(c.get("ends"))),
            ("最大の電力", txt(c.get("power"))),
            ("データ転送", txt(c.get("data"))),
            ("映像出力", yesno(c.get("video"))),
            ("e-Marker", yesno(c.get("emarker"))),
            ("長さ", txt(c.get("length"))),
            ("被ふく・コネクター", txt(c.get("jacket"))),
            ("ディスプレイ", txt(c.get("display"))),
            ("色", txt("・".join(p.get("colors") or []))),
            ("保証", txt(p.get("warranty"))),
            ("国内の販売者", txt(p.get("seller_jp"))),
            ("値段(掲載時点)", txt(p.get("price"))),
        ]
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
    if p["category"] == "cable":  # ケーブルには PSE の札を出さない(公式にも記載が無い)
        return ""
    st = p["pse"]["status"]
    return f'<span class="pse pse-{st}" title="{e(PSE[st][1])}">PSE {e(PSE[st][0])}</span>'


# ── 画面(READOUT、2026-11-21 本人「この方向で入れる」) ─────────────────────
# 充電器の小さな画面に、取説の数字を出す。「1台だけのとき」と「2台同時のとき」の2つ。

def _w(v: float) -> str:
    return f"{v:g}"


def readout(p: dict) -> dict | None:
    """画面に出す2つの数字。{one_k, one, two_k, two, note}。数字が取れない物は None"""
    usb = p.get("usb") or {}
    ports = [x for x in usb.get("ports") or [] if isinstance(x.get("max_w"), (int, float))]
    rows = [r for r in sharing_list(p) if r["out"]]
    if ports and rows:
        cmax = max([x["max_w"] for x in ports if port_kind(x.get("type")) == "c"] or [x["max_w"] for x in ports])
        out = rows[0]["out"]
        two = None
        if "合計" in out:
            m = re.search(r"合計[^0-9]*?(\d+(?:\.\d+)?)\s*W", out) or re.search(r"\((\d+(?:\.\d+)?)\s*W\)", out)
            if m:
                two = f"計{_w(float(m.group(1)))}W"
            else:
                va = re.search(r"(\d+(?:\.\d+)?)\s*V\s*/?\s*(\d+(?:\.\d+)?)\s*A", out)
                if va:
                    two = f"計{_w(float(va.group(1)) * float(va.group(2)))}W"
        else:
            first = re.split(r"\s+(?:/|or)\s+", out.strip())[0]
            vals = []
            for tok in re.split(r"\s*\+\s*", re.sub(r"\([^)]*\)$", "", first)):
                got = _watts(tok)
                if got is None:
                    vals = []
                    break
                vals += got
            if vals:
                two = "+".join(_w(v) for v in vals) + "W"
        if not two:
            return None
        return {"one_k": "1台だけ", "one": f"{_w(cmax)}W", "two_k": "2台同時", "two": two,
                "note": f'{rows[0]["use"]}: {out}'}
    o, r = p.get("outlets") or {}, p.get("rating") or {}
    if o.get("ac") and r.get("watt_max"):
        return {"one_k": "AC", "one": f'{o["ac"]}口', "two_k": "全部で", "two": f'{r["watt_max"]:,}W', "note": ""}
    return None


def strip_html(p: dict) -> str:
    rd = readout(p)
    if not rd:
        return ""
    return (f'<div class="rd-strip" aria-label="{e(rd["one_k"])} {e(rd["one"])}、{e(rd["two_k"])} {e(rd["two"])}">'
            f'<div><small>{e(rd["one_k"])}</small><b>{e(rd["one"])}</b></div><span class="rd-arrow" aria-hidden="true">▶</span>'
            f'<div><small>{e(rd["two_k"])}</small><b>{e(rd["two"])}</b></div></div>')


def device_html(p: dict, autoplay: bool = False) -> str:
    """押せる画面。右の差し込み口を押すと「2台目を挿した」数字に変わる。2台の数字が無い物は出さない"""
    rd = readout(p)
    if not rd or rd["one_k"] != "1台だけ":
        return ""
    one = rd["one"].removesuffix("W")
    two = rd["two"].removesuffix("W")
    note2 = "2台同時に挿したとき(合計)" if two.startswith("計") else "2台同時に挿したとき"
    return (f'<div class="rd-device" data-one="{e(one)}" data-two="{e(two)}" data-one-note="1台だけ挿したとき" '
            f'data-two-note="{e(note2)}"{" data-autoplay=\"1\"" if autoplay else ""}>'
            '<div class="rd-screen" aria-live="polite"><div class="rd-row"><span>OUTPUT</span><span class="rd-mode">1台</span></div>'
            f'<div class="rd-watt"><span class="rd-num">{e(one)}</span><span class="rd-unit">W</span></div>'
            '<div class="rd-foot">1台だけ挿したとき</div></div>'
            '<div class="rd-ports"><span class="rd-port on" aria-hidden="true"><span class="rd-lbl">1台目</span></span>'
            '<button type="button" class="rd-port" aria-pressed="false" aria-label="2台目を挿す"><span class="rd-lbl">2台目</span></button></div>'
            '<p class="rd-cap"><b>右の差し込み口を押す</b>と、2台目を挿したときの数字に変わります</p></div>')


def img(p: dict, cls: str = "pimg") -> str:
    if not p.get("image"):
        return f'<div class="{cls} noimg">{e(p["maker"])}</div>'
    return (f'<figure class="{cls}"><img src="{e(p["image"])}" alt="{e(p["name"])}" loading="lazy" referrerpolicy="no-referrer">'
            f'<figcaption>画像: {e(p.get("image_credit") or p["maker"] + " 公式サイト")}</figcaption></figure>')


def prod_images(p: dict) -> list[dict]:
    """製品の写真をすべて。image(1枚目)＋ images(文字列か {src, alt, color})。重なりは除く。
    2026-11-23 本人「複数画像があるなら、なるべく掲載する」「色違いがあるならそれも掲載する」"""
    out, seen = [], set()
    for x in [p.get("image")] + list(p.get("images") or []):
        if not x:
            continue
        d = {"src": x} if isinstance(x, str) else dict(x)
        if d["src"] in seen:
            continue
        seen.add(d["src"])
        d.setdefault("alt", p["name"] + (f'({d["color"]})' if d.get("color") else ""))
        out.append(d)
    return out


def gallery(p: dict) -> str:
    """製品ページの写真。大きい1枚＋小さい写真の列(押すと入れ替わる)。色違いは小さい写真の下に色の名前"""
    ims = prod_images(p)
    if len(ims) < 2:
        return img(p)
    credit = e(p.get("image_credit") or p["maker"] + " 公式サイト")
    thumbs = "".join(
        f'<button type="button"{" aria-current=\"true\"" if i == 0 else ""} aria-label="{e(x["alt"])}を大きく">'
        f'<img src="{e(x["src"])}" alt="" loading="lazy" referrerpolicy="no-referrer">'
        + (f'<small>{e(x["color"])}</small>' if x.get("color") else "") + "</button>"
        for i, x in enumerate(ims))
    return (f'<div class="pgal"><figure class="pimg"><img src="{e(ims[0]["src"])}" alt="{e(ims[0]["alt"])}" referrerpolicy="no-referrer">'
            f'<figcaption>画像: {credit}</figcaption></figure><div class="pgal-th">{thumbs}</div></div>'
            '<script src="/assets/gallery.js" defer></script>')


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


def pitch_html(p: dict) -> str:
    """製品ページの頭の「特徴」(11/23 本人「まず『特徴』だろう」)。2026-11-23 本人「商品の魅力を多少は語らないと意味ない」。
    製品データの pitch: {lead: 2文, points: [見どころ3つ]}。事実は公式の数字だけ(docs/WRITING.md の「特徴」)"""
    pt = p.get("pitch") or {}
    if not pt.get("lead"):
        return ""
    pts = "".join(f"<li>{e(x)}</li>" for x in pt.get("points") or [])
    art = next((a for a in POSTS if a["product"] == p["id"]), None)
    more = '<p class="pitch-more"><a href="{a_url}">紹介記事でくわしく読む →</a></p>'.replace("{a_url}", art["url"]) if art else ""
    return (f'<section class="pitch"><h2>特徴</h2><p class="pitch-lead">{e(pt["lead"])}</p>'
            + (f'<ul class="pitch-pts">{pts}</ul>' if pts else "") + more + "</section>")


def more_nums(p: dict, tag: str = "") -> str:
    """「ほかの〜」のカードの上の数字。同じ名前の物でも見分けられるように2つまで"""
    out = []
    mah = (p.get("battery") or {}).get("mah")
    if mah:
        out.append(f"<b>{mah:,}</b>mAh")
    ports = (p.get("usb") or {}).get("ports") or []
    w = max([x.get("max_w") or 0 for x in ports] or [0])
    if w:
        out.append(f"<b>{w:g}</b>W")
    elif (p.get("rating") or {}).get("watt_max"):
        out.append(f'<b>{p["rating"]["watt_max"]:,}</b>W まで')
    return '<span class="mc-num">' + "".join(f"<span>{x}</span>" for x in out) + tag + "</span>"


def more_card(p: dict) -> str:
    """製品ページ末尾「ほかの〜」の横長カード(2026-11-25 本人 OK = mock/v10。高さを揃える)"""
    rel = zk_month(p, dt.date.today().year)
    tag = f'<span class="mc-rel">{rel}月発売</span>' if rel else ""
    return (f'<a class="mc" href="{p["url"]}"><span class="mc-ph"><img src="{e(p.get("image") or "")}" alt="" loading="lazy" referrerpolicy="no-referrer"></span>'
            f'<span class="mc-b">{more_nums(p, tag)}<b class="mc-hook">{e(zk_hook(p))}</b>'
            f'<span class="mc-n">{e(p["maker"])} <i>{e(p["model"])}</i></span>{port_face(p)}</span>'
            f'<span class="mc-go" aria-hidden="true">→</span></a>')


def product_checks(p: dict) -> str:
    """製品ページの「確かめたこと」: PSE・リコール・公式情報を見た日を3行で(2026-11-24 本人 OK = mock/v9)"""
    pse = p["pse"]
    st = pse["status"]
    if p["category"] == "cable":
        pse_t = "公式の製品ページ・プレスリリースに、PSE の記載はありません(ケーブル)。"
    else:
        pse_t = e(PSE[st][1]) + f"。この製品で確かめる PSE マークの形: {PSE_MARK[pse_mark(p)]}。"
        if st != "unconfirmed":
            pse_t += f'<br>届出事業者名: {e(pse.get("notifier") or "")}'
            if pse_mark(p) == "diamond" and pse.get("inspector"):
                pse_t += f' ・ 登録検査機関名: {e(pse["inspector"])}'
            pse_t += f'<br>確かめた方法: {e(pse.get("how") or "")}({e(str(pse.get("date") or ""))})'
    rc = p.get("recall")
    if p.get("recall_checked"):
        rc_t = (f"消費者庁リコール情報サイトなどで型番「{e(p['model'])}」を引き、該当するリコールは見つかりませんでした"
                if rc in (None, "none") else f'型番が一致するリコールがあります: <a href="{e(rc)}">{e(rc)}</a>') + f'({e(p["recall_checked"])} 時点)。'
    else:
        rc_t = "リコール情報はまだ引いていません。"
    return (post_h2("確かめたこと", "CHECKS") + '<div class="v9-checks">'
            f'<div><p class="v9-ck-k">PSE</p><div>{pse_badge(p)}<p>{pse_t}</p></div></div>'
            f'<div><p class="v9-ck-k">RECALL</p><div><p>{rc_t}</p></div></div>'
            f'<div><p class="v9-ck-k">CHECKED</p><div><p>公式情報を見た日 {e(str(p.get("checked") or ""))}</p></div></div></div>')


def build_product(p: dict, products: list[dict], arts: list[dict]) -> str:
    """製品ページ(2026-11-24 本人 OK = mock/v9。「スライダーの先と新製品の先でデザインが違う」→ 記事 v7 と同じ1列の形に)。
    記事との違い: 本文の代わりに「特徴」(pitch の見どころ3つ)。PSE・リコールは「確かめたこと」に3行で"""
    ims = prod_images(p)
    first = ims[0] if ims else {"src": p.get("image") or "", "alt": p["name"]}
    thumbs = ""
    if len(ims) > 1:
        thumbs = '<div class="a3-thumbs v7-thumbs v9-thumbs">' + "".join(
            f'<button type="button"{" aria-current=\"true\"" if i == 0 else ""} aria-label="{e(x["alt"])}を大きく">'
            f'<img src="{e(x["src"])}" alt="{e(x["alt"])}" loading="lazy" referrerpolicy="no-referrer">'
            + (f'<small>{e(x["color"])}</small>' if x.get("color") else "") + "</button>"
            for i, x in enumerate(ims)) + "</div>"
    credit = e(p.get("image_credit") or p["maker"] + " 公式サイト")
    g = gaps(p)
    cat = GROUP.get(p["category"], CAT[p["category"]]["name"])
    rel = str(p.get("released") or "")
    released = f'<span>発売 {e(rel[:4])}年{int(rel[5:7])}月</span>' if re.match(r"\d{4}-\d{2}", rel) else ""
    top_ad = '<span class="adnote v7-ad">広告を含みます</span>' if (has_buy(p) and HAS_AFF) else ""
    pt = p.get("pitch") or {}
    feats = ""
    if pt.get("points"):
        feats = (post_h2("特徴") + '<ol class="v9-pts">'
                 + "".join(f'<li><span>{i + 1:02d}</span><p>{e(x)}</p></li>' for i, x in enumerate(pt["points"])) + "</ol>")
    gap_html = ""
    if g:
        gap_html = (post_h2("公式の中で、数字が食い違っていた所", "CROSS-CHECK")
                    + '<p class="v7-note">製品ページ・取扱説明書・公式画像を突き合わせて見つけた所です。</p>'
                    + '<ul class="v7-gaps">' + "".join(f"<li>{e(x)}</li>" for x in g) + "</ul>")
    rows = sharing_list(p)
    share = ""
    if rows:
        share = (post_h2("同時に挿したときの配り方", "POWER SHARING") + '<div class="tbl"><table class="share3 v7-share"><tbody>'
                 + "".join(f'<tr><th>{e(r["use"])}</th><td>{split_bar(p, r["use"], r["out"])}</td></tr>' for r in rows)
                 + "</tbody></table></div>")
    allrows = spec_rows(p) + (usb_rows(p) if p["category"] in TAP_CATS else [])
    allrows = [(k, v) for k, v in allrows if k != "同時に使ったときの配り方"]
    seen, have, none = set(), [], []
    for k, v in allrows:
        if k in seen:
            continue
        seen.add(k)
        (none if re.sub(r"<[^>]+>", "", v).strip() == "記載なし" else have).append((k, v))
    plate = (post_h2("全部の数字", "SPEC SHEET")
             + '<p class="v7-note">メーカー公式ページと取扱説明書に書かれている値だけです。</p><div class="v7-plate"><dl>'
             + "".join(f"<div><dt>{e(k)}</dt><dd>{v}</dd></div>" for k, v in have) + "</dl>"
             + (f'<p class="v7-none">公式に記載なし: {"・".join(e(k) for k, _ in none)}</p>' if none else "") + "</div>")
    srcs = [(f'{p["maker"]} 公式の製品ページ', p["official_url"])] + ([("取扱説明書(PDF)", p["manual_url"])] if p.get("manual_url") else [])
    src_html = (post_h2("読んだ資料", "SOURCES") + '<ol class="v7-srcs">'
                + "".join(f'<li><a href="{e(u)}">{e(n)}</a><span></span></li>' for n, u in srcs) + "</ol>")
    art = post_for(p)
    art_html = (f'<a class="v9-art" href="{art["url"]}"><small>この製品の紹介記事</small><b>{e(catch(art))}</b><span>→</span></a>') if art else ""
    rel_arts = [a for a in arts if p["id"] in (a.get("products") or [])]
    q_html = ((post_h2("この製品にかかわる疑問", "QUESTIONS") + "<ul>" + "".join(f'<li><a href="{a["url"]}">{e(a["title"])}</a></li>' for a in rel_arts) + "</ul>")
              if rel_arts else "")
    same = [x for x in products if x["id"] != p["id"] and GROUP.get(x["category"]) == GROUP.get(p["category"])][:4]
    more = (f'<h2 class="more-h v7-more">ほかの{e(cat)}</h2><div class="mcs">' + "".join(more_card(x) for x in same) + "</div>") if same else ""
    price = f'<p class="v7-price">{e(p["price"])}<small>掲載時点</small></p>' if p.get("price") else ""
    lcd = post_lcd(p)
    out_block = f'<div class="v7-block"><p class="v7-label">OUTPUT<span>何ワットになるか</span></p>{lcd}</div>' if lcd else ""
    face_ = port_face(p, big=True)
    port_block = f'<div class="v7-block"><p class="v7-label">PORTS<span>ポートの顔</span></p>{face_}</div>' if face_ else ""
    name = re.sub(r"[（(].*?[)）]", "", p["name"]).strip() or p["name"]
    lead_html = f'<p class="v7-sum">{e(pt["lead"])}</p>' if pt.get("lead") else ""  # 安全の話で保留中の物(pitch_draft だけ)は出さない
    body = f"""<main class="v7 v9"><div class="wrap v7-wrap">
<p class="v7-crumb"><a href="/">トップ</a> / <a href="/compare/">比べ表</a> / {e(cat)} / {e(p['maker'])}</p>
<header class="v7-head">
  <div class="v7-meta"><span class="v7-cat">{e(cat)}</span>{released}{top_ad}</div>
  <h1>{e(name)}</h1>
  <p class="v7-maker">{e(p['maker'])}<span>{e(p['model'])}</span>{pse_badge(p)}</p>
</header>

<div class="v7-top">
  <figure class="v7-photo">
    <div class="a3-grid v7-ph"><div class="anat solo"><div class="anat-ph"><img src="{e(first['src'])}" alt="{e(first['alt'])}" referrerpolicy="no-referrer"></div></div></div>
    {thumbs}
    <figcaption>画像: {credit}</figcaption>
  </figure>
  <aside class="v7-panel{' v9-one' if not (port_block and out_block) else ''}">
    {port_block}{out_block}
    <dl class="v7-tally"><div><dt>確かめた項目</dt><dd>{leaves(p)}</dd></div><div><dt>読んだ資料</dt><dd>{sources(p)}</dd></div>
      <div><dt>公式の食い違い</dt><dd class="hot">{len(g)}</dd></div></dl>
  </aside>
</div>

<section class="v7-lead">
  {lead_html}
  <div class="v7-buy">{price}{store_buttons(p, 'product-top').replace(AD_NOTE, '')}</div>
</section>

<article class="v7-body">
{feats}
{art_html}
{gap_html}
{share}
{plate}
{product_checks(p)}
<div class="v7-buy end">{price}{store_buttons(p, 'product-bottom').replace(AD_NOTE, '')}</div>
{src_html}
{q_html}
</article>
{more}
</div></main>
<script src="/assets/home.js" defer></script>"""
    ld = [{"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": SITE["title"], "item": SITE["base_url"] + "/"},
        {"@type": "ListItem", "position": 2, "name": "比べ表", "item": SITE["base_url"] + "/compare/"},
        {"@type": "ListItem", "position": 3, "name": f'{p["maker"]} {p["model"]}'}]}]
    r = p.get("rating") or {}
    desc = (f'{p["maker"]}「{p["model"]}」の定格' + (f'(最大{r["watt_max"]:,}W)' if r.get("watt_max") else "")
            + "・口数・コード・雷サージ・USB の出力と PSE の表示を、公式ページと取扱説明書から並べました。")
    return page(title=f'{p["maker"]} {p["model"]} の仕様', desc=desc, path=p["url"], body=body, current="compare",
                image=p.get("image") or "", ld=ld)


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
            return split_bar(p, r["use"], r["out"])
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
        f'<p class="meta-line">{pse_badge(p)} {usb_summary(p)} <span class="small mono">USB 合計 {num((p.get("usb") or {}).get("total_w"), "W")}</span></p>'
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
                path="/usb-c/", body=body, current="usbc", pr=any(has_buy(p) for p in items))


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
    link = lambda s: f'<a href="{e(s["url"])}">{e(s["name"])}</a>'
    # 出典が全部の行で同じなら、列にせず表の下に1回だけ書く(2026-11-26 本人「1つにまとめて表示すればいい」)
    one = len({a["source"] for a in rows}) == 1
    if one:
        trs = "".join(f'<tr><th>{e(a["name"])}</th><td>{e(a["label"])}</td></tr>' for a in rows)
        head = "<th>家電</th><th>消費電力の目安</th>"
        note = f'出典: {link(rows[0]["src"])}。'
    else:
        trs = "".join(f'<tr><th>{e(a["name"])}</th><td>{e(a["label"])}</td><td>{link(a["src"])}</td></tr>' for a in rows)
        head = "<th>家電</th><th>消費電力の目安</th><th>出典</th>"
        note = ""
    return (f'<div class="tscroll"><table class="spec wtable"><thead><tr>{head}</tr></thead>'
            f'<tbody>{trs}</tbody></table></div><p class="small">{note}目安です。お使いの家電の本体の表示(銘板)か取扱説明書の消費電力を見てください。</p>')


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
    has_buy_ = any(has_buy(products[i]) for i in a.get("products") or [])
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
    return page(title=a["title"], desc=a["summary"], path=a["url"], body=body, current="q", pr=has_buy_, ld=ld)


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


# ── 新製品の紹介記事(柱。2026-11-14 本人「ガジェット的に電源タップやチャージャーを紹介するサイトに」「新製品を1つずつ」) ──
# content/p/YYYY-MM-DD-<名前>.md → /p/<名前>/。1記事1製品。製品の数字は data/products/<product>.yaml から自動で付ける

POSTS: list[dict] = []


def load_posts(products: dict[str, dict]) -> list[dict]:
    posts = []
    for path in sorted((ROOT / "content" / "p").glob("*.md")):
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})-([a-z0-9]+(?:-[a-z0-9]+)*)", path.stem)
        if not m:
            die(f"{path.name}: ファイル名は YYYY-MM-DD-<英小文字の名前>.md にしてください")
        fm, body = split_fm(path)
        for k in ("title", "date", "summary", "product"):
            if not fm.get(k):
                die(f"{path.name}: {k} がありません")
        if fm["product"] not in products:
            die(f"{path.name}: product の {fm['product']} が data/products にありません")
        if fm.get("draft") and "--drafts" not in sys.argv:
            continue
        fm["slug"] = m.group(2)
        fm["url"] = f"/p/{m.group(2)}/"
        fm["body"] = body
        fm["p"] = products[fm["product"]]
        posts.append(fm)
    if len({x["slug"] for x in posts}) != len(posts):
        die("新製品記事の名前(日付を除いた部分)が重なっています")
    posts.sort(key=lambda a: str(a["date"]), reverse=True)
    return posts


def post_images(a: dict) -> list[dict]:
    """記事の写真。images が無ければ製品データの写真1枚"""
    p = a["p"]
    imgs = a.get("images") or ([{"src": p["image"], "alt": p["name"]}] if p.get("image") else [])
    out = [{"src": x["src"], "alt": x.get("alt") or p["name"]} for x in imgs]
    # 色違いの写真は記事にも足す(2026-11-23 本人「色違いがあるならそれも掲載する」)
    have = {x["src"] for x in out}
    out += [{"src": x["src"], "alt": x["alt"]} for x in prod_images(p) if x.get("color") and x["src"] not in have]
    return out


def key_chips(p: dict) -> str:
    """カードと記事の頭に出す、ひと目でわかる数字"""
    b = p.get("battery") or {}
    usb = p.get("usb") or {}
    r = p.get("rating") or {}
    o = p.get("outlets") or {}
    cmax = max([x.get("max_w") or 0 for x in usb_c_ports(p)] or [0])
    bits = [f"USB-C {cmax:g}W" if cmax else "", f"{b['mah']:,}mAh" if b.get("mah") else "",
            f"{o['ac']}個口" if p["category"] in TAP_CATS and o.get("ac") else "",
            f"{r['watt_max']:,}W" if p["category"] in TAP_CATS and r.get("watt_max") else "",
            "GaN" if usb.get("gan") else "", f"{p['weight_g']:g}g" if p.get("weight_g") else ""]
    return "".join(f"<i>{e(x)}</i>" for x in bits if x)


def post_card(a: dict, big: bool = False) -> str:
    p = a["p"]
    im = post_images(a)
    pic = (f'<figure class="pc-img"><img src="{e(im[0]["src"])}" alt="{e(im[0]["alt"])}" loading="lazy" referrerpolicy="no-referrer"></figure>'
           if im else '<figure class="pc-img noimg"></figure>')
    return (f'<a class="postcard{" big" if big else ""}" href="{a["url"]}">{pic}<div class="pc-body">'
            f'<p class="pc-meta"><span>{e(CAT[p["category"]]["name"])}</span><time>{e(a["date"])}</time></p>'
            f'<b>{e(catch(a))}</b><span class="pc-model">{e(p["maker"])} {e(p["model"])}</span>{strip_html(p)}</div></a>')


def catch(a: dict) -> str:
    """題名から後ろの「メーカー 型番」を除いた特徴の部分(カードでは型番を別の行に出すため)"""
    tail = f'{a["p"]["maker"]} {a["p"]["model"]}'
    t = str(a["title"]).strip()
    return t[:-len(tail)].strip() if t.endswith(tail) and t[:-len(tail)].strip() else t


def post_h1(a: dict) -> str:
    """新製品記事の大見出し。1行目に特徴(キャッチコピー)、2行目にメーカーと型番(2026-11-15 本人)。
    題名は「<特徴> <メーカー> <型番>」の形で書く。形が違えば題名をそのまま1行で出す"""
    p = a["p"]
    tail = f'{p["maker"]} {p["model"]}'
    t = str(a["title"]).strip()
    if t.endswith(tail) and t[:-len(tail)].strip():
        return (f'<h1 class="ph1"><span class="catch">{e(t[:-len(tail)].strip())}</span>'
                f'<span class="pname">{e(p["maker"])} <b>{e(p["model"])}</b></span></h1>')
    return f'<h1>{e(t)}</h1>'


def side_specs(p: dict) -> str:
    """記事の横の、ひと目でわかる仕様"""
    b, usb, r, o = p.get("battery") or {}, p.get("usb") or {}, p.get("rating") or {}, p.get("outlets") or {}
    cmax = max([x.get("max_w") or 0 for x in usb_c_ports(p)] or [0])
    rows = [("容量", f'{b["mah"]:,}mAh' + (f' / {b["wh"]:g}Wh' if b.get("wh") else "")) if b.get("mah") else None,
            ("電池", e(b["cell"])) if b.get("cell") else None,
            ("差し込み口", f'{o["ac"]}個口') if p["category"] in TAP_CATS and o.get("ac") else None,
            ("合計の最大", f'{r["watt_max"]:,}W') if p["category"] in TAP_CATS and r.get("watt_max") else None,
            ("USB-C 1ポート最大", f"{cmax:g}W") if cmax else None,
            ("USB の合計", f'{usb["total_w"]:g}W') if usb.get("total_w") else None,
            ("重さ", f'{p["weight_g"]:g}g') if p.get("weight_g") else None,
            ("パススルー", "あり" if b["passthrough"] else '<span class="no">なし</span>') if "passthrough" in b and b["passthrough"] is not None else None,
            ("PSE", pse_badge(p))]
    return "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in (x for x in rows if x))


H2_EN = {"何が新しいか": "WHAT'S NEW", "ここが面白い": "FEATURES", "特徴": "FEATURES", "どんな使い方に合うか": "HOW TO USE"}


def post_h2(jp: str, en: str = "") -> str:
    en = en or H2_EN.get(jp, "")
    return f'<h2 class="v7-h"><small>{e(en)}</small>{e(jp)}</h2>'


def post_lcd(p: dict) -> str:
    """何ワットになるかの画面。USB は「右の口を押すと2台目」、コンセントだけの物は合計の上限を出す"""
    rd = readout(p)
    if rd and rd["one_k"] == "1台だけ":
        one, two = rd["one"].removesuffix("W"), rd["two"].removesuffix("W")
        return f"""<div class="lcd" data-one="{e(one)}" data-two="{e(two)}">
  <div class="lcd-scr" aria-live="polite">
    <div class="lcd-top"><span>USB-C OUTPUT</span><span class="lcd-mode">1台</span></div>
    <div class="lcd-num"><b>{e(one)}</b><i>W</i></div>
    <div class="lcd-foot">1台だけ挿したとき</div>
  </div>
  <div class="lcd-side">
    <div class="lcd-ports"><span class="lcd-port on" aria-hidden="true"></span><button type="button" class="lcd-port" aria-pressed="false" aria-label="2台目を挿す"></button></div>
    <p><b>右の口を押す</b>と<br>2台目を挿した数字に</p>
    <p class="lcd-src">{e(p['model'])}<br>{e(rd['note'])}</p>
  </div>
</div>"""
    o, r = p.get("outlets") or {}, p.get("rating") or {}
    if o.get("ac") and r.get("watt_max"):
        return f"""<div class="lcd static">
  <div class="lcd-scr">
    <div class="lcd-top"><span>AC OUTPUT</span><span>{o['ac']}口</span></div>
    <div class="lcd-num"><b>{r['watt_max']}</b><i>W</i></div>
    <div class="lcd-foot">{o['ac']}口ぜんぶの合計まで</div>
  </div>
  <div class="lcd-side">
    <p><b>{r.get('volt', 125)}V・{r.get('amp', 15)}A</b><br>ドライヤー1台でほぼ上限</p>
    <p class="lcd-src">{e(p['model'])}<br>定格の表示より</p>
  </div>
</div>"""
    return ""


def build_post(a: dict) -> str:
    """新製品記事(2026-11-23 本人 OK = mock/v7。「通販サイトみたいで野暮ったい」→「左右のカラムをやめたい」)
    上から1列: 見出し / 写真と小さい写真 / 計器の板(ポートの顔・何ワットになるか・確かめた量) / 要約と買うボタン /
    タプ夫・本文(見出しに小さな英字)・食い違い・配り方・全部の数字(黒い画面、記載なしは1行に)・買うボタン・読んだ資料 / ほかの新製品"""
    p = a["p"]
    im = post_images(a)
    first = im[0] if im else {"src": p.get("image") or "", "alt": p["name"]}
    thumbs = ""
    if len(im) > 1:
        thumbs = '<div class="a3-thumbs v7-thumbs">' + "".join(
            f'<button type="button"{" aria-current=\"true\"" if i == 0 else ""} aria-label="{i + 1}枚目を大きく">'
            f'<img src="{e(x["src"])}" alt="{e(x["alt"])}" loading="lazy" referrerpolicy="no-referrer"></button>'
            for i, x in enumerate(im)) + "</div>"
    credit = e(a.get("image_credit") or p.get("image_credit") or p["maker"] + " 公式サイト")
    g = gaps(p)
    cat = GROUP.get(p["category"], CAT[p["category"]]["name"])
    released = f'<span>発売 {e(a["released"])}</span>' if a.get("released") else ""

    # 本文: 「ここが面白い」は「特徴」に(本人 11/23)。見出しに小さな英字を添える
    html = markdown.markdown(a["body"].replace("## ここが面白い", "## 特徴"), extensions=["tables"])
    html = re.sub(r"<h2>(.*?)</h2>", lambda m: post_h2(m.group(1)), html)

    gap_html = ""
    if g:
        gap_html = (post_h2("公式の中で、数字が食い違っていた所", "CROSS-CHECK")
                    + '<p class="v7-note">製品ページ・取扱説明書・公式画像(早見表や底面ラベル)を突き合わせて見つけた所です。</p>'
                    + '<ul class="v7-gaps">' + "".join(f"<li>{e(x)}</li>" for x in g) + "</ul>")
    rows = sharing_list(p)
    share = ""
    if rows:
        share = (post_h2("同時に挿したときの配り方", "POWER SHARING") + '<div class="tbl"><table class="share3 v7-share"><tbody>'
                 + "".join(f'<tr><th>{e(r["use"])}</th><td>{split_bar(p, r["use"], r["out"])}</td></tr>' for r in rows)
                 + "</tbody></table></div>")
    allrows = spec_rows(p) + (usb_rows(p) if p["category"] in TAP_CATS else [])
    allrows = [(k, v) for k, v in allrows if k != "同時に使ったときの配り方"]
    # 「記載なし」は1行ずつ並べず、最後にまとめる(読む所を減らす)
    seen, have, none = set(), [], []
    for k, v in allrows:
        if k in seen:
            continue
        seen.add(k)
        (none if re.sub(r"<[^>]+>", "", v).strip() == "記載なし" else have).append((k, v))
    plate = (post_h2("全部の数字", "SPEC SHEET") + '<div class="v7-plate"><dl>'
             + "".join(f"<div><dt>{e(k)}</dt><dd>{v}</dd></div>" for k, v in have) + "</dl>"
             + (f'<p class="v7-none">公式に記載なし: {"・".join(e(k) for k, _ in none)}</p>' if none else "")
             + f'<p class="v7-none">全部の注記は <a href="{p["url"]}">{e(p["model"])} の仕様のページ</a>に。</p></div>')
    srcs = a.get("sources") or []
    src_html = (post_h2("読んだ資料", "SOURCES") + '<ol class="v7-srcs">' + "".join(
        f'<li><a href="{e(s["url"])}">{e(s["name"])}</a><span>{e(str(s.get("date", "")))}</span></li>' for s in srcs) + "</ol>") if srcs else ""
    intro = bubble(a.get("face", "futsu"), a["intro"]) if a.get("intro") else ""
    others = [x for x in POSTS if x["slug"] != a["slug"]][:3]
    more = ('<h2 class="more-h v7-more">ほかの新製品</h2><div class="postgrid">' + "".join(post_card(x) for x in others) + "</div>") if others else ""
    # 「広告を含みます」はページの頭の左上でなく、分類と日付の行の右端に1つだけ(11/23 本人。買うボタンの近くには出さない)
    top_ad = '<span class="adnote v7-ad">広告を含みます</span>' if (has_buy(p) and HAS_AFF) else ""
    price = f'<p class="v7-price">{e(p["price"])}<small>掲載時点</small></p>' if p.get("price") else ""

    body = f"""<main class="v7"><div class="wrap v7-wrap">
<p class="v7-crumb"><a href="/">トップ</a> / <a href="/p/">新製品</a> / {e(cat)} / {e(p['maker'])}</p>
<header class="v7-head">
  <div class="v7-meta"><span class="v7-cat">{e(cat)}</span>{released}<span>掲載 {e(str(a['date']))}</span>{top_ad}</div>
  <h1>{e(catch(a))}</h1>
  <p class="v7-maker">{e(p['maker'])}<span>{e(p['model'])}</span></p>
</header>

<div class="v7-top">
  <figure class="v7-photo">
    <div class="a3-grid v7-ph"><div class="anat solo"><div class="anat-ph"><img src="{e(first['src'])}" alt="{e(first['alt'])}" referrerpolicy="no-referrer"></div></div></div>
    {thumbs}
    <figcaption>画像: {credit}</figcaption>
  </figure>
  <aside class="v7-panel">
    <div class="v7-block"><p class="v7-label">PORTS<span>ポートの顔</span></p>{port_face(p, big=True)}</div>
    <div class="v7-block"><p class="v7-label">OUTPUT<span>何ワットになるか</span></p>{post_lcd(p)}</div>
    <dl class="v7-tally"><div><dt>確かめた項目</dt><dd>{leaves(p)}</dd></div><div><dt>読んだ資料</dt><dd>{sources(p)}</dd></div>
      <div><dt>公式の食い違い</dt><dd class="hot">{len(g)}</dd></div></dl>
  </aside>
</div>

<section class="v7-lead">
  <p class="v7-sum">{e(a['summary'])}</p>
  <div class="v7-buy">{price}{store_buttons(p, 'post-top').replace(AD_NOTE, '')}</div>
</section>

<article class="v7-body">
{intro}
<div class="v7-prose">{html}</div>
{gap_html}
{share}
{plate}
<div class="v7-buy end">{price}{store_buttons(p, 'post-bottom').replace(AD_NOTE, '')}</div>
{src_html}
</article>
{more}
</div></main>
<script src="/assets/home.js" defer></script>"""
    ld = [{"@context": "https://schema.org", "@type": "Article", "headline": a["title"], "datePublished": str(a["date"]),
           "dateModified": str(a.get("updated") or a["date"]), "image": [x["src"] for x in im],
           "author": {"@type": "Organization", "name": SITE["title"]},
           "publisher": {"@type": "Organization", "name": SITE["author"]}}]
    return page(title=a["title"], desc=a["summary"], path=a["url"], body=body, current="posts",
                image=im[0]["src"] if im else "", ld=ld)


def build_post_index() -> str:
    body = f"""<main class="article wide"><div class="wrap">
<p class="crumb"><a href="/">トップ</a> › 新製品</p>
<h1>新製品</h1>
<p>USB-C の充電器・電源タップ・モバイルバッテリーの新製品を、1つずつ紹介しています。数字はメーカー公式ページと取扱説明書で確かめたものです。</p>
<div class="postgrid">{''.join(post_card(a) for a in POSTS)}</div>
</div></main>"""
    return page(title="新製品", desc="USB-C の充電器・電源タップ・モバイルバッテリーの新製品の紹介", path="/p/", body=body, current="posts")


# ── 特集(2026-11-14 本人「GTみたいに特集記事も」) ──────────────────────
# content/f/<名前>.md → /f/<名前>/。テーマを1つ決め、製品データの機種をカードで並べる。
# 各カードに、ひとこと(hook)・本文(note)・ポートの札・同時出力の帯グラフ・買うボタンが付く

FEATURES: list[dict] = []


def load_features(products: dict[str, dict]) -> list[dict]:
    feats = []
    for path in sorted((ROOT / "content" / "f").glob("*.md")):
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", path.stem):
            die(f"{path.name}: ファイル名は英小文字・数字・ハイフンにしてください")
        fm, body = split_fm(path)
        for k in ("title", "date", "summary", "items"):
            if not fm.get(k):
                die(f"{path.name}: {k} がありません")
        if fm.get("draft") and "--drafts" not in sys.argv:
            continue
        for it in fm["items"]:
            if it.get("product") not in products:
                die(f"{path.name}: items の {it.get('product')} が data/products にありません")
            if not it.get("hook") or not it.get("note"):
                die(f"{path.name}: {it['product']} の hook か note がありません")
            it["p"] = products[it["product"]]
        fm["slug"] = path.stem
        fm["url"] = f"/f/{path.stem}/"
        fm["body"] = body
        feats.append(fm)
    feats.sort(key=lambda a: str(a.get("updated") or a["date"]), reverse=True)
    return feats


def feature_card(f: dict) -> str:
    p = f["items"][0]["p"]
    pic = (f'<figure class="pc-img"><img src="{e(p["image"])}" alt="{e(p["name"])}" loading="lazy" referrerpolicy="no-referrer"></figure>'
           if p.get("image") else '<figure class="pc-img noimg"></figure>')
    return (f'<a class="postcard feat" href="{f["url"]}">{pic}<div class="pc-body">'
            f'<p class="pc-meta"><span>特集</span><time>{e(f.get("updated") or f["date"])}</time></p>'
            f'<b>{e(f["title"])}</b><span class="small">{e(f["summary"])}</span>'
            f'<span class="tags"><i>{len(f["items"])}機種</i></span></div></a>')


def feature_item(i: int, it: dict) -> str:
    p = it["p"]
    post = next((a for a in POSTS if a["product"] == p["id"]), None)
    links = f'<a href="{p["url"]}">仕様をすべて見る</a>' + (f' ・ <a href="{post["url"]}">紹介記事</a>' if post else "")
    share = f'<h4>同時に挿したときの配り方</h4>{sharing_html(p)}' if (p.get("usb") or {}).get("sharing") else ""
    price = f'<p class="small">値段: {e(p["price"])}</p>' if p.get("price") else ""
    return f"""<article class="fitem" id="{p['id']}">
<div class="fitem-head">{img(p, "fimg")}<div>
<p class="pc-meta"><span>{i:02d}</span><span>{e(CAT[p['category']]['name'])}</span></p>
<h3><span class="maker">{e(p['maker'])}</span> {e(p['model'])}</h3>
<p class="hook">{e(it['hook'])}</p>
<div class="post-head"><span class="tags">{key_chips(p)}</span>{pse_badge(p)}</div>
<p class="meta-line">{usb_summary(p)}</p>
</div></div>
<div class="prose">{markdown.markdown(it['note'])}</div>
{share}
{price}
{store_buttons(p, 'feature')}
<p class="small">{links}</p>
</article>"""


def feature_thumb(it: dict) -> str:
    return (f'<th><a class="fthumb" href="#{it["p"]["id"]}">'
            f'{(chr(60) + "img src=" + chr(34) + e(it["p"]["image"]) + chr(34) + " alt=" + chr(34) + chr(34) + " loading=lazy referrerpolicy=no-referrer>") if it["p"].get("image") else "<i></i>"}'
            f'<span>{e(it["p"]["maker"])} {e(it["p"]["model"])}</span></a></th>')


def feature_table(f: dict) -> str:
    """特集ごとの比べる項目。ケーブル(items の cable: {kind, length, max_w})か、
    画面(screen: {where, shows}。2026-11-27 特集「画面付き」)"""
    scr = [it for it in f["items"] if it.get("screen")]
    if scr:
        trs = "".join(
            f'<tr>{feature_thumb(it)}<td>{e(CAT[it["p"]["category"]]["name"])}</td>'
            f'<td>{e(it["screen"].get("where", ""))}</td><td>{e(it["screen"].get("shows", ""))}</td>'
            f'<td class="num">{num(it["p"].get("weight_g"), "g")}</td></tr>' for it in scr)
        return (f'<h2>ひと目で比べる</h2><div class="tscroll"><table class="ctable ftable"><thead><tr><th>機種</th><th>種類</th><th>画面の場所</th>'
                f'<th>画面に出るもの</th><th>重さ</th></tr></thead><tbody>{trs}</tbody></table></div>')
    rows = [it for it in f["items"] if it.get("cable")]
    if not rows:
        return ""
    trs = "".join(
        f'<tr><th><a class="fthumb" href="#{it["p"]["id"]}">'
        f'{(chr(60) + "img src=" + chr(34) + e(it["p"]["image"]) + chr(34) + " alt=" + chr(34) + chr(34) + " loading=lazy referrerpolicy=no-referrer>") if it["p"].get("image") else "<i></i>"}'
        f'<span>{e(it["p"]["maker"])} {e(it["p"]["model"])}</span></a></th>'
        f'<td>{e(CAT[it["p"]["category"]]["name"])}</td><td>{e(it["cable"].get("kind", ""))}</td>'
        f'<td>{e(it["cable"].get("length", ""))}</td><td class="num">{e(it["cable"].get("max_w", ""))}</td>'
        f'<td class="num">{num(it["p"].get("weight_g"), "g")}</td></tr>' for it in rows)
    return (f'<h2>ひと目で比べる</h2><div class="tscroll"><table class="ctable ftable"><thead><tr><th>機種</th><th>種類</th><th>ケーブルの形</th>'
            f'<th>長さ</th><th>ケーブルの最大</th><th>重さ</th></tr></thead><tbody>{trs}</tbody></table></div>')


def build_feature(f: dict) -> str:
    items = "".join(feature_item(i + 1, it) for i, it in enumerate(f["items"]))
    toc = "".join(f'<li><a href="#{it["p"]["id"]}">{e(it["p"]["maker"])} {e(it["p"]["model"])}</a> ── {e(it["hook"])}</li>'
                  for it in f["items"])
    intro = bubble(f.get("face", "futsu"), f["intro"]) if f.get("intro") else ""
    srcs = f.get("sources") or []
    src_html = ("<h2>出典</h2><ol class=\"src\">" + "".join(
        f'<li><a href="{e(s["url"])}">{e(s["name"])}</a>(取得 {e(s.get("date", ""))})</li>' for s in srcs) + "</ol>") if srcs else ""
    upd = f' ・ 更新 {e(f["updated"])}' if f.get("updated") and str(f["updated"]) != str(f["date"]) else ""
    body = f"""<main class="article post feature"><div class="wrap">
<p class="crumb"><a href="/">トップ</a> › <a href="/f/">特集</a></p>
<p class="pc-meta"><span>特集</span><time>{e(f['date'])}</time>{upd}</p>
<h1>{e(f['title'])}</h1>
<p class="lead">{e(f['summary'])}</p>
{intro}
<div class="prose">{markdown.markdown(f['body'], extensions=['tables'])}</div>
<ol class="ftoc">{toc}</ol>
{feature_table(f)}
<h2>{len(f['items'])}機種</h2>
{items}
<p class="small">数字はメーカー公式ページと取扱説明書のものです(各機種の仕様のページに出典があります)。値段は掲載時点の公式の価格です。</p>
{src_html}
</div></main>"""
    imgs = [it["p"]["image"] for it in f["items"] if it["p"].get("image")]
    ld = [{"@context": "https://schema.org", "@type": "Article", "headline": f["title"], "datePublished": str(f["date"]),
           "dateModified": str(f.get("updated") or f["date"]), "image": imgs[:4],
           "author": {"@type": "Organization", "name": SITE["title"]},
           "publisher": {"@type": "Organization", "name": SITE["author"]}}]
    return page(title=f["title"], desc=f["summary"], path=f["url"], body=body, current="features",
                image=imgs[0] if imgs else "", pr=any(has_buy(it["p"]) for it in f["items"]), ld=ld)


def build_feature_index() -> str:
    body = f"""<main class="article wide"><div class="wrap">
<p class="crumb"><a href="/">トップ</a> › 特集</p>
<h1>特集</h1>
<p>テーマを1つ決めて、日本で買える充電器・タップ・モバイルバッテリーを並べています。数字はメーカー公式ページと取扱説明書で確かめたものです。</p>
<div class="postgrid">{''.join(feature_card(f) for f in FEATURES)}</div>
</div></main>"""
    return page(title="特集", desc="充電器・電源タップ・モバイルバッテリーの特集", path="/f/", body=body, current="features")


# ── トップ・固定ページ ───────────────────────────────────────

FACE_LABEL = {"ac": "AC", "c": "C", "a": "A", "cable": "ケーブル", "wl": "無線", "plug": "プラグ", "line": ""}


PICKS_MAX = 6


def pick_slides(products: list[dict]) -> str:
    """最初の画面の横スライド(data/picks.yaml)。製品データにある物だけ。記事があれば記事へ、無ければ図鑑へ"""
    path = ROOT / "data" / "picks.yaml"
    if not path.exists():
        return ""
    by_id = {p["id"]: p for p in products}
    post_of = {a["p"]["id"]: a for a in POSTS}
    items = []
    picks = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    # 出すのは上から6つまで(2026-11-23 本人「スライダーに表示させるガジェットは最大6個で」)。7つ目からは控え
    if len(picks) > PICKS_MAX:
        print(f"横スライドは上から {PICKS_MAX} つだけ出す。控え: {', '.join(str(x.get('id')) for x in picks[PICKS_MAX:])}")
    for i, x in enumerate(picks[:PICKS_MAX]):
        p = by_id.get(x.get("id"))
        if not p:
            die(f"data/picks.yaml: {x.get('id')} が data/products にありません")
        a = post_of.get(p["id"])
        href = a["url"] if a else p["url"]
        im = post_images(a)[0]["src"] if a and post_images(a) else p.get("image")
        face = "".join(f'<span class="pf-i pf-{k}"><i aria-hidden="true"></i><small>{FACE_LABEL.get(k, k)}</small></span>'
                       for k in x.get("face") or [])
        items.append(
            f'<li class="sl{" cover" if x.get("cover") else ""}" style="--sl-bg:{e(x.get("bg") or "#E4E6EA")}"><a href="{href}">'
            f'<div class="sl-ph"><img src="{e(im or "")}" alt="{e(p["maker"])} {e(p["model"])}" referrerpolicy="no-referrer"'
            f' loading="{"eager" if i < 4 else "lazy"}"></div>'
            f'<div class="sl-cap"><p class="sl-k">{e(CAT[p["category"]]["name"])}</p><p class="sl-hook">{x["hook"]}</p>'
            f'<p class="sl-n">{e(p["maker"])} {e(p["model"])}</p>'
            f'<div class="sl-row"><div class="pf">{face}</div><span class="sl-f">{e(x.get("fact") or "")}</span></div></div></a></li>')
    if len(items) < 4:
        die("data/picks.yaml: 4つ以上並べてください")
    return f"""<section class="show5"><div class="wrap">
  <div class="s5-head">
    <div><p class="kicker">見た目で選んだ充電まわり <span>PICKS</span></p><h1><span>見たことのない、</span><span>充電まわり。</span></h1></div>
    <div class="s5-ctl"><span class="s5-count"><b>01</b> / {len(items):02d}</span></div>
  </div>
</div>
<div class="s5-viewport"><ul class="s5-track">{"".join(items)}</ul></div>
<div class="wrap"><div class="s5-bar"><div class="s5-dots"></div><a href="/p/">新製品をすべて見る →</a></div></div>
</section>
<script src="/assets/slides.js" defer></script>
"""


# ── トップの2段目と一覧(2026-11-21 本人がモック v5 の形で OK。「ここまでマニアックに」を数で見せる) ──
_DIG_SKIP = {"image", "images", "image_credit", "official_url", "manual_url", "url", "q", "stores", "note", "id", "checked",
             "recall_checked", "sharing_source", "how", "date"}
GROUP = {"tap": "電源タップ", "extension": "電源タップ", "usb-tap": "電源タップ", "charger": "USB 充電器", "battery": "モバイルバッテリー", "cable": "ケーブル"}
CABLE_PORTS = {("adtec-apd-v100lacrc-dg", "C1")}  # 名前にケーブルと書いていない内蔵ケーブル


def leaves(d) -> int:
    """確かめた項目の数(製品データの値の数。写真・リンク・メモは数えない)"""
    if isinstance(d, dict):
        return sum(leaves(v) for k, v in d.items() if k not in _DIG_SKIP)
    if isinstance(d, list):
        return sum(leaves(v) for v in d)
    return 0 if d in (None, "", []) else 1


def gaps(p: dict) -> list[str]:
    """公式の資料どうしの食い違い(製品データの note に書いた行)"""
    return [l.strip() for l in str(p.get("note", "")).splitlines() if "食い違" in l or "合わない" in l]


def post_for(p: dict) -> dict | None:
    return next((x for x in POSTS if x["p"]["id"] == p["id"]), None)


def sources(p: dict) -> int:
    a = post_for(p)
    return len(a.get("sources") or []) if a else len([x for x in (p.get("official_url"), p.get("manual_url")) if x])


def port_face(p: dict, big: bool = False) -> str:
    """ポートの顔: 本体の差し込み口を決まった記号で並べる"""
    items = [("ac", "AC") for _ in range((p.get("outlets") or {}).get("ac") or 0)]
    for x in (p.get("usb") or {}).get("ports") or []:
        k = port_kind(x.get("type"))
        n = str(x.get("name") or "")
        cable = (p["id"], x.get("name")) in CABLE_PORTS or (bool(re.search(r"ケーブル|Line|リール|Cable|コード", n)) and "ポート" not in n)
        kind = "cable" if cable else {"c": "c", "a": "a", "wireless": "wl"}.get(k, "c")
        w = x.get("max_w")
        items.append((kind, FACE_LABEL[kind] + (f"<em>{w:g}W</em>" if big and isinstance(w, (int, float)) else "")))
    if not items:
        return ""
    cnt: dict[str, int] = {}
    for _, lab in items:
        lab = lab.split("<em>")[0]
        cnt[lab] = cnt.get(lab, 0) + 1
    alt = "・".join(f"{k}×{v}" for k, v in cnt.items())
    cells = "".join(f'<span class="pf-i pf-{k}"><i aria-hidden="true"></i><small>{lab}</small></span>' for k, lab in items)
    return f'<div class="pf{" big" if big else ""}" role="img" aria-label="差し込み口 {e(alt)}">{cells}</div>'


def home_card(p: dict) -> str:
    a = post_for(p)
    title = catch(a) if a else re.sub(r"[（(].*?[)）]", "", p["name"]).strip()
    g = gaps(p)
    shots = post_images(a) if a else []
    im = (shots[0]["src"] if shots else p.get("image")) or ""
    new = '<span class="hc-new">新製品</span>' if a else ""
    gap = f'<span class="gap">食い違い {len(g)}</span>' if g else ""
    return (f'<a class="hcard" href="{a["url"] if a else p["url"]}">'
            f'<div class="hc-ph"><img src="{e(im)}" alt="" loading="lazy" referrerpolicy="no-referrer">{new}</div>'
            f'<div class="hc-body"><div class="hc-meta"><span class="cat">{GROUP.get(p["category"], CAT[p["category"]]["name"])}</span>'
            f'<span>{e(p["maker"])}</span></div>'
            f'<h3>{e(title)}</h3>{port_face(p)}'
            f'<div class="dig"><span><b>{leaves(p)}</b>項目</span><span><b>{sources(p)}</b>資料</span>{gap}</div></div></a>')


def anatomy_block(products: list[dict]) -> str:
    path = ROOT / "data" / "anatomy.yaml"
    if not path.exists():
        return ""
    an = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    p = next((x for x in products if x["id"] == an.get("id")), None)
    if not p or not p.get("image"):
        return ""
    a = post_for(p)
    pts = an.get("points") or []
    dots = "".join(f'<button type="button" class="dot" style="left:{x["x"]}%;top:{x["y"]}%" data-i="{i}" aria-label="{e(x["t"])}">{i + 1}</button>'
                   for i, x in enumerate(pts))
    notes = "".join(f'<li data-i="{i}"><b><span>{i + 1}</span>{e(x["t"])}</b><p>{e(x["d"])}</p></li>' for i, x in enumerate(pts))
    lcd = an.get("lcd") or {}
    lcd_html = ""
    if lcd:
        lcd_html = f"""<div class="lcd" data-one="{e(lcd['one'])}" data-two="{e(lcd['two'])}">
  <div class="lcd-scr" aria-live="polite">
    <div class="lcd-top"><span>USB-C OUTPUT</span><span class="lcd-mode">1台</span></div>
    <div class="lcd-num"><b>{e(lcd['one'])}</b><i>W</i></div>
    <div class="lcd-foot">1台だけ挿したとき</div>
  </div>
  <div class="lcd-side">
    <div class="lcd-ports"><span class="lcd-port on" aria-hidden="true"></span><button type="button" class="lcd-port" aria-pressed="false" aria-label="2台目を挿す"></button></div>
    <p><b>右の口を押す</b>と<br>2台目を挿した数字に</p>
    <p class="lcd-src">{e(p['model'])}<br>{e(lcd.get('src') or '')}</p>
  </div>
</div>"""
    total = sum(leaves(x) for x in products)
    ngap = sum(len(gaps(x)) for x in products)
    name = f'{e(p["maker"])} <span class="mono">{e(p["model"])}</span>'
    head = f'<a href="{a["url"]}">{name}</a>' if a else name
    return f"""<section class="hero3"><div class="wrap">
  <div class="h3-l">
    <p class="kicker">このサイトの読み方 <span>HOW WE READ</span></p>
    <h2 class="h3-h"><span>底面ラベルまで、</span><span>読んでます。</span></h2>
    <dl class="tally">
      <div><dt>載せた機種</dt><dd>{len(products)}</dd></div>
      <div><dt>確かめた項目</dt><dd>{total}</dd></div>
      <div><dt>公式の中の食い違い</dt><dd class="hot">{ngap}</dd></div>
    </dl>
    {lcd_html}
  </div>
  <div class="h3-r">
    <p class="spec-label">きょうの解剖 ── {head}</p>
    <div class="anat"><div class="anat-ph"><img src="{e(p['image'])}" alt="{e(p['model'])} の本体" referrerpolicy="no-referrer">{dots}</div>
    <ol class="anat-notes">{notes}</ol></div>
  </div>
</div></section>
<script src="/assets/home.js" defer></script>"""


# ── 図鑑の物の一言と発売月(「ほかの〜」のカードで使う。トップの棚は 2026-11-25 に本人「やだな」で外した)


def zk_month(p: dict, year: int) -> int | None:
    r = p.get("released")
    if isinstance(r, (dt.date, dt.datetime)):
        return r.month if r.year == year else None
    r = str(r or "")
    return int(r[5:7]) if re.match(str(year) + r"-\d{2}", r) else None


def zk_hook(p: dict) -> str:
    z = p.get("zukan") or {}
    art = post_for(p)
    return z.get("hook") or (catch(art) if art else re.sub(r"[（(].*?[)）]", "", p["name"]).strip() or p["name"])


# ── 新製品の一覧は1ページ20件まで。2ページ目からは /new/2/ … (2026-11-25 本人)
NEW_PER = 20


def new_order(products: list[dict]) -> list[dict]:
    """並び: 新製品記事のある物(新しい順) → 残りの製品 → 図鑑の物(zukan のある物)を発売の新しい順。
    図鑑の物は別の棚にせず、一覧の古い側に置く(2026-11-25 本人「新商品一覧の古いところに置いてあるとよかった」)"""
    with_post = [a["p"] for a in POSTS]
    ids = {x["id"] for x in with_post}
    rest = [p for p in products if p["id"] not in ids and not p.get("zukan")]
    zk = sorted((p for p in products if p["id"] not in ids and p.get("zukan")),
                key=lambda p: str(p.get("released") or "")[:10], reverse=True)
    return with_post + rest + zk


# 製品カテゴリで絞る(2026-11-25 本人「新商品を製品カテゴリごとにセグメントできるように」)。
# 絞った一覧は /new/<slug>/・/new/<slug>/2/ … の別ページ(ページ送りもそのカテゴリの中で)
SEGS = [("tap", "電源タップ"), ("charger", "USB 充電器"), ("battery", "モバイルバッテリー"), ("cable", "ケーブル")]
SEG_NAME = dict(SEGS)


def seg_items(products: list[dict], g: str = "") -> list[dict]:
    order = new_order(products)
    return [p for p in order if GROUP.get(p["category"]) == SEG_NAME[g]] if g else order


def new_url(n: int, g: str = "") -> str:
    if g:
        return f"/new/{g}/#list" if n == 1 else f"/new/{g}/{n}/#list"
    return "/#list" if n == 1 else f"/new/{n}/#list"


def new_path(n: int, g: str = "") -> str:
    return new_url(n, g).removesuffix("#list").replace("/#", "/") or "/"


def pager(n: int, total: int, g: str = "") -> str:
    """電池の形のページ送り(2026-11-25 本人 OK = mock/v11)。目盛りがページで、今のページまでオレンジで満ちる"""
    if total <= 1:
        return ""
    u = lambda i: new_url(i, g)  # noqa: E731
    prev = f'<a class="bp-step" href="{u(n - 1)}" rel="prev"><span aria-hidden="true">←</span>前へ</a>' if n > 1 else '<span class="bp-step off" aria-hidden="true"><span>←</span>前へ</span>'
    nxt = f'<a class="bp-step" href="{u(n + 1)}" rel="next">次へ<span aria-hidden="true">→</span></a>' if n < total else '<span class="bp-step off" aria-hidden="true">次へ<span>→</span></span>'
    cells = "".join(
        (f'<span class="bp-c on now" aria-current="page">{i:02d}</span>' if i == n else
         f'<a class="bp-c{" on" if i < n else ""}" href="{u(i)}" aria-label="{i}ページ目">{i:02d}</a>')
        for i in range(1, total + 1))
    return (f'<nav class="bpager" aria-label="新製品のページ">{prev}'
            f'<div class="bp-bat"><div class="bp-cells">{cells}</div><i class="bp-tip"></i></div>'
            f'{nxt}<p class="bp-cap"><b>{n}</b> / {total} ページ</p></nav>')


def seg_nav(products: list[dict], g: str) -> str:
    segs = [("", "すべて")] + SEGS
    out = []
    for s, name in segs:
        k = len(seg_items(products, s))
        if s and not k:
            continue
        inner = f'{e(name)}<span class="sg-k">{k}</span>'
        out.append(f'<span class="sg" aria-current="page">{inner}</span>' if s == g else f'<a class="sg" href="{new_url(1, s)}">{inner}</a>')
    return f'<nav class="segs" aria-label="製品カテゴリで絞る">{"".join(out)}</nav>'


LEGEND = ('<div class="legend"><span class="pf-i pf-ac"><i></i></span>コンセント<span class="pf-i pf-c"><i></i></span>USB-C'
          '<span class="pf-i pf-a"><i></i></span>USB-A<span class="pf-i pf-cable"><i></i></span>内蔵ケーブル'
          '<span class="pf-i pf-wl"><i></i></span>ワイヤレス</div>')


def new_list_section(products: list[dict], n: int, more: str = "", g: str = "") -> str:
    order = seg_items(products, g)
    total = max(1, -(-len(order) // NEW_PER))
    items = order[(n - 1) * NEW_PER:n * NEW_PER]
    count = f'<span class="pg-count">{len(order)}件中 {(n - 1) * NEW_PER + 1}〜{(n - 1) * NEW_PER + len(items)}件目</span>' if total > 1 else ""
    h = (f'{e(SEG_NAME[g])}の新製品' if g else "新製品") + (f'<span class="pg-of"> {n}ページ目</span>' if n > 1 else "")
    return f"""<section class="band hlist" id="list"><div class="wrap">
  <div class="sec-head"><h2><small>NEW ARRIVALS</small>{h}</h2><a href="/compare/">全機種の比べ表 →</a></div>
  {seg_nav(products, g)}
  {LEGEND}{count}
  <div class="hgrid">{''.join(home_card(p) for p in items)}</div>
  {pager(n, total, g)}
  <p class="hlist-more"><a href="/usb-c/">USB-C の配り方の全機種表</a> ・ <a href="/tools/watt/">消費電力の計算機</a>{more}</p>
</div></section>"""


def build_new_page(products: list[dict], n: int, arts: list[dict], g: str = "") -> str:
    more = ' ・ <a href="/q/">疑問に答える</a>' if arts else ""
    body = f"<main>\n{new_list_section(products, n, more, g)}\n</main>"
    name = f"{SEG_NAME[g]}の新製品" if g else "新製品"
    title = name + (f" {n}ページ目" if n > 1 else "")
    return page(title=title, desc=SITE["description"], path=new_path(n, g), body=body)


def new_pages(products: list[dict], g: str = "") -> int:
    return max(1, -(-len(seg_items(products, g)) // NEW_PER))


def build_index(products: list[dict], arts: list[dict]) -> str:
    feats = ""
    if FEATURES:
        feats = (f'<section class="band"><div class="wrap"><div class="sec-head"><h2><small>FEATURES</small>特集</h2>'
                 f'<a href="/f/">すべて見る →</a></div>'
                 f'<div class="postgrid g3">{"".join(feature_card(f) for f in FEATURES[:3])}</div></div></section>')
    more = ' ・ <a href="/q/">疑問に答える</a>' if arts else ""
    body = f"""<main>
{pick_slides(products)}
{anatomy_block(products)}
{new_list_section(products, 1, more)}
{feats}
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
    POSTS[:] = load_posts(by_id)
    FEATURES[:] = load_features(by_id)
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(ROOT / "assets", OUT / "assets")
    urls = ["/", "/q/", "/compare/", "/tools/watt/", "/about/", "/privacy/", "/fixes/"]
    write("index.html", build_index(products, arts))
    for g in [""] + [s for s, _ in SEGS]:
        if g and not seg_items(products, g):
            continue
        for n in range(1 if g else 2, new_pages(products, g) + 1):
            path = new_path(n, g)
            write(path.strip("/") + "/index.html", build_new_page(products, n, arts, g))
            urls.append(path)
    write("p/index.html", build_post_index())
    urls.append("/p/")
    for a in POSTS:
        write(f"p/{a['slug']}/index.html", build_post(a))
        urls.append(a["url"])
    if FEATURES:
        write("f/index.html", build_feature_index())
        urls.append("/f/")
    for f in FEATURES:
        write(f"f/{f['slug']}/index.html", build_feature(f))
        urls.append(f["url"])
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
    write("about/index.html", build_static("about", "このサイトの確かめ方", "充電沼の確かめ方"))
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
    nobuy = [p["id"] for p in products if not has_buy(p)]
    if nobuy:
        print(f"大手の通販で売っていないため買うボタンが無い製品: {', '.join(nobuy)}")
    unconf = [p["id"] for p in products if p["pse"]["status"] == "unconfirmed" and p["category"] != "cable"]
    if unconf:
        print(f"PSE 未確認(ボタンは出す。表示が読めたら直す): {', '.join(unconf)}")
    missing = [f for f in FACES if not asset_exists(f"chara/face-{f}.png")]
    if missing:
        print(f"注意: タプ夫の顔の画像がまだありません({', '.join(missing)})。オレンジの丸で代わりにしています")
    print(f"新製品記事 {len(POSTS)} 本・特集 {len(FEATURES)} 本・製品 {len(products)} 件・疑問記事 {len(arts)} 本・ページ {len(urls)} 枚(sitemap)・ public/ に書き出した")

    if "--serve" in sys.argv:
        import functools
        import http.server
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(OUT))
        print("http://localhost:8791")
        http.server.ThreadingHTTPServer(("127.0.0.1", 8791), handler).serve_forever()


if __name__ == "__main__":
    main()
