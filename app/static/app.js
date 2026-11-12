// Confirmaciones (data-confirm), avisos que se cierran solos, buscador de la lista, vista previa del formulario y service worker.
document.addEventListener("submit", function (e) {
  var m = e.target.getAttribute("data-confirm");
  if (m && !window.confirm(m)) e.preventDefault();
});

(function () {  // avisos
  var t = document.querySelector(".toast");
  if (!t) return;
  function close() { t.classList.add("out"); setTimeout(function () { t.remove(); }, 320); }
  var b = t.querySelector("[data-close]"); if (b) b.addEventListener("click", close);
  setTimeout(close, t.classList.contains("err") ? 9000 : 5000);
})();

(function () {  // buscador
  var inp = document.querySelector("[data-filter]");
  if (!inp) return;
  var cards = document.querySelectorAll("#subs .sub-card"), none = document.getElementById("nomatch");
  inp.addEventListener("input", function () {
    var q = inp.value.trim().toLowerCase(), shown = 0;
    cards.forEach(function (c) {
      var ok = !q || c.getAttribute("data-name").indexOf(q) !== -1;
      c.hidden = !ok; if (ok) shown++;
    });
    if (none) none.hidden = shown > 0 || cards.length === 0;
  });
})();

(function () {  // vista previa en vivo del formulario
  var f = document.querySelector("form[data-preview]");
  if (!f) return;
  var SYM = {EUR: "€", USD: "$", GBP: "£", JPY: "¥", CNY: "CN¥", INR: "₹", KRW: "₩"};
  var UN = {day: ["día", "días"], week: ["semana", "semanas"], month: ["mes", "meses"], year: ["año", "años"]};
  var FAC = {day: 365, week: 52, month: 12, year: 1};
  function $(id) { return document.getElementById(id); }
  function val(n) { return f.elements[n].value; }
  function amount(s) {
    s = s.replace(/\s/g, "");
    if (s.indexOf(",") !== -1) s = s.replace(/\./g, "").replace(",", ".");
    var v = parseFloat(s); return isFinite(v) && v > 0 ? v : null;
  }
  function money(v, cur) {
    return v.toLocaleString("es-ES", {minimumFractionDigits: 2, maximumFractionDigits: 2}) + " " + (SYM[cur] || cur);
  }
  var AV = [["#7c5cff", "#4f8cf7"], ["#22d3ee", "#3b82f6"], ["#f472b6", "#c026d3"], ["#fb923c", "#ef4444"],
            ["#2dd4bf", "#0ea5e9"], ["#a78bfa", "#ec4899"], ["#fbbf24", "#f97316"], ["#60a5fa", "#6366f1"]];
  function grad(n) { var h = 0; for (var i = 0; i < n.length; i++) h += (i + 7) * n.charCodeAt(i); var c = AV[(h * 37) % AV.length]; return "linear-gradient(135deg," + c[0] + "," + c[1] + ")"; }
  function update() {
    var name = val("name").trim(), cur = val("currency"), a = amount(val("amount")), n = parseInt(val("period_n"), 10), u = val("period_unit");
    var av = $("pv-av");
    av.textContent = (name.replace(/[^\p{L}\p{N}]/gu, "")[0] || "?").toUpperCase();
    av.style.background = grad(name || "?");
    $("pv-name").textContent = name || "Sin nombre";
    var ok = n >= 1 && UN[u];
    $("pv-per").textContent = ok ? (a ? money(a, cur) + " " : "") + (n === 1 ? "cada " + UN[u][0] : "cada " + n + " " + UN[u][1]) : "—";
    if (a && ok) { var yr = a * FAC[u] / n; $("pv-year").textContent = money(yr, cur); $("pv-month").textContent = money(yr / 12, cur); }
    else { $("pv-year").textContent = "—"; $("pv-month").textContent = "—"; }
  }
  f.addEventListener("input", update); f.addEventListener("change", update); update();
})();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", function () {
    navigator.serviceWorker.register("/sw.js").catch(function () {});
  });
}
