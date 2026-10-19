(function () {
    'use strict';

    // Multi-page scan & image viewer with OCR-to-image verification.
    // Supports single images (jpg, png, webp, svg, tiff), multi-page scan sets,
    // zoom, 90-degree rotation, side-by-side OCR verification transcript pane,
    // coordinate bounding box highlights, and client-side in-document search.

    if (!window.RRReader) {
        return;
    }

    var EXTS = { jpg: 1, jpeg: 1, png: 1, gif: 1, webp: 1, svg: 1, tiff: 1, tif: 1 };

    function accepts(ext, mime) {
        return !!EXTS[ext] || (!!mime && mime.indexOf('image/') === 0);
    }

    function el(tag, cls, attrs) {
        var node = document.createElement(tag);
        if (cls) { node.className = cls; }
        if (attrs) {
            Object.keys(attrs).forEach(function (k) { node.setAttribute(k, attrs[k]); });
        }
        return node;
    }

    function injectStylesOnce() {
        if (document.getElementById('rr-reader-image-css')) { return; }
        var style = document.createElement('style');
        style.id = 'rr-reader-image-css';
        style.textContent = [
            '.rr-reader--image{display:grid;gap:.75rem;}',
            '.rr-reader--image.rr-reader--mounted{border:1px solid var(--rr-rule,oklch(85% .012 80));border-radius:4px;background:var(--rr-paper,oklch(97% .008 85));color:var(--rr-ink,oklch(25% .02 60));padding:.85rem;}',
            '.rr-reader__toolbar{display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;}',
            '.rr-reader__btn{min-height:44px;min-width:44px;padding:.5rem .85rem;border:1px solid var(--rr-ink,oklch(25% .02 60));border-radius:3px;background:var(--rr-ink,oklch(25% .02 60));color:var(--rr-paper,oklch(97% .008 85));font-family:var(--rr-mono,ui-monospace,Menlo,Consolas,monospace);font-size:.8rem;letter-spacing:.03em;cursor:pointer;}',
            '.rr-reader__btn:hover:not(:disabled){background:var(--rr-accent,oklch(48% .13 25));border-color:var(--rr-accent,oklch(48% .13 25));}',
            '.rr-reader__btn:disabled{opacity:.4;cursor:default;}',
            '.rr-reader__btn--zoom{min-width:44px;padding:.5rem .75rem;font-size:1.1rem;line-height:1;}',
            '.rr-reader__btn[aria-pressed="true"]{background:var(--rr-accent,oklch(48% .13 25));border-color:var(--rr-accent,oklch(48% .13 25));color:#fff;}',
            '.rr-reader__btn:focus-visible,.rr-reader input.rr-reader__page-input:focus-visible,.rr-reader input.rr-reader__find-input:focus-visible{outline:2px solid var(--rr-focus,oklch(48% .13 25));outline-offset:2px;}',
            '.rr-reader__pageinfo{display:inline-flex;align-items:center;gap:.35rem;font-family:var(--rr-mono,ui-monospace,monospace);font-size:.82rem;color:var(--rr-ink-soft,oklch(45% .02 60));margin-left:auto;}',
            '.rr-reader input.rr-reader__page-input{width:3.5rem;min-height:44px;text-align:center;border:1px solid var(--rr-control-border,var(--rr-ink-soft,oklch(45% .02 60)));border-radius:3px;padding:.25rem;background:var(--rr-paper-raised,oklch(99% .004 85));color:var(--rr-ink,oklch(25% .02 60));font-family:var(--rr-mono,ui-monospace,monospace);}',
            '.rr-reader__page-total{color:var(--rr-ink-soft,oklch(45% .02 60));}',
            '.rr-reader__image-stage{position:relative;max-height:80vh;min-height:240px;overflow:auto;display:flex;justify-content:center;align-items:center;background:var(--rr-paper-raised,oklch(99% .004 85));border:1px solid var(--rr-rule,oklch(85% .012 80));border-radius:3px;padding:.5rem;}',
            '.rr-reader__image-stage:fullscreen{align-items:center;background:#000;max-height:100vh;}',
            '.rr-reader__image-wrap{position:relative;display:inline-block;transition:transform 0.15s ease-out;transform-origin:center center;}',
            '.rr-reader__image{max-width:100%;height:auto;display:block;box-shadow:0 1px 8px rgba(0,0,0,.15);background:#fff;}',
            '.rr-reader__image-stage:fullscreen .rr-reader__image{max-height:90vh;}',
            '.rr-reader__box-overlay{position:absolute;top:0;left:0;right:0;bottom:0;pointer-events:none;}',
            '.rr-reader__box{position:absolute;border:2px solid rgba(220,120,0,.75);background:rgba(255,200,0,.2);border-radius:2px;pointer-events:auto;cursor:pointer;transition:background .1s,border-color .1s;}',
            '.rr-reader__box:hover,.rr-reader__box.is-active{border-color:var(--rr-accent,oklch(48% .13 25));background:rgba(255,180,0,.45);outline:2px solid var(--rr-focus,oklch(48% .13 25));}',
            '.rr-reader__split{display:grid;grid-template-columns:1fr 1fr;gap:.75rem;align-items:stretch;}',
            '@media (max-width:768px){.rr-reader__split{grid-template-columns:1fr;}}',
            '.rr-reader__transcript-pane{max-height:80vh;overflow-y:auto;background:var(--rr-paper-raised,oklch(99% .004 85));border:1px solid var(--rr-rule,oklch(85% .012 80));border-radius:3px;padding:.85rem;font-family:var(--rr-font-sans,system-ui,sans-serif);line-height:1.6;}',
            '.rr-reader__transcript-head{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--rr-rule,oklch(85% .012 80));padding-bottom:.5rem;margin-bottom:.75rem;font-family:var(--rr-mono,ui-monospace,monospace);font-size:.8rem;color:var(--rr-ink-soft,oklch(45% .02 60));}',
            '.rr-reader__transcript-badge{background:var(--rr-paper,oklch(97% .008 85));border:1px solid var(--rr-rule,oklch(85% .012 80));border-radius:3px;padding:.15rem .4rem;text-transform:uppercase;font-size:.75rem;}',
            '.rr-reader__transcript-body{white-space:pre-wrap;word-break:break-word;font-size:.92rem;}',
            '.rr-reader__transcript-token{cursor:pointer;border-radius:2px;padding:0 1px;}',
            '.rr-reader__transcript-token:hover,.rr-reader__transcript-token.is-active{background:rgba(255,205,0,.45);outline:1px solid var(--rr-accent,oklch(48% .13 25));}',
            '.rr-reader__transcript-token.rr-tl-hit{background:rgba(255,205,0,.65);}',
            '.rr-reader__find{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;margin:.4rem 0;}',
            '.rr-reader input.rr-reader__find-input{flex:1 1 12rem;min-width:8rem;min-height:44px;padding:.35rem .5rem;font:inherit;border:1px solid var(--rr-control-border,var(--rr-ink-soft,oklch(45% .02 60)));border-radius:3px;background:var(--rr-paper-raised,oklch(99% .004 85));color:var(--rr-ink,oklch(25% .02 60));}',
            '.rr-reader input.rr-reader__find-input::placeholder{color:var(--rr-ink-soft,oklch(45% .02 60));opacity:1;}',
            '.rr-reader__find-count{font-size:.85em;opacity:.8;min-width:6rem;}',
            '.rr-reader__find-results{list-style:none;margin:.25rem 0 0;padding:0;max-height:14rem;overflow:auto;border-top:1px solid rgba(127,127,127,.3);width:100%;}',
            '.rr-reader__find-results li{margin:0;}',
            '.rr-reader__find-hit{display:block;width:100%;text-align:left;background:none;border:0;border-bottom:1px solid rgba(127,127,127,.15);padding:.45rem .3rem;font:inherit;cursor:pointer;color:inherit;}',
            '.rr-reader__find-hit:hover,.rr-reader__find-hit:focus{background:rgba(127,127,127,.12);}',
            '.rr-reader__find-hit b{display:block;font-size:.8em;opacity:.75;margin-bottom:.15rem;}',
            '.rr-reader__find-hit mark{background:var(--rr-mark,#ffd84d);color:var(--rr-mark-ink,#1b1b1b);}'
        ].join('');
        document.head.appendChild(style);
    }

    function parseHash() {
        var h = window.location.hash || '';
        var matchPage = h.match(/page[=-](\d+)/i);
        var page = matchPage ? parseInt(matchPage[1], 10) : 1;
        var matchBox = h.match(/box=([0-9.]+),([0-9.]+),([0-9.]+),([0-9.]+)/i);
        var box = matchBox ? [parseFloat(matchBox[1]), parseFloat(matchBox[2]), parseFloat(matchBox[3]), parseFloat(matchBox[4])] : null;
        return { page: page, box: box };
    }

    function mount(container, ctx) {
        var R = window.RRReader;
        injectStylesOnce();

        var title = container.getAttribute('data-title') || '';
        var status = container.querySelector('[data-reader-status]');
        var pagesUrl = container.getAttribute('data-pages-url') || '';

        container.classList.add('rr-reader--image');
        container.classList.add('rr-reader--mounted');

        var pagesData = null;
        var currentPage = 1;
        var totalPages = 1;
        var zoom = 1.0;
        var rotation = 0;
        var showTranscript = false;
        var activeBoxTarget = null;

        // Stage & elements
        var mainLayout = el('div', 'rr-reader__main');
        var stage = el('div', 'rr-reader__image-stage');
        var imgWrap = el('div', 'rr-reader__image-wrap');
        var img = el('img', 'rr-reader__image');
        img.alt = title ? ('Scan of ' + title) : 'Document scan';
        img.decoding = 'async';
        var boxOverlay = el('div', 'rr-reader__box-overlay');

        imgWrap.appendChild(img);
        imgWrap.appendChild(boxOverlay);
        stage.appendChild(imgWrap);

        var transcriptPane = el('div', 'rr-reader__transcript-pane');
        transcriptPane.hidden = true;

        // Toolbar
        var toolbar = el('div', 'rr-reader__toolbar', { role: 'toolbar', 'aria-label': 'Scan viewer controls' });
        var prevBtn = el('button', 'rr-reader__btn', { type: 'button', 'aria-label': 'Previous page' });
        prevBtn.textContent = 'Prev'; prevBtn.disabled = true;

        var pageWrap = el('span', 'rr-reader__pageinfo');
        var pageInput = el('input', 'rr-reader__page-input', { type: 'text', inputmode: 'numeric', 'aria-label': 'Go to page', value: '1' });
        var pageTotal = el('span', 'rr-reader__page-total'); pageTotal.textContent = '/ 1';
        pageWrap.appendChild(pageInput);
        pageWrap.appendChild(pageTotal);

        var nextBtn = el('button', 'rr-reader__btn', { type: 'button', 'aria-label': 'Next page' });
        nextBtn.textContent = 'Next'; nextBtn.disabled = true;

        var zoomOutBtn = el('button', 'rr-reader__btn rr-reader__btn--zoom', { type: 'button', 'aria-label': 'Zoom out' });
        zoomOutBtn.textContent = '−';
        var zoomResetBtn = el('button', 'rr-reader__btn', { type: 'button', 'aria-label': 'Reset zoom' });
        zoomResetBtn.textContent = '100%';
        var zoomInBtn = el('button', 'rr-reader__btn rr-reader__btn--zoom', { type: 'button', 'aria-label': 'Zoom in' });
        zoomInBtn.textContent = '+';

        var rotateBtn = el('button', 'rr-reader__btn', { type: 'button', 'aria-label': 'Rotate 90 degrees clockwise' });
        rotateBtn.textContent = '↻';

        var transcriptToggleBtn = el('button', 'rr-reader__btn', { type: 'button', 'aria-label': 'Toggle OCR transcript', 'aria-pressed': 'false' });
        transcriptToggleBtn.textContent = 'Transcript';
        transcriptToggleBtn.hidden = true;

        var fsBtn = null;
        if (stage.requestFullscreen) {
            fsBtn = el('button', 'rr-reader__btn', { type: 'button', 'aria-label': 'View full screen' });
            fsBtn.textContent = 'Fullscreen';
            fsBtn.addEventListener('click', function () {
                if (document.fullscreenElement) {
                    document.exitFullscreen().catch(function () {});
                } else {
                    stage.requestFullscreen().catch(function () {});
                }
            });
        }

        toolbar.appendChild(prevBtn);
        toolbar.appendChild(pageWrap);
        toolbar.appendChild(nextBtn);
        toolbar.appendChild(zoomOutBtn);
        toolbar.appendChild(zoomResetBtn);
        toolbar.appendChild(zoomInBtn);
        toolbar.appendChild(rotateBtn);
        toolbar.appendChild(transcriptToggleBtn);
        if (fsBtn) { toolbar.appendChild(fsBtn); }

        // In-document search
        var findWrap = el('div', 'rr-reader__find', { role: 'search' });
        findWrap.hidden = true;
        var findInput = el('input', 'rr-reader__find-input', { type: 'search', 'aria-label': 'Search scan transcripts', placeholder: 'Search scan text…' });
        var findPrev = el('button', 'rr-reader__btn', { type: 'button', 'aria-label': 'Previous match' }); findPrev.textContent = '‹'; findPrev.disabled = true;
        var findNext = el('button', 'rr-reader__btn', { type: 'button', 'aria-label': 'Next match' }); findNext.textContent = '›'; findNext.disabled = true;
        var findCount = el('span', 'rr-reader__find-count');
        var findResults = el('ul', 'rr-reader__find-results');
        findResults.hidden = true;

        findWrap.appendChild(findInput);
        findWrap.appendChild(findPrev);
        findWrap.appendChild(findNext);
        findWrap.appendChild(findCount);
        findWrap.appendChild(findResults);

        function applyTransform() {
            imgWrap.style.transform = 'scale(' + zoom + ') rotate(' + rotation + 'deg)';
        }

        zoomInBtn.addEventListener('click', function () {
            zoom = Math.min(3.0, Math.round((zoom + 0.25) * 100) / 100);
            zoomResetBtn.textContent = Math.round(zoom * 100) + '%';
            applyTransform();
        });

        zoomOutBtn.addEventListener('click', function () {
            zoom = Math.max(0.5, Math.round((zoom - 0.25) * 100) / 100);
            zoomResetBtn.textContent = Math.round(zoom * 100) + '%';
            applyTransform();
        });

        zoomResetBtn.addEventListener('click', function () {
            zoom = 1.0;
            zoomResetBtn.textContent = '100%';
            applyTransform();
        });

        rotateBtn.addEventListener('click', function () {
            rotation = (rotation + 90) % 360;
            applyTransform();
        });

        function renderBoxes(boxes) {
            while (boxOverlay.firstChild) { boxOverlay.removeChild(boxOverlay.firstChild); }
            if (!Array.isArray(boxes) || !boxes.length) { return; }

            boxes.forEach(function (b, idx) {
                var coord = b.box;
                if (!Array.isArray(coord) || coord.length < 4) { return; }
                var ymin = coord[0], xmin = coord[1], ymax = coord[2], xmax = coord[3];
                var boxEl = el('div', 'rr-reader__box');
                boxEl.style.top = (ymin * 100) + '%';
                boxEl.style.left = (xmin * 100) + '%';
                boxEl.style.height = ((ymax - ymin) * 100) + '%';
                boxEl.style.width = ((xmax - xmin) * 100) + '%';
                boxEl.setAttribute('data-box-index', String(idx));
                if (b.text) { boxEl.title = b.text; }

                boxEl.addEventListener('click', function () {
                    activateBox(idx);
                });
                boxEl.addEventListener('mouseenter', function () {
                    highlightBoxAndToken(idx, true);
                });
                boxEl.addEventListener('mouseleave', function () {
                    highlightBoxAndToken(idx, false);
                });

                boxOverlay.appendChild(boxEl);
            });
        }

        function highlightBoxAndToken(idx, on) {
            var bEl = boxOverlay.querySelector('[data-box-index="' + idx + '"]');
            if (bEl) { bEl.classList.toggle('is-active', on); }
            var tEl = transcriptPane.querySelector('[data-box-index="' + idx + '"]');
            if (tEl) { tEl.classList.toggle('is-active', on); }
        }

        function activateBox(idx) {
            activeBoxTarget = idx;
            var bEl = boxOverlay.querySelector('[data-box-index="' + idx + '"]');
            if (bEl) {
                var allBoxes = boxOverlay.querySelectorAll('.rr-reader__box');
                for (var i = 0; i < allBoxes.length; i++) { allBoxes[i].classList.remove('is-active'); }
                bEl.classList.add('is-active');
            }
            var tEl = transcriptPane.querySelector('[data-box-index="' + idx + '"]');
            if (tEl) {
                var allTokens = transcriptPane.querySelectorAll('.rr-reader__transcript-token');
                for (var j = 0; j < allTokens.length; j++) { allTokens[j].classList.remove('is-active'); }
                tEl.classList.add('is-active');
                tEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
        }

        function renderTranscript(page) {
            while (transcriptPane.firstChild) { transcriptPane.removeChild(transcriptPane.firstChild); }
            if (!page) { return; }

            var head = el('div', 'rr-reader__transcript-head');
            var titleSpan = el('span');
            titleSpan.textContent = 'Extracted Text (Page ' + page.n + ')';
            var provBadge = el('span', 'rr-reader__transcript-badge');
            provBadge.textContent = page.provenance || 'OCR';
            head.appendChild(titleSpan);
            head.appendChild(provBadge);
            transcriptPane.appendChild(head);

            var body = el('div', 'rr-reader__transcript-body');

            if (Array.isArray(page.boxes) && page.boxes.length > 0) {
                page.boxes.forEach(function (b, idx) {
                    var token = el('span', 'rr-reader__transcript-token');
                    token.textContent = (b.text || '') + ' ';
                    token.setAttribute('data-box-index', String(idx));
                    token.addEventListener('click', function () {
                        activateBox(idx);
                    });
                    token.addEventListener('mouseenter', function () {
                        highlightBoxAndToken(idx, true);
                    });
                    token.addEventListener('mouseleave', function () {
                        highlightBoxAndToken(idx, false);
                    });
                    body.appendChild(token);
                });
            } else {
                body.textContent = page.text || 'No text extracted for this page.';
            }

            transcriptPane.appendChild(body);
        }

        function updateLayout() {
            if (showTranscript) {
                mainLayout.className = 'rr-reader__split';
                transcriptPane.hidden = false;
                transcriptToggleBtn.setAttribute('aria-pressed', 'true');
            } else {
                mainLayout.className = 'rr-reader__main';
                transcriptPane.hidden = true;
                transcriptToggleBtn.setAttribute('aria-pressed', 'false');
            }
        }

        transcriptToggleBtn.addEventListener('click', function () {
            showTranscript = !showTranscript;
            updateLayout();
        });

        function displayPage(n) {
            if (n < 1) { n = 1; }
            if (n > totalPages) { n = totalPages; }
            currentPage = n;
            pageInput.value = String(n);
            prevBtn.disabled = (n <= 1);
            nextBtn.disabled = (n >= totalPages);

            var pageObj = (pagesData && pagesData[n - 1]) ? pagesData[n - 1] : null;
            var pageImgUrl = (pageObj && pageObj.image_url) ? pageObj.image_url : ctx.fileUrl;

            img.src = pageImgUrl;
            img.alt = title ? (totalPages > 1 ? (title + ' — Page ' + n) : ('Scan of ' + title)) : (totalPages > 1 ? ('Page ' + n) : 'Document image');

            if (pageObj) {
                renderBoxes(pageObj.boxes || []);
                renderTranscript(pageObj);
            } else {
                while (boxOverlay.firstChild) { boxOverlay.removeChild(boxOverlay.firstChild); }
                while (transcriptPane.firstChild) { transcriptPane.removeChild(transcriptPane.firstChild); }
            }
        }

        prevBtn.addEventListener('click', function () {
            if (currentPage > 1) { displayPage(currentPage - 1); }
        });

        nextBtn.addEventListener('click', function () {
            if (currentPage < totalPages) { displayPage(currentPage + 1); }
        });

        pageInput.addEventListener('change', function () {
            var val = parseInt(pageInput.value, 10);
            if (!isNaN(val)) { displayPage(val); }
            else { pageInput.value = String(currentPage); }
        });

        pageInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                var val = parseInt(pageInput.value, 10);
                if (!isNaN(val)) { displayPage(val); }
            }
        });

        // Search logic
        var searchHits = [];
        var activeHitIndex = -1;

        function runSearch(q) {
            if (!pagesData || !q) {
                searchHits = [];
                activeHitIndex = -1;
                findResults.hidden = true;
                findCount.textContent = '';
                findPrev.disabled = true;
                findNext.disabled = true;
                return;
            }
            searchHits = R.searchPages(pagesData, q, 100);
            while (findResults.firstChild) { findResults.removeChild(findResults.firstChild); }

            if (!searchHits.length) {
                findCount.textContent = 'No matches';
                findResults.hidden = true;
                findPrev.disabled = true;
                findNext.disabled = true;
                return;
            }

            findCount.textContent = searchHits.length + (searchHits.length === 1 ? ' match' : ' matches');
            findResults.hidden = false;
            findPrev.disabled = searchHits.length <= 1;
            findNext.disabled = searchHits.length <= 1;

            searchHits.forEach(function (hit, idx) {
                var li = el('li');
                var hitBtn = el('button', 'rr-reader__find-hit', { type: 'button' });
                var b = el('b');
                b.textContent = 'Page ' + hit.page_number;
                hitBtn.appendChild(b);
                var snip = el('span');
                snip.textContent = hit.snippet;
                hitBtn.appendChild(snip);

                hitBtn.addEventListener('click', function () {
                    activeHitIndex = idx;
                    displayPage(hit.page_number);
                    if (!showTranscript) {
                        showTranscript = true;
                        updateLayout();
                    }
                });
                li.appendChild(hitBtn);
                findResults.appendChild(li);
            });
        }

        findInput.addEventListener('input', function () {
            runSearch(findInput.value.trim());
        });

        findNext.addEventListener('click', function () {
            if (!searchHits.length) { return; }
            activeHitIndex = (activeHitIndex + 1) % searchHits.length;
            displayPage(searchHits[activeHitIndex].page_number);
        });

        findPrev.addEventListener('click', function () {
            if (!searchHits.length) { return; }
            activeHitIndex = (activeHitIndex - 1 + searchHits.length) % searchHits.length;
            displayPage(searchHits[activeHitIndex].page_number);
        });

        img.addEventListener('load', function () {
            if (status) { status.textContent = ''; }
            R.emit(container, 'ready', { total: totalPages });
        });

        img.addEventListener('error', function () {
            mainLayout.parentNode && mainLayout.parentNode.removeChild(mainLayout);
            toolbar.parentNode && toolbar.parentNode.removeChild(toolbar);
            findWrap.parentNode && findWrap.parentNode.removeChild(findWrap);
            R.fail(container, R.msg('loadFailed', 'The inline reader could not load this file. Use the open or download buttons.'));
        });

        mainLayout.appendChild(stage);
        mainLayout.appendChild(transcriptPane);

        container.appendChild(toolbar);
        container.appendChild(findWrap);
        container.appendChild(mainLayout);

        if (status) { status.textContent = R.msg('loading', 'Loading…'); }

        // Load pages.json if present
        if (pagesUrl) {
            fetch(pagesUrl, { credentials: 'same-origin' })
                .then(function (res) { return res.ok ? res.json() : null; })
                .then(function (data) {
                    if (data && Array.isArray(data.pages) && data.pages.length > 0) {
                        pagesData = data.pages;
                        totalPages = pagesData.length;
                        pageTotal.textContent = '/ ' + totalPages;

                        var hasText = pagesData.some(function (p) { return p.text && p.text.trim(); });
                        var hasBoxes = pagesData.some(function (p) { return Array.isArray(p.boxes) && p.boxes.length > 0; });

                        if (hasText || hasBoxes) {
                            transcriptToggleBtn.hidden = false;
                            findWrap.hidden = false;
                        }

                        if (totalPages > 1) {
                            nextBtn.disabled = false;
                        }
                    }
                    var initHash = parseHash();
                    displayPage(initHash.page);
                })
                .catch(function () {
                    // Fall back to single file view
                    displayPage(1);
                });
        } else {
            // Single image mode
            displayPage(1);
        }

        window.addEventListener('hashchange', function () {
            var h = parseHash();
            if (h.page !== currentPage) {
                displayPage(h.page);
            }
        });
    }

    window.RRReader.register({ id: 'image', accepts: accepts, mount: mount });
})();
