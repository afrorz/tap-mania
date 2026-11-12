// 比べ表の絞り込み。行の data-* と、フォームの値を比べて隠す(静的サイトのまま)
(function () {
  var f = document.querySelector('[data-filter]');
  if (!f) return;
  var rows = document.querySelectorAll('.ctable tbody tr');
  var count = f.querySelector('[data-count]');
  function apply() {
    var ac = +f.ac.value, w = +f.w.value, usbc = +f.usbc.value, cord = +f.cord.value, color = f.color.value;
    var n = 0;
    rows.forEach(function (r) {
      var d = r.dataset, ok = true;
      if (+d.ac < ac) ok = false;
      if (+d.w < w) ok = false;
      if (usbc === 1 && +d.usbc <= 0) ok = false;
      if (usbc > 1 && +d.usbc < usbc) ok = false;
      if (+d.cord < cord) ok = false;
      if (color && d.colors.split('|').indexOf(color) < 0) ok = false;
      if (f.magnet.checked && d.magnet !== '1') ok = false;
      if (f.shutter.checked && d.shutter !== '1') ok = false;
      if (f.surge.checked && d.surge !== '1') ok = false;
      r.hidden = !ok;
      if (ok) n++;
    });
    count.textContent = n + ' 機種';
  }
  f.addEventListener('change', apply);
  apply();
})();
