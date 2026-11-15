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
  // room.js's card engine: filters (facets, vendor, year range) and the flat sort.
  var R = window.roomCards;
  if (!R) { return; }
  var form = finder.querySelector("form");
  var q = document.getElementById("room-q");
  var listbox = document.getElementById("room-suggest");
  var facets = Array.prototype.slice.call(finder.querySelectorAll("[data-room-facet]"));
  var cards = Array.prototype.slice.call(root.querySelectorAll(".room__card"));
  var flat = root.querySelector("[data-room-flat]");
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
  // The site's own reading of a query (manifest site.index.search_terms, site A's
  // SiteA_Search::terms + sanitize_boolean_query): lowercase a-z0-9 words of at least
  // `min` characters, the first `max`. "" when none is left: the site's page then
  // matches its rows' text only. Without the setting, the query as typed.
  var TERMS = (finder.getAttribute("data-room-terms") || "").split(" ").map(Number);
  // Pagefind's ranking weights from the site pack (search_ranking); absent, its defaults.
  var RANKING = null;
  try { RANKING = JSON.parse(finder.getAttribute("data-room-ranking") || "null"); } catch (e) {}
  function pagefindQuery(text) {
    if (!TERMS[0]) { return text; }
    return text.toLowerCase().split(/[^a-z0-9]+/).filter(function (t) { return t.length >= TERMS[0]; })
      .slice(0, TERMS[1]).join(" ");
  }
  window.roomSearchQuery = pagefindQuery;
  // The site's other half (site A, with search_terms): a record whose row text holds the
  // whole query, as typed, is a hit too (site-a-reading-room.js matches(): data-search
  // indexOf(q)). Those come first, in list order, then the word hits in Pagefind's order.
  function cardHit(c) {
    var a = c.querySelector(".room__card-title a");
    var url = a.getAttribute("href");
    return { slug: slugOf(url), data: function () {
      return Promise.resolve({ url: url, meta: { title: a.textContent }, excerpt: "", sub_results: [] });
    } };
  }
  function phraseHits(text, keep) {
    var lc = text.toLowerCase();
    return cards.filter(function (c) { return (c.getAttribute("data-room-text") || "").indexOf(lc) !== -1 && keep(c); })
      .sort(function (a, b) { return parseInt(a.getAttribute("data-room-n") || "0", 10) - parseInt(b.getAttribute("data-room-n") || "0", 10); })
      .map(cardHit);
  }
  var SITE = null;
  try { SITE = JSON.parse((finder.querySelector("[data-room-suggest]") || {}).textContent || "null"); } catch (e) {}
  var total = cards.length;
  var byUrl = {}, bySlug = {};
  function slugOf(u) { return String(u || "").replace(/[?#].*$/, "").replace(/\/+$/, "").split("/").pop(); }
  cards.forEach(function (c) {
    var a = c.querySelector(".room__card-title a");
    if (a) { byUrl[a.getAttribute("href")] = c; bySlug[slugOf(a.getAttribute("href"))] = c; }
  });
  finder.hidden = false;

  // --- the index, loaded once, on first use --------------------------------------
  var loading = null;
  function engine() {
    if (!loading) {
      loading = import(BASE + "pagefind.js").then(function (pf) {
        // Pagefind's URLs are /<slug>/; the room is served at BASE's parent.
        var opts = { baseUrl: BASE.replace(/pagefind\/$/, ""), excerptLength: 24 };
        if (RANKING) { opts.ranking = RANKING; }
        return Promise.resolve(pf.options(opts))
          .then(function () { return pf.init ? pf.init() : null; })
          .then(function () { return pf; });
      }).catch(function () { return null; });
    }
    return loading;
  }

  function noun() { return count.getAttribute(total === 1 ? "data-room-one" : "data-room-other"); }
  // Pagefind filters for the controls that are set: a facet or vendor is one value; a
  // year range is every year option inside it (Pagefind has no range filter).
  function pagefindFilters() {
    var k = R.controls(), out = {};
    k.facets.forEach(function (s) { out[s.name] = s.value; });
    k.multis.forEach(function (s) { out[s.getAttribute("data-room-multi")] = s.value; });
    var byName = {};
    k.ranges.forEach(function (s) { (byName[s.getAttribute("data-room-range")] = byName[s.getAttribute("data-room-range")] || []).push(s); });
    Object.keys(byName).forEach(function (name) {
      var opts = Array.prototype.slice.call(byName[name][0].options).map(function (o) { return o.value; }).filter(Boolean);
      var years = opts.filter(function (v) {
        return byName[name].every(function (s) {
          var y = parseInt(v, 10), b = parseInt(s.value, 10);
          return s.getAttribute("data-room-bound") === "from" ? y >= b : y <= b;
        });
      });
      out[name] = { any: years.length ? years : ["-"] };
    });
    return out;
  }

  // --- no text (or no index): filter the cards already on the page ----------------
  function showCards(words) {
    results.hidden = true;
    R.apply(words);
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
    var actions = el("div", "room__result-actions");
    var citeBtn = el("button", "room__btn-cite", "Copy Citation");
    citeBtn.type = "button";
    citeBtn.setAttribute("aria-label", "Copy citation for " + ((d.meta && d.meta.title) || "document"));
    citeBtn.addEventListener("click", function (evt) {
      evt.preventDefault();
      evt.stopPropagation();
      var title = (d.meta && d.meta.title) || d.url;
      var dateEl = card ? card.querySelector(".room__card-date") : null;
      var date = dateEl ? dateEl.textContent.trim() : "";
      var citeText = title + (date ? " (" + date + ")" : "") + ". " + window.location.origin + (d.url.charAt(0) === "/" ? d.url : "/" + d.url);
      function show(label) {
        citeBtn.textContent = label;
        citeBtn.setAttribute("data-copied", "true");
        setTimeout(function () {
          citeBtn.textContent = "Copy Citation";
          citeBtn.removeAttribute("data-copied");
        }, 2000);
      }
      function failed() { show("Copy failed"); }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(citeText).then(function () { show("Copied!"); }, failed);
      } else {
        failed();
      }
    });
    actions.appendChild(citeBtn);

    var dlLink = card ? (card.querySelector(".room__card-dl") || card.querySelector("a[download]")) : null;
    var openLink = el("a", "room__btn-open", dlLink ? "Download PDF" : "Open Document");
    openLink.href = dlLink ? dlLink.getAttribute("href") : d.url;
    if (dlLink) { openLink.setAttribute("download", ""); }
    actions.appendChild(openLink);

    li.appendChild(actions);
    return li;
  }

  var token = 0, hits = [], drawn = 0;
  // Each page waits for the one before it: a page of whole-query hits (cards, no fetch)
  // resolves at once, and a quick second click must not land it ahead of Pagefind's.
  var drawing = Promise.resolve();
  function drawMore(my) {
    var next = hits.slice(drawn, drawn + PAGE);
    drawn += next.length;
    more.hidden = drawn >= hits.length;
    var data = Promise.all(next.map(function (r) { return r.data(); }));
    drawing = drawing.then(function () { return data; }).then(function (ds) {
      if (my !== token) { return; }
      ds.forEach(function (d) { list.appendChild(resultItem(d)); });
    });
    return drawing;
  }
  function showResults(found, my) {
    hits = found; drawn = 0; drawing = Promise.resolve();
    list.textContent = "";
    sections.forEach(function (sec) { sec.hidden = true; });
    if (flat) { flat.hidden = true; }
    if (jump) { jump.hidden = true; }
    results.hidden = !found.length;
    if (empty) { empty.hidden = found.length > 0; }
    count.textContent = found.length + " of " + total + " " + noun() + " match";
    if (window.roomPager) { window.roomPager.off(); }
    return drawMore(my);
  }

  // A sort other than default orders text hits as it orders cards (room.js compare), by
  // the record each hit is: Pagefind result id -> URL from result-urls.json, then the card.
  var urlsLoading = null;
  function resultUrls() {
    if (!urlsLoading) {
      urlsLoading = window.fetch(BASE + "result-urls.json").then(function (r) { return r.ok ? r.json() : {}; })
        .catch(function () { return {}; });
    }
    return urlsLoading;
  }
  function sorted(found) {
    var how = R.sortKey();
    if (!how || !found.length) { return Promise.resolve(found); }
    return resultUrls().then(function (urls) {
      var card = function (r) { return bySlug[r.slug || slugOf(urls[r.id])]; };
      if (!found.every(card)) { return found; }
      var cmp = R.compare(how);
      var n = function (r) { return parseInt(card(r).getAttribute("data-room-n"), 10); };
      return found.slice().sort(function (a, b) { return n(a) - n(b); })
        .sort(function (a, b) { return cmp(card(a), card(b)); });
    });
  }

  // Pagefind's hits for the words, and with search_terms the cards holding the whole
  // query first (each once). `keep` is the card filter the controls set.
  function textHits(pf, text, words, filters, keep) {
    return pf.search(words, { filters: filters }).then(function (res) {
      var found = (res && res.results) || [];
      if (!TERMS[0]) { return found; }
      var first = phraseHits(text, keep);
      if (!first.length) { return found; }
      return resultUrls().then(function (urls) {
        var seen = {};
        first.forEach(function (h) { seen[h.slug] = 1; });
        return first.concat(found.filter(function (r) { return !seen[slugOf(urls[r.id])]; }));
      });
    });
  }
  // What a search for `text` lists, unfiltered, as URLs: for search_parity.py.
  window.roomSearchHits = function (text) {
    return engine().then(function (pf) {
      var words = pagefindQuery(text);
      if (!pf || !words) { return []; }
      return textHits(pf, text, words, {}, function () { return true; })
        .then(function (rs) { return Promise.all(rs.map(function (r) { return r.data(); })); })
        .then(function (ds) { return ds.map(function (d) { return d.url; }); });
    });
  };

  function run(push) {
    var text = q.value.trim();
    var my = ++token;
    if (push) { R.push(text); }
    if (R.refresh) { R.refresh(text); }
    if (!text) { showCards([]); return; }
    engine().then(function (pf) {
      if (my !== token) { return; }
      if (!pf) { showCards(text.toLowerCase().split(/\s+/).filter(Boolean)); return; }
      var words = pagefindQuery(text);
      if (!words) { showCards([text.toLowerCase()]); return; }
      return textHits(pf, text, words, pagefindFilters(), R.passes).then(sorted).then(function (found) {
        if (my === token) { return showResults(found, my); }
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
    if (o.kind === "go") { window.location.href = o.url; return; }
    if (o.kind === "fill") { q.value = o.value; }
    if (o.kind === "facet") { o.select.value = o.value; q.value = ""; }
    if (o.kind === "query") { q.value = o.value; remember(o.value); }
    run(true);
  }
  function draw(groups, first) {
    listbox.textContent = "";
    options = []; current = -1;
    groups.filter(function (g) { return g.items.length; }).forEach(function (g, gi) {
      var box = el("div", "room__suggest-group");
      if (g.label) {
        box.setAttribute("role", "group");
        var h = el("div", "room__suggest-h", g.label);
        h.id = "room-suggest-g" + gi;
        h.setAttribute("role", "presentation");
        box.setAttribute("aria-labelledby", h.id);
        box.appendChild(h);
      } else {
        box.setAttribute("role", "presentation");
      }
      g.items.forEach(function (it) {
        var o = el("div", "room__suggest-opt", it.label);
        o.id = "room-suggest-o" + options.length;
        o.setAttribute("role", "option");
        o.setAttribute("aria-selected", "false");
        if (it.note) { o.appendChild(el("span", "room__suggest-note", it.note)); }
        if (it.url) { o.setAttribute("data-room-url", it.url); }
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
  // site B's site-b-reading-room.js normalize(), scoreDoc() and getRankedDocs(), ported
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
        var hay = it.label + " " + (it.facet ? it.value : it.query);
        return (RANKED ? norm(hay) : hay.toLowerCase()).indexOf(lc) !== -1;
      }) : g.items;
      return { label: g.label, items: items.slice(0, n).map(function (it) {
        var note = typeof it.count === "number" ? " (" + it.count + " " + count.getAttribute(it.count === 1 ? "data-room-one" : "data-room-other") + ")" : "";
        // A facet item sets that filter, as the finder's own facet suggestions do.
        var sel = it.facet ? facets.filter(function (s) { return s.getAttribute("data-room-facet") === it.facet; })[0] : null;
        if (it.facet) { return sel ? { kind: "facet", select: sel, value: it.value, label: it.label, note: note } : null; }
        return { kind: "query", value: it.query, label: it.label, note: note };
      }).filter(Boolean) };
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
  // A flat list (site.index.suggest style "list", site A), ported from site-a-reading-room:
  // localSuggestions() (site-a-reading-room.js) over the documents and their collections in
  // list order; SiteA_Suggest::build() (class-site-a-suggest.php), the ranking the site's
  // /suggest endpoint answers with; and site-a-suggest-combobox.js's dedupeMerge() and
  // defaultRenderLabel(). The site's local titles are the row's text, badge included; the
  // room's are the title (finder_parity.py's suggest check says so).
  var LIST = SITE && SITE.style === "list" ? SITE : null;
  var pool = [];
  if (LIST) {
    (function () {
      var seen = {};
      function add(item) {
        var key = item.type + "|" + item.label.toLowerCase();
        if (item.label && !seen[key]) { seen[key] = 1; pool.push(item); }
      }
      LIST.docs.forEach(function (d) {
        add({ type: "document", label: d[0] });
        var g = LIST.groups[d[1]];
        if (g && g.label && g.url) { add({ type: "collection", label: g.label, url: g.url }); }
      });
    })();
  }
  function localSuggestions(v) {
    v = (v || "").toLowerCase();
    if (!v) { return []; }
    return pool.filter(function (item) { return item.label.toLowerCase().indexOf(v) !== -1; }).slice(0, LIST.local);
  }
  // 0 exact, 1 prefix, 2 contains, null none (match_rank).
  function matchRank(hay, needle) {
    if (!needle || !hay) { return null; }
    var h = hay.toLowerCase(), n = needle.toLowerCase();
    if (h === n) { return 0; }
    if (h.indexOf(n) === 0) { return 1; }
    if (h.indexOf(n) !== -1) { return 2; }
    return null;
  }
  // strcasecmp: ASCII letters folded, then byte order.
  function caseCmp(a, b) {
    var fold = function (x) { return x.replace(/[A-Z]/g, function (c) { return c.toLowerCase(); }); };
    a = fold(a); b = fold(b);
    return a < b ? -1 : (a > b ? 1 : 0);
  }
  function byRank(a, b) {
    if (a.rank !== b.rank) { return a.rank - b.rank; }
    var ac = a.count || 0, bc = b.count || 0;
    if (ac !== bc) { return bc - ac; }
    return caseCmp(a.label, b.label);
  }
  function build(text) {
    var C = LIST.caps;
    function bucket(rows, type, b, cap) {
      return rows.map(function (r) {
        var rank = matchRank(r.label, text);
        return rank === null ? null : { rank: rank, bucket: b, type: type || r.type, label: r.label, url: r.url,
                                        count: typeof r.count === "number" ? r.count : null };
      }).filter(Boolean).sort(byRank).slice(0, cap);
    }
    var docs = LIST.docs.map(function (d) { return { label: d[0] }; });
    var merged = bucket(LIST.entities, "", 0, C.entity)
      .concat(bucket(LIST.collections, "collection", 1, C.collection), bucket(docs, "document", 2, C.document));
    merged.sort(function (a, b) {
      if (a.rank !== b.rank) { return a.rank - b.rank; }
      if (a.bucket !== b.bucket) { return a.bucket - b.bucket; }
      return byRank(a, b);
    });
    return merged.slice(0, C.total);
  }
  function listGroup(text) {
    if (!text) { return { label: "", items: [] }; }
    var local = localSuggestions(text), remote = text.length >= LIST.min ? build(text) : [];
    var seen = {}, out = [];
    local.concat(remote).forEach(function (item) {
      var key = item.type + "|" + item.label.toLowerCase();
      if (seen[key]) { return; }
      seen[key] = 1;
      out.push(item);
    });
    return { label: "", items: out.slice(0, LIST.caps.total).map(function (item) {
      var label = (LIST.prefix[item.type] || "") + item.label +
        (typeof item.count === "number" ? LIST.count.replace("{n}", item.count) : "");
      // A document filters the list to its title, as the site's box does; the rest open their page.
      return item.type === "document" ? { kind: "fill", value: item.label, label: label }
                                      : { kind: "go", url: item.url, label: label };
    }) };
  }

  function suggest(first) {
    var text = q.value.trim(), my = ++sugToken;
    if (LIST) {
      var g = listGroup(text);
      if (document.activeElement === q) { draw([g], first); }
      return;
    }
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
  Array.prototype.forEach.call(R.all, function (s) { s.addEventListener("change", function () { run(true); }); });
  more.addEventListener("click", function () { drawMore(token); });
  form.addEventListener("submit", function (e) { e.preventDefault(); dismissed = true; close(); remember(q.value); run(true); });
  form.addEventListener("reset", function () { window.setTimeout(function () { close(); run(true); q.focus(); }, 0); });

  // The site's empty state offers a few searches (site.index.suggest no_results).
  if (LIST && empty) {
    var nr = LIST.no_results;
    empty.appendChild(document.createTextNode(" " + nr.lead + " "));
    nr.words.forEach(function (w, i) {
      if (i) { empty.appendChild(document.createTextNode(i === nr.words.length - 1 ? (nr.words.length > 2 ? ", " : " ") + nr.or + " " : ", ")); }
      var a = el("a", "", w);
      a.href = "?q=" + encodeURIComponent(w);
      a.addEventListener("click", function (e) { e.preventDefault(); q.value = w; remember(w); run(true); });
      empty.appendChild(a);
    });
    empty.appendChild(document.createTextNode("."));
  }

  var params = new URLSearchParams(window.location.search);
  q.value = params.get("q") || params.get("rr_search") || "";
  run(false);
}());
