(function () {
    'use strict';

    // rr-read-aloud.js — browser-only read-aloud pilot (TTS slice 1).
    //
    // Site-side companion to the reading-room reader engine, NOT an engine
    // module: it is never vendored by sync.sh and the engine never knows
    // about it. Opt-in per mount via a data-read-aloud attribute; the panel
    // renders AFTER the mount (engine modules replace mount contents).
    //
    // Synthesis is window.speechSynthesis only: on-device client voices, zero
    // network egress, zero stored audio. No autoplay: speech starts on Play.
    // Text comes from the mount's data-pages-url (static mode) or a provider
    // override (RRReadAloud.setTextProvider). REST mounts with no provider get
    // an honest cannot-read note, never fabricated speech.

    var PANEL_CLASS = 'rr-aloud';
    var STYLE_ID = 'rr-aloud-style';
    var CHUNK_LEN = 200;

    var textProvider = null;
    var pagesCache = {}; // pagesUrl -> Promise<[{n, text}] | null>
    var wired = [];

    function setTextProvider(fn) {
        if (typeof fn === 'function') { textProvider = fn; }
    }

    function supported() {
        return ('speechSynthesis' in window) && ('SpeechSynthesisUtterance' in window);
    }

    function el(tag, cls, text) {
        var n = document.createElement(tag);
        if (cls) { n.className = cls; }
        if (text !== undefined && text !== null) { n.textContent = text; }
        return n;
    }

    function injectStyle() {
        if (document.getElementById(STYLE_ID)) { return; }
        var css = '' +
            '.rr-aloud{margin-top:12px;padding:10px 12px;border:1px solid var(--rr-rule,#d8d8d8);' +
            'background:var(--rr-paper-raised,#fff);color:var(--rr-ink-soft,#333);font-size:1rem;}' +
            '.rr-aloud__row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;}' +
            '.rr-aloud__row button,.rr-aloud__row select{min-height:44px;min-width:44px;' +
            'padding:8px 14px;font-size:1rem;color:var(--rr-ink-soft,#333);' +
            'background:var(--rr-paper-raised,#fff);' +
            'border:1px solid var(--rr-control-border,var(--rr-ink-soft,#333));border-radius:4px;}' +
            '.rr-aloud__row button{cursor:pointer;background:var(--rr-ink,#222);color:#fff;' +
            'border-color:var(--rr-ink,#222);}' +
            '.rr-aloud__row button[aria-pressed="true"]{background:var(--rr-accent,#0b6e99);' +
            'border-color:var(--rr-accent,#0b6e99);}' +
            '.rr-aloud__row button:focus-visible,.rr-aloud__row select:focus-visible{' +
            'outline:3px solid var(--rr-focus,#0b6e99);outline-offset:2px;}' +
            '.rr-aloud__row label{display:inline-flex;align-items:center;gap:6px;}' +
            '.rr-aloud p.rr-aloud__status{margin:8px 0 0;font-size:0.95rem;}' +
            '.rr-aloud p.rr-aloud__note{margin:6px 0 0;font-size:0.85rem;opacity:0.9;}';
        var s = document.createElement('style');
        s.id = STYLE_ID;
        s.setAttribute('type', 'text/css');
        if (s.styleSheet) { s.styleSheet.cssText = css; }
        else { s.appendChild(document.createTextNode(css)); }
        document.getElementsByTagName('head')[0].appendChild(s);
    }

    function fetchPages(pagesUrl) {
        if (!pagesCache[pagesUrl]) {
            pagesCache[pagesUrl] = fetch(pagesUrl, { credentials: 'same-origin' })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (json) { return (json && Array.isArray(json.pages)) ? json.pages : null; })
                .catch(function () { return null; })
                .then(function (pages) { if (!pages) { delete pagesCache[pagesUrl]; } return pages; });
        }
        return pagesCache[pagesUrl];
    }

    // Collapse whitespace AND rejoin OCR line-end hyphenation ("hear-\ning"
    // -> "hearing", including the ¬ continuation mark). Mirrors IA
    // BookReader's _removeDanglingHyphens: unfiltered fragments make voices
    // stutter or misread, the top user-facing TTS quality issue.
    function cleanText(text) {
        return String(text || '')
            .replace(/[-\u00AC]\s*\n\s*/g, '')
            .replace(/\s+/g, ' ')
            .trim();
    }

    // Split into speakable chunks at sentence boundaries, ~CHUNK_LEN max.
    // Chunking works around browsers that drop very long utterances.
    function chunkText(text) {
        var flat = cleanText(text);
        if (!flat) { return []; }
        var parts = flat.match(/[^.!?…]+[.!?…]+["'”’)]?|\S.*$/g) || [flat];
        var chunks = [];
        var cur = '';
        for (var i = 0; i < parts.length; i++) {
            var p = parts[i].trim();
            if (!p) { continue; }
            if ((cur + ' ' + p).trim().length <= CHUNK_LEN || !cur) {
                cur = (cur + ' ' + p).trim();
            } else {
                chunks.push(cur);
                cur = p;
            }
        }
        if (cur) { chunks.push(cur); }
        return chunks;
    }

    function pageLabel(pages, total) {
        if (!pages || !pages.length) { return 'Page 1 of ' + total; }
        var t = total || Math.max.apply(null, pages);
        return 'Page ' + pages.join(' and ') + ' of ' + t;
    }

    function pickVoice(voices, lang) {
        var want = String(lang || 'en').toLowerCase();
        var short = want.split(/[-_]/)[0];
        var i;
        for (i = 0; i < voices.length; i++) {
            if (String(voices[i].lang || '').toLowerCase() === want) { return voices[i]; }
        }
        for (i = 0; i < voices.length; i++) {
            if (String(voices[i].lang || '').toLowerCase().split(/[-_]/)[0] === short) { return voices[i]; }
        }
        return null;
    }

    function wire(container) {
        if (!container || container.getAttribute('data-aloud-wired') === '1') { return; }
        container.setAttribute('data-aloud-wired', '1');
        injectStyle();

        var slug = container.getAttribute('data-slug') || '';
        var lang = container.getAttribute('data-lang') || 'en';
        var pagesUrl = container.getAttribute('data-pages-url') || '';

        var state = {
            container: container,
            pages: [1],
            total: 1,
            chunks: [],
            index: 0,
            speaking: false,
            paused: false,
            voices: []
        };

        var panel = el('div', PANEL_CLASS);
        panel.setAttribute('data-aloud-panel', slug);
        var row = el('div', PANEL_CLASS + '__row');
        var playBtn = el('button', null, 'Play this page');
        playBtn.setAttribute('type', 'button');
        playBtn.setAttribute('aria-pressed', 'false');
        var stopBtn = el('button', null, 'Stop');
        stopBtn.setAttribute('type', 'button');
        stopBtn.disabled = true;
        var voiceLabel = el('label', null, 'Voice ');
        var voiceSel = el('select', null);
        voiceLabel.appendChild(voiceSel);
        var rateLabel = el('label', null, 'Speed ');
        var rateSel = el('select', null);
        ['0.75', '1', '1.25', '1.5'].forEach(function (r) {
            var o = document.createElement('option');
            o.value = r;
            o.textContent = r + '×';
            if (r === '1') { o.selected = true; }
            rateSel.appendChild(o);
        });
        rateLabel.appendChild(rateSel);
        var status = el('p', PANEL_CLASS + '__status');
        status.setAttribute('role', 'status');
        status.setAttribute('aria-live', 'polite');
        var note = el('p', PANEL_CLASS + '__note',
            'Machine-read aloud in your browser — voices vary by device. ' +
            'The record is the document file, not this audio.');
        row.appendChild(playBtn);
        row.appendChild(stopBtn);
        row.appendChild(voiceLabel);
        row.appendChild(rateLabel);
        panel.appendChild(row);
        panel.appendChild(status);
        panel.appendChild(note);
        if (container.parentNode) {
            container.parentNode.insertBefore(panel, container.nextSibling);
        } else {
            return;
        }

        function say(msg) { status.textContent = msg; }

        function refreshVoices() {
            try { state.voices = window.speechSynthesis.getVoices() || []; }
            catch (e) { state.voices = []; }
            while (voiceSel.firstChild) { voiceSel.removeChild(voiceSel.firstChild); }
            var best = pickVoice(state.voices, lang);
            state.voices.forEach(function (v) {
                var o = document.createElement('option');
                o.value = v.name;
                o.textContent = v.name + ' (' + (v.lang || '?') + ')';
                if (best && v.name === best.name) { o.selected = true; }
                voiceSel.appendChild(o);
            });
            if (!state.voices.length) {
                var o = document.createElement('option');
                o.value = '';
                o.textContent = 'Default voice';
                voiceSel.appendChild(o);
            }
        }

        function currentVoice() {
            for (var i = 0; i < state.voices.length; i++) {
                if (state.voices[i].name === voiceSel.value) { return state.voices[i]; }
            }
            return pickVoice(state.voices, lang);
        }

        function stop(silent) {
            if (state.watchdog) {
                try { clearInterval(state.watchdog); } catch (e) { /* timer already gone */ }
                state.watchdog = 0;
            }
            try { window.speechSynthesis.cancel(); } catch (e) { /* no synth, nothing to cancel */ }
            state.speaking = false;
            state.paused = false;
            state.index = 0;
            playBtn.textContent = 'Play ' + pageLabel(state.pages, state.total).toLowerCase();
            playBtn.setAttribute('aria-pressed', 'false');
            stopBtn.disabled = true;
            if (!silent) { say('Stopped. ' + pageLabel(state.pages, state.total) + ' ready.'); }
        }

        function speakChunks() {
            if (state.index >= state.chunks.length) {
                var done = pageLabel(state.pages, state.total);
                stop(true);
                say('Finished ' + done.toLowerCase() + '.');
                return;
            }
            var u;
            try {
                u = new SpeechSynthesisUtterance(state.chunks[state.index]);
            } catch (e) {
                stop(true);
                say('Read-aloud failed in this browser.');
                return;
            }
            var v = currentVoice();
            if (v) { u.voice = v; u.lang = v.lang || lang; }
            else { u.lang = lang; }
            var rate = parseFloat(rateSel.value);
            u.rate = (rate > 0 && rate <= 3) ? rate : 1;
            u.onend = function () {
                if (!state.speaking) { return; }
                state.index += 1;
                speakChunks();
            };
            u.onerror = function () {
                if (!state.speaking) { return; }
                stop(true);
                say('Read-aloud stopped (browser reported an error).');
            };
            try {
                window.speechSynthesis.speak(u);
            } catch (e) {
                stop(true);
                say('Read-aloud failed in this browser.');
            }
        }

        function play() {
            if (state.paused) {
                try { window.speechSynthesis.resume(); } catch (e) { /* resume unsupported */ }
                state.paused = false;
                state.speaking = true;
                playBtn.textContent = 'Pause';
                playBtn.setAttribute('aria-pressed', 'true');
                say('Reading ' + pageLabel(state.pages, state.total).toLowerCase() + '.');
                return;
            }
            if (state.speaking) {
                try { window.speechSynthesis.pause(); } catch (e) { stop(); return; }
                state.paused = true;
                playBtn.textContent = 'Resume';
                playBtn.setAttribute('aria-pressed', 'false');
                say('Paused.');
                return;
            }
            resolveText().then(function (res) {
                // Provider may return a bare string or {text, isMachine};
                // machine-translated speech is announced as such, never silent.
                var announced = (res && typeof res === 'object' && res.isMachine)
                    ? 'machine translation, ' : '';
                var cleaned = cleanText(res && typeof res === 'object' ? res.text : res);
                if (!cleaned) {
                    if (res === null && !pagesUrl && !textProvider) {
                        say('This page has no readable text feed yet (needs a page-text source).');
                    } else {
                        say("There's no readable text for this page.");
                    }
                    return;
                }
                try { window.speechSynthesis.cancel(); } catch (e) { /* fresh start */ }
                state.chunks = chunkText(cleaned);
                state.index = 0;
                state.speaking = true;
                state.paused = false;
                // Chrome drops remote-voice utterances after ~15s (chromium
                // #679437). Re-arming pause/resume resets the timer; chunks are
                // short but slow rates/voices can still exceed the window.
                // Mirrors IA BookReader's WebTTSSound 14s workaround.
                if (state.watchdog) {
                    try { clearInterval(state.watchdog); } catch (e) { /* stale timer */ }
                }
                try {
                    state.watchdog = setInterval(function () {
                        if (!state.speaking || state.paused) { return; }
                        try {
                            window.speechSynthesis.pause();
                            window.speechSynthesis.resume();
                        } catch (e) { /* engine ignores pause; chunking still bounds utterances */ }
                    }, 14000);
                } catch (e) { state.watchdog = 0; }
                playBtn.textContent = 'Pause';
                playBtn.setAttribute('aria-pressed', 'true');
                stopBtn.disabled = false;
                say('Reading ' + announced + pageLabel(state.pages, state.total).toLowerCase() + '.');
                speakChunks();
            });
        }

        // Resolve speakable text for the current page(s): provider first,
        // then the static pages.json feed. Provider may return a bare string
        // or {text, isMachine} (translation cache shape); objects pass through
        // so play() can announce machine translation. Returns Promise<...|null>.
        function resolveText() {
            if (textProvider) {
                try {
                    return Promise.resolve(textProvider(container, state.pages.slice()))
                        .then(function (t) {
                            if (t == null) { return null; }
                            if (typeof t === 'object') { return t; }
                            return String(t);
                        })
                        .catch(function () { return null; });
                } catch (e) { return Promise.resolve(null); }
            }
            if (pagesUrl) {
                return fetchPages(pagesUrl).then(function (pages) {
                    if (!pages) { return null; }
                    var out = [];
                    state.pages.forEach(function (n) {
                        for (var i = 0; i < pages.length; i++) {
                            if (pages[i] && pages[i].n === n && pages[i].text) { out.push(pages[i].text); break; }
                        }
                    });
                    return out.length ? out.join('\n\n') : null;
                });
            }
            return Promise.resolve(null);
        }

        playBtn.addEventListener('click', play);
        stopBtn.addEventListener('click', function () { stop(false); });
        voiceSel.addEventListener('change', function () {
            if (state.speaking && !state.paused) { play(); stop(false); play(); }
        });
        rateSel.addEventListener('change', function () {
            if (state.speaking && !state.paused) { play(); stop(false); play(); }
        });

        if (!supported()) {
            playBtn.disabled = true;
            stopBtn.disabled = true;
            voiceSel.disabled = true;
            rateSel.disabled = true;
            say("Read-aloud isn't available in this browser. Use the open or download links.");
            return;
        }

        refreshVoices();
        // addEventListener (not .onvoiceschanged assignment) so co-located
        // site code with its own voices listener is never clobbered.
        // Async-voice browsers are covered by the retry below.
        if (window.speechSynthesis && typeof window.speechSynthesis.addEventListener === 'function') {
            window.speechSynthesis.addEventListener('voiceschanged', refreshVoices);
        }
        // Some browsers only populate voices asynchronously.
        setTimeout(refreshVoices, 500);

        document.addEventListener('rr-reader:pagechange', function (e) {
            if (e.target !== container) { return; }
            var d = (e && e.detail) || {};
            if (Array.isArray(d.pages) && d.pages.length) { state.pages = d.pages.slice(); }
            if (d.total) { state.total = d.total; }
            stop(true);
            say(pageLabel(state.pages, state.total) + ' ready — press Play to listen.');
        });

        window.addEventListener('pagehide', function () { stop(true); });

        say(pageLabel(state.pages, state.total) + ' ready — press Play to listen.');
        wired.push(container);
    }

    function wireAll() {
        var nodes = document.querySelectorAll(
            '.rr-reader[data-file-url][data-read-aloud], .ggrr-reader[data-file-url][data-read-aloud]');
        for (var i = 0; i < nodes.length; i++) { wire(nodes[i]); }
    }

    var api = {
        wire: wire,
        wireAll: wireAll,
        setTextProvider: setTextProvider,
        supported: supported,
        // Exposed for unit tests (chunking rule is the utterance-drop workaround).
        _chunkText: chunkText,
        _cleanText: cleanText,
        _pickVoice: pickVoice
    };

    window.RRReadAloud = api;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', wireAll);
    } else {
        wireAll();
    }
})();
