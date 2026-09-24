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

// Tabovi na strani agenta (ADR-0019). Bez JS-a su svi odeljci vidljivi, pa
// strana radi i kada skripta ne prođe; ovde se samo skriva sve osim izabranog.
(function () {
  var nav = document.querySelector("[data-tabs]");
  if (!nav) return;
  var links = Array.prototype.slice.call(nav.querySelectorAll("a[href^='#']"));
  var panes = Array.prototype.slice.call(document.querySelectorAll("section[data-tab]"));
  if (!links.length || !panes.length) return;

  function show(name) {
    var found = false;
    panes.forEach(function (s) {
      var on = s.dataset.tab === name;
      s.hidden = !on;
      if (on) found = true;
    });
    if (!found) { panes[0].hidden = false; name = panes[0].dataset.tab; }
    links.forEach(function (a) {
      a.className = a.getAttribute("href").slice(1) === name ? "on" : "";
    });
    try { sessionStorage.setItem("konzola.tab", name); } catch (e) { /* privatni režim */ }
  }

  var start = location.hash.slice(1);
  if (!start) { try { start = sessionStorage.getItem("konzola.tab") || ""; } catch (e) { start = ""; } }
  show(start || panes[0].dataset.tab);

  links.forEach(function (a) {
    a.addEventListener("click", function (e) {
      e.preventDefault();
      var name = a.getAttribute("href").slice(1);
      history.replaceState(null, "", "#" + name);
      show(name);
    });
  });
  window.addEventListener("hashchange", function () { show(location.hash.slice(1)); });
})();
