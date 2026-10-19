(function () {
    'use strict';

    if (!window.RRReader) {
        return;
    }

    // Below this viewport width the two-page spread is forced off: a book spread
    // needs horizontal room, so phones always read one page at a time regardless
    // of the saved preference (archive.org BookReader does the same).
    var SPREAD_MIN_WIDTH = 760;
    var VIEW_PREF_KEY = 'rrReaderView';
    var LOAD_SLOW_MS = 20000;

    function el(tag, cls, attrs) {
        var node = document.createElement(tag);
        if (cls) { node.className = cls; }
        if (attrs) {
            Object.keys(attrs).forEach(function (k) { node.setAttribute(k, attrs[k]); });
        }
        return node;
    }

    function readPref() {
        try { return window.localStorage.getItem(VIEW_PREF_KEY) === 'spread' ? 'spread' : 'single'; }
        catch (e) { return 'single'; }
    }
    function writePref(mode) {
        try { window.localStorage.setItem(VIEW_PREF_KEY, mode); } catch (e) {}
    }

    // Complete reader stylesheet, injected once. Self-sufficient: the engine
    // owns all its styling so it works on any site. Colors are CSS custom
    // properties (--rr-*) with the GG oklch palette as fallbacks, so it looks
    // correct unstyled; each site maps its own palette onto --rr-* via a bridge.
    // The text-layer rules mirror pdf.js pdf_viewer.css (transparent selectable
    // spans over the canvas); the book rules lay out the two-page spread.
    function injectStylesOnce() {
        if (document.getElementById('rr-reader-pdf-css')) { return; }
        var css = [
            // --- container + toolbar + controls (tokenized, GG fallbacks) ---
            '.rr-reader--mounted{display:grid;gap:.75rem;border:1px solid var(--rr-rule,oklch(85% .012 80));border-radius:4px;background:var(--rr-paper,oklch(97% .008 85));color:var(--rr-ink,oklch(25% .02 60));padding:.85rem;}',
            '.rr-reader__toolbar{display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;}',
            '.rr-reader__btn{min-height:44px;min-width:44px;padding:.5rem .95rem;border:1px solid var(--rr-ink,oklch(25% .02 60));border-radius:3px;background:var(--rr-ink,oklch(25% .02 60));color:var(--rr-paper,oklch(97% .008 85));font-family:var(--rr-mono,ui-monospace,Menlo,Consolas,monospace);font-size:.8rem;letter-spacing:.03em;cursor:pointer;}',
            '.rr-reader__btn:hover:not(:disabled){background:var(--rr-accent,oklch(48% .13 25));border-color:var(--rr-accent,oklch(48% .13 25));}',
            '.rr-reader__btn:disabled{opacity:.4;cursor:default;}',
            '.rr-reader__btn--zoom{min-width:44px;padding:.5rem .75rem;font-size:1.1rem;line-height:1;}',
            '.rr-reader__btn:focus-visible,.rr-reader__stage:focus-visible,.rr-reader__find-hit:focus-visible,.rr-reader__find-cite:focus-visible,.rr-reader__cite:focus-visible,.rr-reader input.rr-reader__page-input:focus-visible,.rr-reader input.rr-reader__find-input:focus-visible{outline:2px solid var(--rr-focus,oklch(48% .13 25));outline-offset:2px;}',
            '.rr-reader__btn[aria-pressed="true"]{background:var(--rr-accent,oklch(48% .13 25));border-color:var(--rr-accent,oklch(48% .13 25));color:#fff;}',
            '.rr-reader__pageinfo{display:inline-flex;align-items:center;gap:.35rem;font-family:var(--rr-mono,ui-monospace,monospace);font-size:.82rem;color:var(--rr-ink-soft,oklch(45% .02 60));margin-left:auto;}',
            // Inputs use a `.rr-reader input.rr-reader__*` selector so the engine's
            // theming wins over host-theme input resets like Astra's
            // `input[type="text"|"search"]{background:...}` (specificity 0,0,1,1).
            '.rr-reader input.rr-reader__page-input{width:3.5rem;min-height:44px;text-align:center;border:1px solid var(--rr-control-border,var(--rr-ink-soft,oklch(45% .02 60)));border-radius:3px;padding:.25rem;background:var(--rr-paper-raised,oklch(99% .004 85));color:var(--rr-ink,oklch(25% .02 60));font-family:var(--rr-mono,ui-monospace,monospace);}',
            '.rr-reader__page-total{color:var(--rr-ink-soft,oklch(45% .02 60));}',
            '.rr-reader__poster{display:block;max-width:100%;height:auto;margin:0 auto;background:#fff;}',
            '.rr-reader__stage.has-poster .rr-reader__pagebox{display:none;}',
            '.rr-reader__stage{max-height:80vh;overflow:auto;display:flex;justify-content:center;background:var(--rr-paper-raised,oklch(99% .004 85));border:1px solid var(--rr-rule,oklch(85% .012 80));border-radius:3px;padding:.5rem;}',
            '.rr-reader__canvas{max-width:100%;height:auto;box-shadow:0 1px 8px rgba(0,0,0,.18);background:#fff;}',
            '.rr-reader__status{margin:0;color:var(--rr-ink-soft,oklch(45% .02 60));font-size:.92rem;}',
            // --- text layer (selectable, over canvas) ---
            '.rr-reader__pagebox{position:relative;margin:0 auto;flex:0 0 auto;}',
            '.rr-reader__textlayer{position:absolute;left:0;top:0;right:0;bottom:0;overflow:hidden;line-height:1;text-align:initial;transform-origin:0 0;z-index:2;}',
            '.rr-reader__textlayer span,.rr-reader__textlayer br{color:transparent;position:absolute;white-space:pre;cursor:text;transform-origin:0% 0%;}',
            '.rr-reader__textlayer .rr-tl-hit{background:rgba(255,205,0,.45);border-radius:2px;}',
            '.rr-reader__textlayer ::selection{background:rgba(40,110,255,.30);}',
            // --- two-page book spread: facing leaves, tops aligned, center spine ---
            '.rr-reader__book{display:flex;justify-content:center;align-items:flex-start;gap:0;}',
            '.rr-reader__book .rr-reader__pagebox{margin:0;}',
            '.rr-reader__book .rr-reader__pagebox--left{margin-right:1px;}',
            '.rr-reader__book .rr-reader__pagebox--left::after,.rr-reader__book .rr-reader__pagebox--right::before{content:"";position:absolute;top:0;bottom:0;width:10px;z-index:3;pointer-events:none;}',
            '.rr-reader__book .rr-reader__pagebox--left::after{right:0;background:linear-gradient(to right,rgba(0,0,0,0),rgba(0,0,0,.18));}',
            '.rr-reader__book .rr-reader__pagebox--right::before{left:0;background:linear-gradient(to left,rgba(0,0,0,0),rgba(0,0,0,.18));}',
            // --- in-document search affordance ---
            '.rr-reader__find{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;margin:.4rem 0;}',
            '.rr-reader input.rr-reader__find-input{flex:1 1 12rem;min-width:8rem;min-height:44px;padding:.35rem .5rem;font:inherit;border:1px solid var(--rr-control-border,var(--rr-ink-soft,oklch(45% .02 60)));border-radius:3px;background:var(--rr-paper-raised,oklch(99% .004 85));color:var(--rr-ink,oklch(25% .02 60));}',
            '.rr-reader input.rr-reader__find-input::placeholder{color:var(--rr-ink-soft,oklch(45% .02 60));opacity:1;}',
            '.rr-reader__find-count{font-size:.85em;opacity:.8;min-width:6rem;}',
            '.rr-reader__find-results{list-style:none;margin:.25rem 0 0;padding:0;max-height:14rem;overflow:auto;border-top:1px solid rgba(127,127,127,.3);}',
            '.rr-reader__find-results li{margin:0;}',
            '.rr-reader__find-hit{display:block;width:100%;text-align:left;background:none;border:0;border-bottom:1px solid rgba(127,127,127,.15);padding:.45rem .3rem;font:inherit;cursor:pointer;color:inherit;}',
            '.rr-reader__find-hit:hover,.rr-reader__find-hit:focus{background:rgba(127,127,127,.12);}',
            '.rr-reader__find-hit b{display:block;font-size:.8em;opacity:.75;margin-bottom:.15rem;}',
            // Opaque, with its own ink: a translucent mark over inherited text failed
            // contrast on dark consumers (deflockdane.org, 0.4.0 live check).
            '.rr-reader__find-hit mark{background:var(--rr-mark,#ffd84d);color:var(--rr-mark-ink,#1b1b1b);}',
            // --- per-hit "Cite" affordance and the citation panel it fills ---
            '.rr-reader__find-row{display:flex;align-items:stretch;gap:.25rem;border-bottom:1px solid rgba(127,127,127,.15);}',
            '.rr-reader__find-row .rr-reader__find-hit{border-bottom:0;flex:1 1 auto;min-width:0;}',
            '.rr-reader__find-cite{flex:0 0 auto;align-self:center;min-height:44px;min-width:44px;background:none;border:1px solid var(--rr-control-border,var(--rr-ink-soft,oklch(45% .02 60)));border-radius:3px;padding:.25rem .6rem;margin-right:.3rem;font:inherit;font-size:.82em;cursor:pointer;color:inherit;}',
            '.rr-reader__find-cite:hover{background:rgba(127,127,127,.15);}',
            '.rr-reader__cite{margin:0;padding:.6rem .7rem;border:1px solid var(--rr-rule,oklch(85% .012 80));border-radius:4px;background:var(--rr-paper-raised,oklch(99% .004 85));}',
            '.rr-reader__cite[hidden]{display:none;}',
            '.rr-reader__cite-head{display:flex;align-items:center;justify-content:space-between;gap:.5rem;margin-bottom:.4rem;}',
            '.rr-reader__cite-title{font-size:.9em;font-weight:600;margin:0;}',
            '.rr-reader__cite-quote{margin:0 0 .5rem;padding:.4rem .6rem;border-left:3px solid var(--rr-ink-soft,oklch(45% .02 60));font-size:.9em;white-space:pre-wrap;overflow-wrap:anywhere;}',
            '.rr-reader__cite-ref{margin:0 0 .45rem;font-size:.86em;line-height:1.5;overflow-wrap:anywhere;}',
            '.rr-reader__cite-note{margin:0 0 .45rem;font-size:.86em;line-height:1.5;font-style:italic;}',
            '.rr-reader__cite-note[hidden]{display:none;}',
            '.rr-reader__cite-prov{margin:0;font-size:.8em;color:var(--rr-ink-soft,oklch(45% .02 60));line-height:1.5;}',
            '.rr-reader__cite-prov code{font-size:.95em;overflow-wrap:anywhere;}',
            '.rr-reader__cite-actions{display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:.45rem;}',
            '.rr-reader__sr-only{position:absolute!important;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0;}',
            '.rr-reader__fallback-link{color:inherit;text-decoration:underline;}',
            '@media (prefers-reduced-motion:reduce){.rr-reader__btn{transition:none;}}',
            '@media (max-width:900px){.rr-reader__stage{max-height:62vh;}.rr-reader__pageinfo{margin-left:0;}}',
            // --- lightbox + fullscreen support ---
            '.rr-reader--lightbox,.rr-reader:fullscreen{position:fixed!important;top:0!important;left:0!important;right:0!important;bottom:0!important;z-index:99999!important;background:var(--rr-paper,oklch(97% .008 85))!important;padding:1.5rem!important;display:flex!important;flex-direction:column!important;gap:.75rem!important;max-width:none!important;margin:0!important;border:0!important;border-radius:0!important;}',
            '.rr-reader--lightbox .rr-reader__stage,.rr-reader:fullscreen .rr-reader__stage{flex:1 1 auto!important;max-height:none!important;height:100%!important;}',
            '.rr-reader__btn--fullscreen{display:none;}',
            '.rr-reader--lightbox .rr-reader__btn--fullscreen,.rr-reader:fullscreen .rr-reader__btn--fullscreen{display:inline-block;}'
        ].join('');
        var style = document.createElement('style');
        style.id = 'rr-reader-pdf-css';
        style.textContent = css;
        document.head.appendChild(style);
    }

    // Append `text` to `parent`, wrapping each occurrence of a search term in
    // <mark>. Works on the raw snippet and builds text nodes, so a term like
    // "amp" can never match inside an HTML entity and nothing is parsed as markup.
    function appendHighlighted(parent, text, terms) {
        text = String(text == null ? '' : text);
        if (!terms.length) { parent.appendChild(document.createTextNode(text)); return; }
        var esc = terms.map(function (t) { return t.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&'); });
        var re = new RegExp(esc.join('|'), 'gi');
        var last = 0;
        var m;
        while ((m = re.exec(text)) !== null) {
            if (m[0] === '') { re.lastIndex++; continue; }
            if (m.index > last) { parent.appendChild(document.createTextNode(text.slice(last, m.index))); }
            var mark = document.createElement('mark');
            mark.textContent = m[0];
            parent.appendChild(mark);
            last = m.index + m[0].length;
        }
        if (last < text.length) { parent.appendChild(document.createTextNode(text.slice(last))); }
    }

    // Lowercase alnum terms >= 3 chars, mirroring the server's search tokenizer.
    function queryTerms(q) {
        return String(q || '').toLowerCase().split(/[^a-z0-9]+/).filter(function (t) { return t.length >= 3; });
    }

    function pageFromHash() {
        var m = /(?:^|#)page-(\d+)/.exec(window.location.hash || '');
        return m ? parseInt(m[1], 10) : 0;
    }

    function mount(container, ctx) {
        injectStylesOnce();
        var config = ctx.config || {};
        var R = window.RRReader;
        var slug = container.getAttribute('data-slug') || '';
        var docSearchUrl = config.docSearchUrl || '';
        var passageUrl = config.passageUrl || '';
        // Static mode: the document's page texts as a file (roomkit writes
        // <slug>/pages.json). Searched in the browser, so no search route is
        // needed; it wins over docSearchUrl because it is set per document.
        var pagesUrl = container.getAttribute('data-pages-url') || '';
        // data-features is a token list; absent means the defaults below.
        // spread and search default on; lightbox and fullscreen opt in. Cite is
        // governed by whether the site wired a passage route, not by this list
        // (existing templates predate the token), and is opted out with
        // "no-cite".
        var f = R.features(container);
        var features = {
            spread: f ? !!f.spread : true,
            search: f ? !!f.search : true,
            cite: !(f && f['no-cite']),
            lightbox: f ? !!f.lightbox : false,
            fullscreen: f ? !!f.fullscreen : false
        };
        var searchOn = features.search && !!slug && (!!pagesUrl || !!docSearchUrl);
        // Citations are resolved server-side (passage route), so the engine only
        // offers them where the site wired that route. In static mode a page's
        // own citation can ship in pages.json (`cite`, the site's page-scoped
        // citation): "Cite page" then shows it with no request, and a passage
        // that cannot be resolved falls back to it.
        var citeOn = features.cite && !!passageUrl && !!slug;
        var CITE_TIMEOUT_MS = config.citeTimeoutMs || 8000;  // a slow route gives way to the page citation
        var copyOn = R.canCopy();

        while (container.firstChild) { container.removeChild(container.firstChild); }
        container.classList.add('rr-reader--pdf');
        container.classList.add('rr-reader--mounted');

        var toolbar = el('div', 'rr-reader__toolbar', { role: 'toolbar', 'aria-label': 'Document controls' });
        var prev = el('button', 'rr-reader__btn', { type: 'button', 'aria-label': 'Previous page' });
        prev.textContent = 'Prev'; prev.disabled = true;
        var pageWrap = el('span', 'rr-reader__pageinfo');
        var pageInput = el('input', 'rr-reader__page-input', { type: 'text', inputmode: 'numeric', 'aria-label': 'Go to page', value: '1' });
        var pageTotal = el('span', 'rr-reader__page-total'); pageTotal.textContent = '/ –';
        pageWrap.appendChild(pageInput); pageWrap.appendChild(pageTotal);
        var next = el('button', 'rr-reader__btn', { type: 'button', 'aria-label': 'Next page' });
        next.textContent = 'Next'; next.disabled = true;
        var zoomOut = el('button', 'rr-reader__btn rr-reader__btn--zoom', { type: 'button', 'aria-label': 'Zoom out' });
        zoomOut.textContent = '−';
        var zoomIn = el('button', 'rr-reader__btn rr-reader__btn--zoom', { type: 'button', 'aria-label': 'Zoom in' });
        zoomIn.textContent = '+';

        toolbar.appendChild(prev); toolbar.appendChild(pageWrap); toolbar.appendChild(next);
        toolbar.appendChild(zoomOut); toolbar.appendChild(zoomIn);

        // Two-page (book spread) toggle. Hidden on narrow viewports (forced single).
        var viewBtn = el('button', 'rr-reader__btn rr-reader__btn--view', { type: 'button', 'aria-label': 'Two-page view', 'aria-pressed': 'false' });
        viewBtn.textContent = 'Two-page';
        if (features.spread) {
            toolbar.appendChild(viewBtn);
        }

        // Page-scoped citing needs no text selection, so it works on image-only
        // scans too.
        var citeBtn = el('button', 'rr-reader__btn rr-reader__btn--cite', { type: 'button', 'aria-label': 'Cite the current page' });
        citeBtn.textContent = 'Cite page';
        if (citeOn) { toolbar.appendChild(citeBtn); }

        var enlargeBtn = null;
        var fullscreenBtn = null;

        if (features.lightbox) {
            enlargeBtn = el('button', 'rr-reader__btn rr-reader__btn--enlarge', { type: 'button', 'aria-label': 'Enlarge reader' });
            enlargeBtn.textContent = 'Enlarge';
            toolbar.appendChild(enlargeBtn);

            if (features.fullscreen) {
                var canFS = !!(container.requestFullscreen || container.webkitRequestFullscreen || container.mozRequestFullScreen || container.msRequestFullscreen);
                if (canFS) {
                    fullscreenBtn = el('button', 'rr-reader__btn rr-reader__btn--fullscreen', { type: 'button', 'aria-label': 'Fullscreen mode' });
                    fullscreenBtn.textContent = 'Fullscreen';
                    toolbar.appendChild(fullscreenBtn);
                }
            }
        }

        // In-document search bar (server-backed; works on image-only scans).
        var find = el('div', 'rr-reader__find', { role: 'search' });
        var findInput = el('input', 'rr-reader__find-input', { type: 'search', 'aria-label': 'Search within this document', placeholder: 'Search within this document…' });
        var findPrev = el('button', 'rr-reader__btn', { type: 'button', 'aria-label': 'Previous match' }); findPrev.textContent = '‹'; findPrev.disabled = true;
        var findNext = el('button', 'rr-reader__btn', { type: 'button', 'aria-label': 'Next match' }); findNext.textContent = '›'; findNext.disabled = true;
        var findCount = el('span', 'rr-reader__find-count', { role: 'status', 'aria-live': 'polite' });
        find.appendChild(findInput); find.appendChild(findPrev); find.appendChild(findNext); find.appendChild(findCount);
        var findResults = el('ul', 'rr-reader__find-results', { 'aria-label': 'Search results in this document' });

        // Citation panel. Server-rendered strings only: the reference text, the
        // quoted span and the durable key all come back from the passage route,
        // so the reader never composes a citation of its own.
        var citePanel = el('section', 'rr-reader__cite', { 'aria-labelledby': '', tabindex: '-1', hidden: 'hidden' });
        var citeHead = el('div', 'rr-reader__cite-head');
        var citeTitle = el('h3', 'rr-reader__cite-title');
        citeTitle.id = 'rr-cite-title-' + Math.random().toString(36).slice(2, 9);
        citePanel.setAttribute('aria-labelledby', citeTitle.id);
        var citeClose = el('button', 'rr-reader__find-cite', { type: 'button', 'aria-label': 'Close citation' });
        citeClose.textContent = 'Close';
        citeHead.appendChild(citeTitle); citeHead.appendChild(citeClose);
        var citeQuote = el('blockquote', 'rr-reader__cite-quote', { hidden: 'hidden' });
        var citeRef = el('p', 'rr-reader__cite-ref');
        var citeNote = el('p', 'rr-reader__cite-note', { hidden: 'hidden' });
        var citeActions = el('div', 'rr-reader__cite-actions');
        var citeCopy = el('button', 'rr-reader__find-cite', { type: 'button', hidden: 'hidden' });
        citeCopy.textContent = 'Copy citation';
        var citeCopyQuote = el('button', 'rr-reader__find-cite', { type: 'button', hidden: 'hidden' });
        citeCopyQuote.textContent = 'Copy quote';
        var citeProv = el('p', 'rr-reader__cite-prov');
        var citeLive = el('span', 'rr-reader__sr-only', { role: 'status', 'aria-live': 'polite' });
        citeActions.appendChild(citeCopy); citeActions.appendChild(citeCopyQuote);
        citePanel.appendChild(citeHead); citePanel.appendChild(citeNote); citePanel.appendChild(citeQuote);
        citePanel.appendChild(citeRef); citePanel.appendChild(citeActions);
        citePanel.appendChild(citeProv); citePanel.appendChild(citeLive);

        var stage = el('div', 'rr-reader__stage', { tabindex: '0', role: 'document', 'aria-label': 'Document pages' });
        var status = el('p', 'rr-reader__status', { 'data-reader-status': '', role: 'status', 'aria-live': 'polite' });
        status.textContent = R.msg('loading', 'Loading PDF…');

        container.appendChild(toolbar);
        if (searchOn) { container.appendChild(find); container.appendChild(findResults); }
        if (citeOn) { container.appendChild(citePanel); }
        container.appendChild(stage);
        container.appendChild(status);

        // Poster: a server-rendered image of page 1 (data-poster), shown at
        // once while pdf.js fetches what it needs. pdf.js reads every page's
        // entry in the file before it can draw page 1 (most of a 1.8 MB
        // record on deflockdane.org), so without this a slow link stares at
        // an empty box. Skipped for a #page-N deep link: it would show the
        // wrong page. Replaced by the real page once that has drawn.
        var poster = null;
        var posterUrl = container.getAttribute('data-poster') || '';
        if (posterUrl && pageFromHash() <= 1) {
            var docTitle = container.getAttribute('data-title') || '';
            poster = el('img', 'rr-reader__poster', {
                src: posterUrl,
                alt: 'Page 1' + (docTitle ? ' of ' + docTitle : '') + ', a preview image while the reader loads',
                decoding: 'async'
            });
            poster.addEventListener('error', dropPoster);
            stage.appendChild(poster);
            stage.classList.add('has-poster');
        }
        function dropPoster() {
            if (!poster) { return; }
            if (poster.parentNode) { poster.parentNode.removeChild(poster); }
            stage.classList.remove('has-poster');
            poster = null;
        }

        var pdfDoc = null;
        var pageNum = 1;            // the focused/anchor page; spread derived from it
        var zoomStep = 0;
        var rendering = false;
        var queued = false;
        var resizeTimer = null;
        var activeTerms = [];       // terms to highlight in the text layers
        var viewPref = readPref();  // 'single' | 'spread' (user preference)
        var builtMode = null;       // mode the stage DOM is currently built for
        var slots = [];             // [{ pageBox, canvas, textLayer, textTask }]
        var shownPages = [1];       // page numbers currently painted (for controls)

        // search state
        var matches = [];           // [ page_number, ... ] in reading order
        var matchIdx = -1;
        var findTimer = null;
        var findCtrl = null;
        var findQuery = '';

        // citation state
        var citeCtrl = null;
        var citeSeq = 0;
        var loadTimer = null;

        function setStatus(t) { status.textContent = t; }
        function clampZoom(z) { return Math.max(-4, Math.min(6, z)); }

        // Effective mode honors the preference but is forced to single when the
        // viewport is too narrow for a spread.
        function effectiveMode() {
            return (features.spread && viewPref === 'spread' && window.innerWidth >= SPREAD_MIN_WIDTH) ? 'spread' : 'single';
        }

        // Cover-alone (book) parity, matching archive.org BookReader / pdf.js
        // SpreadMode.EVEN: page 1 sits alone on the right, then (2,3),(4,5)…
        // Returns the page number(s) to show, aligned to the slot order.
        function spreadPagesFor(n) {
            if (effectiveMode() !== 'spread') { return [n]; }
            if (n <= 1) { return [null, 1]; }
            var k = Math.floor(n / 2);
            var left = 2 * k;
            var right = 2 * k + 1;
            return [left, (pdfDoc && right <= pdfDoc.numPages) ? right : null];
        }

        function makeSlot(edge) {
            var pageBox = el('div', 'rr-reader__pagebox' + (edge ? ' rr-reader__pagebox--' + edge : ''));
            var canvas = el('canvas', 'rr-reader__canvas');
            var textLayer = el('div', 'rr-reader__textlayer');
            pageBox.appendChild(canvas); pageBox.appendChild(textLayer);
            return { pageBox: pageBox, canvas: canvas, textLayer: textLayer, textTask: null };
        }

        function cancelSlotText(slot) {
            if (slot.textTask && typeof slot.textTask.cancel === 'function') {
                try { slot.textTask.cancel(); } catch (e) {}
            }
            slot.textTask = null;
        }

        function buildStage(mode) {
            slots.forEach(cancelSlotText);
            while (stage.firstChild) { stage.removeChild(stage.firstChild); }
            if (poster) { stage.appendChild(poster); }
            slots = [];
            if (mode === 'spread') {
                var book = el('div', 'rr-reader__book');
                var left = makeSlot('left');
                var right = makeSlot('right');
                book.appendChild(left.pageBox); book.appendChild(right.pageBox);
                stage.appendChild(book);
                slots = [left, right];
                stage.classList.add('is-spread');
            } else {
                var s = makeSlot();
                stage.appendChild(s.pageBox);
                slots = [s];
                stage.classList.remove('is-spread');
            }
            builtMode = mode;
        }

        function ensureStage() {
            var mode = effectiveMode();
            if (builtMode !== mode) { buildStage(mode); }
        }

        function highlightSlot(slot) {
            if (!activeTerms.length) { return; }
            var spans = slot.textLayer.querySelectorAll('span');
            for (var i = 0; i < spans.length; i++) {
                var low = (spans[i].textContent || '').toLowerCase();
                for (var j = 0; j < activeTerms.length; j++) {
                    if (low.indexOf(activeTerms[j]) !== -1) { spans[i].classList.add('rr-tl-hit'); break; }
                }
            }
        }

        function renderTextLayerInto(slot, page, viewport) {
            cancelSlotText(slot);
            while (slot.textLayer.firstChild) { slot.textLayer.removeChild(slot.textLayer.firstChild); }
            slot.textLayer.style.width = Math.floor(viewport.width) + 'px';
            slot.textLayer.style.height = Math.floor(viewport.height) + 'px';
            slot.textLayer.style.setProperty('--scale-factor', viewport.scale);
            // The text layer uses the pdf.js 3.x renderTextLayer API. pdf.js 4
            // removed it; rather than silently drop selection and highlighting,
            // flag the container so the gap is visible to tests and audits.
            if (!window.pdfjsLib || typeof window.pdfjsLib.renderTextLayer !== 'function') {
                container.setAttribute('data-text-layer', 'unavailable');
                return;
            }
            page.getTextContent().then(function (tc) {
                var task = window.pdfjsLib.renderTextLayer({
                    textContentSource: tc,
                    container: slot.textLayer,
                    viewport: viewport,
                    textDivs: []
                });
                slot.textTask = task;
                var done = task && task.promise ? task.promise : task;
                Promise.resolve(done).then(function () { highlightSlot(slot); }).catch(function () {});
            }).catch(function () {});
        }

        function paintSlot(slot, page, scale) {
            var viewport = page.getViewport({ scale: scale });
            var ratio = window.devicePixelRatio || 1;
            var cxt = slot.canvas.getContext('2d');
            slot.canvas.width = Math.floor(viewport.width * ratio);
            slot.canvas.height = Math.floor(viewport.height * ratio);
            slot.canvas.style.width = Math.floor(viewport.width) + 'px';
            slot.canvas.style.height = Math.floor(viewport.height) + 'px';
            slot.pageBox.style.width = Math.floor(viewport.width) + 'px';
            slot.pageBox.style.height = Math.floor(viewport.height) + 'px';
            slot.pageBox.style.display = '';
            cxt.setTransform(ratio, 0, 0, ratio, 0, 0);
            return page.render({ canvasContext: cxt, viewport: viewport }).promise.then(function () {
                renderTextLayerInto(slot, page, viewport);
            });
        }

        function blankSlot(slot) {
            cancelSlotText(slot);
            while (slot.textLayer.firstChild) { slot.textLayer.removeChild(slot.textLayer.firstChild); }
            slot.pageBox.style.display = 'none';
        }

        function fitScale(bases) {
            var sStyle = window.getComputedStyle(stage);
            var padX = (parseFloat(sStyle.paddingLeft) || 0) + (parseFloat(sStyle.paddingRight) || 0);
            var padY = (parseFloat(sStyle.paddingTop) || 0) + (parseFloat(sStyle.paddingBottom) || 0);
            var present = bases.filter(function (b) { return b; });
            var gutter = present.length > 1 ? 4 : 0; // spine margin between leaves
            var avail = (stage.clientWidth ? stage.clientWidth - padX : container.clientWidth) - gutter - 2;
            var maxH = stage.clientHeight ? stage.clientHeight - padY - 2 : 0;
            var sumW = 0, maxBaseH = 0;
            present.forEach(function (b) { sumW += b.width; if (b.height > maxBaseH) { maxBaseH = b.height; } });
            var scaleW = (avail > 0 && sumW > 0) ? avail / sumW : 1;
            var scaleH = (maxH > 0 && maxBaseH > 0) ? maxH / maxBaseH : Infinity;
            var fit = Math.min(scaleW, scaleH);
            fit = Math.min(1.6, Math.max(0.5, fit));
            return fit * Math.pow(1.15, zoomStep);
        }

        function renderView() {
            if (!pdfDoc) { return; }
            if (rendering) { queued = true; return; }
            ensureStage();
            rendering = true;
            var targets = spreadPagesFor(pageNum);
            shownPages = targets.filter(function (n) { return n; });
            setStatus((R.msg('rendering', 'Rendering page')) + ' ' + (shownPages.join('–') || pageNum) + '…');
            var jobs = targets.map(function (n) {
                return n ? pdfDoc.getPage(n) : Promise.resolve(null);
            });
            Promise.all(jobs).then(function (pages) {
                // Shared scale across both leaves so heights match and the pair fits.
                var bases = pages.map(function (p) { return p ? p.getViewport({ scale: 1 }) : null; });
                var scale = fitScale(bases);
                var paints = [];
                for (var i = 0; i < slots.length; i++) {
                    if (pages[i]) { paints.push(paintSlot(slots[i], pages[i], scale)); }
                    else { blankSlot(slots[i]); }
                }
                return Promise.all(paints);
            }).then(function () {
                pageTotal.textContent = '/ ' + pdfDoc.numPages;
                var shownMax = shownPages.length ? Math.max.apply(null, shownPages) : pageNum;
                dropPoster();
                setStatus('Page ' + (shownPages.join(' and ') || pageNum) + ' of ' + pdfDoc.numPages + '.');
                updateControls(shownMax);
                R.emit(container, 'pagechange', { pages: shownPages.slice(), total: pdfDoc.numPages, slug: slug });
            }).catch(function () {
                R.fail(container, R.msg('loadFailed', 'The reader could not render this PDF. Use the open or download buttons.'));
            }).then(function () {
                rendering = false;
                if (queued) { queued = false; renderView(); }
            });
        }

        function updateControls(shownMax) {
            var has = !!pdfDoc;
            prev.disabled = !has || pageNum <= 1;
            next.disabled = !has || (shownMax || pageNum) >= pdfDoc.numPages;
            pageInput.value = String(pageNum);
            var spread = effectiveMode() === 'spread';
            if (viewBtn) {
                viewBtn.setAttribute('aria-pressed', spread ? 'true' : 'false');
                viewBtn.style.display = (features.spread && window.innerWidth >= SPREAD_MIN_WIDTH) ? '' : 'none';
            }
        }

        function go(n) {
            if (!pdfDoc) { return; }
            n = Math.max(1, Math.min(pdfDoc.numPages, n | 0));
            pageNum = n;
            renderView();
        }

        // Step by a whole spread in two-page mode, by one page in single mode.
        function navStep(dir) {
            if (effectiveMode() === 'spread') {
                var pr = spreadPagesFor(pageNum);
                if (dir > 0) { go((pr[1] || pr[0] || pageNum) + 1); }
                else { go((pr[0] || pr[1] || pageNum) - 1); }
            } else {
                go(pageNum + dir);
            }
        }

        function toggleView() {
            viewPref = (viewPref === 'spread') ? 'single' : 'spread';
            writePref(viewPref);
            renderView(); // ensureStage() inside rebuilds DOM for the new mode
        }

        // ---- in-document search ----
        function clearAllHighlights() {
            slots.forEach(function (slot) {
                var hit = slot.textLayer.querySelectorAll('.rr-tl-hit');
                for (var i = 0; i < hit.length; i++) { hit[i].classList.remove('rr-tl-hit'); }
            });
        }

        function clearFind() {
            matches = []; matchIdx = -1; activeTerms = [];
            while (findResults.firstChild) { findResults.removeChild(findResults.firstChild); }
            findCount.textContent = '';
            findPrev.disabled = true; findNext.disabled = true;
        }

        function gotoMatch(i) {
            if (!matches.length) { return; }
            matchIdx = (i + matches.length) % matches.length;
            findCount.textContent = (matchIdx + 1) + ' of ' + matches.length + (matches.length === 1 ? ' page' : ' pages');
            var pn = matches[matchIdx];
            if (pn && pn > 0) { go(pn); } // go() opens the spread containing pn
        }

        function renderFindResults(pages) {
            while (findResults.firstChild) { findResults.removeChild(findResults.firstChild); }
            matches = [];
            pages.forEach(function (p) {
                var pn = (typeof p.page_number === 'number') ? p.page_number : null;
                matches.push(pn);
                var li = document.createElement('li');
                var btn = el('button', 'rr-reader__find-hit', { type: 'button' });
                var label = pn ? ('Page ' + pn) : 'Document text';
                var b = document.createElement('b');
                b.textContent = label;
                btn.appendChild(b);
                appendHighlighted(btn, p.snippet || '', activeTerms);
                btn.addEventListener('click', function () {
                    var idx = matches.indexOf(pn);
                    gotoMatch(idx >= 0 ? idx : 0);
                });

                if (!citeOn) {
                    li.appendChild(btn);
                    findResults.appendChild(li);
                    return;
                }

                // The search response carries exact offsets for this hit, which
                // is everything a span citation needs. Hits where the server
                // could not locate a span fall back to citing the page.
                var hasSpan = (typeof p.offset_start === 'number' && typeof p.offset_end === 'number');
                var start = hasSpan ? p.offset_start : null;
                var end = hasSpan ? p.offset_end : null;
                var row = el('div', 'rr-reader__find-row');
                var cite = el('button', 'rr-reader__find-cite', {
                    type: 'button',
                    'aria-label': hasSpan
                        ? ('Cite this passage on ' + (pn ? 'page ' + pn : 'the document text'))
                        : ('Cite ' + (pn ? 'page ' + pn : 'the document text'))
                });
                cite.textContent = 'Cite';
                cite.addEventListener('click', function () { showCite(pn, start, end); });
                row.appendChild(btn);
                row.appendChild(cite);
                li.appendChild(row);
                findResults.appendChild(li);
            });
            findPrev.disabled = matches.length <= 1;
            findNext.disabled = matches.length <= 1;
            findCount.textContent = matches.length
                ? (matches.length + (matches.length === 1 ? ' page' : ' pages'))
                : 'No matches';
        }

        // Fetched once, on the first search, and kept for the page's life.
        var pagesPromise = null;
        function localPages() {
            if (!pagesPromise) {
                pagesPromise = fetch(pagesUrl, { credentials: 'same-origin' })
                    .then(function (r) { return r.ok ? r.json() : null; })
                    .then(function (json) { return (json && Array.isArray(json.pages)) ? json.pages : null; })
                    .catch(function () { return null; })
                    .then(function (pages) { if (!pages) { pagesPromise = null; } return pages; });
            }
            return pagesPromise;
        }

        function findRequest(val) {
            if (pagesUrl) {
                return localPages().then(function (pages) {
                    return pages ? { pages: R.searchPages(pages, val, 50) } : null;
                });
            }
            if (findCtrl) { try { findCtrl.abort(); } catch (e) {} }
            findCtrl = ('AbortController' in window) ? new AbortController() : null;
            var opts = findCtrl ? { signal: findCtrl.signal, credentials: 'same-origin' } : { credentials: 'same-origin' };
            var url = docSearchUrl + '?slug=' + encodeURIComponent(slug) + '&q=' + encodeURIComponent(val);
            return fetch(url, opts).then(function (r) { return r.ok ? r.json() : null; });
        }

        var findSeq = 0;
        function runFind(val) {
            activeTerms = queryTerms(val);
            var seq = ++findSeq;
            findRequest(val)
                .then(function (json) {
                    if (seq !== findSeq) { return; }  // a later query superseded this one
                    findQuery = val;
                    if (!json || !json.pages) { clearFind(); return; }
                    renderFindResults(json.pages);
                    clearAllHighlights();
                    slots.forEach(highlightSlot);
                })
                .catch(function (err) { if (!err || err.name !== 'AbortError') { clearFind(); } });
        }

        function scheduleFind(raw) {
            if (findTimer) { clearTimeout(findTimer); findTimer = null; }
            var val = (raw || '').trim();
            if (val.toLowerCase() === findQuery.toLowerCase()) { return; }
            if (!queryTerms(val).length) { findQuery = ''; clearFind(); clearAllHighlights(); return; }
            findTimer = setTimeout(function () { runFind(val); }, 250);
        }

        // ---- citations ----
        // Every string shown here comes from the passage route. Built as DOM
        // nodes so no server string is ever parsed as HTML.
        function renderProvenance(target, p) {
            while (target.firstChild) { target.removeChild(target.firstChild); }
            var bits = [];
            bits.push('Provenance: ' + (p.provenance_level || 'unknown'));
            if (typeof p.offset_start === 'number' && typeof p.offset_end === 'number') {
                bits.push('characters ' + p.offset_start + ' to ' + p.offset_end + ' of the page text');
            }
            bits.push(typeof p.ocr_confidence === 'number'
                ? 'OCR confidence ' + p.ocr_confidence.toFixed(3)
                : 'OCR confidence not recorded');
            target.appendChild(document.createTextNode(bits.join(' · ')));
            if (!p.stable_key) { return; }
            target.appendChild(document.createElement('br'));
            target.appendChild(document.createTextNode('Durable key: '));
            var code = document.createElement('code');
            code.textContent = p.stable_key;
            target.appendChild(code);
            target.appendChild(document.createElement('br'));
            target.appendChild(document.createTextNode(p.minted
                ? 'This span is a curated citation in this reading room.'
                : 'Derived from the published text on request. Nothing was recorded.'));
        }

        function copyFrom(btn, text, label) {
            R.copyText(text).then(function (ok) {
                if (ok) {
                    var was = btn.textContent;
                    btn.textContent = 'Copied';
                    citeLive.textContent = label + ' copied to the clipboard';
                    setTimeout(function () { btn.textContent = was; }, 1800);
                } else {
                    citeLive.textContent = 'Copy failed. Select the ' + label.toLowerCase() + ' text and copy it.';
                }
            });
        }

        function citeFailed() {
            citeNote.hidden = true;
            citeRef.textContent = 'This passage could not be resolved, so no citation is offered.';
            citeQuote.hidden = true;
            citeCopy.hidden = true;
            citeCopyQuote.hidden = true;
            citeProv.textContent = '';
            citeLive.textContent = 'Citation unavailable';
        }

        // The page's own citation from pages.json, or null (no pages file, no
        // cite on that page, or the file failed to load).
        function localCite(page) {
            if (!pagesUrl || !page) { return Promise.resolve(null); }
            return localPages().then(function (pages) {
                var hit = (pages || []).filter(function (p) { return p.n === page; })[0];
                var c = hit && hit.cite;
                return (c && typeof c.reference === 'string' && c.reference) ? c : null;
            });
        }

        // Shows a page citation from pages.json: the same strings the passage
        // route answers for that page, so nothing here is composed. `note` says
        // why a passage citation became a page one.
        function showPageCite(page, c, note) {
            citeTitle.textContent = 'Citation for page ' + page;
            citeNote.textContent = note || '';
            citeNote.hidden = !note;
            citeRef.textContent = c.reference;
            citeCopy.setAttribute('data-cite', c.reference);
            citeCopy.hidden = !copyOn;
            citeQuote.hidden = true;
            citeCopyQuote.hidden = true;
            renderProvenance(citeProv, { provenance_level: c.provenance_level, ocr_confidence: c.ocr_confidence,
                                         offset_start: null, offset_end: null, stable_key: null });
            citeLive.textContent = note ? 'Exact passage unavailable; citing page ' + page
                                        : citeTitle.textContent + ' ready';
            citePanel.focus();
        }

        function openPanel() {
            citePanel.hidden = false;
            citeTitle.textContent = 'Citation';
            citeNote.hidden = true;
            citeRef.textContent = 'Resolving…';
            citeQuote.hidden = true;
            citeCopy.hidden = true;
            citeCopyQuote.hidden = true;
            citeProv.textContent = '';
        }

        function showCite(page, start, end) {
            if (!citeOn) { return; }
            if (citeCtrl) { try { citeCtrl.abort(); } catch (e) {} }
            citeCtrl = null;
            var span = (typeof start === 'number' && typeof end === 'number');
            var seq = ++citeSeq;
            openPanel();
            if (!span) {
                localCite(page).then(function (c) {
                    if (seq !== citeSeq) { return; }
                    if (c) { showPageCite(page, c, ''); } else { askRoute(page, null, null, seq); }
                });
                return;
            }
            askRoute(page, start, end, seq);
        }

        function askRoute(page, start, end, seq) {
            var ctrl = ('AbortController' in window) ? new AbortController() : null;
            citeCtrl = ctrl;
            var opts = ctrl ? { signal: ctrl.signal, credentials: 'same-origin' } : { credentials: 'same-origin' };
            var timer = ctrl ? setTimeout(function () { try { ctrl.abort(); } catch (e) {} }, CITE_TIMEOUT_MS) : null;

            var url = passageUrl + (passageUrl.indexOf('?') === -1 ? '?' : '&') + 'slug=' + encodeURIComponent(slug);
            if (page) { url += '&page=' + encodeURIComponent(page); }
            if (typeof start === 'number' && typeof end === 'number') {
                url += '&start=' + encodeURIComponent(start) + '&end=' + encodeURIComponent(end);
            }

            // Any failure (offline, blocked, an error status, found:false, the
            // timeout) offers the page's own citation where pages.json has it.
            function failed() {
                if (seq !== citeSeq) { return; }
                localCite(page).then(function (c) {
                    if (seq !== citeSeq) { return; }
                    if (c) { showPageCite(page, c, 'The exact passage could not be resolved here; this cites the page.'); }
                    else { citeFailed(); }
                });
            }

            fetch(url, opts)
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (json) {
                    if (timer) { clearTimeout(timer); }
                    if (seq !== citeSeq) { return; }
                    if (!json || !json.found || !json.passage) { failed(); return; }
                    var p = json.passage;
                    citeTitle.textContent = (typeof p.page_number === 'number')
                        ? ('Citation for page ' + p.page_number)
                        : 'Citation for this document';
                    citeRef.textContent = json.reference || '';
                    citeCopy.setAttribute('data-cite', json.reference || '');
                    citeCopy.hidden = !copyOn || !json.reference;
                    if (p.text) {
                        citeQuote.textContent = p.text;
                        citeQuote.hidden = false;
                        citeCopyQuote.setAttribute('data-quote', p.text);
                        citeCopyQuote.hidden = !copyOn;
                    }
                    renderProvenance(citeProv, p);
                    citeLive.textContent = citeTitle.textContent + ' ready';
                    citePanel.focus();
                })
                .catch(function () {
                    if (timer) { clearTimeout(timer); }
                    // A newer citation aborted this one: it owns the panel now.
                    if (seq !== citeSeq) { return; }
                    failed();
                });
        }

        citeBtn.addEventListener('click', function () { showCite(shownPages[0] || pageNum, null, null); });
        citeClose.addEventListener('click', function () {
            citePanel.hidden = true;
            citeLive.textContent = '';
            if (citeOn) { citeBtn.focus(); }
        });
        citeCopy.addEventListener('click', function () {
            copyFrom(citeCopy, citeCopy.getAttribute('data-cite') || '', 'Citation');
        });
        citeCopyQuote.addEventListener('click', function () {
            copyFrom(citeCopyQuote, citeCopyQuote.getAttribute('data-quote') || '', 'Quote');
        });

        function toggleLightbox() {
            var active = container.classList.toggle('rr-reader--lightbox');
            if (enlargeBtn) {
                enlargeBtn.textContent = active ? 'Close' : 'Enlarge';
                enlargeBtn.setAttribute('aria-label', active ? 'Close enlarged reader' : 'Enlarge reader');
            }
            // Expose the overlay as a modal dialog to assistive tech; move focus in
            // on open and return it to the trigger on close so keyboard users are
            // not stranded. (Esc closes via escHandler.)
            if (active) {
                container.setAttribute('role', 'dialog');
                container.setAttribute('aria-modal', 'true');
                container.setAttribute('aria-label', 'Enlarged document reader');
                stage.focus();
            } else {
                container.removeAttribute('role');
                container.removeAttribute('aria-modal');
                container.removeAttribute('aria-label');
                if (enlargeBtn && typeof enlargeBtn.focus === 'function') { enlargeBtn.focus(); }
            }
            if (!active && document.fullscreenElement) {
                var exit = document.exitFullscreen || document.webkitExitFullscreen || document.mozCancelFullScreen || document.msExitFullscreen;
                if (exit) { exit.call(document).catch(function () {}); }
            }
            renderView();
        }

        function toggleFullscreen() {
            var isFS = !!(document.fullscreenElement || document.webkitFullscreenElement || document.mozFullScreenElement || document.msFullscreenElement);
            if (!isFS) {
                var req = container.requestFullscreen || container.webkitRequestFullscreen || container.mozRequestFullScreen || container.msRequestFullscreen;
                if (req) { req.call(container).catch(function () {}); }
            } else {
                var exit = document.exitFullscreen || document.webkitExitFullscreen || document.mozCancelFullScreen || document.msExitFullscreen;
                if (exit) { exit.call(document).catch(function () {}); }
            }
        }

        prev.addEventListener('click', function () { navStep(-1); });
        next.addEventListener('click', function () { navStep(1); });
        zoomIn.addEventListener('click', function () { zoomStep = clampZoom(zoomStep + 1); renderView(); });
        zoomOut.addEventListener('click', function () { zoomStep = clampZoom(zoomStep - 1); renderView(); });
        if (viewBtn) {
            viewBtn.addEventListener('click', function () { toggleView(); });
        }
        pageInput.addEventListener('change', function () { go(parseInt(pageInput.value, 10) || 1); });

        if (enlargeBtn) {
            enlargeBtn.addEventListener('click', toggleLightbox);
        }
        if (fullscreenBtn) {
            fullscreenBtn.addEventListener('click', toggleFullscreen);
            var fsChangeHandler = function () {
                var isFS = (document.fullscreenElement === container || document.webkitFullscreenElement === container || document.mozFullScreenElement === container || document.msFullscreenElement === container);
                fullscreenBtn.textContent = isFS ? 'Exit Fullscreen' : 'Fullscreen';
                fullscreenBtn.setAttribute('aria-pressed', isFS ? 'true' : 'false');
            };
            document.addEventListener('fullscreenchange', fsChangeHandler);
            document.addEventListener('webkitfullscreenchange', fsChangeHandler);
            document.addEventListener('mozfullscreenchange', fsChangeHandler);
            document.addEventListener('MSFullscreenChange', fsChangeHandler);
        }

        var escHandler = function (e) {
            if (e.key === 'Escape' && container.classList.contains('rr-reader--lightbox')) {
                toggleLightbox();
            }
        };
        window.addEventListener('keydown', escHandler);

        // Focus trap for the lightbox overlay (a CSS modal, not native fullscreen,
        // so the browser does not constrain Tab for us). While open, Tab / Shift+Tab
        // cycle within the reader's own controls instead of escaping to the page
        // behind. Native :fullscreen already confines focus, so we only trap the
        // lightbox class.
        function focusableEls() {
            var sel = 'button:not([disabled]),[href],input:not([disabled]),[tabindex]:not([tabindex="-1"])';
            return Array.prototype.filter.call(container.querySelectorAll(sel), function (node) {
                return node.offsetWidth > 0 || node.offsetHeight > 0 || node === document.activeElement;
            });
        }
        container.addEventListener('keydown', function (e) {
            if (e.key !== 'Tab' || !container.classList.contains('rr-reader--lightbox')) { return; }
            var foc = focusableEls();
            if (!foc.length) { return; }
            var first = foc[0], last = foc[foc.length - 1];
            if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
            else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
            else if (foc.indexOf(document.activeElement) === -1) { e.preventDefault(); first.focus(); }
        });

        findInput.addEventListener('input', function () { scheduleFind(findInput.value); });
        findInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') { e.preventDefault(); if (matches.length) { gotoMatch(matchIdx + 1); } else { scheduleFind(findInput.value); } }
        });
        findPrev.addEventListener('click', function () { gotoMatch(matchIdx - 1); });
        findNext.addEventListener('click', function () { gotoMatch(matchIdx + 1); });
        stage.addEventListener('keydown', function (e) {
            if (e.key === 'ArrowRight' || e.key === 'PageDown') { e.preventDefault(); navStep(1); }
            else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); navStep(-1); }
            else if (e.key === '+' || e.key === '=') { e.preventDefault(); zoomStep = clampZoom(zoomStep + 1); renderView(); }
            else if (e.key === '-') { e.preventDefault(); zoomStep = clampZoom(zoomStep - 1); renderView(); }
        });
        window.addEventListener('resize', function () {
            if (!pdfDoc) { return; }
            window.clearTimeout(resizeTimer);
            // A resize may cross the spread breakpoint (mode flip) — renderView's
            // ensureStage() rebuilds the DOM when effectiveMode changes.
            resizeTimer = window.setTimeout(function () { renderView(); }, 180);
        });
        window.addEventListener('hashchange', function () {
            var hp = pageFromHash();
            if (hp >= 1) { go(hp); }
        });

        function withPdfJs(cb) {
            if (window.pdfjsLib) {
                if (config.pdfWorkerUrl) { window.pdfjsLib.GlobalWorkerOptions.workerSrc = config.pdfWorkerUrl; }
                return cb();
            }
            if (!config.pdfJsUrl) { R.fail(container, R.msg('loadFailed', 'The PDF reader is unavailable. Use the open or download buttons.')); return; }
            var s = document.createElement('script');
            s.src = config.pdfJsUrl; s.async = true;
            s.addEventListener('load', function () {
                if (window.pdfjsLib && config.pdfWorkerUrl) { window.pdfjsLib.GlobalWorkerOptions.workerSrc = config.pdfWorkerUrl; }
                cb();
            });
            s.addEventListener('error', function () { R.fail(container, R.msg('loadFailed', 'The PDF reader could not load. Use the open or download buttons.')); });
            document.head.appendChild(s);
        }

        withPdfJs(function () {
            if (!window.pdfjsLib) { R.fail(container, R.msg('loadFailed', 'The PDF reader is unavailable. Use the open or download buttons.')); return; }
            setStatus(R.msg('loading', 'Loading PDF…'));
            // Large scans can take a long time over a slow link. Do not leave the
            // reader staring at "Loading": after a while, offer the file directly
            // while the load continues in the background.
            loadTimer = window.setTimeout(function () {
                if (!pdfDoc) {
                    R.fail(container, R.msg('slowLoad', 'This file is taking a long time to load. You can keep waiting or open it directly.'));
                }
            }, config.slowLoadMs > 0 ? config.slowLoadMs : LOAD_SLOW_MS);
            window.pdfjsLib.getDocument(ctx.fileUrl).promise.then(function (pdf) {
                window.clearTimeout(loadTimer);
                // A slow load already put the fallback links back; the reader
                // has the file now, so take the page back from them.
                container.removeAttribute('data-reader-failed');
                var restored = container.querySelector('[data-reader-fallback]');
                if (restored) { restored.parentNode.removeChild(restored); }
                pdfDoc = pdf;
                var hp = pageFromHash();
                pageNum = (hp >= 1) ? Math.min(hp, pdf.numPages) : 1;
                ensureStage();
                renderView();
                R.emit(container, 'ready', { total: pdf.numPages, slug: slug });
            }).catch(function () {
                window.clearTimeout(loadTimer);
                R.fail(container, R.msg('loadFailed', 'The reader could not open this PDF. Use the open or download buttons.'));
            });
        });
    }

    window.RRReader.register({
        id: 'pdf',
        accepts: function (ext, mime) { return ext === 'pdf' || mime === 'application/pdf'; },
        mount: mount
    });
})();
