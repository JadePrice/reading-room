<?php
/**
 * roomkit manifest exporter for glassgovernment.org (plugin gg-reading-room).
 *
 * READ-ONLY. Run from the Mac, script on stdin, nothing copied to the host:
 *
 *   ssh $GG_HOST "$GG_WP eval-file -" \
 *     < roomkit/exporters/glassgovernment.php > gg-manifest.json
 *
 * (`$GG_WP` is the operator's wp-cli command for the GG install; the
 * same route scripts/wiki/corpus_manifest.py reads the census by.)
 *
 * Prints one JSON manifest (roomkit/manifest.py) of the public
 * documents, in the library's own order. Everything a page shows comes from
 * the plugin's own helpers, called the way templates/single-ggrr-document.php
 * calls them: the citation is GGRR_Citations::format_reference, the badge
 * GGRR_Template::provenance_badge's label, the rights line
 * GGRR_Template::provenance_rights' output taken apart, entities
 * GGRR_Entities::for_doc with the template's two headings, and the entity index
 * and entity pages (`entities`) from list_approved, entity_label,
 * docs_for_entity and co_occurring under index-ggrr-entities.php's and
 * entity-ggrr.php's own words, and the collections page, collection pages and
 * the index's collections table (`collections`) from collections_by_category,
 * collection_docs, ggrr_collection_meta and ggrr_collection_sources under
 * index-ggrr-collections.php's, archive-ggrr-collection.php's and
 * index-ggrr-reading-room.php's own words. Where the template
 * composes something inline (the Pages row, the record-type words, the
 * JSON-LD), the formula is repeated here and named; `roomkit parity` checks
 * the citation and file URLs against the live pages.
 *
 * Not called, because they write: get_thumbnail_path() (builds a preview
 * cache). The poster is offered only when the large thumbnail already exists
 * on disk, which is the template's condition without the side effect.
 *
 * Page text is exported (ROOMKIT_WITH_PAGES=0 leaves it out), as for dd
 * (decision D6, conductor/plans/2026-10-08-static-reading-room.md). A record
 * whose page rows are not a complete 1..N run (most often one row with
 * page_number NULL: a large scan OCR'd as one blob) has no `pages`; its
 * full_text, the column the live search reads, goes out as `search_text`
 * instead, which the room indexes for search and never shows.
 *
 * ROOMKIT_SLICE ("<offset>:<limit>", env or constant) exports one window of
 * the records in the same order, with `slice` {offset, limit, total} beside
 * the documents, so a slow link can fetch the manifest in pieces and
 * roomkit/exporters/merge-slices.py joins them (refusing a gap or an
 * overlap). Without it, everything goes out at once, as before.
 *
 * A record with no file attached but full_text is exported as a text-only record
 * (`file` null, `display.no_file`, a "Pending local file hash" rail row), the page the live
 * site shows; its text goes out as pages or `search_text`.
 *
 * Refuses (exit 1, JSON {"error", "problems"}) when a public record has no
 * servable file or its bytes do not hash to file_sha256; with
 * ROOMKIT_ALLOW_EXCLUDED=1 they go to `excluded` with the problem instead.
 * Fails (exit 1, one line on stderr, nothing on stdout) if the manifest can't be JSON-encoded, e.g. invalid UTF-8.
 *
 * Passage citations (`passages`, roomkit passages.py; the room uses them only with
 * the pack's passage-cite switch): each record's `document_id`; on each page its
 * `cite`, the reference GGRR_REST::passage answers for `?slug=&page=N` (its own
 * date formula, the permalink with `#page-N`, the page row's provenance_level and
 * ocr_confidence as resolve_passage reads them); and, in the first slice, the
 * curated citations (every wp_ggrr_citations row, as GGRR_Citations::get_by_stable_key
 * shapes it, i.e. what `ggrr/v1/citation?key=` answers) with the passage route's
 * URL. A row whose record is not public goes to `passages.excluded` with why.
 */

if (!class_exists('GGRR_Storage') || !class_exists('GGRR_Template') || !class_exists('GGRR_Citations')) {
    fwrite(STDOUT, json_encode(['error' => 'gg-reading-room is not active']) . "\n");
    exit(1);
}

global $wpdb;
$S = 'GGRR_Storage';
$T = 'GGRR_Template';
// sudo ($GG_WP) does not pass environment variables, so the flags may also
// arrive as constants defined in a one-line PHP block prepended on stdin
// (roomkit/publish/glassgovernment-staging.sh does this).
$with_pages = getenv('ROOMKIT_WITH_PAGES') !== '0' && !defined('ROOMKIT_NO_PAGES');
$allow_excluded = getenv('ROOMKIT_ALLOW_EXCLUDED') === '1' || defined('ROOMKIT_ALLOW_EXCLUDED');

// get_documents() caps a page at 500; read them all, in its own order.
$rows = [];
for ($offset = 0; ; $offset += 500) {
    $batch = $S::get_documents(['visibility' => 'public', 'limit' => 500, 'offset' => $offset]);
    $rows = array_merge($rows, $batch);
    if (count($batch) < 500) {
        break;
    }
}
// Every public record's slug by id, before any slice: a curated citation names its
// record by id, and that record may sit in another slice.
$public_slug = array_column($rows, 'slug', 'id');
// ...and its file hash, for the citations that pin the file they were made against.
$public_sha = array_map('strtolower', array_column($rows, 'file_sha256', 'id'));
$slice = null;
$slice_raw = defined('ROOMKIT_SLICE') ? (string) ROOMKIT_SLICE : (string) getenv('ROOMKIT_SLICE');
if ($slice_raw !== '') {
    if (!preg_match('/^(\d+):(\d+)$/', $slice_raw, $mm) || (int) $mm[2] < 1) {
        fwrite(STDOUT, json_encode(['error' => "ROOMKIT_SLICE is not <offset>:<limit>: $slice_raw"]) . "\n");
        exit(1);
    }
    $slice = ['offset' => (int) $mm[1], 'limit' => (int) $mm[2], 'total' => count($rows)];
    $rows = array_slice($rows, $slice['offset'], $slice['limit']);
}

function roomkit_gg_poster(array $doc): string {
    // The template's condition (a large thumbnail exists), read off disk
    // instead of through get_thumbnail_path(), which would build one.
    $att = (int) ($doc['attachment_id'] ?? 0);
    if ($att <= 0) {
        return '';
    }
    $meta = wp_get_attachment_metadata($att);
    $file = get_attached_file($att);
    if (!is_array($meta) || !$file || empty($meta['sizes']['large']['file'])) {
        return '';
    }
    return is_readable(trailingslashit(dirname($file)) . $meta['sizes']['large']['file'])
        ? GGRR_Storage::get_thumbnail_url($doc, 'large') : '';
}

// The rights line is HTML (a link and a note); its parts, as the plugin wrote them.
function roomkit_gg_rights(array $doc): ?array {
    $html = GGRR_Template::provenance_rights($doc);
    if ($html === '') {
        return null;
    }
    [$who, $note] = array_pad(explode('<br>', $html, 2), 2, '');
    $row = ['label' => 'Rights', 'value' => html_entity_decode(trim(wp_strip_all_tags($who)), ENT_QUOTES)];
    if (preg_match('/href="([^"]+)"/', $who, $m)) {
        $row['url'] = html_entity_decode($m[1], ENT_QUOTES);
    }
    $note = html_entity_decode(trim(wp_strip_all_tags($note)), ENT_QUOTES);
    if ($note !== '') {
        $row['note'] = $note;
    }
    return $row;
}

