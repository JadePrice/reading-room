(function () {
    'use strict';

    // Archived web pages: an HTML mirror, or a page replayed from a WACZ web
    // archive. The site marks the mount with data-archive="html" or "wacz"; the
    // loader gives such a mount to this module ahead of the text viewer, which
    // would otherwise show an .html file as source.
    //
    // html: the mirror in an iframe with an empty sandbox attribute, so the
    //   archived page runs no script, cannot reach the room's origin, and cannot
    //   navigate the top window. It can still request what its markup names, so
    //   a site must send a CSP on its mirror files (default-src 'self') if no
    //   request may leave the origin; the archive tests check that header.
    // wacz: ReplayWeb.page (vendor/replaywebpage, AGPL-3.0, unmodified), loaded
    //   from config.replayBase, the directory holding its ui.js and sw.js. It
    //   replays snapshot.page at snapshot.ts out of the WACZ, reading the file
    //   by byte range. Adblock, Ruffle and the replayweb.page new-window base are
    //   all left off, so nothing is fetched from Webrecorder's hosts.
    //
    // Either way the site's provenance panel and fallback links (the mirror, the
    // WACZ download, the archives of record) are server markup and stay put:
    // this module only adds the viewer.

    if (!window.RRReader) {
        return;
    }

    var KINDS = { html: 1, wacz: 1 };
    var uiLoading = null; // one ui.js per page, shared by every wacz mount

    function kindOf(container) {
        return (container && container.getAttribute && (container.getAttribute('data-archive') || '').toLowerCase()) || '';
    }

    function claims(container) {
        return !!KINDS[kindOf(container)];
    }

    function accepts(ext) {
        return ext === 'wacz';
    }

    function injectStylesOnce() {
        if (document.getElementById('rr-reader-archive-css')) { return; }
        var style = document.createElement('style');
        style.id = 'rr-reader-archive-css';
        style.textContent = [
            '.rr-reader__archive-frame,.rr-reader__replay{display:block;width:100%;height:80vh;min-height:24rem;',
            'border:1px solid var(--rr-rule,oklch(85% .012 80));border-radius:3px;background:#fff;}',
            '.rr-reader__archive-frame:focus-visible{outline:2px solid var(--rr-focus,oklch(48% .13 25));outline-offset:2px;}'
        ].join('');
        document.head.appendChild(style);
    }

    function absolute(url) {
        try { return new URL(url, window.location.href).href; } catch (e) { return url; }
    }

    function insert(container, node) {
        var status = container.querySelector('[data-reader-status]');
        container.insertBefore(node, status || null);
    }

    function mountHtml(container, ctx) {
        var R = window.RRReader;
        var frame = document.createElement('iframe');
        frame.className = 'rr-reader__archive-frame';
        // Empty sandbox: no scripts, no forms, no popups, an opaque origin.
        frame.setAttribute('sandbox', '');
        frame.setAttribute('referrerpolicy', 'no-referrer');
        frame.setAttribute('title', 'Archived copy: ' + (container.getAttribute('data-title') || 'web page'));
        frame.src = ctx.fileUrl;
        frame.addEventListener('load', function () {
            R.setStatus(container, R.msg('archiveHtml', 'Archived copy of a web page. Its scripts and forms are turned off.'));
            R.emit(container, 'ready', { total: 1, archive: 'html' });
        });
        insert(container, frame);
    }

    function loadUi(base) {
        if (window.customElements && window.customElements.get('replay-web-page')) {
            return Promise.resolve();
        }
        if (!uiLoading) {
            uiLoading = new Promise(function (resolve, reject) {
                var s = document.createElement('script');
                s.src = base + 'ui.js';
                s.onload = function () { resolve(); };
                s.onerror = function () { uiLoading = null; reject(new Error('ui.js')); };
                document.head.appendChild(s);
            });
        }
        return uiLoading;
    }

    function mountWacz(container, ctx) {
        var R = window.RRReader;
        var base = (ctx.config && ctx.config.replayBase) || '';
        if (!base || !('serviceWorker' in navigator)) {
            R.fail(container, R.msg('archiveUnavailable', 'This browser cannot replay the web archive here. Use the links below.'));
            return;
        }
        if (base.charAt(base.length - 1) !== '/') { base += '/'; }
        R.setStatus(container, R.msg('archiveLoading', 'Loading the web archive…'));
        loadUi(base).then(function () {
            var el = document.createElement('replay-web-page');
            el.className = 'rr-reader__replay';
            el.setAttribute('source', absolute(ctx.fileUrl));
            el.setAttribute('replayBase', base);
            el.setAttribute('embed', 'replay-with-info');
            // New windows open in this room, never on replayweb.page.
            el.setAttribute('newWindowBase', absolute(base));
            var page = container.getAttribute('data-archive-page');
            var ts = container.getAttribute('data-archive-ts');
            if (page) { el.setAttribute('url', page); }
            if (ts) { el.setAttribute('ts', ts); }
            insert(container, el);
            R.setStatus(container, R.msg('archiveWacz', 'Replayed from a web archive (WACZ). The archive info button shows how and when it was captured.'));
            R.emit(container, 'ready', { total: 1, archive: 'wacz' });
        }, function () {
            R.fail(container, R.msg('archiveUnavailable', 'This browser cannot replay the web archive here. Use the links below.'));
        });
    }

    function mount(container, ctx) {
        injectStylesOnce();
        container.classList.add('rr-reader--archive');
        var kind = kindOf(container) || (ctx.ext === 'wacz' ? 'wacz' : '');
        if (kind === 'html') {
            mountHtml(container, ctx);
        } else {
            mountWacz(container, ctx);
        }
    }

    window.RRReader.register({ id: 'archive', claims: claims, accepts: accepts, mount: mount });
})();
