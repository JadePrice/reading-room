(function () {
    'use strict';

    // Plain-text viewer for txt/md/csv/json/xml/html. Shows the file's text
    // verbatim (HTML is shown as source, never rendered). Ported from
    // gg-reading-room's ggrr-reader-text.js (engine v0.4.0); the failure path
    // now builds its link as DOM nodes instead of innerHTML, and the size cap
    // also applies when the server sends no Content-Length.

    if (!window.RRReader) {
        return;
    }

    var MAX_TEXT_SIZE = 1024 * 1024; // 1 MB; bigger files go to the download link
    var EXTS = { txt: 1, text: 1, md: 1, csv: 1, json: 1, xml: 1, html: 1 };

    function accepts(ext, mime) {
        return !!EXTS[ext] || (!!mime && mime.indexOf('text/') === 0);
    }

    function injectStylesOnce() {
        if (document.getElementById('rr-reader-text-css')) { return; }
        var style = document.createElement('style');
        style.id = 'rr-reader-text-css';
        style.textContent = [
            '.rr-reader__text{margin:0;max-height:80vh;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;',
            'font-family:var(--rr-mono,ui-monospace,Menlo,Consolas,monospace);font-size:.875rem;line-height:1.5;padding:1rem;',
            'background:var(--rr-paper-raised,oklch(99% .004 85));color:var(--rr-ink,oklch(25% .02 60));',
            'border:1px solid var(--rr-rule,oklch(85% .012 80));border-radius:3px;}',
            '.rr-reader__text:focus-visible{outline:2px solid var(--rr-focus,oklch(48% .13 25));outline-offset:2px;}'
        ].join('');
        document.head.appendChild(style);
    }

    function mount(container, ctx) {
        var R = window.RRReader;
        injectStylesOnce();
        container.classList.add('rr-reader--text');
        R.setStatus(container, 'Loading text…');

        function tooBig() {
            R.fail(container, R.msg('textTooLarge', 'This text file is too large to show here.'));
        }

        fetch(ctx.fileUrl, { credentials: 'same-origin' })
            .then(function (r) {
                if (!r.ok) { throw new Error('HTTP ' + r.status); }
                var cl = r.headers.get('content-length');
                if (cl && parseInt(cl, 10) > MAX_TEXT_SIZE) { throw new Error('too-large'); }
                return r.text();
            })
            .then(function (text) {
                if (text.length > MAX_TEXT_SIZE) { tooBig(); return; }
                var pre = document.createElement('pre');
                pre.className = 'rr-reader__text';
                // Scrollable region: focusable so keyboard users can scroll it.
                pre.setAttribute('tabindex', '0');
                pre.setAttribute('role', 'region');
                pre.setAttribute('aria-label', 'Document text');
                pre.textContent = text;
                var status = container.querySelector('[data-reader-status]');
                container.insertBefore(pre, status || null);
                R.setStatus(container, '');
                R.emit(container, 'ready', { total: 1 });
            })
            .catch(function (err) {
                if (err && err.message === 'too-large') { tooBig(); return; }
                R.fail(container, R.msg('loadFailed', 'The inline reader could not load this file. Use the open or download buttons.'));
            });
    }

    window.RRReader.register({ id: 'text', accepts: accepts, mount: mount });
})();