// What the live index's selects narrow by (agency, record type, vendor, year), from the
// row builder the index template itself calls, so each record's facet pages hold what live
// filtering by that value holds (browse.py). The row's labels are the selects' option text.
$browse_by_slug = [];
// The record type and source selects too: the row's raw record_type, and its source
// (source_label ?? source_system: an empty label stays empty, so the record lists no source).
$facets_by_slug = [];
foreach ((array) ggrr_reading_room_documents() as $r) {
    $facets_by_slug[(string) ($r['slug'] ?? '')] = ['type' => (string) ($r['record_type'] ?? ''), 'source' => (string) ($r['source'] ?? '')];
    $browse_by_slug[(string) ($r['slug'] ?? '')] = array_filter([
        'agency' => array_values(array_filter([trim((string) ($r['agency'] ?? ''))])),
        'type' => array_values(array_filter([(string) ($r['record_type'] ?? '')])),
        'vendor' => array_values(array_unique(array_filter(array_map(fn($v) => (string) ($v['label'] ?? ''), (array) ($r['vendors'] ?? []))))),
        'year' => array_values(array_filter([ctype_digit((string) ($r['year'] ?? '')) ? (string) $r['year'] : ''])),
    ]);
}

$ent_headings = [
    'authorship' => ['Attributed to', 'Recorded in the catalog as the party that produced this document.'],
    'named' => ['Named in this document', 'Matched verbatim in the document text. The highlighted words are the match; the rest is the line around them.'],
];
$ent_types = ['vendor' => 'Vendor', 'agency' => 'Agency', 'org' => 'Organization', 'program' => 'Program', 'location' => 'Location'];

