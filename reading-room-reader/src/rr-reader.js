(function () {
    'use strict';

    // Common reading-room reader: a tiny registry + dispatcher. Format modules
    // (pdf, image, text, ...) register themselves and declare which files they
    // accept. The dispatcher mounts the first match into each .rr-reader
    // container; if no module matches, the download fallback in the markup stays
    // visible. A module that throws degrades the same way.
    //
    // Vendored into each site's plugin via reading-room-reader/sync.sh. Site
    // supplies per-doc data via container data-attributes and site-wide config
    // via a localized window.rrReaderConfig global. Back-compat aliases keep
    // glassgovernment.org working before its template is migrated.
    //
    // Fallback rule: the reader may only ADD to the page. Every failure path
    // ends in a visible status line plus the site's own fallback links (or a
    // plain link to the file), never a blank box.
    //
    // Server markup contract: inside the mount, the site renders a block
    // marked [data-reader-fallback] holding working links (open, text view,
    // download). With no script, or a script that never arrives, that block
    // is what people get. Modules replace the container's contents on mount;
    // the loader keeps a copy of the block and fail() puts it back.

    var VERSION = '0.8.0';
    var config = window.rrReaderConfig || window.ggrrReaderConfig || {};
    var registry = [];
    var fallbacks = {};   // data-reader-id -> pristine copy of [data-reader-fallback]
    var nextId = 0;

    function register(module) {
        if (module && typeof module.mount === 'function' && typeof module.accepts === 'function') {
            registry.push(module);
            mountAll(); // modules may load after first mount pass; mountAll is idempotent
        }
    }

    function pickModule(ext, mime) {
        for (var i = 0; i < registry.length; i++) {
            try {
                if (registry[i].accepts(ext, mime)) {
                    return registry[i];
                }
            } catch (e) {
                /* a misbehaving accepts() must not block other modules */
            }
        }
        return null;
    }

    function msg(key, fallback) {
        return (config.messages && config.messages[key]) ? config.messages[key] : fallback;
    }

    function statusNode(container) {
        var node = container.querySelector('[data-reader-status]');
        if (!node) {
            node = document.createElement('p');
            node.className = 'rr-reader__status';
            node.setAttribute('data-reader-status', '');
            node.setAttribute('role', 'status');
            node.setAttribute('aria-live', 'polite');
            container.appendChild(node);
        }
        return node;
    }

    function setStatus(container, message) {
        statusNode(container).textContent = message;
    }

    // Terminal failure: say so, and hand the reader a plain link to the file.
    // Built as DOM nodes so nothing from the URL is parsed as markup.
    function fail(container, message) {
        var node = statusNode(container);
        node.style.display = '';
        node.textContent = message + ' ';
        container.setAttribute('data-reader-failed', '1');
        var saved = fallbacks[container.getAttribute('data-reader-id')];
        if (saved && !container.querySelector('[data-reader-fallback]')) {
            var copy = saved.cloneNode(true);
            copy.hidden = false;
            container.insertBefore(copy, node.nextSibling);
            return;
        }
        var fileUrl = container.getAttribute('data-file-url') || '';
        if (fileUrl && !container.querySelector('[data-reader-fallback]')) {
            var a = document.createElement('a');
            a.href = fileUrl;
            a.className = 'rr-reader__fallback-link';
            a.textContent = msg('openFile', 'Open the file');
            node.appendChild(a);
        }
    }

    // Clipboard write with a fallback for browsers or contexts (http, iframes,
    // denied permission) where navigator.clipboard is missing or rejects.
    // Always settles; resolves true on success, false on failure.
    function legacyCopy(text) {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.top = '-1000px';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        var ok = false;
        var active = document.activeElement;
        try {
            ta.select();
            ok = document.execCommand('copy');
        } catch (e) {
            ok = false;
        }
        document.body.removeChild(ta);
        if (active && typeof active.focus === 'function') { active.focus(); }
        return ok;
    }

    function copyText(text) {
        if (!text) { return Promise.resolve(false); }
        if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
            return navigator.clipboard.writeText(text).then(
                function () { return true; },
                function () { return legacyCopy(text); }
            );
        }
        return Promise.resolve(legacyCopy(text));
    }

    function canCopy() {
        if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') { return true; }
        try { return !!(document.queryCommandSupported && document.queryCommandSupported('copy')); }
        catch (e) { return false; }
    }

    // Parse data-features="a,b c" into a lookup. Absent attribute -> null, so
    // modules can apply their own defaults.
    function features(container) {
        var raw = container.getAttribute('data-features');
        if (raw === null) { return null; }
        var out = {};
        raw.split(/[\s,]+/).forEach(function (t) { if (t) { out[t.toLowerCase()] = true; } });
        return out;
    }

    // Lifecycle events other code can hang off (e.g. a translation panel that
    // follows the current page) without the engine knowing about it.
    function emit(container, name, detail) {
        var ev;
        try {
            ev = new CustomEvent('rr-reader:' + name, { bubbles: true, detail: detail || {} });
        } catch (e) {
            ev = document.createEvent('CustomEvent');
            ev.initCustomEvent('rr-reader:' + name, true, false, detail || {});
        }
        container.dispatchEvent(ev);
    }

    function mountOne(container) {
        if (container.getAttribute('data-reader-mounted') === '1') {
            return;
        }
        var fileUrl = container.getAttribute('data-file-url') || '';
        if (!fileUrl) {
            return;
        }
        var ext = (container.getAttribute('data-ext') || '').toLowerCase();
        var mime = (container.getAttribute('data-mime') || '').toLowerCase();
        var mod = pickModule(ext, mime);
        if (!mod) {
            setStatus(container, msg('unsupported', 'Inline preview is not available for this file type. Use the open or download buttons.'));
            return;
        }
        container.setAttribute('data-reader-mounted', '1');
        if (!container.getAttribute('data-reader-id')) {
            container.setAttribute('data-reader-id', 'rr' + (nextId++));
        }
        var fb = container.querySelector('[data-reader-fallback]');
        if (fb) { fallbacks[container.getAttribute('data-reader-id')] = fb.cloneNode(true); }
        try {
            mod.mount(container, { fileUrl: fileUrl, ext: ext, mime: mime, config: config });
        } catch (e) {
            container.setAttribute('data-reader-mounted', '');
            fail(container, msg('loadFailed', 'The inline reader could not load this file. Use the open or download buttons.'));
        }
    }

    function mountAll() {
        // Dual selector: .rr-reader is canonical; .ggrr-reader is matched for
        // back-compat until the GG template emits .rr-reader.
        var nodes = document.querySelectorAll('.rr-reader[data-file-url], .ggrr-reader[data-file-url]');
        for (var i = 0; i < nodes.length; i++) {
            mountOne(nodes[i]);
        }
    }

    // In-document search over page texts held in the browser (static mode:
    // a site with no search route ships <slug>/pages.json instead). Same
    // contract as the sites' doc-search routes, so the reader cannot tell
    // them apart: [{page_number, snippet}] in reading order, at most `limit`.
    // Matching follows deflockdane's route: every query word of 3+ characters
    // (at most 8) must start a word on the page; if no page has them all, the
    // whole query as plain text, case-insensitive. Snippet: the text with
    // whitespace collapsed, 90 characters either side of the first word found.
    // Span: offset_start/offset_end of the hit in the page's own text, as GG's
    // route gives them (GGRR_Search::locate), so a hit can be cited exactly: the
    // earliest case-insensitive occurrence of any query term (lowercase [a-z0-9]
    // runs of 3+), as long as that term, counted in code points as PHP's mb_*
    // functions count; null when no term occurs.
    var WORD_SPLIT = /[^\p{L}\p{N}]+/u;
    var WORD_CHAR = /[\p{L}\p{N}]/u;

    function searchTerms(query) {
        return String(query || '').split(WORD_SPLIT).filter(function (w) {
            return Array.from(w).length >= 3;
        }).slice(0, 8);
    }

    function startsWord(lower, term) {
        var from = 0;
        for (;;) {
            var i = lower.indexOf(term, from);
            if (i < 0) { return false; }
            if (i === 0 || !WORD_CHAR.test(lower.charAt(i - 1))) { return true; }
            from = i + 1;
        }
    }

    function snippetOf(text, terms, radius) {
        var flat = String(text || '').replace(/\s+/g, ' ').trim();
        if (!flat) { return ''; }
        var chars = Array.from(flat);
        var lowerChars = chars.map(function (c) { return c.toLowerCase(); });
        var lower = lowerChars.join('');
        var pos = 0;
        for (var k = 0; k < terms.length; k++) {
            var at = lower.indexOf(terms[k].toLowerCase());
            if (at >= 0) { pos = Array.from(lower.slice(0, at)).length; break; }
        }
        var start = Math.max(0, pos - radius);
        var len = radius * 2;
        var out = chars.slice(start, start + len).join('');
        if (start > 0) { out = '…' + out; }
        if (start + len < chars.length) { out += '…'; }
        return out;
    }

    function locateTerms(query) {
        return String(query || '').toLowerCase().split(/[^a-z0-9]+/).filter(function (w) {
            return w.length >= 3;
        });
    }

    function locate(text, terms) {
        if (!text || !terms.length) { return null; }
        // One code point per entry, folded only where the fold keeps it one code
        // point (as mb_stripos's simple folding does), so indices stay aligned.
        var lowered = Array.from(String(text)).map(function (c) {
            var l = c.toLowerCase();
            return Array.from(l).length === 1 ? l : c;
        }).join('');
        var best = null;
        terms.forEach(function (t) {
            var at = lowered.indexOf(t);
            if (at < 0) { return; }
            var cp = Array.from(lowered.slice(0, at)).length;
            if (best === null || cp < best.offset) { best = { offset: cp, length: t.length }; }
        });
        return best;
    }

    function searchPages(pages, query, limit) {
        var q = String(query || '').trim();
        limit = Math.max(1, Math.min(200, limit || 50));
        if (!q || !Array.isArray(pages)) { return []; }
        var terms = searchTerms(q).map(function (w) { return w.toLowerCase(); });
        var hits = [];
        if (terms.length) {
            hits = pages.filter(function (p) {
                var lower = String(p.text || '').toLowerCase();
                return terms.every(function (term) { return startsWord(lower, term); });
            });
        }
        if (!hits.length) {
            var needle = q.toLowerCase();
            hits = pages.filter(function (p) { return String(p.text || '').toLowerCase().indexOf(needle) >= 0; });
        }
        var snipTerms = searchTerms(q);
        var spanTerms = locateTerms(q);
        return hits.slice().sort(function (a, b) { return a.n - b.n; }).slice(0, limit).map(function (p) {
            var loc = locate(String(p.text || ''), spanTerms);
            return {
                page_number: p.n,
                snippet: snippetOf(p.text, snipTerms, 90),
                offset_start: loc ? loc.offset : null,
                offset_end: loc ? loc.offset + loc.length : null
            };
        });
    }

    var api = {
        version: VERSION,
        register: register,
        mountAll: mountAll,
        msg: msg,
        setStatus: setStatus,
        fail: fail,
        copyText: copyText,
        canCopy: canCopy,
        features: features,
        emit: emit,
        searchPages: searchPages
    };

    window.RRReader = api;
    // Back-compat alias for modules written against GGRRReader.
    if (!window.GGRRReader) { window.GGRRReader = api; }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mountAll);
    } else {
        mountAll();
    }
})();
