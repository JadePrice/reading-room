/* The twin of roomkit/text_clean.py and of the read-aloud player's cleanText: one rule for
   machine-read page text. A hyphen (or the "¬" continuation mark) at a line end, with the
   whitespace around the break, is removed and the two halves join. Not shipped by the room yet;
   it is here so a room script that needs the rule uses this one, and the tests hold the three
   implementations to the same answers (tests/roomkit/test_text_clean.py). ES5. */
(function (root) {
  'use strict';
  function joinHyphenated(text) {
    return String(text == null ? '' : text).replace(/[-\u00AC]\s*\n\s*/g, '');
  }
  function cleanText(text) {
    return joinHyphenated(text).replace(/\s+/g, ' ').trim();
  }
  function paragraphs(text) {
    var joined = joinHyphenated(String(text || '').replace(/\r\n?/g, '\n')), out = [];
    joined.split(/\n\s*\n/).forEach(function (block) {
      var lines = block.split('\n').map(function (ln) { return ln.trim().replace(/\s+/g, ' '); })
        .filter(function (ln) { return ln; });
      if (lines.length) { out.push(lines); }
    });
    return out;
  }
  var api = { joinHyphenated: joinHyphenated, cleanText: cleanText, paragraphs: paragraphs };
  if (typeof module === 'object' && module.exports) { module.exports = api; } else { root.RoomTextClean = api; }
})(this);