$docs = [];
$problems = [];
foreach ($rows as $doc) {
    $slug = (string) $doc['slug'];
    $id = (int) $doc['id'];
    // A record with no file attached but full text is a text-only page, as the live site shows it
    // ("No file is attached to this record yet."). One whose file is attached but unreadable or
    // altered is still a problem: get_file_path() answers '' for a managed_path that is gone
    // from disk too, so "attached" is read from the row, not from has_servable_file().
    $attached = trim((string) ($doc['managed_path'] ?? '')) !== '' || (int) ($doc['attachment_id'] ?? 0) > 0
        || (!empty($doc['ia_id']) && ($doc['ia_status'] ?? '') === 'confirmed');
    $text_only = !$attached && trim((string) ($doc['full_text'] ?? '')) !== '';
    $path = $text_only ? '' : $S::get_file_path($doc);
    $sha = '';
    $ext = '';
    $mime = '';
    if (!$text_only) {
        if (!$S::has_servable_file($doc) || $path === '' || !is_readable($path)) {
            $problems[] = ['slug' => $slug, 'problem' => 'no servable file'];
            continue;
        }
        $sha = strtolower((string) $doc['file_sha256']);
        if (!preg_match('/^[a-f0-9]{64}$/', $sha) || !hash_equals($sha, (string) hash_file('sha256', $path))) {
            $problems[] = ['slug' => $slug, 'problem' => 'file bytes do not hash to file_sha256'];
            continue;
        }
        $ext = $S::get_file_extension($doc);
        $mime = (string) (wp_check_filetype('x.' . $ext)['type'] ?? '');
    }
    $inline = $text_only ? '' : $S::get_inline_file_url($doc);
    $date = (string) ($doc['document_date'] ?? '');
    $has_date = $date !== '' && $date !== '0000-00-00';
    $date_display = $has_date ? $T::format_display_date($date) : '';
    $collection = (string) ($doc['collection'] ?? '');
    $collection_label = $collection !== '' ? $T::collection_label($collection) : 'Public record';
    $collection_url = $collection !== '' ? home_url('/library/collection/' . rawurlencode($collection) . '/') : home_url('/library/');
    $permalink = home_url('/library/' . rawurlencode($slug) . '/');
    $ia_ok = !empty($doc['ia_id']) && ($doc['ia_status'] ?? '') === 'confirmed';
    $ia_url = $ia_ok ? 'https://archive.org/details/' . rawurlencode((string) $doc['ia_id']) : '';

    // single-ggrr-document.php "Formatted citation".
    $cite = GGRR_Citations::format_reference(
        (string) ($doc['agency'] ?? ''), (string) ($doc['title'] ?? ''),
        $has_date ? $date_display : 'n.d.', $permalink, null, $ia_ok ? (string) $doc['ia_id'] : ''
    );

    $file = null;
    if (!$text_only) {
        $file = [
            'url' => $inline,
            'download_url' => $S::get_download_file_url($doc),
            'sha256' => $sha,
            'bytes' => (int) filesize($path),
            'ext' => $ext,
            'mime' => $mime,
        ];
        if ($ext === 'pdf') {
            $poster = roomkit_gg_poster($doc);
            if ($poster !== '') {
                $file['poster_url'] = $poster;
            }
        }
    }

    // --- the provenance rail, row for row ---
    $details = [
        ['label' => 'Collection', 'value' => $collection_label, 'url' => $collection_url],
        ['label' => 'Agency', 'value' => (string) ($doc['agency'] ?: 'Not listed')],
    ];
    if (!empty($doc['record_type'])) {
        $details[] = ['label' => 'Record type', 'value' => ucwords(str_replace(['_', '-'], ' ', (string) $doc['record_type']))];
    }
    $details[] = ['label' => 'Document date', 'value' => $has_date ? $date_display : 'date unknown'];
    $pages_word = !empty($doc['page_count']) ? (int) $doc['page_count'] . ' pages'
        : (trim((string) ($doc['full_text'] ?? '')) !== '' ? 'Full text' : 'Text pending');
    $details[] = ['label' => 'Pages', 'value' => $pages_word];
    if (!empty($doc['reading_time'])) {
        $details[] = ['label' => 'Reading time', 'value' => (int) $doc['reading_time'] . ' min'];
    }
    if (!empty($doc['language']) && $doc['language'] !== 'en') {
        $details[] = ['label' => 'Language', 'value' => strtoupper((string) $doc['language'])];
    }
    if ($rights = roomkit_gg_rights($doc)) {
        $details[] = $rights;
    }
    if (!empty($doc['license'])) {
        $lic = (string) $doc['license'];
        $lmet = function_exists('ggrr_license_meta') ? ggrr_license_meta($lic) : null;
        $row = ['label' => 'License', 'value' => function_exists('ggrr_license_label') ? ggrr_license_label($lic) : $lic];
        if ($lmet !== null && $lmet['url'] !== '') {
            $row['url'] = $lmet['url'];
        }
        if ($lmet !== null && $lmet['note'] !== '') {
            $row['note'] = $lmet['note'];
        }
        $details[] = $row;
    }
    $details[] = !empty($doc['source_url'])
        ? ['label' => 'Source', 'value' => (string) ($doc['source_label'] ?: $doc['source_url']), 'url' => (string) $doc['source_url']]
        : ['label' => 'Source', 'value' => (string) ($doc['source_label'] ?: 'Not listed')];
    if ($ia_ok) {
        // The template's badge words, as live shows them (lowercase).
        $details[] = ['label' => 'Permanent copy', 'value' => 'Internet Archive', 'url' => $ia_url, 'note' => 'verified'];
    } elseif (!empty($doc['ia_id']) && ($doc['ia_status'] ?? '') === 'pending') {
        $details[] = ['label' => 'Permanent copy', 'value' => 'backup pending', 'note' => 'Internet Archive upload in progress'];
    } elseif (!empty($doc['ia_id'])) {
        $details[] = ['label' => 'Permanent copy', 'value' => 'not yet archived'];
    }
    $details[] = $text_only
        ? ['label' => 'SHA-256', 'value' => 'Pending local file hash']
        : ['label' => 'SHA-256', 'value' => $sha, 'code' => true];

    // --- topics, entities, power maps, related: the rail's lists ---
    $groups = [];
    $topics = $S::get_doc_topics($id);
    if ($topics) {
        $groups[] = ['heading' => 'Topics', 'style' => 'chips', 'items' => array_map(fn($t) => [
            'label' => ucwords(str_replace(['_', '-'], ' ', $t)),
            'url' => home_url('/library/topics/' . rawurlencode($t) . '/'),
        ], $topics)];
    }
    $by_basis = ['authorship' => [], 'named' => []];
    foreach (class_exists('GGRR_Entities') ? GGRR_Entities::for_doc($id) : [] as $ent) {
        $span = ($ent['basis'] === 'named' && $ent['evidence'] !== null && strcasecmp($ent['evidence'], $ent['label']) !== 0)
            ? $ent['evidence'] : '';
        $by_basis[$ent['basis'] === 'named' ? 'named' : 'authorship'][] = array_filter([
            'label' => $ent['label'],
            'kind' => $ent_types[$ent['type']] ?? ucfirst($ent['type']),
            'quote' => $span,
            'url' => home_url('/library/entity/' . rawurlencode($ent['type']) . '/' . rawurlencode($ent['slug']) . '/'),
        ], fn($v) => $v !== '');
    }
    foreach ($by_basis as $basis => $items) {
        if ($items) {
            $groups[] = ['heading' => $ent_headings[$basis][0], 'blurb' => $ent_headings[$basis][1], 'style' => 'chips', 'items' => $items];
        }
    }
    $maps = class_exists('GGRR_Power_Maps') ? GGRR_Power_Maps::maps_citing_document($id) : [];
    if ($maps) {
        $groups[] = ['heading' => 'Quoted in a power map', 'style' => 'list', 'items' => array_map(fn($pm) => [
            'label' => (string) $pm['title'], 'url' => home_url('/library/power-map/' . rawurlencode((string) $pm['slug']) . '/'),
        ], $maps)];
    }
    $related = class_exists('GGRR_Entities') ? GGRR_Entities::related_docs($id) : [];
    if ($related) {
        $groups[] = ['heading' => 'Related Documents', 'style' => 'list', 'items' => array_map(fn($r) => [
            'label' => $r['title'], 'url' => home_url('/library/' . rawurlencode($r['slug']) . '/'),
            'meta' => (string) $r['collection'],  // the template prints the raw slug
        ], $related)];
    }

    $badge = '';
    $badge_kind = '';
    $badge_sr = '';
    if (class_exists('GGRR_Template') && method_exists('GGRR_Template', 'provenance_badge')) {
        $binfo = roomkit_gg_badge($doc);
        $badge = $binfo['badge'] ?? '';
        $badge_kind = $binfo['badge_kind'] ?? '';
        $badge_sr = $binfo['badge_sr'] ?? '';
    } elseif (function_exists('ggrr_doc_class')) {
        $badge_kind = ggrr_doc_class($doc);
        if ($badge_kind === 'government') {
            $badge = 'Government record';
            $badge_sr = 'Provenance: ';
        } elseif ($badge_kind === 'third-party') {
            $badge = 'Third-party report';
            $badge_sr = 'Provenance: ';
        } else {
            $badge_kind = '';
        }
    }
    $sens = function_exists('ggrr_collection_sensitivity') ? ggrr_collection_sensitivity($collection) : null;

    // JSON-LD: the template's formula, repeated (it is built inline there).
    $lic_ld = (string) ($doc['license'] ?? '');
    if ($lic_ld !== '' && function_exists('ggrr_license_meta') && ($m = ggrr_license_meta($lic_ld)) !== null) {
        $lic_ld = $m['url'] !== '' ? $m['url'] : $m['label'];
    }
    $agency = trim((string) ($doc['agency'] ?? ''));
    $jsonld = array_filter([
        '@context' => 'https://schema.org',
        '@type' => $ext === 'pdf' ? 'DigitalDocument' : 'CreativeWork',
        'name' => (string) ($doc['title'] ?? ''),
        'description' => (string) ($doc['summary'] ?? ''),
        'url' => $permalink,
        'mainEntityOfPage' => $permalink,
        'datePublished' => $date,
        'author' => $agency !== '' ? ['@type' => 'Organization', 'name' => $agency] : null,
        'genre' => $collection_label,
        'license' => $lic_ld,
        'identifier' => $sha,
        'creativeWorkStatus' => (string) ($doc['ia_status'] ?? 'none'),
        'archivedAt' => $ia_url,
    ], fn($v) => $v !== '' && $v !== null);

    $cm = function_exists('ggrr_collection_meta') ? ggrr_collection_meta($collection) : null;
    $hdr_meta = array_values(array_filter([
        (string) ($doc['agency'] ?: 'Agency'),
        $cm ? (string) $cm['title'] : '',
        (!empty($cm['year_start']) && !empty($cm['year_end'])) ? ((int) $cm['year_start'] . '–' . (int) $cm['year_end']) : '',
    ]));
    $hdr = [
        'meta' => $hdr_meta,
        'original_url' => $inline !== '' ? $inline . (str_contains($inline, '?') ? '&' : '?') . 'original=1' : '',
        'category' => (string) ($cm['category'] ?? 'historical'),
    ];
    if ($ia_ok) {
        $hdr['ia_url'] = $ia_url;
    } elseif (!empty($doc['ia_id']) && ($doc['ia_status'] ?? '') === 'pending') {
        $hdr['ia_pending'] = true;
    }

    $display = array_filter([
        'breadcrumbs' => [
            ['label' => 'Home', 'url' => home_url('/')],
            ['label' => 'Reading Room', 'url' => home_url('/library/')],
            ['label' => $collection_label, 'url' => $collection_url],
            ['label' => (string) $doc['title']],
        ],
        'header' => $hdr,
        'eyebrow' => ['label' => $collection_label, 'url' => $collection_url],
        'badge' => $badge,
        'badge_kind' => $badge_kind,
        'badge_sr' => $badge_sr,
        'released' => $date_display,
        'notice' => $sens ? array_filter(['heading' => $sens['heading'], 'body' => $sens['body'], 'report' => (string) ($sens['report'] ?? '')]) : null,
        'details' => $details,
        'notes' => (string) ($doc['notes_public'] ?? ''),
        'no_file' => $text_only ? 'No file is attached to this record yet.' : '',
        'groups' => $groups,
        'jsonld' => $jsonld,
    ], fn($v) => $v !== '' && $v !== null && $v !== []);

    $meta = array_values(array_filter([
        !empty($doc['record_type']) ? ucwords(str_replace(['_', '-'], ' ', (string) $doc['record_type'])) : '',
        !empty($doc['page_count']) ? (int) $doc['page_count'] . ' pages' : '',
        $pages_word === 'Text pending' ? 'Text pending' : '',
    ]));
    $row = [
        'slug' => $slug,
        'document_id' => $id,
        'title' => (string) $doc['title'],
        'visibility' => 'public',
        'citation' => $cite,
        'agency' => (string) ($doc['agency'] ?? ''),
        'date' => $has_date ? $date : '',
        'summary' => (string) ($doc['summary'] ?? ''),
        'file' => $file,
        'display' => $display,
        'index' => [
            'group' => $collection_label,
            'card_date' => $date_display,
            'meta' => $meta,
            'browse' => (object) ($browse_by_slug[$slug] ?? []),
            'facets' => (object) array_filter([
                'type' => $facets_by_slug[$slug]['type'] ?? '',
                'source' => $facets_by_slug[$slug]['source'] ?? '',
                'agency' => $agency,
                'year' => $has_date ? substr($date, 0, 4) : '',
            ]),
        ],
    ];
    if ($ia_ok) {
        $row['archive_url'] = $ia_url;
    }
    if ($with_pages) {
        $pages = $wpdb->get_results($wpdb->prepare(
            "SELECT page_number, ocr_text, provenance_level, ocr_confidence FROM " . $S::pages_table_name() . " WHERE document_id = %d AND page_number IS NOT NULL ORDER BY page_number ASC, id ASC",
            $id
        ), ARRAY_A);
        // class-ggrr-rest.php passage(): its date formula (not the page's
        // "n.d." rule above), the permalink plus "#page-N", and the page row's
        // provenance_level and ocr_confidence as resolve_passage() returns them.
        $p_date = !empty($doc['document_date']) ? $T::format_display_date((string) $doc['document_date']) : 'n.d.';
        $pages = array_map(fn($p) => [
            'n' => (int) $p['page_number'],
            'text' => (string) $p['ocr_text'],
            'provenance' => 'site',
            'cite' => [
                'reference' => GGRR_Citations::format_reference(
                    (string) ($doc['agency'] ?? ''), (string) ($doc['title'] ?? ''), $p_date,
                    $permalink . '#page-' . (int) $p['page_number'], (int) $p['page_number'],
                    $ia_ok ? (string) $doc['ia_id'] : ''
                ),
                'provenance_level' => (string) $p['provenance_level'],
                'ocr_confidence' => $p['ocr_confidence'] !== null ? (float) $p['ocr_confidence'] : null,
            ],
        ], (array) $pages);
        // Only a complete 1..N run: a gap would misnumber every page after it.
        if ($pages && array_column($pages, 'n') === range(1, count($pages))) {
            $row['pages'] = $pages;
        } elseif (trim((string) ($doc['full_text'] ?? '')) !== '') {
            // No usable pages: search-only text, as the live search sees it.
            $row['search_text'] = trim((string) $doc['full_text']);
        }
    }
    $docs[] = $row;
}

