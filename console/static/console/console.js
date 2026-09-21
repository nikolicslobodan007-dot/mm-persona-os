// Odbrojavanje do isteka odobrenja i potvrda pre nepovratnih radnji.
(function () {
  function tick() {
    document.querySelectorAll("[data-expires]").forEach(function (el) {
      var ms = new Date(el.dataset.expires) - new Date();
      if (ms <= 0) { el.textContent = "isteklo"; el.className = "pill bad"; return; }
      var m = Math.floor(ms / 60000), s = Math.floor((ms % 60000) / 1000);
      el.textContent = "ističe za " + m + " min " + (s < 10 ? "0" : "") + s + " s";
      el.className = "pill " + (m < 15 ? "bad" : "warn");
    });
  }
  tick(); setInterval(tick, 1000);
  document.querySelectorAll("form[data-confirm]").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      if (!window.confirm(f.dataset.confirm)) e.preventDefault();
    });
  });
  document.querySelectorAll("[data-toggle]").forEach(function (b) {
    b.addEventListener("click", function () {
      var t = document.getElementById(b.dataset.toggle);
      if (t) t.hidden = !t.hidden;
    });
  });
  var auto = document.querySelector("[data-autorefresh]");
  if (auto) setTimeout(function () { location.reload(); }, 1000 * +auto.dataset.autorefresh);
})();
