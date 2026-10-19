/**
 * rr-cite — shared "copy citation" control for the reading-room reader engine.
 *
 * Site-agnostic progressive enhancement. Each consuming plugin renders the
 * citation string server-side (crawlable, works with JS off) inside a button
 * carrying:
 *   data-rr-cite-copy                 marks the button for wiring
 *                                     (data-ggrr-cite-copy is matched too, for
 *                                     glassgovernment.org's existing template)
 *   data-cite="<formatted citation>"  the text copied to the clipboard
 *   data-cite-copied-label="Copied"   optional; label shown after a copy
 *
 * The button ships hidden; this reveals it only when some copy path exists,
 * so no-JS users still see the citation text and never a dead button. Copy
 * uses the Clipboard API and falls back to execCommand when that is missing
 * or refused; a failed copy says so instead of failing silently. Building the
 * citation string stays per-site; only the copy behavior is shared.
 *
 * Standalone: works with or without rr-reader.js loaded.
 */
(function () {
    "use strict";

    function legacyCopy(text) {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "");
        ta.style.position = "fixed";
        ta.style.top = "-1000px";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        var ok = false;
        try { ta.select(); ok = document.execCommand("copy"); } catch (e) { ok = false; }
        document.body.removeChild(ta);
        return ok;
    }

    function copyText(text) {
        if (window.RRReader && typeof window.RRReader.copyText === "function") {
            return window.RRReader.copyText(text);
        }
        if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
            return navigator.clipboard.writeText(text).then(
                function () { return true; },
                function () { return legacyCopy(text); }
            );
        }
        return Promise.resolve(legacyCopy(text));
    }

    function canCopy() {
        if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") { return true; }
        try { return !!(document.queryCommandSupported && document.queryCommandSupported("copy")); }
        catch (e) { return false; }
    }

    function wire(btn) {
        if (btn.getAttribute("data-rr-cite-wired") === "1") { return; }
        btn.setAttribute("data-rr-cite-wired", "1");
        btn.hidden = false;
        var label = btn.textContent;
        var doneLabel = btn.getAttribute("data-cite-copied-label") || "Copied";
        var failLabel = btn.getAttribute("data-cite-failed-label") || "Copy failed, select the text";
        btn.addEventListener("click", function () {
            var text = btn.getAttribute("data-cite") || "";
            if (text === "") { return; }
            copyText(text).then(function (ok) {
                btn.textContent = ok ? doneLabel : failLabel;
                btn.setAttribute("data-copied", ok ? "1" : "0");
                setTimeout(function () {
                    btn.textContent = label;
                    btn.removeAttribute("data-copied");
                }, ok ? 2000 : 4000);
            });
        });
    }

    function init() {
        if (!canCopy()) { return; }
        var btns = document.querySelectorAll("[data-rr-cite-copy], [data-ggrr-cite-copy]");
        for (var i = 0; i < btns.length; i++) { wire(btns[i]); }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