if ($problems && !$allow_excluded) {
    fwrite(STDOUT, json_encode(['error' => 'public records with missing or mismatched files', 'problems' => $problems], JSON_UNESCAPED_SLASHES) . "\n");
    exit(1);
}

// Collection order: the library's own grouping (category, then group), as /library/ lists it.
$group_order = [];
$group_sets = [];  // the live collection select's optgroups: the library's group names
foreach ($T::collections_by_category() as $cat => $grps) {
    foreach ($grps as $grp => $cols) {
        $labels_in = [];
        foreach ($cols as $c) {
            $group_order[] = $labels_in[] = $T::collection_label((string) $c['slug']);
        }
        $group_sets[] = ['label' => (string) $grp, 'groups' => $labels_in];
    }
}

// --- entities: the index (templates/index-ggrr-entities.php) and one page per
// entity (templates/entity-ggrr.php), every word as those templates write it and
// every list from the plugin's own queries, in their order. The templates build
// their strings inline, so each formula is repeated here and named; `roomkit
// parity --entities` compares the result with the live pages. Only the first
// slice carries it (merge-slices.py keeps the first piece's other keys).

// GGRR_Template::provenance_badge()'s markup, taken apart: kind (its class), the
// visually hidden prefix, the label. Markup it does not recognise stops the export.
function roomkit_gg_badge(array $d): array {
    $html = GGRR_Template::provenance_badge($d);
    if ($html === '') {
        return [];
    }
    if (!preg_match('#^<span class="ggrr-prov-badge ggrr-prov-badge--([a-z0-9-]+)"><span class="visually-hidden">([^<]*)</span>([^<]*)</span>$#', $html, $m)) {
        fwrite(STDOUT, json_encode(['error' => 'GGRR_Template::provenance_badge markup is not the one this exporter reads', 'markup' => $html]) . "\n");
        exit(1);
    }
    return ['badge' => html_entity_decode($m[3], ENT_QUOTES), 'badge_kind' => $m[1], 'badge_sr' => html_entity_decode($m[2], ENT_QUOTES)];
}

function roomkit_gg_entity_url(string $type, string $slug): string {
    return home_url('/library/entity/' . rawurlencode($type) . '/' . rawurlencode($slug) . '/');
}

// entity-ggrr.php, top to bottom, for one (type, slug).
function roomkit_gg_entity_page(string $etype, string $eslug): ?array {
    $T = 'GGRR_Template';
    $label = GGRR_Entities::entity_label($etype, $eslug);          // current_entity_label()
    if ($label === '') {
        return null;  // the route 404s (is_known_entity_request); roomkit refuses an index entry with no page
    }
    $docs = ($label !== '') ? GGRR_Entities::docs_for_entity($etype, $eslug) : [];
    $also = ($label !== '' && method_exists('GGRR_Entities', 'co_occurring'))
        ? GGRR_Entities::co_occurring($etype, $eslug, 12) : [];
    $entity_schema = ['agency' => 'GovernmentOrganization', 'vendor' => 'Organization', 'org' => 'Organization',
                      'program' => 'GovernmentService', 'location' => 'Place'];
    $entity_type_labels = ['vendor' => 'Vendor', 'agency' => 'Agency', 'org' => 'Organization', 'program' => 'Program',
                           'location' => 'Location'];
    $url = roomkit_gg_entity_url($etype, $eslug);
    $etype_label = $entity_type_labels[$etype] ?? 'Entity';
    $jsonld = array_filter([
        '@context' => 'https://schema.org',
        '@type' => $entity_schema[$etype] ?? 'Organization',
        'name' => $label,
        'url' => $url,
        'description' => $etype_label . ' (' . $label . ') — ' . count($docs) . ' document' . (count($docs) === 1 ? '' : 's') . ' in the Glass Government Reading Room',
        'identifier' => $eslug,
    ], fn($v) => $v !== '' && $v !== null);
    $by_coll = [];
    foreach ($docs as $d) {
        $by_coll[(string) $d['collection']][] = $d;
    }
    $type_label = $entity_type_labels[$etype] ?? ucfirst($etype);
    $stats = [];
    if (!empty($docs)) {
        $stats[] = ['figure' => (string) (int) count($docs), 'label' => 'documents'];
        $stats[] = ['figure' => (string) (int) count($by_coll), 'label' => 'collections'];
        if (!empty($also)) {
            $stats[] = ['figure' => (string) (int) count($also), 'label' => 'connected entities'];
        }
    }
    $groups = [];
    foreach ($by_coll as $coll => $list) {
        $groups[] = ['heading' => $T::collection_label((string) $coll), 'documents' => array_map(function ($d) {
            $year = (strlen((string) $d['date']) >= 4) ? substr((string) $d['date'], 0, 4) : '';
            return array_filter([
                'slug' => (string) $d['slug'],
                'title' => (string) $d['title'],
                'url' => home_url('/library/' . rawurlencode((string) $d['slug']) . '/'),
                'meta' => $year,
            ] + roomkit_gg_badge($d), fn($v) => $v !== '');
        }, $list)];
    }
    $page = [
        'type' => $etype,
        'slug' => $eslug,
        'url' => $url,
        'head_title' => ($label !== '' ? $label : 'Entity') . ' – Glass Government',   // filter_document_title
        'crumbs' => [
            ['label' => 'Home', 'url' => home_url('/')],
            ['label' => 'Reading Room', 'url' => home_url('/library/')],
            ['label' => 'Entities', 'url' => home_url('/library/entities/')],
            ['label' => $label !== '' ? $label : $type_label],
        ],
        'eyebrow' => 'Entity · ' . $type_label,
        'title' => $label !== '' ? $label : 'Unknown entity',
        'stats' => $stats,
        'documents_heading' => 'Documents linked to this entity',
        'documents_heading_hidden' => true,
        'groups' => $groups,
        'empty_text' => 'No public documents are linked to this entity.',
        'jsonld' => $jsonld,
    ];
    if (!empty($also)) {
        $page['alongside'] = [
            'heading' => 'Appears alongside',
            'note' => 'Other parties named on the same documents. The number is how many documents they share with ' . $label . '.',
            'count_sr' => ' shared documents',
            'items' => array_map(fn($a) => [
                'type' => (string) $a['type'],
                'slug' => (string) $a['slug'],
                'label' => (string) $a['label'],
                'kind' => $entity_type_labels[$a['type']] ?? ucfirst((string) $a['type']),
                'count' => (string) (int) $a['shared'],
                'url' => roomkit_gg_entity_url((string) $a['type'], (string) $a['slug']),
            ], $also),
        ];
    }
    return $page;
}

