<?php
/**
 * roomkit manifest exporter for glassgovernment.org (plugin gg-reading-room).
 *
 * READ-ONLY. Run from the Mac, script on stdin, nothing copied to the host:
 *
 *   ssh gg-core 'sudo -n /usr/local/bin/wp-prod eval-file -' \
 *     < scripts/roomkit/exporters/glassgovernment.php > gg-manifest.json
 *
 * (`wp-prod` is the operator's wp-cli wrapper for /srv/wp-prod/current; the
 * same route scripts/wiki/corpus_manifest.py reads the census by.)
 *
 * Prints one JSON manifest (scripts/roomkit/manifest.py) of the public
 * documents, in the library's own order. Everything a page shows comes from
 * the plugin's own helpers, called the way templates/single-ggrr-document.php
 * calls them: the citation is GGRR_Citations::format_reference, the badge
 * GGRR_Template::provenance_badge's label, the rights line
 * GGRR_Template::provenance_rights' output taken apart, entities
 * GGRR_Entities::for_doc with the template's two headings, and the entity index
 * and entity pages (`entities`) from list_approved, entity_label,
 * docs_for_entity and co_occurring under index-ggrr-entities.php's and
 * entity-ggrr.php's own words. Where the template
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
 * scripts/roomkit/exporters/merge-slices.py joins them (refusing a gap or an
 * overlap). Without it, everything goes out at once, as before.
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
// sudo (wp-prod) does not pass environment variables, so the flags may also
// arrive as constants defined in a one-line PHP block prepended on stdin
// (scripts/roomkit/publish/glassgovernment-staging.sh does this).
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

$ent_headings = [
    'authorship' => ['Attributed to', 'Recorded in the catalog as the party that produced this document.'],
    'named' => ['Named in this document', 'Matched verbatim in the document text. The quoted words are the match and the line around them.'],
];
$ent_types = ['vendor' => 'Vendor', 'agency' => 'Agency', 'org' => 'Organization', 'program' => 'Program', 'location' => 'Location'];

$docs = [];
$problems = [];
foreach ($rows as $doc) {
    $slug = (string) $doc['slug'];
    $id = (int) $doc['id'];
    $path = $S::get_file_path($doc);
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
    $inline = $S::get_inline_file_url($doc);
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
        $details[] = ['label' => 'Permanent copy', 'value' => 'Internet Archive', 'url' => $ia_url, 'note' => 'Verified present'];
    } elseif (!empty($doc['ia_id']) && ($doc['ia_status'] ?? '') === 'pending') {
        $details[] = ['label' => 'Permanent copy', 'value' => 'Backup pending', 'note' => 'Internet Archive upload in progress'];
    } elseif (!empty($doc['ia_id'])) {
        $details[] = ['label' => 'Permanent copy', 'value' => 'Not yet archived'];
    }
    $details[] = ['label' => 'SHA-256', 'value' => $sha, 'code' => true];

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
        $groups[] = ['heading' => 'Related documents', 'style' => 'list', 'items' => array_map(fn($r) => [
            'label' => $r['title'], 'url' => home_url('/library/' . rawurlencode($r['slug']) . '/'),
            'meta' => $T::collection_label($r['collection']),
        ], $related)];
    }

    $badge = '';
    $badge_kind = function_exists('ggrr_doc_class') ? ggrr_doc_class($doc) : '';
    if ($badge_kind === 'government') {
        $badge = 'Government record';
    } elseif ($badge_kind === 'third-party') {
        $badge = 'Third-party report';
    } else {
        $badge_kind = '';
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

    $display = array_filter([
        'breadcrumbs' => [
            ['label' => 'Home', 'url' => home_url('/')],
            ['label' => 'Reading Room', 'url' => home_url('/library/')],
            ['label' => $collection_label, 'url' => $collection_url],
            ['label' => (string) $doc['title']],
        ],
        'eyebrow' => ['label' => $collection_label, 'url' => $collection_url],
        'badge' => $badge,
        'badge_kind' => $badge_kind,
        'released' => $date_display,
        'notice' => $sens ? array_filter(['heading' => $sens['heading'], 'body' => $sens['body'], 'report' => (string) ($sens['report'] ?? '')]) : null,
        'details' => $details,
        'notes' => (string) ($doc['notes_public'] ?? ''),
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
            'facets' => (object) array_filter([
                'type' => !empty($doc['record_type']) ? ucwords(str_replace(['_', '-'], ' ', (string) $doc['record_type'])) : '',
                'source' => (string) ($doc['source_label'] ?: ($doc['source_system'] ?? '')),
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
foreach ($T::collections_by_category() as $cat => $grps) {
    foreach ($grps as $grp => $cols) {
        foreach ($cols as $c) {
            $group_order[] = $T::collection_label((string) $c['slug']);
        }
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
        $curated[] = ['slug' => (string) $slug_of] + $c;
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
            'groups' => array_values(array_unique($group_order)),
            'group_label' => 'Collection',
            'links' => [[
                'label' => 'Power maps',
                'url' => home_url('/library/power-maps/'),
                'text' => 'who contracts with and oversees whom, each connection quoted from records in this room.',
            ]],
            'facets' => [
                ['name' => 'type', 'label' => 'Record type'],
                ['name' => 'source', 'label' => 'Source'],
                ['name' => 'agency', 'label' => 'Agency'],
                ['name' => 'year', 'label' => 'Year'],
            ],
        ],
    ],
    'exported_by' => 'scripts/roomkit/exporters/glassgovernment.php',
    'documents' => $docs,
    'excluded' => $problems,
] + ($entities ? ['entities' => $entities] : []) + ($passages ? ['passages' => $passages] : [])
  + ($slice ? ['slice' => $slice] : []), JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
} catch (JsonException $e) {
    fwrite(STDERR, 'roomkit exporter: manifest is not encodable as JSON (' . $e->getMessage() . '); nothing written' . "\n");
    exit(1);
}
fwrite(STDOUT, $json . "\n");
