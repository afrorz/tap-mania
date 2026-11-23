// 製品ページの写真の列。小さい写真を押すと大きい写真が入れ替わる(2026-11-23)
document.querySelectorAll(".pgal").forEach((g) => {
  const big = g.querySelector(".pimg img");
  const bs = [...g.querySelectorAll(".pgal-th button")];
  bs.forEach((b) => b.addEventListener("click", () => {
    big.src = b.querySelector("img").src;
    big.alt = (b.getAttribute("aria-label") || "").replace(/を大きく$/, "");
    bs.forEach((x) => x.removeAttribute("aria-current"));
    b.setAttribute("aria-current", "true");
  }));
});
