// トップの2段目: 解剖図(番号と説明が光る)と小さな画面(右の口を押すと2台目の数字)。2026-11-21 モック v3・v4 から
document.querySelectorAll(".anat").forEach((an) => {
  const on = (i) => {
    an.querySelectorAll("[data-i]").forEach((el) => el.classList.toggle("on", el.dataset.i === i));
  };
  an.querySelectorAll(".dot, .anat-notes li").forEach((el) => {
    el.addEventListener("mouseenter", () => on(el.dataset.i));
    el.addEventListener("click", () => on(el.dataset.i));
  });
});
document.querySelectorAll(".lcd").forEach((el) => {
  const num = el.querySelector(".lcd-num b"), mode = el.querySelector(".lcd-mode"), foot = el.querySelector(".lcd-foot");
  const btn = el.querySelector("button.lcd-port"), scr = el.querySelector(".lcd-scr");
  const set = (on) => {
    btn.setAttribute("aria-pressed", String(on));
    num.textContent = on ? el.dataset.two : el.dataset.one;
    num.classList.toggle("long", on);
    mode.textContent = on ? "2台" : "1台";
    foot.textContent = on ? "2台同時に挿したとき" : "1台だけ挿したとき";
    scr.classList.remove("flick"); void scr.offsetWidth; scr.classList.add("flick");
  };
  btn.addEventListener("click", () => set(btn.getAttribute("aria-pressed") !== "true"));
  if (!matchMedia("(prefers-reduced-motion: reduce)").matches && "IntersectionObserver" in window) {
    const io = new IntersectionObserver((es) => {
      if (es.some((x) => x.isIntersecting)) { io.disconnect(); setTimeout(() => set(true), 900); }
    }, { threshold: 0.8 });
    io.observe(el);
  }
});
// 記事の小さい写真を押すと、大きい写真が入れ替わる(解剖図の番号は1枚目だけ)
document.querySelectorAll(".a3-thumbs button").forEach((b, i, all) => b.addEventListener("click", () => {
  const ph = document.querySelector(".a3-grid .anat-ph");
  if (!ph) return;
  ph.querySelector("img").src = b.querySelector("img").src;
  ph.querySelectorAll(".dot").forEach((d) => (d.hidden = i !== 0));
  all.forEach((x) => x.removeAttribute("aria-current"));
  b.setAttribute("aria-current", "true");
}));