$entities = null;
if (class_exists('GGRR_Entities') && ($slice === null || $slice['offset'] === 0)) {
    // index-ggrr-entities.php: every type with approved entities, in TYPES order.
    $ggrr_group_labels = ['vendor' => 'Vendors', 'agency' => 'Agencies', 'org' => 'Organizations',
                          'program' => 'Programs', 'location' => 'Locations'];
    $ix_groups = [];
    $ix_total = 0;
    $ent_pages = [];
    foreach (GGRR_Entities::TYPES as $type) {
        $list = GGRR_Entities::list_approved($type);
        if (empty($list)) {
            continue;
        }
        $ix_total += count($list);
        $ix_groups[] = [
            'type' => $type,
            'heading' => $ggrr_group_labels[$type] ?? ucfirst($type),
            'count' => number_format_i18n(count($list)),
            'entities' => array_map(fn($e) => [
                'type' => $type,
                'slug' => (string) $e['slug'],
                'label' => (string) $e['label'],
                'count' => number_format_i18n($e['count']),
                'url' => roomkit_gg_entity_url($type, (string) $e['slug']),
            ], $list),
        ];
        foreach ($list as $e) {
            $k = $type . '/' . $e['slug'];
            if (!array_key_exists($k, $ent_pages)) {
                $ent_pages[$k] = roomkit_gg_entity_page($type, (string) $e['slug']);
            }
        }
    }
    $entities = [
        'index' => [
            'url' => home_url('/library/entities/'),
            'head_title' => 'Entities – Glass Government',                       // filter_document_title
            'back' => ['label' => '← Reading Room', 'url' => home_url('/library/')],
            'title' => 'Entities',
            'lede' => number_format_i18n($ix_total) . ' agencies, vendors, organizations and programs across the collection',
            'note' => 'An entity groups every document that names the same party. Agencies and organizations are recorded as the party that produced a document; vendors are matched verbatim in the text.',
            'empty_text' => 'No entities found.',
            'groups' => $ix_groups,
        ],
        'pages' => array_values(array_filter($ent_pages)),
        // The files whose formulas are repeated above, as read on the host, so a
        // change to them can be seen next to the export (not rendered).
        'source' => array_map(fn($f) => is_readable(GGRR_PATH . $f) ? hash_file('sha256', GGRR_PATH . $f) : '', [
            'templates/index-ggrr-entities.php' => 'templates/index-ggrr-entities.php',
            'templates/entity-ggrr.php' => 'templates/entity-ggrr.php',
            'includes/class-ggrr-entities.php' => 'includes/class-ggrr-entities.php',
        ]),
    ];
}

// --- collections: the collections page (templates/index-ggrr-collections.php), one
// page per collection (templates/archive-ggrr-collection.php) and the collections
// table on the index (templates/index-ggrr-reading-room.php, section 1), every word
// as those templates write it and every list from the plugin's own helpers, in their
// order. The templates build their strings inline, so each formula is repeated here
// and named; `roomkit parity --collections` compares the result with the live pages.
// First slice only, as entities.

// ggrr_filesize_h() (archive-ggrr-collection.php), which that template defines inline.
function roomkit_gg_filesize_h(array $doc): string {
    $path = GGRR_Storage::get_file_path($doc);
    if ($path === '' || !is_readable($path)) { return ''; }
    $b = filesize($path);
    if ($b === false) { return ''; }
    if ($b >= 1048576) { return number_format($b / 1048576, 1) . ' MB'; }
    if ($b >= 1024) { return number_format($b / 1024, 0) . ' KB'; }
    return $b . ' B';
}

function roomkit_gg_collection_url(string $slug): string {
    return home_url('/library/collection/' . rawurlencode($slug) . '/');
}

// archive-ggrr-collection.php, top to bottom, for one collection.
function roomkit_gg_collection_page(string $collection): array {
    $T = 'GGRR_Template';
    $label = $T::collection_label($collection);
    $desc = $T::collection_description($collection);
    $docs = $T::collection_docs($collection);
    $n = count($docs);
    $url = roomkit_gg_collection_url($collection);
    $jsonld = array_filter([
        '@context' => 'https://schema.org',
        '@type' => 'Collection',
        'name' => $label,
        'description' => $desc,
        'url' => $url,
        'numberOfItems' => $n,
    ], fn($v) => $v !== '' && $v !== null);
    $page = [
        'slug' => $collection,
        'url' => $url,
        'head_title' => $label . ' – Glass Government',                  // filter_document_title
        'back' => ['label' => '← All collections', 'url' => home_url('/library/collections/')],
        'eyebrow' => 'Collection',
        'title' => $label,
        'count' => $n . ' ' . ($n === 1 ? 'file' : 'files') . ', in order',
        'list_label' => $label . ' files',
        'empty_text' => 'No files in this collection yet.',
        'jsonld' => $jsonld,
    ];
    $m = ggrr_collection_meta($collection);
    if ($m) {
        $page['stamp'] = $m['category'] === 'historical' ? 'Federal File' : 'Public Records';
        $page['stamp_kind'] = (string) $m['category'];
        if (!empty($m['year_start'])) {
            $page['years'] = (int) $m['year_start'] . '–' . (int) $m['year_end'];
        }
        if (!empty($m['blurb'])) {
            $page['blurb'] = (string) $m['blurb'];
        }
    } elseif ($desc !== '') {
        $page['description'] = $desc;
    }
    $sens = function_exists('ggrr_collection_sensitivity') ? ggrr_collection_sensitivity($collection) : null;
    if ($sens) {
        $page['notice'] = array_filter(['heading' => $sens['heading'], 'body' => $sens['body'],
                                        'report' => (string) ($sens['report'] ?? '')], fn($v) => $v !== '');
    }
    if ($n > 8) {
        $page['search'] = ['label' => 'Search this collection', 'placeholder' => 'Filter ' . $n . ' files by title',
                           'status' => '{shown} of {total} files'];
    }
    $i = 0;
    $page['documents'] = array_map(function ($doc) use (&$i) {
        $i++;
        $t = strtolower((string) ($doc['title'] ?? ''));
        $final = strpos($t, '(final)') !== false || preg_match('/\bfinal\b/', $t) === 1;   // $is_final
        $num = ((int) ($doc['sort_order'] ?? 0)) ?: $i;
        return array_filter([
            'slug' => (string) $doc['slug'],
            'title' => (string) $doc['title'],
            'url' => home_url('/library/' . rawurlencode((string) $doc['slug']) . '/'),
            'num' => str_pad((string) (int) $num, 2, '0', STR_PAD_LEFT),
            'final' => $final ? 'Final' : '',
            'size' => roomkit_gg_filesize_h($doc),
        ] + roomkit_gg_badge($doc), fn($v) => $v !== '');
    }, $docs);
    return $page;
}

