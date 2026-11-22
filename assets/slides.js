// トップの横スライド(data/picks.yaml)。PC は1枚ずつ横にずらす(点・5秒ごとの自動送り。矢印は 11/22 本人「なくてもいい」で外した)。スマホは指で流す(自動送りなし)
// PC は終わりなく流れる(2026-11-21 本人「右端で左端に戻るのではなく、エンドレスに」)。
// 後ろに同じ並びの写しを足し、写しの1枚目まで進んだら、動きを切って本物の1枚目へ瞬時に戻す
(() => {
  const vp = document.querySelector(".s5-viewport");
  const track = document.querySelector(".s5-track");
  if (!vp || !track) return;
  const slides = [...track.querySelectorAll(".sl")];
  const n = slides.length;
  if (n < 2) return;
  // 写しは読み上げ・Tab の対象にしない(スマホでは CSS で隠す)
  for (let r = 0; r < 2; r++) {
    slides.forEach((s) => {
      const c = s.cloneNode(true);
      c.classList.add("clone");
      c.setAttribute("aria-hidden", "true");
      c.querySelectorAll("a, button").forEach((a) => a.setAttribute("tabindex", "-1"));
      c.querySelectorAll("img").forEach((im) => im.setAttribute("loading", "lazy"));
      track.appendChild(c);
    });
  }
  const dotsBox = document.querySelector(".s5-dots");
  const count = document.querySelector(".s5-count");
  const mobile = matchMedia("(max-width: 640px)");
  let i = 0;
  let busy = false;
  const step = () => slides[1].offsetLeft - slides[0].offsetLeft;
  const place = (animate) => {
    if (mobile.matches) { track.style.transform = ""; return; }
    if (!animate) track.style.transition = "none";
    track.style.transform = `translateX(${-i * step()}px)`;
    if (!animate) { void track.offsetWidth; track.style.transition = ""; }
  };
  if (dotsBox) {
    dotsBox.innerHTML = slides.map((_, k) => `<button type="button" aria-label="${k + 1}枚目へ"></button>`).join("");
    [...dotsBox.children].forEach((d, k) => d.addEventListener("click", () => { i = k; place(true); label(); }));
  }
  const label = () => {
    const k = ((i % n) + n) % n;
    [...(dotsBox?.children || [])].forEach((d, j) => (j === k ? d.setAttribute("aria-current", "true") : d.removeAttribute("aria-current")));
    if (count) count.innerHTML = `<b>${String(k + 1).padStart(2, "0")}</b> / ${String(n).padStart(2, "0")}`;
  };
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const go = (d) => {
    if (busy || mobile.matches) return;
    if (d < 0 && i === 0) { i = n; place(false); }  // 1枚目から戻るときは、写しの1枚目へ瞬時に移ってから戻す
    i += d;
    busy = true;
    place(true);
    label();
    // 動き(0.7秒)が終わったころに戻す。transitionend はタブが裏にあると来ないことがあるので時間で
    setTimeout(settle, reduce ? 0 : 760);
  };
  // 写しの側まで進んだら、見た目を変えずに本物の側へ戻す
  const settle = () => { busy = false; if (i >= n) { i -= n; place(false); } };
  document.querySelector(".s5-prev")?.addEventListener("click", () => go(-1));
  document.querySelector(".s5-next")?.addEventListener("click", () => go(1));
  addEventListener("resize", () => place(false));
  place(false);
  label();
  let hold = false;
  ["pointerenter", "focusin"].forEach((ev) => vp.addEventListener(ev, () => (hold = true)));
  ["pointerleave", "focusout"].forEach((ev) => vp.addEventListener(ev, () => (hold = false)));
  if (!reduce) {
    setInterval(() => { if (!hold && !document.hidden && !mobile.matches) go(1); }, 5000);
  }
})();
