# キャラクター作り直し(画面の顔)— Gemini に渡す文

2026-11-18 本人「タプ夫がちょっとイケてない」→ 3案から「画面の顔」を選んだ。
頭を「W 数が出る画面付きの GaN 充電器」にし、画面に表情と数字が出る。サイトの売り「取説の数字まで」をキャラの顔にする。

## 決めたこと

| 項目 | 内容 |
|---|---|
| 頭 | 白に近い明るいグレーの、角の丸い立方体の GaN 充電器。上に折りたたみのプラグ(2本、アンテナのように立つ) |
| 顔 | 前面いっぱいの黒い画面。目と口はオレンジの太い線(ドット絵ではなく、なめらかな線)。右下に小さく「65W」 |
| あご | 画面の下の縁に、オレンジで縁取った USB-C の差し込み口が2つ |
| しっぽ | 巻いた USB-C ケーブルが1本、背中から出ている |
| 体 | 約2頭身。オレンジのパーカー・黒いパンツ・白いスニーカーは今のまま(ロゴやサイトの色とそろえる) |
| 持ち物 | 黒い本(取扱説明書)。表に「MANUAL」 |
| 絵柄 | ステッカー風。太さのそろった黒い線、影なしの平らな塗り、色は白・グレー・黒・オレンジ(#F88425)だけ |
| 名前 | ひとまず「タプ夫」のまま(変えるかは本人が決める) |

## 1. まず「ふつう」を1枚作る

```
Create a mascot character illustration for a Japanese gadget website about USB-C chargers and power strips.

Character: a small chibi character (about 2 heads tall) whose head is a compact GaN USB-C wall charger.
- Head: a rounded cube, off-white / very light gray matte plastic, with two folding metal plug prongs sticking up on top like little antennas.
- The entire front face of the head is a black glossy display screen. On the screen, the face is drawn with thick, smooth glowing orange lines (#F88425): two simple eyes and a small smile. Not pixel art. In the lower right corner of the screen, a small orange digital readout says "65W".
- Below the screen, on the bottom edge of the head, two USB-C ports outlined in orange, like a chin.
- A coiled USB-C cable comes out of the back like a short tail, ending in a USB-C plug.
- Body: orange hoodie (#F88425), black pants, chunky white sneakers. White cartoon gloves.
- Pose: standing, slightly 3/4 view, waving with the right hand, holding a black hardcover book labeled "MANUAL" in the left hand.

Style: clean sticker-style vector illustration, bold uniform black outlines, flat colors, no gradients, no shading, no texture. Colors limited to white, light gray, black and orange. Friendly, smart, a bit geeky. Must stay readable when shrunk to a 40px icon.
Full body, centered, plain pure white background, no text other than "65W" and "MANUAL", no logo, no frame. Square image.
```

## 2. 表情をそろえる(1 の絵を添えて、1枚ずつ)

1 の絵を添付して、下の文の `{画面}` と `{ポーズ}` だけ入れ替えて頼む。

```
Using the attached character as the exact reference, draw the same character again. Keep the head, body, colors, outline thickness and style exactly the same. Change only the display face and the pose:
- Display face: {画面}
- Pose: {ポーズ}
Plain pure white background, full body, square image.
```

| 表情 | ファイル名 | {画面} | {ポーズ} |
|---|---|---|---|
| しんぱい | `tapuo-shinpai.png` | worried eyebrows slanting down, small wavy mouth, the readout shows "!" instead of "65W" | holding the manual with both hands close to the chest |
| おどろき | `tapuo-odoroki.png` | eyes stretched tall and wide, small round "o" mouth, the readout shows "100W" | leaning back slightly, manual open, one hand raised in surprise |
| まじめ | `tapuo-majime.png` | flat straight eyes, straight line mouth, no readout | standing straight, pointing at an open page of the manual |
| うれしい | `tapuo-ureshii.png` | eyes as happy upside-down arcs, big open smile, the readout shows "65W" | waving with both hands, manual tucked under one arm |

## 3. できたら(2026-11-18 済み。Gemini の絵の白い背景を抜いて置いた。おどろきの最初の絵は本を2冊持っていたので作り直させた)

- 5枚を `assets/chara/` に、上のファイル名で置く(今の絵は上書きしてよい。git に残っている)
- 頭だけの `face-*.png` は Claude が切り出して作る
- そのあと Claude が `python scripts/make_brand_images.py` でロゴと共有用の画像を作り直し、`docs/WRITING.md` の「タプ夫」の見た目の欄を直す
