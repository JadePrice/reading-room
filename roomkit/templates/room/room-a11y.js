(function () {
  "use strict";
  // The site's accessibility toolbar (pack a11y_toolbar), ported from the plugin that
  // draws it on the site's WordPress pages (wp-accessibility 2.4.5: js/wpa-toolbar.min.js,
  // and the font-size handler in js/wp-accessibility.min.js). The same cookies, classes and
  // stylesheet, so a choice made on a WordPress page holds in the room, and back. The markup
  // is in the page (partials/a11y-toolbar.html), hidden until this file runs, as the plugin
  // draws nothing without script.
  var bar = document.querySelector(".a11y-toolbar");
  if (!bar) { return; }
  var body = document.body, html = document.documentElement;
  var FACTOR = parseFloat(bar.getAttribute("data-room-a11y-factor")) || 1.6;
  var CONTRAST_CSS = bar.getAttribute("data-room-a11y-contrast");
  // The plugin's cookies: "1" while on; turned off, the value is emptied (a session cookie).
  function setCookie(name, value) { document.cookie = name + "=" + value + "; path=/; SameSite=Strict;"; }
  function getCookie(name) {
    var want = name + "=", parts = document.cookie.split(";");
    for (var i = 0; i < parts.length; i++) {
      var c = parts[i].replace(/^ +/, "");
      if (c.indexOf(want) === 0) { return c.substring(want.length); }
    }
    return null;
  }
  function press(from, to, on) {
    document.querySelectorAll('[data-id="' + from + '"]').forEach(function (b) {
      b.setAttribute("data-id", to);
      b.setAttribute("aria-pressed", on ? "true" : "false");
      b.classList.toggle("active", on);
    });
  }
  function contrastOn() {
    body.classList.add("contrast");
    press("is_normal_contrast", "is_high_contrast", true);
    setCookie("a11y-high-contrast", "1");
    if (CONTRAST_CSS && !document.getElementById("highContrastStylesheet")) {
      var link = document.createElement("link");
      link.setAttribute("href", CONTRAST_CSS);
      link.setAttribute("id", "highContrastStylesheet");
      link.setAttribute("rel", "stylesheet");
      document.head.insertAdjacentElement("beforeend", link);
    }
  }
  function contrastOff() {
    body.classList.remove("contrast");
    press("is_high_contrast", "is_normal_contrast", false);
    setCookie("a11y-high-contrast", "");
    var link = document.getElementById("highContrastStylesheet");
    if (link) { link.remove(); }
  }
  // Larger text: every element that holds text (and every form field) outside the toolbar
  // gets its computed size times the factor, !important, once; reset puts back what it had.
  function resize(change) {
    function marked(el) {
      for (; el; el = el.parentElement) { if (el.hasAttribute("data-wpa-resized")) { return true; } }
      return false;
    }
    function one(el) {
      if (change === "increase" && !marked(el)) {
        var px = parseFloat(window.getComputedStyle(el).getPropertyValue("font-size"));
        el.setAttribute("data-wpa-resized", el.style.fontSize || "true");
        el.style.cssText += "font-size: " + px * FACTOR + "px !important";
      }
      if (change === "reset") {
        el.style.removeProperty("font-size");
        var was = el.getAttribute("data-wpa-resized");
        if (was && was !== "true") { el.style.fontSize = was; }
        el.removeAttribute("data-wpa-resized");
      }
    }
    var walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT, {
      acceptNode: function (n) {
        var tag = n.parentElement ? n.parentElement.tagName : "";
        if (["SCRIPT", "STYLE", "NOSCRIPT", "SVG"].indexOf(tag) >= 0 || bar.contains(n)) { return NodeFilter.FILTER_REJECT; }
        return n.textContent.trim().length > 0 ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      }
    });
    var seen = new Set();
    while (walker.nextNode()) {
      var el = walker.currentNode.parentElement;
      if (el && !seen.has(el)) { seen.add(el); one(el); }
    }
    body.querySelectorAll("input, select, textarea").forEach(function (el) {
      if (!bar.contains(el) && !seen.has(el)) { seen.add(el); one(el); }
    });
  }
  function fontsizeOn() {
    html.classList.add("fontsize");
    resize("increase");
    press("is_normal_fontsize", "is_large_fontsize", true);
    setCookie("a11y-larger-fontsize", "1");
  }
  function fontsizeOff() {
    html.classList.remove("fontsize");
    resize("reset");
    press("is_large_fontsize", "is_normal_fontsize", false);
    setCookie("a11y-larger-fontsize", "");
  }
  // Below 1280px the buttons sit in the page's top line beside the Dark toggle instead of
  // floating over the text (the buttons, their classes and cookies are the same; only the parent
  // moves). Up to about 1268px a floating bar covers the right edge of the 1180px column; at 768
  // it covered text. Wider screens, and pages with no top line, keep the
  // plugin's fixed place, in the margin.
  var phone = window.matchMedia("(max-width: 1279px)"), home = bar.parentNode, next = bar.nextSibling;
  function place() {
    var line = document.querySelector(".room__topline");
    if (phone.matches && line) {
      if (bar.parentNode !== line) { line.appendChild(bar); }
    } else if (bar.parentNode !== home) {
      home.insertBefore(bar, next && next.parentNode === home ? next : null);
    }
  }
  if (phone.addEventListener) { phone.addEventListener("change", place); } else if (phone.addListener) { phone.addListener(place); }
  place();
  bar.hidden = false;
  var toggles = bar.querySelectorAll(".a11y-toggle");
  toggles.forEach(function (b) {
    b.addEventListener("focus", function () { b.classList.remove("tooltip-dismissed"); });
    // Escape hides the tooltip (the plugin's own line calls classList.addClass, which throws).
    b.addEventListener("keyup", function (e) { if (e.key === "Escape") { b.classList.add("tooltip-dismissed"); } });
  });
  if (getCookie("a11y-high-contrast")) { contrastOn(); }
  if (getCookie("a11y-larger-fontsize")) { fontsizeOn(); }
  bar.querySelectorAll(".toggle-contrast").forEach(function (b) {
    b.addEventListener("click", function () { if (this.getAttribute("data-id") === "is_normal_contrast") { contrastOn(); } else { contrastOff(); } });
  });
  bar.querySelectorAll(".toggle-fontsize").forEach(function (b) {
    b.addEventListener("click", function () { if (this.getAttribute("data-id") === "is_normal_fontsize") { fontsizeOn(); } else { fontsizeOff(); } });
  });
  // A focused control under the fixed toolbar scrolls clear of it.
  document.querySelectorAll('input,a[href],select,textarea,button:not(.a11y-toggle),[tabindex]:not([tabindex="-1"])').forEach(function (el) {
    el.addEventListener("focus", function () {
      var r = el.getBoundingClientRect(), t = bar.getBoundingClientRect();
      if (!(r.top > t.bottom || r.right < t.left || r.bottom < t.top || r.left > t.right)) { window.scrollBy(0, r.bottom - t.top); }
    });
  });
})();