$collections = null;
if (function_exists('ggrr_collection_meta') && ($slice === null || $slice['offset'] === 0)) {
    $byCat = $T::collections_by_category();
    $coll_pages = [];
    foreach ($byCat as $grps) {
        foreach ($grps as $cols) {
            foreach ($cols as $c) {
                $coll_pages[] = roomkit_gg_collection_page((string) $c['slug']);
            }
        }
    }

    // index-ggrr-collections.php
    $cat_order = ['historical' => 'Historical', 'modern' => 'Modern', 'uncategorized' => 'Other'];
    $cat_stamp = ['historical' => 'Federal File', 'modern' => 'Public Records', 'uncategorized' => ''];
    $categories = [];
    foreach ($cat_order as $cat => $cat_title) {
        if (empty($byCat[$cat])) { continue; }
        $groups = [];
        foreach ($byCat[$cat] as $group => $rows) {
            $groups[] = ['id' => sanitize_title($group), 'heading' => (string) $group, 'collections' => array_map(function ($row) use ($cat, $group) {
                $m = $row['meta'];
                $slug = (string) $row['slug'];
                $title = $m['title'] ?? GGRR_Template::collection_label($slug);
                $y0 = $m['year_start'] ?? null;
                $y1 = $m['year_end'] ?? null;
                return array_filter([
                    'slug' => $slug,
                    'title' => (string) $title,
                    'url' => roomkit_gg_collection_url($slug),
                    'code' => strtoupper(substr(str_replace('_', '-', $slug), 0, 10)),
                    'blurb' => (string) ($m['blurb'] ?? ''),
                    'years' => ($y0 && $y1) ? (int) $y0 . '–' . (int) $y1 : '',
                    'year' => $y0 ? (string) (int) $y0 : '',      // data-ggrr-year (9999 there means none)
                    'count' => (int) $row['count'] . ' files',
                    'tags' => function_exists('ggrr_collection_filter_tags')
                        ? ggrr_collection_filter_tags($cat, (string) $group, (string) $title) : [],
                    'match' => strtolower($title . ' ' . $group . ' ' . ($m['blurb'] ?? '')),        // data-ggrr-search-match
                ], fn($v) => $v !== '' && $v !== []);
            }, $rows)];
        }
        $categories[] = array_filter(['key' => $cat, 'heading' => $cat_title, 'stamp' => $cat_stamp[$cat], 'groups' => $groups],
                                     fn($v) => $v !== '');
    }
    $banner = get_stylesheet_directory() . '/assets/images/reading_room_banner.png';

    // index-ggrr-reading-room.php, section 1 (its own $catOrder: 'modern' is 'Recent' there).
    $grid_order = ['historical' => 'Historical', 'modern' => 'Recent', 'uncategorized' => 'Other'];
    $coll_sources = function_exists('ggrr_collection_sources') ? ggrr_collection_sources() : [];
    $eras = [];
    foreach ($grid_order as $cat => $cat_title) {
        if (empty($byCat[$cat])) { continue; }
        $groups = [];
        foreach ($byCat[$cat] as $group => $rows) {
            $groups[] = ['heading' => (string) $group, 'rows' => array_map(function ($row) use ($group, $coll_sources) {
                $m = $row['meta'];
                $slug = (string) $row['slug'];
                $y0 = $m['year_start'] ?? null;
                $y1 = $m['year_end'] ?? null;
                $srcs = $coll_sources[$slug] ?? [];
                $srcs_text = implode(', ', $srcs);
                $blurb = (string) ($m['blurb'] ?? '');
                return array_filter([
                    'slug' => $slug,
                    'title' => (string) ($m['title'] ?? $group),
                    'url' => roomkit_gg_collection_url($slug),
                    'years' => ($y0 && $y1) ? (int) $y0 . '–' . (int) $y1 : '',
                    'year' => $y0 ? (string) (int) $y0 : '',
                    'sources' => $srcs_text,
                    'sources_line' => $srcs ? (count($srcs) > 1 ? 'Sources: ' : 'Source: ') . $srcs_text : '',
                    'sources_empty' => $srcs ? '' : 'Source not recorded.',
                    'blurb' => $blurb,
                    'blurb_empty' => $blurb !== '' ? '' : 'No description available.',
                ], fn($v) => $v !== '');
            }, $rows)];
        }
        $eras[] = ['heading' => $cat_title, 'groups' => $groups];
    }

    $collections = [
        'index' => array_filter([
            'url' => home_url('/library/collections/'),
            'head_title' => 'Reading Room – Glass Government',                  // filter_document_title
            'back' => ['label' => '← Reading Room', 'url' => home_url('/library/')],
            'eyebrow' => 'Declassified collections',
            'title' => 'The Reading Room',
            'lede' => 'Public records, served whole. Each collection below is a set of released government files with their original source and a verifiable hash. Open a collection to read its files in order.',
            'image' => file_exists($banner) ? ['url' => get_stylesheet_directory_uri() . '/assets/images/reading_room_banner.png',
                                               'alt' => 'FBI COINTELPRO declassified files folders'] : null,
            'search' => ['label' => 'Search archive', 'placeholder' => 'Search collections or keywords...'],
            'filters' => ['label' => 'Quick filters:', 'group_label' => 'Filter collections', 'options' => [
                ['value' => 'all', 'label' => 'All'],
                ['value' => 'federal', 'label' => 'Federal Agencies'],
                ['value' => 'police', 'label' => 'Local Police'],
                ['value' => 'environmental', 'label' => 'Environmental'],
            ]],
            'sort' => ['label' => 'Sort by:', 'options' => [
                ['value' => 'default', 'label' => 'Default'],
                ['value' => 'year-asc', 'label' => 'Year (Oldest First)'],
                ['value' => 'year-desc', 'label' => 'Year (Newest First)'],
                ['value' => 'alpha', 'label' => 'Alphabetical'],
            ]],
            'empty_text' => 'No collections are published yet. Files appear here as they are processed and verified.',
            'categories' => $categories,
        ], fn($v) => $v !== null),
        'pages' => $coll_pages,
        'grid' => [
            'heading' => 'Collections',
            'columns' => ['Period', 'Collection', 'Sources', 'Description'],
            'sort' => ['label' => 'Sort', 'options' => [
                ['value' => 'default', 'label' => 'Grouped (default)'],
                ['value' => 'name', 'label' => 'Name (A–Z)'],
                ['value' => 'year-desc', 'label' => 'Year (newest)'],
                ['value' => 'year-asc', 'label' => 'Year (oldest)'],
            ]],
            'eras' => $eras,
        ],
        'source' => array_map(fn($f) => is_readable(GGRR_PATH . $f) ? hash_file('sha256', GGRR_PATH . $f) : '', [
            'templates/index-ggrr-collections.php' => 'templates/index-ggrr-collections.php',
            'templates/archive-ggrr-collection.php' => 'templates/archive-ggrr-collection.php',
            'templates/index-ggrr-reading-room.php' => 'templates/index-ggrr-reading-room.php',
            'includes/ggrr-collections-registry.php' => 'includes/ggrr-collections-registry.php',
            'includes/class-ggrr-template.php' => 'includes/class-ggrr-template.php',
        ]),
    ];
}

