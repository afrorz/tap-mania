// 記事の写真: 小さい写真を押すと大きい写真が入れ替わり、大きい写真を押すと画面いっぱいに出る
document.querySelectorAll(".gallery").forEach(g => {
  const main = g.querySelector(".main");
  g.querySelectorAll(".th").forEach(b => b.addEventListener("click", () => {
    const im = b.querySelector("img");
    main.src = im.src; main.alt = im.alt;
    g.querySelectorAll(".th").forEach(x => x.classList.toggle("on", x === b));
  }));
  g.querySelector(".zoom").addEventListener("click", () => {
    const box = document.createElement("div");
    box.className = "lightbox";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-label", "拡大した写真(押すと閉じる)");
    const im = document.createElement("img");
    im.src = main.src; im.alt = main.alt; im.referrerPolicy = "no-referrer";
    box.appendChild(im);
    const close = () => { box.remove(); document.removeEventListener("keydown", esc); };
    const esc = ev => { if (ev.key === "Escape") close(); };
    box.addEventListener("click", close);
    document.addEventListener("keydown", esc);
    document.body.appendChild(box);
  });
});
