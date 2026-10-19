(function () {
    'use strict';

    // Image viewer: one <img>, fit to width, with an optional fullscreen
    // control. Ported from gg-reading-room's ggrr-reader-image.js (engine
    // v0.4.0); alt text now comes from the document title, the fullscreen
    // trigger is a real button, and a broken image falls back to a file link.

    if (!window.RRReader) {
        return;
    }

    var EXTS = { jpg: 1, jpeg: 1, png: 1, gif: 1, webp: 1, svg: 1 };

    function accepts(ext, mime) {
        return !!EXTS[ext] || (!!mime && mime.indexOf('image/') === 0);
    }

    function injectStylesOnce() {
        if (document.getElementById('rr-reader-image-css')) { return; }
        var style = document.createElement('style');
        style.id = 'rr-reader-image-css';
        style.textContent = [
            '.rr-reader--image{display:grid;gap:.75rem;}',
            '.rr-reader__image-stage{display:flex;justify-content:center;background:var(--rr-paper-raised,oklch(99% .004 85));border:1px solid var(--rr-rule,oklch(85% .012 80));border-radius:3px;padding:.5rem;}',
            '.rr-reader__image{max-width:100%;height:auto;display:block;}',
            '.rr-reader__image-stage:fullscreen{align-items:center;background:#000;}',
            '.rr-reader__image-stage:fullscreen .rr-reader__image{max-height:100vh;}'
        ].join('');
        document.head.appendChild(style);
    }

    function mount(container, ctx) {
        var R = window.RRReader;
        injectStylesOnce();
        var title = container.getAttribute('data-title') || '';
        var status = container.querySelector('[data-reader-status]');

        container.classList.add('rr-reader--image');
        var stage = document.createElement('div');
        stage.className = 'rr-reader__image-stage';
        var img = document.createElement('img');
        img.className = 'rr-reader__image';
        img.alt = title ? ('Scan of ' + title) : 'Document image';
        img.decoding = 'async';

        img.addEventListener('load', function () {
            if (status) { status.textContent = ''; }
            R.emit(container, 'ready', { total: 1 });
        });
        img.addEventListener('error', function () {
            stage.parentNode && stage.parentNode.removeChild(stage);
            if (fsBtn && fsBtn.parentNode) { fsBtn.parentNode.removeChild(fsBtn); }
            R.fail(container, R.msg('loadFailed', 'The inline reader could not load this file. Use the open or download buttons.'));
        });

        stage.appendChild(img);

        var fsBtn = null;
        if (stage.requestFullscreen) {
            fsBtn = document.createElement('button');
            fsBtn.type = 'button';
            fsBtn.className = 'rr-reader__btn';
            fsBtn.textContent = 'View full screen';
            fsBtn.addEventListener('click', function () {
                if (document.fullscreenElement) {
                    document.exitFullscreen().catch(function () {});
                } else {
                    stage.requestFullscreen().catch(function () {});
                }
            });
        }

        if (status) { status.textContent = R.msg('loading', 'Loading…'); }
        container.insertBefore(stage, status || null);
        if (fsBtn) { container.insertBefore(fsBtn, stage); }
        img.src = ctx.fileUrl;
    }

    window.RRReader.register({ id: 'image', accepts: accepts, mount: mount });
})();
