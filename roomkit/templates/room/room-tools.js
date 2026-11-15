/* RoomTools: the seam the room's optional reading tools share (pack-switched tools only; ships
   when at least one tool that registers here is on). ES5, no inline handlers, no network.
   One "Reading tools" disclosure after the reader, one status line, one preferences store.
   A tool never touches another tool's DOM:
     RoomTools.register({id, label, mount(container, prefs), unmount()})
     RoomTools.unregister(id)
     RoomTools.prefs.get(id, fallback) / .set(id, value)   localStorage "room-tools:<id>", try/catch
     RoomTools.announce(text)                              the shared role="status" line */
(function () {
  'use strict';
  var KEY = 'room-tools:', tools = {}, box, list, live, timer;

  function get(id, fallback) {
    try {
      var v = window.localStorage.getItem(KEY + id);
      return v === null ? fallback : JSON.parse(v);
    } catch (e) { return fallback; }
  }
  function set(id, value) {
    try { window.localStorage.setItem(KEY + id, JSON.stringify(value)); return true; } catch (e) { return false; }
  }
  var prefs = { get: get, set: set };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    n.className = cls;
    if (text) { n.textContent = text; }
    return n;
  }

  function frame() {
    var mount = document.querySelector('.rr-reader');
    if (box || !mount || !mount.parentNode) { return box; }
    box = el('details', 'room-tools');
    box.appendChild(el('summary', 'room-tools__summary', 'Reading tools'));
    list = el('div', 'room-tools__list');
    live = el('p', 'room-tools__status');
    live.setAttribute('role', 'status');
    box.appendChild(list);
    box.appendChild(live);
    mount.parentNode.insertBefore(box, mount.nextSibling);
    return box;
  }

  function register(tool) {
    if (!tool || !tool.id || typeof tool.mount !== 'function' || tools[tool.id] || !frame()) { return false; }
    var item = el('section', 'room-tools__item');
    var head = el('h3', 'room-tools__label', tool.label || tool.id);
    item.setAttribute('data-tool', tool.id);
    item.appendChild(head);
    list.appendChild(item);
    tools[tool.id] = { tool: tool, item: item };
    try { tool.mount(item, prefs); } catch (e) { item.parentNode.removeChild(item); delete tools[tool.id]; return false; }
    return true;
  }

  function unregister(id) {
    var t = tools[id];
    if (!t) { return; }
    try { if (t.tool.unmount) { t.tool.unmount(); } } catch (e) { /* a tool that will not stop is still removed */ }
    t.item.parentNode.removeChild(t.item);
    delete tools[id];
  }

  function announce(text) {
    if (!live) { return; }
    live.textContent = '';
    clearTimeout(timer);
    timer = setTimeout(function () { live.textContent = text; }, 50);
  }

  window.RoomTools = { register: register, unregister: unregister, prefs: prefs, announce: announce };
})();