// --- machine_text: /library/documents.txt (templates/txt-ggrr-documents.php), first
// slice only. The template echoes its lines inline; they are repeated here in its
// order and words, from the same call (get_documents with limit 999, which the
// storage layer caps at 500, as live), the time on its "Generated:" line being the
// export's. `roomkit parity --machine-text` compares it with the live file.
$machine_text = null;
if (class_exists('GGRR_Storage') && ($slice === null || $slice['offset'] === 0)) {
    $mt_docs = GGRR_Storage::get_documents(['visibility' => 'public', 'limit' => 999]);
    $out = "Glass Government — Records Reading Room\n";
    $out .= "========================================\n";
    $out .= "Total documents: " . count($mt_docs) . "\n";
    $out .= "URL: " . home_url('/library/') . "\n";
    $out .= "Generated: " . gmdate('Y-m-d H:i:s T') . "\n";
    $out .= "\n";
    foreach ($mt_docs as $d) {
        $_url = home_url('/library/' . rawurlencode((string) ($d['slug'] ?? '')) . '/');
        $_title = (string) ($d['title'] ?? '');
        $_lic = (string) ($d['license'] ?? '');
        if ($_lic !== '' && function_exists('ggrr_license_label')) {
            $_lic = ggrr_license_label($_lic);
        }
        $_class = function_exists('ggrr_doc_class') ? ggrr_doc_class($d) : '';
        $meta = implode(' | ', array_filter([$_title, (string) ($d['agency'] ?? ''), (string) ($d['collection'] ?? ''),
                                             (string) ($d['document_date'] ?? ''), $_lic]));
        $out .= "- [{$_title}]({$_url})";
        if ($meta !== '') { $out .= " — {$meta}"; }
        if ($_class === 'third-party') { $out .= " [third-party]"; }
        if ((string) ($d['file_sha256'] ?? '') !== '') { $out .= " (sha256:" . $d['file_sha256'] . ")"; }
        if ((string) ($d['ia_id'] ?? '') !== '' && ($d['ia_status'] ?? '') === 'confirmed') { $out .= " [IA]"; }
        $out .= "\n";
    }
    $out .= "\n---\n";
    $out .= "End of index. " . count($mt_docs) . " documents listed.\n";
    $machine_text = [
        'files' => [['url' => home_url('/library/documents.txt'), 'text' => $out]],
        'source' => ['templates/txt-ggrr-documents.php' => is_readable(GGRR_PATH . 'templates/txt-ggrr-documents.php')
                     ? hash_file('sha256', GGRR_PATH . 'templates/txt-ggrr-documents.php') : ''],
    ];
}

// --- topics: the topics page (templates/archive-ggrr-topics.php) and every page of
// every topic (templates/archive-ggrr-topic.php, 50 records a page as /page/N/),
// each word as those templates write it, the records from the plugin's own calls in
// their order. The templates build their strings inline, so each formula is repeated
// here and named; `roomkit parity --topics` compares the result with the live pages.
// First slice only, as entities.

function roomkit_gg_topic_url(string $topic, int $n = 1): string {
    $base = home_url('/library/topics/' . rawurlencode($topic) . '/');
    return $n === 1 ? $base : $base . 'page/' . $n . '/';
}

// archive-ggrr-topic.php for one (topic, page), with no ?s=.
function roomkit_gg_topic_page(string $topic, int $topic_page, int $total, int $per_page): array {
    $T = 'GGRR_Template';
    // $topic_label: segments, the template's acronym list uppercased, the rest ucfirst.
    $segments = explode(' ', str_replace(['_', '-'], ' ', strtolower($topic)));
    $acronyms = ['acs', 'agloso', 'chip', 'cointelpro', 'cpusa', 'dhs', 'doj', 'fbi', 'ffp', 'fmap', 'huac', 'lapd', 'mco',
                 'naacp', 'oasdi', 'pccm', 'pfas', 'plp', 'sclc', 'sds', 'snap', 'sncc', 'ssoc', 'swp', 'tanf', 'wsa', 'ysa'];
    $label = implode(' ', array_map(fn($seg) => in_array($seg, $acronyms, true) ? strtoupper($seg) : ucfirst($seg), $segments));
    $docs = GGRR_Storage::get_documents_by_topic($topic, $per_page, ($topic_page - 1) * $per_page, '');
    $total_pages = (int) ceil($total / max(1, $per_page));
    $base = roomkit_gg_topic_url($topic);
    $page = [
        'slug' => $topic,
        'page' => $topic_page,
        'url' => roomkit_gg_topic_url($topic, $topic_page),
        'head_title' => ucwords(str_replace(['_', '-'], ' ', $topic)) . ' – Glass Government',   // filter_document_title
        'crumbs' => [['label' => 'Home', 'url' => home_url('/')], ['label' => 'Reading Room', 'url' => home_url('/library/')],
                     ['label' => 'Topics', 'url' => home_url('/library/topics/')], ['label' => $label]],
        'back' => ['label' => '← Reading Room', 'url' => home_url('/library/')],
        'eyebrow' => 'Topic',
        'title' => $label,
        'subtitle' => sprintf(_n('%d document', '%d documents', $total, 'ggrr'), $total),
        'empty_text' => 'No documents found for this topic.',
        'jsonld' => array_filter([
            '@context' => 'https://schema.org',
            '@type' => 'DefinedTerm',
            'name' => $label,
            'description' => $total . ' document' . ($total === 1 ? '' : 's') . ' tagged with ' . $label . ' in the Glass Government Reading Room',
            'url' => $base,
            'inDefinedTermSet' => 'Glass Government Reading Room Topics',
        ], fn($v) => $v !== '' && $v !== null),
    ];
    if ($total > $per_page) {
        // archive-ggrr-topic.php .ggrr-search-form: name="s", answered by get_documents_by_topic($topic, ..., $search).
        $page['search'] = ['label' => 'Filter documents', 'placeholder' => 'Filter within this topic…', 'param' => 's'];
    }
    $page['documents'] = array_map(function ($doc) use ($T) {
        $collection = (string) ($doc['collection'] ?? '');
        $date = (string) ($doc['document_date'] ?? '');
        $summary = (string) ($doc['summary'] ?? '');
        $row = ['slug' => (string) $doc['slug'], 'title' => (string) ($doc['title'] ?? ''),
                'url' => home_url('/library/' . rawurlencode($doc['slug']) . '/')] + roomkit_gg_badge($doc);
        if ($date !== '') { $row['date'] = $T::format_display_date($date); }
        if ($collection !== '') {
            $row['collection'] = ['label' => $T::collection_label($collection), 'url' => roomkit_gg_collection_url($collection)];
        }
        if (!empty($doc['reading_time'])) { $row['reading_time'] = (int) $doc['reading_time'] . ' min'; }
        if ((string) ($doc['agency'] ?? '') !== '') { $row['agency'] = (string) $doc['agency']; }
        // wp_trim_words ends a cut summary with &hellip;, which esc_html leaves as it is.
        if ($summary !== '') { $row['summary'] = html_entity_decode(wp_trim_words($summary, 40), ENT_QUOTES); }
        return $row;
    }, $docs);
    if ($total_pages > 1) {
        $items = [];
        if ($topic_page > 1) {
            $items[] = ['kind' => 'prev', 'label' => '← Previous', 'url' => roomkit_gg_topic_url($topic, $topic_page - 1)];
        }
        $range = 2;
        $dots_shown = false;
        for ($i = 1; $i <= $total_pages; $i++) {
            if ($i === $topic_page) {
                $items[] = ['kind' => 'current', 'label' => (string) $i];
                $dots_shown = false;
            } elseif ($i === 1 || $i === $total_pages || ($i >= $topic_page - $range && $i <= $topic_page + $range)) {
                $items[] = ['kind' => 'page', 'label' => (string) $i, 'url' => roomkit_gg_topic_url($topic, $i)];
                $dots_shown = false;
            } elseif (!$dots_shown) {
                $items[] = ['kind' => 'dots', 'label' => '…'];
                $dots_shown = true;
            }
        }
        if ($topic_page < $total_pages) {
            $items[] = ['kind' => 'next', 'label' => 'Next →', 'url' => roomkit_gg_topic_url($topic, $topic_page + 1)];
        }
        $page['pagination'] = ['label' => 'Page navigation', 'items' => $items];
    }
    return $page;
}

