(function () {
    'use strict';

    // Tabular data viewer (CSV/TSV): interactive accessible grid with RFC 4180 parsing,
    // column sorting, client-side pagination, quick filtering, row/cell deep-linking,
    // and citation copying. Pure vanilla DOM, 0 dependencies, XSS-immune.

    if (!window.RRReader) {
        return;
    }

    var MAX_TABLE_SIZE = 5 * 1024 * 1024; // 5 MB; larger files fall back to download
    var EXTS = { csv: 1, tsv: 1 };

    function accepts(ext, mime) {
        return !!EXTS[ext] || mime === 'text/csv' || mime === 'text/tab-separated-values';
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
        if (document.getElementById('rr-reader-table-css')) { return; }
        var style = document.createElement('style');
        style.id = 'rr-reader-table-css';
        style.textContent = [
            '.rr-reader--table{display:grid;gap:.75rem;}',
            '.rr-reader--table.rr-reader--mounted{border:1px solid var(--rr-rule,oklch(85% .012 80));border-radius:4px;background:var(--rr-paper,oklch(97% .008 85));color:var(--rr-ink,oklch(25% .02 60));padding:.85rem;}',
            '.rr-reader__table-toolbar{display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;}',
            '.rr-reader__table-filter{flex:1 1 12rem;min-width:8rem;min-height:44px;padding:.35rem .6rem;font:inherit;font-size:.85rem;border:1px solid var(--rr-control-border,var(--rr-ink-soft,oklch(45% .02 60)));border-radius:3px;background:var(--rr-paper-raised,oklch(99% .004 85));color:var(--rr-ink,oklch(25% .02 60));}',
            '.rr-reader__table-filter::placeholder{color:var(--rr-ink-soft,oklch(45% .02 60));opacity:1;}',
            '.rr-reader__table-filter:focus-visible,.rr-reader__table-wrap:focus-visible{outline:2px solid var(--rr-focus,oklch(48% .13 25));outline-offset:2px;}',
            '.rr-reader__table-wrap{max-height:75vh;overflow:auto;border:1px solid var(--rr-rule,oklch(85% .012 80));border-radius:3px;background:var(--rr-paper-raised,oklch(99% .004 85));position:relative;}',
            '.rr-reader__grid{width:100%;border-collapse:collapse;font-family:var(--rr-mono,ui-monospace,Menlo,Consolas,monospace);font-size:.82rem;line-height:1.45;text-align:left;}',
            '.rr-reader__grid th,.rr-reader__grid td{padding:.45rem .65rem;border-bottom:1px solid var(--rr-rule,oklch(85% .012 80));border-right:1px solid var(--rr-rule,oklch(85% .012 80));white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:320px;}',
            '.rr-reader__grid th{position:sticky;top:0;z-index:3;background:var(--rr-paper,oklch(97% .008 85));color:var(--rr-ink,oklch(25% .02 60));font-weight:600;cursor:pointer;user-select:none;}',
            '.rr-reader__grid th:hover{background:var(--rr-paper-raised,oklch(99% .004 85));color:var(--rr-accent,oklch(48% .13 25));}',
            '.rr-reader__grid th:focus-visible{outline:2px solid var(--rr-focus,oklch(48% .13 25));outline-offset:-2px;}',
            '.rr-reader__grid th .rr-sort-indicator{margin-left:.35rem;font-size:.75em;opacity:.7;}',
            '.rr-reader__grid-row-num{position:sticky;left:0;z-index:2;background:var(--rr-paper,oklch(97% .008 85));color:var(--rr-ink-soft,oklch(45% .02 60));text-align:right;width:3rem;min-width:3rem;max-width:3rem;font-size:.78rem;cursor:pointer;}',
            '.rr-reader__grid th.rr-reader__grid-row-num{z-index:4;cursor:default;}',
            '.rr-reader__grid tr:hover td{background:rgba(127,127,127,.08);}',
            '.rr-reader__grid tr.is-row-highlight td{background:rgba(255,205,0,.28);border-bottom-color:rgba(220,120,0,.6);}',
            '.rr-reader__grid td.is-cell-highlight{background:rgba(255,205,0,.5);outline:2px solid var(--rr-accent,oklch(48% .13 25));outline-offset:-2px;}',
            '.rr-reader__table-footer{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.5rem;font-family:var(--rr-mono,ui-monospace,monospace);font-size:.8rem;color:var(--rr-ink-soft,oklch(45% .02 60));}',
            '.rr-reader__table-pager{display:inline-flex;align-items:center;gap:.35rem;margin-left:auto;}',
            '.rr-reader__table-pagesize{background:var(--rr-paper-raised,oklch(99% .004 85));color:var(--rr-ink,oklch(25% .02 60));border:1px solid var(--rr-control-border,var(--rr-ink-soft,oklch(45% .02 60)));border-radius:3px;padding:.2rem .4rem;font:inherit;}',
            '.rr-reader__table-citation{padding:.5rem .75rem;background:var(--rr-paper-raised,oklch(99% .004 85));border:1px solid var(--rr-rule,oklch(85% .012 80));border-radius:3px;font-size:.82rem;display:flex;justify-content:space-between;align-items:center;gap:.5rem;}',
            '.rr-reader__table-citation-text{font-family:var(--rr-mono,ui-monospace,monospace);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}'
        ].join('');
        document.head.appendChild(style);
    }

    function parseDelimited(text, delimiter) {
        var rows = [];
        var curRow = [];
        var curField = '';
        var inQuotes = false;
        var i = 0;
        var len = text.length;

        if (!delimiter) {
            var firstLine = text.split('\n')[0] || '';
            delimiter = (firstLine.indexOf('\t') >= 0 && firstLine.split('\t').length > firstLine.split(',').length) ? '\t' : ',';
        }

        while (i < len) {
            var ch = text.charAt(i);
            if (inQuotes) {
                if (ch === '"') {
                    if (i + 1 < len && text.charAt(i + 1) === '"') {
                        curField += '"';
                        i += 2;
                        continue;
                    } else {
                        inQuotes = false;
                        i++;
                        continue;
                    }
                } else {
                    curField += ch;
                    i++;
                    continue;
                }
            } else {
                if (ch === '"') {
                    inQuotes = true;
                    i++;
                    continue;
                } else if (ch === delimiter) {
                    curRow.push(curField);
                    curField = '';
                    i++;
                    continue;
                } else if (ch === '\r') {
                    if (i + 1 < len && text.charAt(i + 1) === '\n') { i++; }
                    curRow.push(curField);
                    rows.push(curRow);
                    curRow = [];
                    curField = '';
                    i++;
                    continue;
                } else if (ch === '\n') {
                    curRow.push(curField);
                    rows.push(curRow);
                    curRow = [];
                    curField = '';
                    i++;
                    continue;
                } else {
                    curField += ch;
                    i++;
                    continue;
                }
            }
        }
        if (curField.length > 0 || curRow.length > 0) {
            curRow.push(curField);
            rows.push(curRow);
        }
        if (rows.length > 1 && rows[rows.length - 1].length === 1 && rows[rows.length - 1][0] === '') {
            rows.pop();
        }
        return { rows: rows, delimiter: delimiter };
    }

    function parseHash() {
        var h = window.location.hash || '';
        var rowMatch = h.match(/row[=-](\d+)/i);
        var colMatch = h.match(/col[=-](\d+)/i);
        var cellMatch = h.match(/cell[=-](\d+)[,-](\d+)/i);
        var row = cellMatch ? parseInt(cellMatch[1], 10) : (rowMatch ? parseInt(rowMatch[1], 10) : null);
        var col = cellMatch ? parseInt(cellMatch[2], 10) : (colMatch ? parseInt(colMatch[1], 10) : null);
        return { row: row, col: col };
    }

    function mount(container, ctx) {
        var R = window.RRReader;
        injectStylesOnce();

        var title = container.getAttribute('data-title') || 'Dataset';
        var status = container.querySelector('[data-reader-status]');

        container.classList.add('rr-reader--table');
        container.classList.add('rr-reader--mounted');

        var allHeaders = [];
        var allRows = [];      // Array of { originalIndex: int, cells: string[] }
        var filteredRows = []; // Sorted/filtered view of allRows
        var pageSize = 50;
        var currentPage = 0;
        var sortCol = -1;
        var sortDir = 'none';  // 'none' | 'asc' | 'desc'
        var activeRow = null;
        var activeCol = null;

        // Toolbar
        var toolbar = el('div', 'rr-reader__table-toolbar', { role: 'toolbar', 'aria-label': 'Table controls' });
        var filterInput = el('input', 'rr-reader__table-filter', { type: 'search', 'aria-label': 'Filter rows', placeholder: 'Filter rows…' });
        toolbar.appendChild(filterInput);

        // Grid Container
        var wrap = el('div', 'rr-reader__table-wrap', { tabindex: '0', role: 'region', 'aria-label': title + ' data grid' });
        var table = el('table', 'rr-reader__grid', { role: 'grid' });
        var thead = el('thead');
        var tbody = el('tbody');
        table.appendChild(thead);
        table.appendChild(tbody);
        wrap.appendChild(table);

        // Citation Bar
        var citationBar = el('div', 'rr-reader__table-citation');
        citationBar.hidden = true;
        var citationText = el('span', 'rr-reader__table-citation-text');
        var copyCiteBtn = el('button', 'rr-reader__btn', { type: 'button' });
        copyCiteBtn.textContent = 'Copy row citation';
        citationBar.appendChild(citationText);
        citationBar.appendChild(copyCiteBtn);

        // Footer / Pager
        var footer = el('div', 'rr-reader__table-footer');
        var rowInfo = el('span', 'rr-reader__table-count');

        var pager = el('div', 'rr-reader__table-pager');
        var sizeSelect = el('select', 'rr-reader__table-pagesize', { 'aria-label': 'Rows per page' });
        [25, 50, 100, 250].forEach(function (size) {
            var opt = el('option');
            opt.value = String(size);
            opt.textContent = size + ' rows';
            if (size === pageSize) { opt.selected = true; }
            sizeSelect.appendChild(opt);
        });

        var firstBtn = el('button', 'rr-reader__btn', { type: 'button', 'aria-label': 'First page' }); firstBtn.textContent = '«';
        var prevBtn = el('button', 'rr-reader__btn', { type: 'button', 'aria-label': 'Previous page' }); prevBtn.textContent = '‹';
        var pageInfo = el('span');
        var nextBtn = el('button', 'rr-reader__btn', { type: 'button', 'aria-label': 'Next page' }); nextBtn.textContent = '›';
        var lastBtn = el('button', 'rr-reader__btn', { type: 'button', 'aria-label': 'Last page' }); lastBtn.textContent = '»';

        pager.appendChild(sizeSelect);
        pager.appendChild(firstBtn);
        pager.appendChild(prevBtn);
        pager.appendChild(pageInfo);
        pager.appendChild(nextBtn);
        pager.appendChild(lastBtn);

        footer.appendChild(rowInfo);
        footer.appendChild(pager);

        function updateCitation(rowNum, colNum) {
            if (rowNum === null) {
                citationBar.hidden = true;
                return;
            }
            var rowObj = allRows[rowNum - 1];
            if (!rowObj) { return; }

            var ref = title + ', Row ' + rowNum;
            if (colNum !== null && allHeaders[colNum] && rowObj.cells[colNum] !== undefined) {
                ref += ' (' + allHeaders[colNum] + ': ' + rowObj.cells[colNum].trim() + ')';
            }
            citationText.textContent = ref;
            citationBar.hidden = false;
        }

        copyCiteBtn.addEventListener('click', function () {
            if (!citationText.textContent) { return; }
            R.copyText(citationText.textContent).then(function (ok) {
                if (ok) {
                    var orig = copyCiteBtn.textContent;
                    copyCiteBtn.textContent = 'Copied!';
                    setTimeout(function () { copyCiteBtn.textContent = orig; }, 2000);
                }
            });
        });

        function sortData(colIdx) {
            if (sortCol === colIdx) {
                if (sortDir === 'asc') { sortDir = 'desc'; }
                else if (sortDir === 'desc') { sortDir = 'none'; sortCol = -1; }
            } else {
                sortCol = colIdx;
                sortDir = 'asc';
            }
            applyFilterAndSort();
        }

        function applyFilterAndSort() {
            var q = filterInput.value.trim().toLowerCase();
            if (q) {
                filteredRows = allRows.filter(function (r) {
                    for (var i = 0; i < r.cells.length; i++) {
                        if (r.cells[i].toLowerCase().indexOf(q) >= 0) { return true; }
                    }
                    return false;
                });
            } else {
                filteredRows = allRows.slice();
            }

            if (sortCol >= 0 && sortDir !== 'none') {
                var c = sortCol;
                var asc = (sortDir === 'asc');
                filteredRows.sort(function (a, b) {
                    var vA = (a.cells[c] || '').trim();
                    var vB = (b.cells[c] || '').trim();
                    var nA = parseFloat(vA);
                    var nB = parseFloat(vB);
                    if (!isNaN(nA) && !isNaN(nB) && String(nA) === vA && String(nB) === vB) {
                        return asc ? (nA - nB) : (nB - nA);
                    }
                    return asc ? vA.localeCompare(vB) : vB.localeCompare(vA);
                });
            }

            currentPage = 0;
            renderPage();
            renderHeaders();
        }

        function renderHeaders() {
            while (thead.firstChild) { thead.removeChild(thead.firstChild); }
            var tr = el('tr');

            var thNum = el('th', 'rr-reader__grid-row-num', { scope: 'col' });
            thNum.textContent = '#';
            tr.appendChild(thNum);

            allHeaders.forEach(function (h, idx) {
                var th = el('th', '', { scope: 'col', tabindex: '0', role: 'columnheader' });
                th.textContent = h;

                if (sortCol === idx) {
                    var ind = el('span', 'rr-sort-indicator');
                    ind.textContent = sortDir === 'asc' ? '▲' : (sortDir === 'desc' ? '▼' : '');
                    th.appendChild(ind);
                    th.setAttribute('aria-sort', sortDir === 'asc' ? 'ascending' : 'descending');
                } else {
                    th.setAttribute('aria-sort', 'none');
                }

                th.addEventListener('click', function () { sortData(idx); });
                th.addEventListener('keydown', function (e) {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        sortData(idx);
                    }
                });
                tr.appendChild(th);
            });
            thead.appendChild(tr);
        }

        function renderPage() {
            while (tbody.firstChild) { tbody.removeChild(tbody.firstChild); }
            var total = filteredRows.length;
            var maxPage = Math.max(0, Math.ceil(total / pageSize) - 1);
            if (currentPage > maxPage) { currentPage = maxPage; }

            var start = currentPage * pageSize;
            var end = Math.min(start + pageSize, total);
            var pageSlice = filteredRows.slice(start, end);

            pageSlice.forEach(function (r) {
                var tr = el('tr');
                if (activeRow === r.originalIndex) { tr.classList.add('is-row-highlight'); }

                var tdNum = el('td', 'rr-reader__grid-row-num');
                tdNum.textContent = String(r.originalIndex);
                tdNum.title = 'Click to cite Row ' + r.originalIndex;
                tdNum.addEventListener('click', function () {
                    activeRow = r.originalIndex;
                    activeCol = null;
                    updateCitation(activeRow, null);
                    renderPage();
                });
                tr.appendChild(tdNum);

                r.cells.forEach(function (cellVal, colIdx) {
                    var td = el('td');
                    td.textContent = cellVal;
                    td.title = cellVal;
                    if (activeRow === r.originalIndex && activeCol === colIdx) {
                        td.classList.add('is-cell-highlight');
                    }
                    td.addEventListener('click', function () {
                        activeRow = r.originalIndex;
                        activeCol = colIdx;
                        updateCitation(activeRow, activeCol);
                        renderPage();
                    });
                    tr.appendChild(td);
                });
                tbody.appendChild(tr);
            });

            // Update Pager Controls
            rowInfo.textContent = total ? ('Showing ' + (start + 1) + '–' + end + ' of ' + total + ' rows') : '0 rows';
            pageInfo.textContent = (currentPage + 1) + ' / ' + (maxPage + 1);
            firstBtn.disabled = (currentPage === 0);
            prevBtn.disabled = (currentPage === 0);
            nextBtn.disabled = (currentPage >= maxPage);
            lastBtn.disabled = (currentPage >= maxPage);
        }

        firstBtn.addEventListener('click', function () { currentPage = 0; renderPage(); });
        prevBtn.addEventListener('click', function () { if (currentPage > 0) { currentPage--; renderPage(); } });
        nextBtn.addEventListener('click', function () { currentPage++; renderPage(); });
        lastBtn.addEventListener('click', function () {
            currentPage = Math.max(0, Math.ceil(filteredRows.length / pageSize) - 1);
            renderPage();
        });

        sizeSelect.addEventListener('change', function () {
            pageSize = parseInt(sizeSelect.value, 10);
            currentPage = 0;
            renderPage();
        });

        filterInput.addEventListener('input', function () {
            applyFilterAndSort();
        });

        container.appendChild(toolbar);
        container.appendChild(wrap);
        container.appendChild(citationBar);
        container.appendChild(footer);

        if (status) { status.textContent = R.msg('loading', 'Loading data…'); }

        fetch(ctx.fileUrl, { credentials: 'same-origin' })
            .then(function (r) {
                if (!r.ok) { throw new Error('HTTP ' + r.status); }
                var cl = r.headers.get('content-length');
                if (cl && parseInt(cl, 10) > MAX_TABLE_SIZE) { throw new Error('too-large'); }

                if (!r.body || !r.body.getReader) {
                    return r.text().then(function (t) {
                        if (t.length > MAX_TABLE_SIZE) { throw new Error('too-large'); }
                        return t;
                    });
                }
                var reader = r.body.getReader();
                var decoder = new TextDecoder();
                var text = '';
                var bytesRead = 0;
                function readChunk() {
                    return reader.read().then(function (result) {
                        if (result.done) { return text; }
                        bytesRead += result.value.byteLength;
                        if (bytesRead > MAX_TABLE_SIZE) {
                            reader.cancel();
                            throw new Error('too-large');
                        }
                        text += decoder.decode(result.value, { stream: true });
                        return readChunk();
                    });
                }
                return readChunk().then(function (finalText) {
                    return finalText + decoder.decode();
                });
            })
            .then(function (rawText) {
                var delim = (ctx.ext === 'tsv') ? '\t' : (ctx.ext === 'csv' ? ',' : null);
                var parsed = parseDelimited(rawText, delim);
                var rows = parsed.rows;
                if (!rows.length) {
                    allHeaders = ['(empty)'];
                    allRows = [];
                } else {
                    allHeaders = rows[0];
                    allRows = rows.slice(1).map(function (rowCells, idx) {
                        return { originalIndex: idx + 1, cells: rowCells };
                    });
                }
                filteredRows = allRows.slice();

                if (status) { status.textContent = ''; }
                renderHeaders();
                renderPage();

                // Process initial hash deep link (#row=N, #col=M)
                var hashTarget = parseHash();
                if (hashTarget.row !== null) {
                    activeRow = hashTarget.row;
                    activeCol = hashTarget.col;
                    currentPage = Math.floor((activeRow - 1) / pageSize);
                    renderPage();
                    updateCitation(activeRow, activeCol);
                }

                R.emit(container, 'ready', { total: allRows.length });
            })
            .catch(function (err) {
                // No dead controls beside the fallback links (as the image module).
                [toolbar, wrap, citationBar, footer].forEach(function (n) { if (n.parentNode) { n.parentNode.removeChild(n); } });
                if (err && err.message === 'too-large') {
                    R.fail(container, R.msg('tableTooLarge', 'This dataset is too large to preview inline. Use the download buttons.'));
                    return;
                }
                R.fail(container, R.msg('loadFailed', 'The inline reader could not load this file. Use the open or download buttons.'));
            });

        window.addEventListener('hashchange', function () {
            var target = parseHash();
            if (target.row !== null && target.row !== activeRow) {
                activeRow = target.row;
                activeCol = target.col;
                currentPage = Math.floor((activeRow - 1) / pageSize);
                renderPage();
                updateCitation(activeRow, activeCol);
            }
        });
    }

    window.RRReader.register({ id: 'table', accepts: accepts, mount: mount });
})();
