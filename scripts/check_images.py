"""製品データの写真(image:)が、今も写真として開けるかを確かめる。Cozy Desk の check_images.py を製品データ用に直したもの。

python scripts/check_images.py          # 開けない写真を一覧にする(全部開ければ「すべて開けました」)
python scripts/check_images.py --json   # 結果を JSON で出す

写真の代わりにウェブページ(text/html)が返る・404 などを「開けない」とする。
403 は、写真の置き場所がプログラムからの取得を断っているだけで、ブラウザでは開けることがある(例: エレコム)。
そのため「要ブラウザ確認」として分けて出す。
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "ja,en;q=0.8",
}


def collect() -> list[tuple[str, str]]:
    """(写真のURL, 製品の id)"""
    rows = []
    for path in sorted((ROOT / "data" / "products").glob("*.yaml")):
        p = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if str(p.get("image", "")).startswith("http"):
            rows.append((p["image"], p.get("id", path.stem)))
    return rows


def check(url: str) -> tuple[str, str]:
    """('ok' | 'ng' | 'browser', 理由)"""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=30) as r:
            ctype = r.headers.get("Content-Type", "")
            head = r.read(512)
            if ctype.startswith("image/") or head[:4] in (b"\x89PNG", b"RIFF", b"GIF8") or head[:2] == b"\xff\xd8":
                return "ok", ctype
            return "ng", f"写真でなく {ctype} が返る"
    except urllib.error.HTTPError as ex:
        if ex.code == 403:
            return "browser", "403(プログラムからの取得を断っている。ブラウザでは開けることがある)"
        return "ng", f"HTTP {ex.code}"
    except Exception as ex:  # noqa: BLE001
        return "ng", f"{type(ex).__name__}: {ex}"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    rows = collect()
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda r: check(r[0]), rows))
    bad = [{"id": pid, "url": url, "state": st, "why": why} for (url, pid), (st, why) in zip(rows, results) if st != "ok"]
    if "--json" in sys.argv:
        print(json.dumps({"checked": len(rows), "problems": bad}, ensure_ascii=False, indent=1))
        return
    if not bad:
        print(f"すべて開けました({len(rows)} 枚)")
        return
    for b in bad:
        print(f"{'要ブラウザ確認' if b['state'] == 'browser' else '開けない'}: {b['id']} {b['url']} … {b['why']}")
    print(f"{len(rows)} 枚中 {len(bad)} 枚に問題")


if __name__ == "__main__":
    main()
