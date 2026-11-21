// トップの横スライド(data/picks.yaml)。PC は列ごと横にずらす(矢印・点・5秒ごとの自動送り)。スマホは指で流す(自動送りなし)
(() => {
  const vp = document.querySelector(".s5-viewport");
  const track = document.querySelector(".s5-track");
  if (!vp || !track) return;
  const slides = [...track.querySelectorAll(".sl")];
  const dotsBox = document.querySelector(".s5-dots");
  const count = document.querySelector(".s5-count");
  const mobile = matchMedia("(max-width: 640px)");
  let i = 0;
  const step = () => slides[1].offsetLeft - slides[0].offsetLeft;
  const shiftMax = () => Math.max(0, track.scrollWidth - vp.clientWidth);
  // 止まる位置の数(画面が広くて全部見えるときは1)
  const pages = () => Math.ceil(shiftMax() / step() - 0.05) + 1;
  const render = () => {
    const n = pages();
    if (i > n - 1) i = n - 1;
    track.style.transform = mobile.matches ? "" : `translateX(${-Math.min(i * step(), shiftMax())}px)`;
    if (dotsBox && dotsBox.children.length !== n) {
      dotsBox.innerHTML = Array.from({ length: n }, (_, k) => `<button type="button" aria-label="${k + 1}つ目の位置へ"></button>`).join("");
      [...dotsBox.children].forEach((d, k) => d.addEventListener("click", () => { i = k; render(); }));
    }
    [...(dotsBox?.children || [])].forEach((d, k) => (k === i ? d.setAttribute("aria-current", "true") : d.removeAttribute("aria-current")));
    if (count) count.innerHTML = `<b>${String(i + 1).padStart(2, "0")}</b> / ${String(n).padStart(2, "0")}`;
    document.querySelector(".show5")?.classList.toggle("one-page", n <= 1);
  };
  const go = (d) => { const n = pages(); i = (i + d + n) % n; render(); };
  document.querySelector(".s5-prev")?.addEventListener("click", () => go(-1));
  document.querySelector(".s5-next")?.addEventListener("click", () => go(1));
  addEventListener("resize", render);
  render();
  let hold = false;
  ["pointerenter", "focusin"].forEach((ev) => vp.addEventListener(ev, () => (hold = true)));
  ["pointerleave", "focusout"].forEach((ev) => vp.addEventListener(ev, () => (hold = false)));
  if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
    setInterval(() => { if (!hold && !document.hidden && !mobile.matches) go(1); }, 5000);
  }
})();
