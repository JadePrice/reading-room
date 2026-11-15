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
  var gateBtn = root.querySelector("[data-room-gate-open]");
  if (gateBtn) {
    gateBtn.hidden = false;
    gateBtn.addEventListener("click", function () {
      var reader = root.querySelector(".rr-reader[data-gate-file-url]");
      if (!reader) { return; }
      reader.setAttribute("data-file-url", reader.getAttribute("data-gate-file-url"));
      reader.removeAttribute("data-gate-file-url");
      reader.hidden = false;
      var gate = gateBtn.closest("[data-room-gate]") || gateBtn;
      gate.hidden = true;
      if (window.RRReader && typeof window.RRReader.mountAll === "function") {
        window.RRReader.mountAll();
      }
      reader.focus();
    });
  }
  // The newest and recently added lists (pack layout.newest + layout.added) as two tabs.
  // Without this script both lists show, one after the other, each under its heading.
  var tabsBox = root.querySelector("[data-room-tabs]");
  var panels = tabsBox ? Array.prototype.slice.call(tabsBox.querySelectorAll("[data-room-tab-panel]")) : [];
  if (panels.length > 1) {
    var bar = document.createElement("div");
    bar.className = "room__tabs";
    bar.setAttribute("role", "tablist");
    var tabs = panels.map(function (p, i) {
      var h = p.querySelector(".room__section-h");
      var t = document.createElement("button");
      t.type = "button";
      t.className = "room__tab";
      t.id = p.id + "-tab";
      t.setAttribute("role", "tab");
      t.setAttribute("aria-controls", p.id);
      t.textContent = h ? h.textContent : "";
      if (h) { h.classList.add("room__sr"); }
      p.setAttribute("role", "tabpanel");
      p.setAttribute("aria-labelledby", t.id);
      p.tabIndex = 0;
      bar.appendChild(t);
      return t;
    });
    var pick = function (i, focus) {
      tabs.forEach(function (t, j) {
        t.setAttribute("aria-selected", j === i ? "true" : "false");
        t.tabIndex = j === i ? 0 : -1;
        panels[j].hidden = j !== i;
      });
      if (focus) { tabs[i].focus(); }
    };
    tabs.forEach(function (t, i) {
      t.addEventListener("click", function () { pick(i, false); });
      t.addEventListener("keydown", function (e) {
        var n = tabs.length, to = null;
        if (e.key === "ArrowRight") { to = (i + 1) % n; }
        else if (e.key === "ArrowLeft") { to = (i - 1 + n) % n; }
        else if (e.key === "Home") { to = 0; }
        else if (e.key === "End") { to = n - 1; }
        if (to !== null) { e.preventDefault(); pick(to, true); }
      });
    });
    tabsBox.insertBefore(bar, panels[0]);
    tabsBox.classList.add("room__lead-tabs--on");
    pick(0, false);
  }
  // The card engine (filters, flat sort) serves both finders: this file's own
  // ([data-room-finder]) and corpus search's ([data-room-search], room-search.js, which
  // loads after this file and calls window.roomCards for everything but text search).
  var searchFinder = root.querySelector("[data-room-search]");
  var finder = root.querySelector("[data-room-finder]") || searchFinder;
  if (!finder) { return; }
  var form = finder.querySelector("form");
  var q = document.getElementById("room-q");
  var facets = Array.prototype.slice.call(finder.querySelectorAll("[data-room-facet]"));
  var multis = Array.prototype.slice.call(finder.querySelectorAll("[data-room-multi]"));
  var ranges = Array.prototype.slice.call(finder.querySelectorAll("[data-room-range]"));
  var sorter = finder.querySelector("[data-room-sort]");
  var cards = Array.prototype.slice.call(root.querySelectorAll(".room__card"));
  cards.forEach(function (c, i) { c.setAttribute("data-room-i", i); });
  var sections = Array.prototype.slice.call(root.querySelectorAll("[data-room-section]"));
  var count = finder.querySelector("[data-room-count]");
  var empty = root.querySelector("[data-room-empty]");
  var jump = root.querySelector("[data-room-jump]");
  var total = cards.length;
  var params = new URLSearchParams(window.location.search);
  facets.concat(multis, ranges, sorter ? [sorter] : []).forEach(function (s) { var v = params.get(s.name); if (v) { s.value = v; } });
  function attr(card, name) {
    return name === "group" ? card.getAttribute("data-room-group") : card.getAttribute("data-room-f-" + name);
  }
  function multiValues(card, name) {
    try { return JSON.parse(card.getAttribute("data-room-m-" + name) || "[]"); } catch (e) { return []; }
  }
  // A sort other than "default" lists every card as one flat list, as the site's own list
  // does: start from the manifest's order (data-room-n, the site's list order), then a stable
  // sort with the site's comparator (site A site-a-reading-room.js applySort): title on the trimmed,
  // lowercased sort text with localeCompare; dates as strings, undated last either way.
  // "default" puts every card back in its group, in the exported order.
  var groupsEl = root.querySelector(".room__groups");
  var flat = root.querySelector("[data-room-flat]");
  var homes = cards.map(function (c) { return c.parentNode; });
  var flatOn = false;
  function titleKey(c) { return (c.getAttribute("data-room-title") || "").trim().toLowerCase(); }
  function order() {
    if (!sorter || !flat) { return; }
    var how = sorter.value;
    if (["title", "date-desc", "date-asc"].indexOf(how) === -1) {
      if (flatOn) {
        cards.forEach(function (c, i) { homes[i].appendChild(c); });
        flat.hidden = true;
        if (groupsEl) { groupsEl.hidden = false; }
        flatOn = false;
      }
      return;
    }
    var items = cards.slice().sort(function (a, b) {
      return parseInt(a.getAttribute("data-room-n"), 10) - parseInt(b.getAttribute("data-room-n"), 10);
    });
    items.sort(compare(how));
    items.forEach(function (c) { flat.appendChild(c); });
    if (groupsEl) { groupsEl.hidden = true; }
    flat.hidden = false;
    flatOn = true;
  }
  function inRange(c, s) {
    var y = parseInt(attr(c, s.getAttribute("data-room-range")), 10);
    if (isNaN(y)) { return false; }
    return s.getAttribute("data-room-bound") === "from" ? y >= parseInt(s.value, 10) : y <= parseInt(s.value, 10);
  }
  function controls() {
    var on = function (s) { return s.value; };
    return { facets: facets.filter(on), multis: multis.filter(on), ranges: ranges.filter(on) };
  }
  // A card passes every control that is set (no text); `skip`, a control to leave out
  // (an option's count asks what that select would show with the others as they are).
  function passes(c, skip) {
    var k = controls(), keep = function (s) { return s !== skip; };
    return k.facets.filter(keep).every(function (s) { return attr(c, s.name) === s.value; })
      && k.multis.filter(keep).every(function (s) { return multiValues(c, s.getAttribute("data-room-multi")).indexOf(s.value) !== -1; })
      && (skip === "ranges" ? true : k.ranges.filter(keep).every(function (s) { return inRange(c, s); }));
  }
  // layout.finder compact (data-room-compact): each option's count, a chip per control
  // that is set, how many are set under More filters, a line saying how many undated
  // records a year filter hides, and the blocks above the list ([data-room-lead]: the
  // newest records, the collections table) out of the way while anything is set.
  var compact = finder.hasAttribute("data-room-compact");
  var chips = finder.querySelector("[data-room-chips]");
  var moreBox = finder.querySelector("[data-room-more-filters]");
  var moreN = finder.querySelector("[data-room-more-n]");
  var undated = root.querySelector("[data-room-undated]");
  var leads = Array.prototype.slice.call(root.querySelectorAll("[data-room-lead]"));
  var counted = facets.concat(multis);
  counted.forEach(function (s) {
    Array.prototype.forEach.call(s.options, function (o) { o.setAttribute("data-room-label", o.textContent); });
  });
  function labelOf(s) {
    var l = finder.querySelector('label[for="' + s.id + '"]');
    return l ? l.textContent.trim() : s.name;
  }
  function optionText(s) {
    var o = s.options[s.selectedIndex];
    return o ? (o.getAttribute("data-room-label") || o.textContent) : s.value;
  }
  function refresh(text) {
    if (!compact) { return; }
    var k = controls(), set = k.facets.concat(k.multis, k.ranges);
    var filtering = set.length > 0 || !!(text && text.trim());
    leads.forEach(function (el) { el.hidden = filtering; });
    counted.forEach(function (s) {
      var n = {}, name = s.getAttribute("data-room-multi");
      cards.forEach(function (c) {
        if (!passes(c, s)) { return; }
        (name ? multiValues(c, name) : [attr(c, s.name)]).forEach(function (v) { n[v] = (n[v] || 0) + 1; });
      });
      Array.prototype.forEach.call(s.options, function (o) {
        if (!o.value) { return; }
        var x = n[o.value] || 0;
        o.textContent = o.getAttribute("data-room-label") + " (" + x + ")";
        o.disabled = x === 0 && o.value !== s.value;
      });
    });
    if (chips) {
      chips.textContent = "";
      set.forEach(function (s) {
        var li = document.createElement("li"), b = document.createElement("button");
        var what = labelOf(s) + ": " + optionText(s);
        b.type = "button";
        b.className = "room__chip";
        b.textContent = what;
        var x = document.createElement("span");
        x.setAttribute("aria-hidden", "true");
        x.textContent = " \u00d7";
        b.appendChild(x);
        b.setAttribute("aria-label", "Remove filter " + what);
        b.addEventListener("click", function () {
          s.value = "";
          s.dispatchEvent(new Event("change"));
          if (q) { q.focus(); }
        });
        li.appendChild(b);
        chips.appendChild(li);
      });
      chips.hidden = set.length === 0;
    }
    if (moreN && moreBox) {
      var inside = set.filter(function (s) { return moreBox.contains(s); }).length;
      moreN.textContent = inside ? "(" + inside + " set)" : "";
    }
    if (undated) {
      var hidden = 0;
      if (k.ranges.length) {
        var by = k.ranges[0].getAttribute("data-room-range");
        cards.forEach(function (c) {
          if (isNaN(parseInt(attr(c, by), 10)) && passes(c, "ranges")) { hidden += 1; }
        });
      }
      undated.textContent = hidden ? undated.getAttribute(hidden === 1 ? "data-room-undated-one" : "data-room-undated-other").replace("{n}", hidden) : "";
      undated.hidden = hidden === 0;
    }
  }
  if (moreBox && controls().facets.concat(controls().multis, controls().ranges).some(function (s) { return moreBox.contains(s); })) {
    moreBox.open = true;
  }
  // Show the cards that hold every word and pass every control; returns how many.
  function filterCards(words) {
    order();
    var k = controls(), active = k.facets, activeM = k.multis, activeR = k.ranges;
    var activeM = multis.filter(function (s) { return s.value; });
    var activeR = ranges.filter(function (s) { return s.value; });
    var shown = 0;
    cards.forEach(function (c) {
      var text = c.getAttribute("data-room-text") || "";
      var hit = words.every(function (w) { return text.indexOf(w) !== -1; })
        && active.every(function (s) { return attr(c, s.name) === s.value; })
        && activeM.every(function (s) { return multiValues(c, s.getAttribute("data-room-multi")).indexOf(s.value) !== -1; })
        && activeR.every(function (s) { return inRange(c, s); });
      c.hidden = !hit;
      if (hit) { shown += 1; }
    });
    var filtering = words.length > 0 || active.length > 0 || activeM.length > 0 || activeR.length > 0;
    sections.forEach(function (sec) {
      var list = sec.querySelectorAll(".room__card");
      var any = Array.prototype.some.call(list, function (c) { return !c.hidden; });
      sec.hidden = filtering && !any;
    });
    if (jump) { jump.hidden = filtering || flatOn; }
    if (empty) { empty.hidden = shown > 0; }
    // The nouns are the pack's (data-room-one/-other); nothing here builds a plural.
    var noun = count.getAttribute(total === 1 ? "data-room-one" : "data-room-other");
    count.textContent = filtering ? shown + " of " + total + " " + noun + " match" : total + " " + noun;
    refresh(words.join(" "));
    if (window.roomPager) { window.roomPager.after(); }
    return shown;
  }
  // The query string: text, then every control that is set, then a non-default sort.
  function push(text) {
    if (!(window.history && window.history.replaceState)) { return; }
    var k = controls(), p = new URLSearchParams();
    if (text) { p.set("q", text); }
    k.facets.concat(k.multis, k.ranges).forEach(function (s) { p.set(s.name, s.value); });
    if (sorter && sorter.value && sorter.selectedIndex > 0) { p.set(sorter.name, sorter.value); }
    var qs = p.toString();
    window.history.replaceState(null, "", window.location.pathname + (qs ? "?" + qs : ""));
  }
  function sortKey() { return sorter && flat && ["title", "date-desc", "date-asc"].indexOf(sorter.value) !== -1 ? sorter.value : ""; }
  // Card order for a sort, for room-search.js to order text hits the same way.
  function compare(how) {
    return function (a, b) {
      if (how === "title") { return titleKey(a).localeCompare(titleKey(b)); }
      var da = a.getAttribute("data-room-date") || "", db = b.getAttribute("data-room-date") || "";
      if (!da && !db) { return 0; }
      if (!da) { return 1; }
      if (!db) { return -1; }
      return how === "date-asc" ? da.localeCompare(db) : db.localeCompare(da);
    };
  }
  window.roomCards = {
    apply: filterCards, push: push, sortKey: sortKey, compare: compare, controls: controls,
    inRange: inRange, passes: function (c) { return passes(c); }, refresh: refresh, all: finder.querySelectorAll("[data-room-facet],[data-room-multi],[data-room-range],[data-room-sort]")
  };
  if (searchFinder) { return; }
  finder.hidden = false;
  q.value = params.get("q") || params.get("rr_search") || "";
  function run(pushIt) {
    filterCards(q.value.toLowerCase().split(/\s+/).filter(Boolean));
    if (pushIt) { push(q.value.trim()); }
  }
  var timer = null;
  q.addEventListener("input", function () { window.clearTimeout(timer); timer = window.setTimeout(function () { run(true); }, 150); });
  facets.concat(multis, ranges, sorter ? [sorter] : []).forEach(function (s) { s.addEventListener("change", function () { run(true); }); });
  form.addEventListener("submit", function (e) { e.preventDefault(); run(true); });
  form.addEventListener("reset", function () { window.setTimeout(function () { run(true); q.focus(); }, 0); });
  run(false);
}());
