// 消費電力の計算機。家電と台数を選ぶと合計 W を出し、選んだタップの定格と比べる
(function () {
  var root = document.querySelector('[data-calc]');
  if (!root) return;
  var data = JSON.parse(document.getElementById('calc-data').textContent);
  var list = root.querySelector('[data-list]');
  var out = root.querySelector('[data-result]');
  var sel = root.querySelector('select[name=tap]');
  var fmt = function (n) { return n.toLocaleString('ja-JP'); };

  data.appliances.forEach(function (a, i) {
    var li = document.createElement('li');
    li.innerHTML = '<label><span class="an"></span><small></small></label>' +
      '<span class="qty"><button type="button" data-d="-1" aria-label="減らす">−</button>' +
      '<output>0</output><button type="button" data-d="1" aria-label="増やす">＋</button></span>';
    li.querySelector('.an').textContent = a.name;
    li.querySelector('small').textContent = fmt(a.w) + 'W';
    li.dataset.w = a.w;
    li.dataset.n = 0;
    list.appendChild(li);
  });
  // 表に無い家電(パソコンなど)は、本体の表示の W を入れてもらう
  var own = document.createElement('li');
  own.className = 'own';
  own.innerHTML = '<label>表に無い家電(本体の表示の W を入れる)<input type="number" min="0" max="5000" step="1" inputmode="numeric" placeholder="例 300"></label>';
  list.appendChild(own);

  function total() {
    var t = 0;
    list.querySelectorAll('li[data-w]').forEach(function (li) { t += li.dataset.w * li.dataset.n; });
    var v = parseInt(own.querySelector('input').value, 10);
    if (v > 0) t += v;
    return t;
  }
  function limit() {
    if (sel.value === 'generic') return { w: 1500, name: '一般的な 15A・125V のタップ', url: '' };
    return data.taps.filter(function (t) { return t.id === sel.value; })[0];
  }
  function render() {
    var t = total(), tap = limit(), pct = Math.min(100, Math.round(t / tap.w * 100));
    var cls = t === 0 ? '' : t > tap.w ? 'over' : t > tap.w * 0.8 ? 'near' : 'ok';
    var msg;
    if (t === 0) msg = '家電を選ぶと、ここに合計が出ます。';
    else if (t > tap.w) msg = 'このタップの定格(' + fmt(tap.w) + 'W)を超えます。同じタップに挿さず、別のコンセントに分けてください。壁のコンセントも2口の合計で 1,500W までです(NITE)。';
    else if (t > tap.w * 0.8) msg = '定格(' + fmt(tap.w) + 'W)の 8 割を超えています。同時に使う時間が重ならないか、家電の本体の表示で W を確かめてください。';
    else msg = '定格(' + fmt(tap.w) + 'W)に収まります。壁のコンセントは2口の合計で 1,500W までなので、もう片方の口に挿している物も足して考えてください。';
    out.className = 'result ' + cls;
    out.innerHTML = '<p class="sum">合計 <b>' + fmt(t) + '</b> W <small>/ 定格 ' + fmt(tap.w) + 'W</small></p>' +
      '<div class="bar"><i style="width:' + pct + '%"></i></div><p></p>' +
      (t > tap.w && data.article ? '<p><a href="' + data.article + '">1,500W を超えるとどうなるか、何Wまで使えるか</a></p>' : '');
    out.querySelectorAll('p')[1].textContent = msg;
  }
  list.addEventListener('click', function (ev) {
    var b = ev.target.closest('button[data-d]');
    if (!b) return;
    var li = b.closest('li');
    li.dataset.n = Math.max(0, Math.min(9, +li.dataset.n + +b.dataset.d));
    li.querySelector('output').textContent = li.dataset.n;
    li.classList.toggle('on', li.dataset.n > 0);
    render();
  });
  own.querySelector('input').addEventListener('input', render);
  sel.addEventListener('change', render);
  render();
})();
