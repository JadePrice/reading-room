(function () {
  "use strict";
  // layout.gallery (the index only): List / Gallery over the same cards, so the filters
  // and the flat sort (room.js, room-search.js) act on both. A card's picture is only a
  // URL (data-room-thumb) until a visitor first picks Gallery: List loads no image.
  // The choice is kept in this browser. Search results (Pagefind) stay a list.
  var root = document.getElementById("room-content");
  var viewBox = root && root.querySelector("[data-room-view]");
  if (!viewBox) { return; }
  var VIEW_KEY = "rrIndexView";
  var viewBtns = Array.prototype.slice.call(viewBox.querySelectorAll("[data-room-view-as]"));
  var drawn = false;
  var show = function (as, save) {
    if (as !== "cards") { as = "rows"; }
    Array.prototype.slice.call(root.querySelectorAll(".room__groups, .room__cards")).forEach(function (el) {
      var base = el.classList.contains("room__groups") ? "room__groups--" : "room__cards--";
      el.classList.remove(base + "rows", base + "cards");
      el.classList.add(base + as);
    });
    if (as === "cards" && !drawn) {
      drawn = true;
      Array.prototype.slice.call(root.querySelectorAll("[data-room-thumb]")).forEach(function (a) {
        var img = document.createElement("img");
        img.alt = "";
        img.width = 116;
        img.height = 150;
        img.loading = "lazy";
        img.decoding = "async";
        img.src = a.getAttribute("data-room-thumb");
        a.appendChild(img);
      });
    }
    viewBtns.forEach(function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-room-view-as") === as ? "true" : "false"); });
    if (save) { try { window.localStorage.setItem(VIEW_KEY, as); } catch (e) {} }
  };
  var savedView = null;
  try { savedView = window.localStorage.getItem(VIEW_KEY); } catch (e) {}
  viewBtns.forEach(function (b) { b.addEventListener("click", function () { show(b.getAttribute("data-room-view-as"), true); }); });
  if (savedView === "cards") { show("cards", false); }
  viewBox.hidden = false;
}());
