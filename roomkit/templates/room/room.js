(function () {
  "use strict";
  var root = document.getElementById("room-content");
  if (!root) { return; }
  var KEY = root.getAttribute("data-room-theme-key");
  var toggle = root.querySelector("[data-room-toggle]");
  if (toggle && KEY) {
    var sysDark = function () { return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches; };
    var apply = function (v) {
      if (v === "light" || v === "dark") { root.setAttribute("data-room-theme", v); } else { root.removeAttribute("data-room-theme"); }
      var dark = v === "dark" || (v !== "light" && sysDark());
      toggle.textContent = dark ? "Light" : "Dark";
      toggle.setAttribute("aria-label", dark ? "Switch to the light reading theme" : "Switch to the dark reading theme");
      toggle.setAttribute("aria-pressed", dark ? "true" : "false");
    };
    var saved = null;
    try { saved = window.localStorage.getItem(KEY); } catch (e) {}
    apply(saved);
    toggle.hidden = false;
    toggle.addEventListener("click", function () {
      var dark = root.getAttribute("data-room-theme") === "dark" || (!root.hasAttribute("data-room-theme") && sysDark());
      var next = dark ? "light" : "dark";
      try { window.localStorage.setItem(KEY, next); } catch (e) {}
      apply(next);
    });
  }
  var finder = root.querySelector("[data-room-finder]");
  if (!finder) { return; }
  var form = finder.querySelector("form");
  var q = document.getElementById("room-q");
  var facets = Array.prototype.slice.call(finder.querySelectorAll("[data-room-facet]"));
  var cards = Array.prototype.slice.call(root.querySelectorAll(".room__card"));
  var sections = Array.prototype.slice.call(root.querySelectorAll("[data-room-section]"));
  var count = finder.querySelector("[data-room-count]");
  var empty = root.querySelector("[data-room-empty]");
  var jump = root.querySelector("[data-room-jump]");
  var total = cards.length;
  finder.hidden = false;
  var params = new URLSearchParams(window.location.search);
  q.value = params.get("q") || params.get("rr_search") || "";
  facets.forEach(function (s) { var v = params.get(s.name); if (v) { s.value = v; } });
  function attr(card, name) {
    return name === "group" ? card.getAttribute("data-room-group") : card.getAttribute("data-room-f-" + name);
  }
  function run(push) {
    var words = q.value.toLowerCase().split(/\s+/).filter(Boolean);
    var active = facets.filter(function (s) { return s.value; });
    var shown = 0;
    cards.forEach(function (c) {
      var text = c.getAttribute("data-room-text") || "";
      var hit = words.every(function (w) { return text.indexOf(w) !== -1; })
        && active.every(function (s) { return attr(c, s.name) === s.value; });
      c.hidden = !hit;
      if (hit) { shown += 1; }
    });
    var filtering = words.length > 0 || active.length > 0;
    sections.forEach(function (sec) {
      var list = sec.querySelectorAll(".room__card");
      var any = Array.prototype.some.call(list, function (c) { return !c.hidden; });
      sec.hidden = filtering && !any;
    });
    if (jump) { jump.hidden = filtering; }
    if (empty) { empty.hidden = shown > 0; }
    // The nouns are the pack's (data-room-one/-other); nothing here builds a plural.
    var noun = count.getAttribute(total === 1 ? "data-room-one" : "data-room-other");
    count.textContent = filtering ? shown + " of " + total + " " + noun + " match" : total + " " + noun;
    if (push && window.history && window.history.replaceState) {
      var p = new URLSearchParams();
      if (q.value.trim()) { p.set("q", q.value.trim()); }
      active.forEach(function (s) { p.set(s.name, s.value); });
      var qs = p.toString();
      window.history.replaceState(null, "", window.location.pathname + (qs ? "?" + qs : ""));
    }
  }
  var timer = null;
  q.addEventListener("input", function () { window.clearTimeout(timer); timer = window.setTimeout(function () { run(true); }, 150); });
  facets.forEach(function (s) { s.addEventListener("change", function () { run(true); }); });
  form.addEventListener("submit", function (e) { e.preventDefault(); run(true); });
  form.addEventListener("reset", function () { window.setTimeout(function () { run(true); q.focus(); }, 0); });
  run(false);
}());
