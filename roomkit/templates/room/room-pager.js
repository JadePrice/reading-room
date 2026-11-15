(function () {
  "use strict";
  // layout.page_size: the index and the facet pages show SIZE records at a time, with
  // numbered Previous / Next controls under the list, so a long room is pages, not one
  // endless scroll. It pages whatever the filters and the sort leave showing (room.js
  // calls window.roomPager.after() each time it filters), so a filter always starts on
  // page 1 of its own matches. The page is in the URL (?page=3): Back and shared links
  // land on it. Search results (room-search.js) keep their own "Show more" and hide the
  // pager. Without JavaScript every record shows, as before.
  var SIZE = __PAGE_SIZE__;
  var root = document.getElementById("room-content");
  if (!root || !(SIZE > 0)) { return; }
  var slice = function (x) { return Array.prototype.slice.call(x); };
  var groupsEl = root.querySelector(".room__groups");
  var flat = root.querySelector("[data-room-flat]");
  var anchor = flat || groupsEl || root.querySelector(".room__cards");
  if (!anchor) { return; }
  var sections = slice(root.querySelectorAll("[data-room-section]"));
  var leads = slice(root.querySelectorAll("[data-room-lead]"));
  var top = root.querySelector("[data-room-count]") || root.querySelector("h1");

  var nav = document.createElement("nav");
  nav.className = "room__pager";
  nav.setAttribute("aria-label", "Pages");
  nav.hidden = true;
  var status = document.createElement("p");
  status.className = "room__pager-status";
  var list = document.createElement("ul");
  list.className = "room__pager-list";
  nav.appendChild(status);
  nav.appendChild(list);
  anchor.parentNode.insertBefore(nav, anchor.nextSibling);

  var pool = [], page = 1, secBase = [], leadBase = [], sig = null;
  function box() {
    if (flat && !flat.hidden) { return flat; }
    return groupsEl || root.querySelector(".room__cards");
  }
  function pages() { return Math.max(1, Math.ceil(pool.length / SIZE)); }
  function fromURL() {
    var n = parseInt(new URLSearchParams(window.location.search).get("page"), 10);
    return n > 0 ? n : 1;
  }
  function toURL(n, push) {
    if (!(window.history && window.history.pushState)) { return; }
    var p = new URLSearchParams(window.location.search);
    if (n > 1) { p.set("page", String(n)); } else { p.delete("page"); }
    var qs = p.toString();
    var url = window.location.pathname + (qs ? "?" + qs : "");
    if (push) { window.history.pushState({ roomPage: n }, "", url); } else { window.history.replaceState(window.history.state, "", url); }
  }
  // The page numbers to draw: the first, the last, and the current one with its
  // neighbors; a gap (null) where numbers are left out.
  function numbers(n, last) {
    var want = [1, last, n - 1, n, n + 1].filter(function (x) { return x >= 1 && x <= last; });
    want = want.filter(function (x, i) { return want.indexOf(x) === i; }).sort(function (a, b) { return a - b; });
    var out = [];
    want.forEach(function (x, i) {
      if (i && x - want[i - 1] > 1) { out.push(x - want[i - 1] === 2 ? x - 1 : null); }
      out.push(x);
    });
    return out;
  }
  function button(label, n, extra) {
    var li = document.createElement("li"), b = document.createElement("button");
    b.type = "button";
    b.className = "room__pager-btn" + (extra ? " " + extra : "");
    b.textContent = label;
    b.setAttribute("data-room-page", String(n));
    li.appendChild(b);
    list.appendChild(li);
    return b;
  }
  function draw() {
    var last = pages();
    nav.hidden = pool.length <= SIZE;
    if (nav.hidden) { return; }
    var lo = (page - 1) * SIZE + 1, hi = Math.min(page * SIZE, pool.length);
    status.textContent = "Showing " + lo + " to " + hi + " of " + pool.length + ". Page " + page + " of " + last + ".";
    list.textContent = "";
    var prev = button("Previous", page - 1, "room__pager-btn--step");
    prev.disabled = page === 1;
    numbers(page, last).forEach(function (x) {
      if (x === null) {
        var li = document.createElement("li");
        li.className = "room__pager-gap";
        li.setAttribute("aria-hidden", "true");
        li.textContent = "…";
        list.appendChild(li);
        return;
      }
      var b = button(String(x), x);
      b.setAttribute("aria-label", "Page " + x);
      if (x === page) { b.setAttribute("aria-current", "page"); }
    });
    var next = button("Next", page + 1, "room__pager-btn--step");
    next.disabled = page === last;
  }
  function show(n) {
    page = Math.min(Math.max(1, n), pages());
    var lo = (page - 1) * SIZE, hi = lo + SIZE;
    pool.forEach(function (c, i) {
      var off = i < lo || i >= hi;
      c.hidden = off;
      if (off) { c.setAttribute("data-room-off", ""); } else { c.removeAttribute("data-room-off"); }
    });
    sections.forEach(function (s, i) {
      var cs = s.querySelectorAll(".room__card");
      s.hidden = secBase[i] || (cs.length > 0 && !slice(cs).some(function (c) { return !c.hidden; }));
    });
    // The lists above the records (newest, collections) belong to page 1.
    leads.forEach(function (l, i) { l.hidden = leadBase[i] || page > 1; });
    draw();
  }
  function go(n) {
    show(n);
    toURL(page, true);
    if (top) {
      if (!top.hasAttribute("tabindex")) { top.setAttribute("tabindex", "-1"); }
      top.focus({ preventScroll: true });
      top.scrollIntoView({ block: "start" });
    }
  }
  // room.js has just filtered or sorted: the cards it left showing are the new pool.
  // The page stays when the pool is the same records in the same order (a re-run with
  // nothing changed, or the first run with ?page= in the URL); otherwise page 1.
  function after() {
    slice(root.querySelectorAll("[data-room-off]")).forEach(function (c) { c.removeAttribute("data-room-off"); });
    secBase = sections.map(function (s) { return s.hidden; });
    leadBase = leads.map(function (l) { return l.hidden; });
    pool = slice(box().querySelectorAll(".room__card")).filter(function (c) {
      if (c.hidden) { return false; }
      var s = c.closest("[data-room-section]");
      return !(s && s.hidden);
    });
    var now = pool.map(function (c) { return c.getAttribute("data-room-i") || ""; }).join(",");
    var keep = sig === null || now === sig;
    sig = now;
    show(keep ? page : 1);
    if (!keep) { toURL(1, false); }
  }
  // Search results replace the list: no pager under them.
  function off() { nav.hidden = true; }
  list.addEventListener("click", function (e) {
    var b = e.target.closest("[data-room-page]");
    if (!b || b.disabled || b.getAttribute("aria-current")) { return; }
    go(parseInt(b.getAttribute("data-room-page"), 10));
  });
  // A jump link (#group) goes to the page that holds the group's first record.
  root.addEventListener("click", function (e) {
    var a = e.target.closest('a[href^="#"]');
    if (!a) { return; }
    var sec = document.getElementById(a.getAttribute("href").slice(1));
    if (!sec || !sec.hasAttribute("data-room-section")) { return; }
    var first = pool.findIndex(function (c) { return sec.contains(c); });
    if (first === -1) { return; }
    var n = Math.floor(first / SIZE) + 1;
    if (n !== page) { show(n); toURL(page, true); }
  }, true);
  window.addEventListener("popstate", function () { show(fromURL()); });
  window.roomPager = { after: after, off: off, show: show, size: SIZE };
  page = fromURL();
  after();
  if (window.location.hash) {
    var sec = document.getElementById(window.location.hash.slice(1));
    var first = sec ? pool.findIndex(function (c) { return sec.contains(c); }) : -1;
    if (first !== -1) { show(Math.floor(first / SIZE) + 1); sec.scrollIntoView(); }
  }
}());