$topics = null;
if (class_exists('GGRR_Storage') && method_exists('GGRR_Storage', 'get_documents_by_topic')
    && ($slice === null || $slice['offset'] === 0)) {
    // archive-ggrr-topics.php's list: the cached summary, or the same built from get_all_topics.
    $tlist = function_exists('ggrr_holdings_topic_summary') ? ggrr_holdings_topic_summary() : [];
    if (empty($tlist)) {
        foreach (GGRR_Storage::get_all_topics() as $tslug => $tcount) {
            $tlist[] = ['topic' => $tslug, 'label' => ucwords(str_replace(['_', '-'], ' ', $tslug)), 'count' => $tcount,
                        'url' => home_url('/library/topics/' . rawurlencode($tslug) . '/')];
        }
        usort($tlist, static fn($a, $b) => $b['count'] <=> $a['count'] ?: strcmp($a['label'], $b['label']));
    }
    $tpages = [];
    foreach ($tlist as $t) {
        $tslug = (string) $t['topic'];
        $ttotal = GGRR_Storage::get_topic_document_count($tslug, '');
        $tn = max(1, (int) ceil($ttotal / 50));
        for ($n = 1; $n <= $tn; $n++) {
            $tpages[] = roomkit_gg_topic_page($tslug, $n, $ttotal, 50);
        }
    }
    $topics = [
        'index' => [
            'url' => home_url('/library/topics/'),
            'head_title' => 'Topics – Glass Government',                       // filter_document_title
            'back' => ['label' => '← Reading Room', 'url' => home_url('/library/')],
            'title' => 'Topics',
            'subtitle' => number_format_i18n(count($tlist)) . ' subjects across the collection',
            'empty_text' => 'No topics found.',
            'topics' => array_map(fn($t) => ['slug' => (string) $t['topic'], 'label' => (string) $t['label'],
                                             'count' => number_format_i18n($t['count']), 'url' => (string) $t['url']], $tlist),
        ],
        'pages' => $tpages,
        'source' => array_map(fn($f) => is_readable(GGRR_PATH . $f) ? hash_file('sha256', GGRR_PATH . $f) : '', [
            'templates/archive-ggrr-topics.php' => 'templates/archive-ggrr-topics.php',
            'templates/archive-ggrr-topic.php' => 'templates/archive-ggrr-topic.php',
            'includes/class-ggrr-storage.php' => 'includes/class-ggrr-storage.php',
            'includes/ggrr-homepage-data.php' => 'includes/ggrr-homepage-data.php',
            'includes/class-ggrr-template.php' => 'includes/class-ggrr-template.php',
        ]),
    ];
}

// --- passages: the passage route and the curated citations (first slice only) ---
$passages = null;
if ($slice === null || $slice['offset'] === 0) {
    $curated = [];
    $cite_excluded = [];
    $keys = $wpdb->get_results("SELECT stable_key, document_id FROM " . $S::citations_table_name() . " ORDER BY id ASC", ARRAY_A);
    foreach ((array) $keys as $k) {
        $key = (string) $k['stable_key'];
        $slug_of = $public_slug[(int) $k['document_id']] ?? null;
        if ($slug_of === null) {
            $cite_excluded[] = ['stable_key' => $key, 'problem' => 'its record is not public'];
            continue;
        }
        $c = GGRR_Citations::get_by_stable_key($key);
        if ($c === null) {
            $cite_excluded[] = ['stable_key' => $key, 'problem' => 'its page is gone'];
            continue;
        }
        $pin = (string) ($public_sha[(int) $k['document_id']] ?? '');
        // Pinned to the file the record has now; roomkit refuses the row if that file changes.
        $curated[] = ['slug' => (string) $slug_of] + $c + (preg_match('/^[a-f0-9]{64}$/', $pin) ? ['file_sha256' => $pin] : []);
    }
    $passages = [
        'api' => rest_url('ggrr/v1/passage'),
        'citations' => $curated,
        'excluded' => $cite_excluded,
        'source' => array_map(fn($f) => is_readable(GGRR_PATH . $f) ? hash_file('sha256', GGRR_PATH . $f) : '', [
            'includes/class-ggrr-citations.php' => 'includes/class-ggrr-citations.php',
            'includes/class-ggrr-rest.php' => 'includes/class-ggrr-rest.php',
        ]),
    ];
}

$home = untrailingslashit(home_url());
try {
    $json = json_encode([
    'site' => [
        'name' => (string) wp_parse_url($home, PHP_URL_HOST),
        'title' => 'Glass Government Reading Room',
        'base_url' => $home,
        'room_path' => '/library/',
        'template' => 'glassgovernment',
        'index' => [
            'eyebrow' => 'Public records, served whole',
            'title' => 'The Reading Room',
            // The no-JS search form (templates/index-ggrr-reading-room.php .ggrr-rr-nojs-form):
            // the server answers /library/?q= with ggrr_reading_room_documents(null, $q).
            'server_search' => ['action' => home_url('/library/'), 'param' => 'q', 'label' => 'Search records',
                                'placeholder' => 'Search by title, agency, collection, or type…', 'button' => 'Search'],
            'groups' => array_values(array_unique($group_order)),
            'group_label' => 'Collection',
            // The live index's span (ggrr_holdings_summary), which counts more than the dated records.
            'years' => (function_exists('ggrr_holdings_summary') && ($hs = ggrr_holdings_summary())
                && !empty($hs['year_min']) && !empty($hs['year_max']))
                ? [(string) $hs['year_min'], (string) $hs['year_max']] : null,
            'links' => [[
                'label' => 'Power maps',
                'url' => home_url('/library/power-maps/'),
                'text' => 'who contracts with and oversees whom, each connection quoted from records in this room.',
            ]],
            'facets' => [
                ['name' => 'type', 'label' => 'Record type'],
                ['name' => 'source', 'label' => 'Source'],
                ['name' => 'agency', 'label' => 'Agency'],
                ['name' => 'vendor', 'label' => 'Vendor', 'multi' => true],
                ['name' => 'year', 'label' => 'Year', 'range' => true, 'from_label' => 'From year', 'to_label' => 'To year'],
            ],
            // The live sort select's options, in its order.
            'sort' => ['label' => 'Sort', 'options' => [
                ['value' => 'default', 'label' => 'Default order'],
                ['value' => 'date-desc', 'label' => 'Date (newest)'],
                ['value' => 'date-asc', 'label' => 'Date (oldest)'],
                ['value' => 'title', 'label' => 'Title (A-Z)'],
            ]],
            'group_sets' => $group_sets,
            // No live page words these; the room's own copy, kept here with the site's.
            'browse' => [
                'heading' => 'Browse records by',
                'facets' => [
                    ['name' => 'agency', 'label' => 'Agency', 'title' => 'Records from {value}'],
                    ['name' => 'type', 'label' => 'Record type', 'title' => 'Record type: {value}'],
                    ['name' => 'vendor', 'label' => 'Vendor', 'title' => 'Records naming {value}'],
                    ['name' => 'year', 'label' => 'Year', 'title' => 'Records from {value}'],
                ],
            ],
        ],
    ],
    'exported_by' => 'roomkit/exporters/glassgovernment.php',
    'documents' => $docs,
    'excluded' => $problems,
] + ($entities ? ['entities' => $entities] : []) + ($collections ? ['collections' => $collections] : [])
  + ($machine_text ? ['machine_text' => $machine_text] : [])
  + ($topics ? ['topics' => $topics] : [])
  + ($passages ? ['passages' => $passages] : [])
  + ($slice ? ['slice' => $slice] : []), JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
} catch (JsonException $e) {
    fwrite(STDERR, 'roomkit exporter: manifest is not encodable as JSON (' . $e->getMessage() . '); nothing written' . "\n");
    exit(1);
}
fwrite(STDOUT, $json . "\n");
