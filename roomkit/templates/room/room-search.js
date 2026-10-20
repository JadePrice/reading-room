(function () {
  "use strict";
  // The index's finder when the pack turns corpus search on (search.py). Text is
  // searched in the room's own Pagefind index (pagefind/, shipped with the room;
  // nothing is fetched from a server). Facet selects narrow both the text results
  // and, with no text, the cards on the page. Suggestions come from the same
  // index: a WAI-ARIA combobox over a grouped listbox, in the site's own groups and
  // words when the page carries them (manifest site.index.suggest), else one group
  // per facet select.
  var root = document.getElementById("room-content");
  if (!root) { return; }
  var finder = root.querySelector("[data-room-search]");
  if (!finder) { return; }
  var form = finder.querySelector("form");
  var q = document.getElementById("room-q");
  var listbox = document.getElementById("room-suggest");
  var facets = Array.prototype.slice.call(finder.querySelectorAll("[data-room-facet]"));
  var cards = Array.prototype.slice.call(root.querySelectorAll(".room__card"));
  var sections = Array.prototype.slice.call(root.querySelectorAll("[data-room-section]"));
  var count = finder.querySelector("[data-room-count]");
  var empty = root.querySelector("[data-room-empty]");
  var jump = root.querySelector("[data-room-jump]");
  var results = root.querySelector("[data-room-results]");
  var list = root.querySelector("[data-room-results-list]");
  var more = root.querySelector("[data-room-more]");
  var BASE = finder.getAttribute("data-room-pagefind");
  var RECENT = finder.getAttribute("data-room-recent-key");
  var PAGE = 20, TOP = 5, PER_FACET = 4, KEEP = 5;
  var SITE = null;
  try { SITE = JSON.parse((finder.querySelector("[data-room-suggest]") || {}).textContent || "null"); } catch (e) {}
  var total = cards.length;
  var byUrl = {};
  cards.forEach(function (c) {
    var a = c.querySelector(".room__card-title a");
    if (a) { byUrl[a.getAttribute("href")] = c; }
  });
  finder.hidden = false;

  // --- the index, loaded once, on first use --------------------------------------
  var loading = null;
  function engine() {
    if (!loading) {
      loading = import(BASE + "pagefind.js").then(function (pf) {
        // Pagefind's URLs are /<slug>/; the room is served at BASE's parent.
        return Promise.resolve(pf.options({ baseUrl: BASE.replace(/pagefind\/$/, ""), excerptLength: 24 }))
          .then(function () { return pf.init ? pf.init() : null; })
          .then(function () { return pf; });
      }).catch(function () { return null; });
    }
    return loading;
  }

  function noun() { return count.getAttribute(total === 1 ? "data-room-one" : "data-room-other"); }
  function attr(card, name) {
    return name === "group" ? card.getAttribute("data-room-group") : card.getAttribute("data-room-f-" + name);
  }
  function activeFacets() { return facets.filter(function (s) { return s.value; }); }

  // --- no text (or no index): filter the cards already on the page ----------------
  function showCards(active, words) {
    results.hidden = true;
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
      var any = Array.prototype.some.call(sec.querySelectorAll(".room__card"), function (c) { return !c.hidden; });
      sec.hidden = filtering && !any;
    });
    if (jump) { jump.hidden = filtering; }
    if (empty) { empty.hidden = shown > 0; }
    count.textContent = filtering ? shown + " of " + total + " " + noun() + " match" : total + " " + noun();
  }

  // --- text: ranked results from the index -----------------------------------------
  function decode(s) {
    return new DOMParser().parseFromString("<!doctype html><body>" + s, "text/html").body.textContent;
  }
  // Pagefind's excerpts mark hits with <mark>; everything else is set as text.
  function excerpt(el, html) {
    String(html || "").split(/<mark>|<\/mark>/).forEach(function (part, i) {
      var t = decode(part);
      if (!t) { return; }
      if (i % 2) { var m = document.createElement("mark"); m.textContent = t; el.appendChild(m); }
      else { el.appendChild(document.createTextNode(t)); }
    });
  }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text) { e.textContent = text; }
    return e;
  }
  function resultItem(d) {
    var li = el("li", "room__result");
    var h = el("h3", "room__result-title");
    var a = el("a", "", (d.meta && d.meta.title) || d.url);
    a.href = d.url;
    h.appendChild(a);
    li.appendChild(h);
    var card = byUrl[d.url];
    var bits = card ? [".room__card-date", ".room__card-meta"].map(function (sel) {
      var x = card.querySelector(sel);
      return x ? x.textContent.trim() : "";
    }).filter(Boolean) : [];
    if (bits.length) { li.appendChild(el("p", "room__result-meta", bits.join(" · "))); }
    var ex = el("p", "room__result-excerpt");
    excerpt(ex, d.excerpt);
    li.appendChild(ex);
    var pages = (d.sub_results || []).filter(function (s) { return /#page-\d+$/.test(s.url); }).slice(0, 3);
    if (pages.length) {
      var ul = el("ul", "room__result-pages");
      pages.forEach(function (s) {
        var pli = el("li");
        var pa = el("a", "", "Page " + s.url.replace(/^.*#page-/, ""));
        pa.href = s.url;
        pli.appendChild(pa);
        var pe = el("span", "room__result-page-ex");
        excerpt(pe, s.excerpt);
        pli.appendChild(document.createTextNode(" "));
        pli.appendChild(pe);
        ul.appendChild(pli);
      });
      li.appendChild(ul);
    }
    return li;
  }

  var token = 0, hits = [], drawn = 0;
  function drawMore(my) {
    var next = hits.slice(drawn, drawn + PAGE);
    drawn += next.length;
    more.hidden = drawn >= hits.length;
    return Promise.all(next.map(function (r) { return r.data(); })).then(function (ds) {
      if (my !== token) { return; }
      ds.forEach(function (d) { list.appendChild(resultItem(d)); });
    });
  }
  function showResults(found, my) {
    hits = found; drawn = 0;
    list.textContent = "";
    sections.forEach(function (sec) { sec.hidden = true; });
    if (jump) { jump.hidden = true; }
    results.hidden = !found.length;
    if (empty) { empty.hidden = found.length > 0; }
    count.textContent = found.length + " of " + total + " " + noun() + " match";
    return drawMore(my);
  }

  function run(push) {
    var text = q.value.trim();
    var active = activeFacets();
    var my = ++token;
    if (push && window.history && window.history.replaceState) {
      var p = new URLSearchParams();
      if (text) { p.set("q", text); }
      active.forEach(function (s) { p.set(s.name, s.value); });
      var qs = p.toString();
      window.history.replaceState(null, "", window.location.pathname + (qs ? "?" + qs : ""));
    }
    if (!text) { showCards(active, []); return; }
    engine().then(function (pf) {
      if (my !== token) { return; }
      if (!pf) { showCards(active, text.toLowerCase().split(/\s+/).filter(Boolean)); return; }
      var filters = {};
      active.forEach(function (s) { filters[s.name] = s.value; });
      return pf.search(text, { filters: filters }).then(function (res) {
        if (my === token) { return showResults((res && res.results) || [], my); }
      });
    });
  }

  // --- suggestions: a combobox over a grouped listbox ------------------------------
  var options = [], current = -1, sugToken = 0, dismissed = false;

  function recent() {
    try { return JSON.parse(window.localStorage.getItem(RECENT) || "[]").filter(function (s) { return typeof s === "string"; }); }
    catch (e) { return []; }
  }
  function remember(text) {
    text = (text || "").trim();
    if (!text) { return; }
    var keep = [text].concat(recent().filter(function (s) { return s !== text; })).slice(0, KEEP);
    try { window.localStorage.setItem(RECENT, JSON.stringify(keep)); } catch (e) {}
  }

  function close() {
    sugToken += 1;
    listbox.hidden = true;
    listbox.textContent = "";
    options = []; current = -1;
    q.setAttribute("aria-expanded", "false");
    q.removeAttribute("aria-activedescendant");
  }
  function setActive(i) {
    if (current >= 0 && options[current]) { options[current].node.setAttribute("aria-selected", "false"); }
    current = i;
    if (i < 0 || !options[i]) { q.removeAttribute("aria-activedescendant"); return; }
    options[i].node.setAttribute("aria-selected", "true");
    q.setAttribute("aria-activedescendant", options[i].node.id);
    if (options[i].node.scrollIntoView) { options[i].node.scrollIntoView({ block: "nearest" }); }
  }
  function choose(o) {
    dismissed = true;
    close();
    if (o.kind === "doc") { remember(q.value); window.location.href = o.url; return; }
    if (o.kind === "facet") { o.select.value = o.value; q.value = ""; }
    if (o.kind === "query") { q.value = o.value; remember(o.value); }
    run(true);
  }
  function draw(groups, first) {
    listbox.textContent = "";
    options = []; current = -1;
    groups.filter(function (g) { return g.items.length; }).forEach(function (g, gi) {
      var box = el("div", "room__suggest-group");
      box.setAttribute("role", "group");
      var h = el("div", "room__suggest-h", g.label);
      h.id = "room-suggest-g" + gi;
      h.setAttribute("role", "presentation");
      box.setAttribute("aria-labelledby", h.id);
      box.appendChild(h);
      g.items.forEach(function (it) {
        var o = el("div", "room__suggest-opt", it.label);
        o.id = "room-suggest-o" + options.length;
        o.setAttribute("role", "option");
        o.setAttribute("aria-selected", "false");
        if (it.note) { o.appendChild(el("span", "room__suggest-note", it.note)); }
        it.node = o;
        o.addEventListener("mousedown", function (e) { e.preventDefault(); });
        o.addEventListener("click", function () { choose(it); });
        options.push(it);
        box.appendChild(o);
      });
      listbox.appendChild(box);
    });
    if (!options.length) { close(); return; }
    listbox.hidden = false;
    q.setAttribute("aria-expanded", "true");
    q.removeAttribute("aria-activedescendant");
    if (first) { setActive(0); }
  }
  function docs(res, label, n) {
    return Promise.all(((res && res.results) || []).slice(0, n || TOP).map(function (r) { return r.data(); }))
      .then(function (ds) {
        return { label: label, items: ds.map(function (d) { return { kind: "doc", url: d.url, label: (d.meta && d.meta.title) || d.url }; }) };
      });
  }
  function facetGroups(text, counts) {
    var lc = text.toLowerCase();
    return facets.map(function (s) {
      var label = (finder.querySelector('label[for="' + s.id + '"]') || {}).textContent || s.name;
      var vals = Array.prototype.slice.call(s.options).map(function (o) { return o.value; })
        .filter(function (v) { return v && v.toLowerCase().indexOf(lc) !== -1; }).slice(0, PER_FACET);
      return { label: label, items: vals.map(function (v) {
        var n = counts && counts[s.name] ? counts[s.name][v] : null;
        return { kind: "facet", select: s, value: v, label: v,
                 note: typeof n === "number" ? " (" + n + " " + (n === 1 ? count.getAttribute("data-room-one") : count.getAttribute("data-room-other")) + ")" : "" };
      }) };
    });
  }
  // dd's deflock-reading-room.js normalize(), scoreDoc() and getRankedDocs(), ported
  // unchanged, so a site panel matches and ranks as the site's own panel does.
  function norm(v) {
    return String(v || "").toLowerCase().replace(/&/g, " and ").replace(/[\u2019']/g, "")
      .replace(/[^a-z0-9]+/g, " ").replace(/\s+/g, " ").trim();
  }
  var RANKED = SITE && SITE.rank ? SITE.rank.map(function (r) {
    return { r: r, title: norm(r.title), agency: norm(r.agency), summary: norm(r.summary), type: norm(r.doc_type),
             year: norm(r.year), aliases: norm(r.aliases.join(" ")),
             all: norm([r.title, r.agency, r.summary, r.doc_type, r.year].concat(r.aliases, r.vendors).join(" ")) };
  }) : null;
  function score(d, query) {
    var s = 0;
    if (!query) { return s; }
    if (d.title === query) { s += 120; }
    if (d.title.indexOf(query) === 0) { s += 80; } else if (d.title.indexOf(query) !== -1) { s += 52; }
    if (d.agency === query) { s += 70; }
    if (d.agency.indexOf(query) === 0) { s += 44; } else if (d.agency.indexOf(query) !== -1) { s += 28; }
    if (d.type && d.type === query) { s += 30; } else if (d.type && d.type.indexOf(query) !== -1) { s += 18; }
    if (d.aliases.indexOf(query) !== -1) { s += 24; }
    if (d.summary.indexOf(query) !== -1) { s += 12; }
    if (d.year === query) { s += 10; }
    if (s > 0 && d.all.indexOf(query) !== -1) { s += 4; }
    if (s > 0 && d.r.date) { s += Math.max(0, 8 - Math.min(8, new Date().getFullYear() - Number((d.r.year || "").slice(0, 4) || 0))); }
    return s;
  }
  function stamp(v) { var t = v ? Date.parse(v) : 0; return isFinite(t) ? t : 0; }
  function rankDocs(text, label, n) {
    var query = norm(text);
    var hits = RANKED.map(function (d) { return { d: d, s: score(d, query) }; })
      .filter(function (e) { return e.s > 0; })
      .sort(function (a, b) {
        if (a.s === b.s) { return (stamp(b.d.r.date) - stamp(a.d.r.date)) || String(a.d.r.title).localeCompare(String(b.d.r.title)); }
        return b.s - a.s;
      });
    return { label: label, items: hits.slice(0, n).map(function (e) { return { kind: "doc", url: e.d.r.url, label: e.d.r.label }; }) };
  }
  function siteGroups(text) {
    var lc = RANKED ? norm(text) : text.toLowerCase();
    return SITE.groups.map(function (g) {
      var n = text ? g.typing : g.empty;
      var items = text ? g.items.filter(function (it) {
        var hay = it.label + " " + it.query;
        return (RANKED ? norm(hay) : hay.toLowerCase()).indexOf(lc) !== -1;
      }) : g.items;
      return { label: g.label, items: items.slice(0, n).map(function (it) {
        return { kind: "query", value: it.query, label: it.label,
                 note: typeof it.count === "number" ? " (" + it.count + " " + count.getAttribute(it.count === 1 ? "data-room-one" : "data-room-other") + ")" : "" };
      }) };
    });
  }
  function siteJobs(pf, text) {
    var L = SITE.labels, jobs = [];
    if (!text) {
      jobs.push(Promise.resolve({ label: L.recent_docs, items: SITE.recent_docs.map(function (d) { return { kind: "doc", url: d.url, label: d.label }; }) }));
      jobs.push(Promise.resolve({ label: L.recent_searches, items: recent().map(function (s) { return { kind: "query", value: s, label: s }; }) }));
    } else if (RANKED) {
      jobs.push(Promise.resolve(rankDocs(text, L.top, SITE.top)));
    } else if (pf) {
      jobs.push(pf.search(text).then(function (r) { return docs(r, L.top, SITE.top); }));
    }
    jobs.push(Promise.resolve(siteGroups(text)));
    return jobs;
  }
  function suggest(first) {
    var text = q.value.trim(), my = ++sugToken;
    engine().then(function (pf) {
      if (my !== sugToken) { return; }
      var jobs;
      if (SITE) {
        jobs = siteJobs(pf, text);
      } else if (!text) {
        jobs = [Promise.resolve({ label: "Recent searches", items: recent().map(function (s) { return { kind: "query", value: s, label: s }; }) })];
        if (pf) { jobs.push(pf.search(null, { sort: { date: "desc" } }).then(function (r) { return docs(r, "Recent documents"); })); }
      } else {
        jobs = pf ? [pf.search(text).then(function (r) { return docs(r, "Top matches"); })] : [];
        jobs.push((pf ? pf.filters() : Promise.resolve(null)).then(function (c) { return facetGroups(text, c); }));
      }
      return Promise.all(jobs).then(function (gs) {
        if (my !== sugToken || document.activeElement !== q) { return; }
        draw([].concat.apply([], gs), first);
      });
    });
  }

  // --- wiring -------------------------------------------------------------------------
  var timer = null;
  q.addEventListener("focus", function () { engine(); });
  q.addEventListener("input", function () {
    window.clearTimeout(timer);
    dismissed = false;
    timer = window.setTimeout(function () { run(true); if (!dismissed) { suggest(false); } }, 150);
  });
  q.addEventListener("click", function () { if (listbox.hidden && !q.value.trim()) { suggest(false); } });
  q.addEventListener("blur", function () { window.setTimeout(function () { if (document.activeElement !== q) { close(); } }, 150); });
  q.addEventListener("keydown", function (e) {
    var open = !listbox.hidden && options.length;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) { suggest(true); return; }
      var n = options.length;
      setActive(e.key === "ArrowDown" ? (current + 1) % n : (current <= 0 ? n - 1 : current - 1));
    } else if (e.key === "Enter" && open && current >= 0) {
      e.preventDefault();
      choose(options[current]);
    } else if (e.key === "Escape") {
      dismissed = true;
      if (open) { e.preventDefault(); close(); }
    } else if (e.key === "Tab") {
      close();
    }
  });
  facets.forEach(function (s) { s.addEventListener("change", function () { run(true); }); });
  more.addEventListener("click", function () { drawMore(token); });
  form.addEventListener("submit", function (e) { e.preventDefault(); dismissed = true; close(); remember(q.value); run(true); });
  form.addEventListener("reset", function () { window.setTimeout(function () { close(); run(true); q.focus(); }, 0); });

  var params = new URLSearchParams(window.location.search);
  q.value = params.get("q") || params.get("rr_search") || "";
  facets.forEach(function (s) { var v = params.get(s.name); if (v) { s.value = v; } });
  run(false);
}());
