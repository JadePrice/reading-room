/* roomkit collections (pack features.collections): the collections page's search,
   quick filters and sort; a collection page's title search; the index's collections
   table sort. Each control is hidden in the markup and shown here, so without
   JavaScript the page lists everything in the site's order. Behavior follows the
   live room's (gg-reading-room ggrr-declassify.js, archive-ggrr-collection.php,
   ggrr-reading-room.js), named at each piece. */
(function () {
  "use strict";
  function all(root, sel) { return Array.prototype.slice.call(root.querySelectorAll(sel)); }
  function year(el, none) {
    var y = parseInt(el.getAttribute("data-room-year") || "", 10);
    return isNaN(y) ? none : y;
  }

  // The collections page (ggrr-declassify.js): words match the card's text, a quick
  // filter matches its tags, and a card with no tags shows under every filter, so a
  // record is never hidden by a filter it cannot belong to. A group, then a category,
  // with nothing left showing is hidden. Sorting reorders the cards within each group.
  var cindex = document.querySelector("[data-room-collections-index]");
  if (cindex) {
    var controls = cindex.querySelector("[data-room-ccontrols]");
    var q = cindex.querySelector("[data-room-cq]");
    var buttons = all(cindex, "[data-room-cfilter]");
    var sorter = cindex.querySelector("[data-room-csort]");
    var lists = all(cindex, ".room__ccards");
    var active = buttons.length ? buttons[0].getAttribute("data-room-cfilter") : "";
    lists.forEach(function (ul) { all(ul, "[data-room-collection]").forEach(function (li, i) { li.setAttribute("data-room-i", i); }); });
    function show() {
      var words = q ? q.value.toLowerCase().trim() : "";
      all(cindex, "[data-room-ccat]").forEach(function (cat) {
        var groups = 0;
        all(cat, "[data-room-cgroup]").forEach(function (g) {
          var rows = 0;
          all(g, "[data-room-collection]").forEach(function (li) {
            var tags = (li.getAttribute("data-room-tags") || "").split(" ").filter(Boolean);
            var hit = (!buttons.length || active === buttons[0].getAttribute("data-room-cfilter") || !tags.length
                       || tags.indexOf(active) !== -1)
              && (li.getAttribute("data-room-match") || "").indexOf(words) !== -1;
            li.hidden = !hit;
            if (hit) { rows += 1; }
          });
          g.hidden = rows === 0;
          if (rows) { groups += 1; }
        });
        cat.hidden = groups === 0;
      });
    }
    function order() {
      var how = sorter ? sorter.value : "default";
      lists.forEach(function (ul) {
        var items = all(ul, "[data-room-collection]");
        items.sort(function (a, b) {
          if (how === "year-asc" || how === "year-desc") {
            // No year sorts last either way (9999 in the live room).
            var ya = year(a, null), yb = year(b, null);
            if (ya !== yb) {
              if (ya === null) { return 1; }
              if (yb === null) { return -1; }
              return how === "year-asc" ? ya - yb : yb - ya;
            }
          } else if (how === "alpha") {
            var ta = (a.querySelector("h4") || a).textContent.trim().toLowerCase();
            var tb = (b.querySelector("h4") || b).textContent.trim().toLowerCase();
            if (ta !== tb) { return ta.localeCompare(tb); }
          }
          return parseInt(a.getAttribute("data-room-i"), 10) - parseInt(b.getAttribute("data-room-i"), 10);
        });
        items.forEach(function (li) { ul.appendChild(li); });
      });
    }
    if (q) { q.addEventListener("input", show); }
    buttons.forEach(function (b) {
      b.addEventListener("click", function () {
        buttons.forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
        active = b.getAttribute("data-room-cfilter");
        show();
      });
    });
    if (sorter) { sorter.addEventListener("change", order); }
    if (controls) { controls.hidden = false; }
  }

  // A collection page (archive-ggrr-collection.php): the title filter and its
  // "{shown} of {total}" status, empty while the box is.
  var csearch = document.querySelector("[data-room-csearch]");
  if (csearch) {
    var input = csearch.querySelector("[data-room-cfq]");
    var status = csearch.querySelector("[data-room-cstatus]");
    var items = all(document, ".room__files [data-room-match]");
    input.addEventListener("input", function () {
      var w = input.value.trim().toLowerCase(), shown = 0;
      items.forEach(function (li) {
        var hit = !w || (li.getAttribute("data-room-match") || "").indexOf(w) !== -1;
        li.hidden = !hit;
        if (hit) { shown += 1; }
      });
      status.textContent = w ? status.getAttribute("data-room-cstatus").replace("{shown}", shown).replace("{total}", items.length) : "";
    });
    csearch.hidden = false;
  }

  // The index's collections table (ggrr-reading-room.js): grouped by default; by name
  // or year, one list. The era and group rows only make sense in the grouped order,
  // so they are hidden while another one is chosen (the live table leaves them
  // stacked above the sorted rows).
  var grid = document.querySelector("[data-room-cgrid]");
  var gsort = grid && grid.querySelector("[data-room-cgrid-sort]");
  if (gsort) {
    var tbody = grid.querySelector("tbody");
    var orig = Array.prototype.slice.call(tbody.children);
    var rows = orig.filter(function (tr) { return tr.hasAttribute("data-room-collection"); });
    gsort.addEventListener("change", function () {
      var how = gsort.value;
      orig.forEach(function (tr) { if (tr.hasAttribute("data-room-cgrid-head")) { tr.hidden = how !== "default"; } });
      if (how === "default") { orig.forEach(function (tr) { tbody.appendChild(tr); }); return; }
      rows.slice().sort(function (a, b) {
        if (how === "name") {
          return a.querySelector("a").textContent.trim().toLowerCase().localeCompare(b.querySelector("a").textContent.trim().toLowerCase());
        }
        var ya = year(a, null), yb = year(b, null);
        if (ya === null && yb === null) { return 0; }
        if (ya === null) { return 1; }
        if (yb === null) { return -1; }
        return how === "year-asc" ? ya - yb : yb - ya;
      }).forEach(function (tr) { tbody.appendChild(tr); });
    });
    grid.querySelector("[data-room-cgrid-sortbox]").hidden = false;
  }
})();
