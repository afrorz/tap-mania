// 画面(READOUT): 右の差し込み口を押すと「2台目を挿した」ことになり、取説どおりの数字に変わる
document.querySelectorAll(".rd-device").forEach((dev) => {
  const screen = dev.querySelector(".rd-screen");
  const num = dev.querySelector(".rd-num");
  const foot = dev.querySelector(".rd-foot");
  const mode = dev.querySelector(".rd-mode");
  const btn = dev.querySelector("button.rd-port");
  const set = (plugged) => {
    btn.setAttribute("aria-pressed", String(plugged));
    num.textContent = plugged ? dev.dataset.two : dev.dataset.one;
    num.classList.toggle("long", num.textContent.length > 3);
    mode.textContent = plugged ? "2台" : "1台";
    foot.textContent = plugged ? dev.dataset.twoNote : dev.dataset.oneNote;
    screen.classList.remove("flick"); void screen.offsetWidth; screen.classList.add("flick");
  };
  btn.addEventListener("click", () => set(btn.getAttribute("aria-pressed") !== "true"));
  // トップでは開いたとき一度だけ、2台目を挿す動きを見せる
  if (dev.dataset.autoplay && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    setTimeout(() => { if (btn.getAttribute("aria-pressed") !== "true") set(true); }, 1600);
  }
});
