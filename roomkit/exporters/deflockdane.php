<?php
/**
 * roomkit manifest exporter for deflockdane.org (plugin deflock-reading-room).
 *
 * READ-ONLY. Run from the Mac, script on stdin, nothing copied to the host:
 *
 *   ssh $DD_HOST '~/bin/wp --path=$HOME/domains/deflockdane.org/public_html eval-file -' \
 *     < roomkit/exporters/deflockdane.php > dd-manifest.json
 *
 * Prints one JSON manifest (roomkit/manifest.py) of the public
 * documents, in the reading room's own order, and `entities`: a page for every
 * approved entity of every type, as entity-reading-room.php shows it
 * (roomkit/entities.py). URLs come from the plugin's own
 * helpers. The citation is the template's formula (single-reading-room.php,
 * "Formatted citation from provenance metadata"), repeated here because the
 * plugin builds it inline; `roomkit parity` checks every exported citation
 * against the live page, so a drift between the two is caught, not shipped.
 *
 * Not called, because they write: get_view_copy() (sets a transient) and
 * get_thumbnail_path() (builds a preview cache). The viewing-copy check below
 * is get_view_copy()'s, minus the transient.
 *
 * Page text is exported (ROOMKIT_WITH_PAGES=0 leaves it out). The plugin never
 * sends a page's full OCR text to the browser (REST returns snippets only);
 * shipping it in pages.json for in-browser search was decided by the project
 * owner on 2026-10-08 (decision D6, conductor/plans/2026-10-08-static-reading-room.md).
 *
 * Refuses (exit 1, JSON {"error", "problems"} on stdout) when a public
 * record's file is missing or its bytes do not hash to file_sha256. With
 * ROOMKIT_ALLOW_EXCLUDED=1 such records are written to the manifest's
 * `excluded` list with the problem instead, and roomkit names them on every
 * build and status: excluded out loud, never dropped quietly.
 * Fails (exit 1, one line on stderr, nothing on stdout) if the manifest can't be JSON-encoded, e.g. invalid UTF-8.
 */

if (!class_exists('Deflock_Reading_Room_Storage') || !class_exists('Deflock_Reading_Room_Template')) {
    fwrite(STDOUT, json_encode(['error' => 'deflock-reading-room is not active']) . "\n");
    exit(1);
}

global $wpdb;
$S = 'Deflock_Reading_Room_Storage';
$T = 'Deflock_Reading_Room_Template';
$with_pages = getenv('ROOMKIT_WITH_PAGES') !== '0';
$allow_excluded = getenv('ROOMKIT_ALLOW_EXCLUDED') === '1';

$rows = $wpdb->get_results(
    "SELECT * FROM " . $S::table_name() . " WHERE visibility = 'public' ORDER BY sort_order ASC, document_date DESC, id DESC",
    ARRAY_A
);

function roomkit_dd_view_url(array $doc, string $inline_url): array {
    // get_view_copy() without its transient: same conditions, hashed every time.
    // [url, its sha256], or ['', ''].
    $sha = strtolower((string) ($doc['file_sha256'] ?? ''));
    $dir = Deflock_Reading_Room_Storage::private_storage_dir();
    if (!preg_match('/^[a-f0-9]{64}$/', $sha) || $dir === '' || $inline_url === '') {
        return ['', ''];
    }
    $base = trailingslashit($dir) . 'view/' . $sha;
    $path = $base . '.pdf';
    if (!is_file($base . '.json') || !is_readable($path)) {
        return ['', ''];
    }
    $meta = json_decode((string) file_get_contents($base . '.json'), true);
    if (!is_array($meta) || empty($meta['ok']) || ($meta['source_sha256'] ?? '') !== $sha) {
        return ['', ''];
    }
    $view = strtolower((string) ($meta['view_sha256'] ?? ''));
    if (!preg_match('/^[a-f0-9]{64}$/', $view) || (int) filesize($path) !== (int) ($meta['view_bytes'] ?? -1)
        || !hash_equals($view, (string) hash_file('sha256', $path))) {
        return ['', ''];
    }
    return [add_query_arg(['v' => substr($view, 0, 12), 'view' => '1'], remove_query_arg('v', $inline_url)), $view];
}

// The archive shortcode's helpers are private; reflection reads them without
// copying their logic (the card date).
$SC = 'Deflock_Reading_Room_Shortcode';
$card_date = new ReflectionMethod($SC, 'format_date');
$card_date->setAccessible(true);
// The card thumbnail, copied into the room (manifest index.thumb): the preview the
// /thumb/ route serves, read from the plugin's cache without get_thumbnail_path(),
// which builds the cache when it is missing (a write). Its size order, repeated.
$previews = new ReflectionMethod($S, 'get_private_preview_paths');
$previews->setAccessible(true);
function roomkit_dd_thumb(ReflectionMethod $previews, array $doc): ?array {
    $cached = $previews->invoke(null, (int) ($doc['attachment_id'] ?? 0));
    foreach (['thumbnail', 'medium', 'large', 'full'] as $size) {
        if (!empty($cached[$size])) {
            $bytes = (string) file_get_contents((string) $cached[$size]);
            $mime = (string) wp_check_filetype(wp_basename((string) $cached[$size]), null)['type'];
            return ['mime' => $mime !== '' ? $mime : 'image/jpeg', 'sha256' => hash('sha256', $bytes),
                    'data' => base64_encode($bytes)];
        }
    }
    return null;
}
function roomkit_dd_suggest(array $archive, array $status_count = ['status' => [], 'kind' => []]): array {
    $s = $archive['suggestions'];
    $m = $archive['messages'];
    $items = fn(array $list) => array_values(array_map(fn($it) => array_filter([
        'label' => (string) $it['label'],
        'query' => (string) $it['query'],
        'count' => isset($it['count']) ? (int) $it['count'] : null,
    ], fn($v) => $v !== null && $v !== ''), $list));
    // The room's own groups: each item sets the finder's Status or Record kind filter.
    $status_groups = [];
    foreach (['status' => ['Status', ['Current', 'Past', 'Unknown']],
              'kind' => ['Record kind', ['Surveillance monitoring', 'Procurement']]] as $facet => [$label, $order]) {
        $opts = [];
        foreach ($order as $v) {
            if (isset($status_count[$facet][$v])) {
                $opts[] = ['label' => $v === 'Unknown' ? 'Status unknown' : $v, 'facet' => $facet, 'value' => $v,
                            'count' => $status_count[$facet][$v]];
            }
        }
        if ($opts) {
            $status_groups[] = ['label' => $label, 'items' => $opts, 'empty' => 3, 'typing' => 3];
        }
    }
    return [
        'labels' => ['top' => $m['topMatches'], 'recent_docs' => $m['recentDocuments'], 'recent_searches' => $m['recentSearches']],
        'top' => (int) $archive['maxResults'],
        'recent_docs' => array_map(fn($d) => basename(rtrim((string) wp_parse_url((string) $d['url'], PHP_URL_PATH), '/')), $s['recentDocs']),
        'groups' => [
            ['label' => $m['featuredQueries'], 'items' => $items($s['featuredQueries']), 'empty' => 6, 'typing' => 0],
            ...$status_groups,
            ['label' => $m['suggestedAgencies'], 'items' => $items($s['agencies']), 'empty' => 4, 'typing' => 4],
            ['label' => $m['suggestedVendors'], 'items' => $items($s['vendors']), 'empty' => 4, 'typing' => 4],
            ['label' => $m['suggestedTypes'], 'items' => $items($s['docTypes']), 'empty' => 4, 'typing' => 4],
            ['label' => $m['suggestedYears'], 'items' => $items($s['years']), 'empty' => 0, 'typing' => 4],
        ],
        // What the live panel's scoreDoc reads for each record (prepareDoc), so the
        // room's top matches rank as live's do.
        'rank' => array_map(fn($d) => [
            'slug' => (string) $d['slug'], 'title' => (string) $d['title'], 'agency' => (string) $d['agency'],
            'summary' => (string) $d['summary'], 'date' => (string) $d['date'], 'year' => (string) $d['year'],
            'doc_type' => (string) $d['docType'],
            'aliases' => array_values(array_map('strval', (array) $d['aliases'])),
            'vendors' => array_values(array_map('strval', (array) $d['vendors'])),
        ], $archive['docs']),
    ];
}
$vendor_map = class_exists('Deflock_Reading_Room_Entities') ? Deflock_Reading_Room_Entities::approved_by_doc(['vendor']) : [];
// These two lists live inline in Deflock_Reading_Room_Shortcode::render();
// repeated here, and a drift shows as a category the live index groups differently.
$categories = [
    'Wisconsin Department of Administration & WI State Capital Police',
    'UW-Madison Police Department',
    'Maple Bluff Police Department',
    'Dane County Sheriff\'s Office',
    'Waunakee Village PD',
];
$agency_aliases = [
    'University of Wisconsin Police Department' => 'UW-Madison Police Department',
    'Village of Maple Bluff PD' => 'Maple Bluff Police Department',
];

// What the live index's finder narrows by (agency, document type, vendor, year), from
// the shortcode's own payload builder fed what render() feeds it, so each record's
// facet pages hold what live filtering by that value holds (browse.py).
$payload = new ReflectionMethod($SC, 'build_archive_search_payload');
$payload->setAccessible(true);
$browse_by_slug = [];
$archive = $payload->invoke(null, $S::get_docs(['visibility' => 'public', 'limit' => 200]), $categories, $agency_aliases, '');
foreach ($archive['docs'] as $p) {
    $browse_by_slug[(string) $p['slug']] = array_filter([
        'agency' => array_values(array_filter([(string) $p['agency']])),
        'type' => array_values(array_filter([(string) $p['docType']])),
        'vendor' => array_values(array_unique(array_filter(array_map('strval', (array) $p['vendors'])))),
        'year' => array_values(array_filter([(string) $p['year']])),
    ]);
}

$docs = [];
$problems = [];
// Each record's status and kind as its page words them (Template::record_status,
// plugin 0.9.0); null for a record never classified, or on an older plugin.
$status_of = fn(array $doc) => method_exists($T, 'record_status') ? $T::record_status($doc) : null;
$status_count = ['status' => [], 'kind' => []];
foreach ((array) $rows as $doc) {
    $slug = (string) $doc['slug'];
    $path = $S::get_file_path($doc);
    if ($path === '' || !is_readable($path)) {
        $problems[] = ['slug' => $slug, 'problem' => 'file missing or unreadable'];
        continue;
    }
    $sha = strtolower((string) $doc['file_sha256']);
    if (!hash_equals($sha, (string) hash_file('sha256', $path))) {
        $problems[] = ['slug' => $slug, 'problem' => 'file bytes do not hash to file_sha256'];
        continue;
    }
    $ext = $S::get_file_extension($doc);
    $mime = $ext === 'pdf' ? 'application/pdf' : (string) (wp_check_filetype('x.' . $ext)['type'] ?? '');
    $inline = $S::get_inline_file_url($doc);

    // --- citation: single-reading-room.php, verbatim formula ---
    $_cite_permalink = home_url('/reading-room/' . rawurlencode($slug) . '/');
    $_cite_author    = trim((string) ($doc['agency'] ?? ''));
    $_cite_title     = trim((string) ($doc['title'] ?? ''));
    $_cite_date      = !empty($doc['document_date'])
        ? $T::format_display_date((string) $doc['document_date'])
        : 'n.d.';
    $_cite = '';
    if ($_cite_author !== '') {
        $_cite .= $_cite_author . '. ';
    }
    if ($_cite_title !== '') {
        $_cite .= '"' . $_cite_title . '." ';
    }
    $_cite .= rtrim($_cite_date, '.') . '. Deflock Dane Reading Room, ' . $_cite_permalink . '.';
    if (!empty($doc['source_url'])) {
        $_cite .= ' Source: ' . (string) $doc['source_url'] . '.';
    }
    // --- end citation ---

    $date = (string) ($doc['document_date'] ?? '');
    $file = [
        'url' => $inline,
        'download_url' => $S::get_download_file_url($doc),
        'sha256' => $sha,
        'bytes' => (int) filesize($path),
        'ext' => $ext,
        'mime' => $mime,
    ];
    if ($ext === 'pdf') {
        [$view, $view_sha] = roomkit_dd_view_url($doc, $inline);
        if ($view !== '') {
            $file['view_url'] = $view;
            $file['view_sha256'] = $view_sha;
        }
        $file['poster_url'] = $S::get_thumbnail_url($doc, 'large');
    }
    // --- display fields: what single-reading-room.php and the archive shortcode
    // show, from the plugin's own helpers, so roomkit's dd template formats nothing.
    $notes = $T::public_notes($doc);
    $source_url = (string) ($doc['source_url'] ?? '');
    $source_label = (string) ($doc['source_label'] ?? '');
    $vendors = array_map(fn($v) => [
        'label' => (string) $v['label'],
        'url' => home_url('/reading-room/entity/vendor/' . rawurlencode((string) $v['slug']) . '/'),
    ], $vendor_map[(int) $doc['id']] ?? []);
    $st = $status_of($doc);
    $row_display = [
        'released' => $date !== '' && $date !== '0000-00-00' ? $T::format_display_date($date) : '',
        'details' => [
            ['label' => 'Agency', 'value' => (string) ($doc['agency'] ?: 'Not listed yet')],
            ['label' => 'Document date', 'value' => $T::format_display_date($date)],
            ['label' => 'Contract start', 'value' => $T::format_display_date((string) ($doc['contract_start'] ?? ''))],
            ['label' => 'Contract end', 'value' => $T::format_display_date((string) ($doc['contract_end'] ?? ''))],
            ...($st !== null ? [
                array_filter(['label' => 'Status', 'value' => $st['status'], 'note' => $st['basis']], fn($v) => $v !== ''),
                ['label' => 'Record kind', 'value' => $st['kind']],
            ] : []),
            $source_url !== ''
                ? ['label' => 'Source', 'value' => $source_label ?: $source_url, 'url' => $source_url]
                : ['label' => 'Source', 'value' => $source_label ?: 'Not listed yet'],
            ['label' => 'SHA-256', 'value' => $sha, 'code' => true],
        ],
        'notes' => $notes,
        'breadcrumbs' => [
            ['label' => 'Reading Room', 'url' => home_url('/reading-room/')],
            ['label' => (string) $doc['title']],
        ],
        'groups' => $vendors ? [[
            'heading' => 'Vendors',
            'style' => 'chips',
            'items' => array_values($vendors),
        ]] : [],
    ];
    // JSON-LD: single-reading-room.php's formula, repeated (it is built inline there).
    $_jl_url = home_url('/reading-room/' . rawurlencode($slug) . '/');
    $_jl_desc = trim((string) ($doc['summary'] ?? ''));
    if ($_jl_desc !== '' && $T::looks_like_ocr($_jl_desc)) {
        $_jl_desc = '';
    }
    $row_display['jsonld'] = array_filter([
        '@context' => 'https://schema.org',
        '@type' => $ext === 'pdf' ? 'DigitalDocument' : 'CreativeWork',
        'name' => (string) ($doc['title'] ?? ''),
        'description' => $_jl_desc,
        'url' => $_jl_url,
        'mainEntityOfPage' => $_jl_url,
        'datePublished' => (string) ($doc['document_date'] ?? ''),
        'author' => ['@type' => 'Organization', 'name' => trim((string) ($doc['agency'] ?? '')) !== '' ? (string) $doc['agency'] : 'Deflock Dane'],
        'identifier' => (string) ($doc['file_sha256'] ?? ''),
        'isPartOf' => ['@type' => 'Collection', 'name' => 'Deflock Dane Reading Room', 'url' => home_url('/reading-room/')],
    ], fn($v) => $v !== '' && $v !== null && $v !== []);
    $agency_c = trim(preg_replace('/\s+/', ' ', (string) ($doc['agency'] ?? '')));
    $agency_c = $agency_aliases[$agency_c] ?? ($agency_c !== '' ? $agency_c : 'Other records');
    $row_index = [
        'group' => $agency_c,
        'facets' => (object) array_filter(['year' => strlen($date) >= 4 && $date !== '0000-00-00' ? substr($date, 0, 4) : '']),
        'browse' => (object) ($browse_by_slug[$slug] ?? []),
        'card_date' => $date !== '' && $date !== '0000-00-00' ? $card_date->invoke(null, $date) : '',
    ];
    if ($st !== null) {
        $row_index['badge'] = $st['label'] === 'Unknown' ? 'Status unknown' : $st['label'];
        $row_index['badge_kind'] = strtolower($st['label']);
        $row_index['badge_sr'] = 'Status: ';
        // The end a current record is winding down to, and the monitoring subgroup.
        $row_index['meta'] = array_values(array_filter([
            $st['status'] !== $st['label'] ? 'Ending ' . $T::format_display_date((string) $doc['status_until']) : '',
            $st['kind'] === 'Surveillance monitoring' ? $st['kind'] : '',
        ]));
        $row_index['facets'] = (object) ((array) $row_index['facets'] + ['status' => $st['label'], 'kind' => $st['kind']]);
        $row_index['browse'] = (object) ((array) $row_index['browse'] + ['status' => [$st['label']], 'kind' => [$st['kind']]]);
        $status_count['status'][$st['label']] = ($status_count['status'][$st['label']] ?? 0) + 1;
        $status_count['kind'][$st['kind']] = ($status_count['kind'][$st['kind']] ?? 0) + 1;
    }
    // A card shows a thumbnail when the record has an attachment (the shortcode's test).
    // Cached: the room's own copy. Not cached: a PDF's is rendered on its first request,
    // so the card keeps the live route; anything else has none (live answers 404, a
    // broken image), so the card shows none.
    if ((int) ($doc['attachment_id'] ?? 0) > 0) {
        $thumb = roomkit_dd_thumb($previews, $doc);
        if ($thumb !== null) {
            $row_index['thumb'] = $thumb;
        } elseif ($ext === 'pdf') {
            $row_index['thumb_url'] = $S::get_thumbnail_url($doc, 'thumbnail');
        }
    }
    // --- end display fields ---

    $row = [
        'slug' => $slug,
        'title' => (string) $doc['title'],
        'visibility' => 'public',
        'citation' => $_cite,
        'agency' => (string) ($doc['agency'] ?? ''),
        'date' => ($date !== '' && $date !== '0000-00-00') ? $date : '',
        'summary' => (string) ($doc['summary'] ?? ''),
        'file' => $file,
        'display' => $row_display,
        'index' => $row_index,
    ];
    if ($with_pages) {
        $pages = $wpdb->get_results($wpdb->prepare(
            "SELECT page_number, ocr_text FROM " . $S::pages_table_name() . " WHERE doc_id = %d ORDER BY page_number ASC",
            (int) $doc['id']
        ), ARRAY_A);
        $row['pages'] = array_map(fn($p) => ['n' => (int) $p['page_number'], 'text' => (string) $p['ocr_text'], 'provenance' => 'site'], (array) $pages);
    }
    $docs[] = $row;
}

if ($problems && !$allow_excluded) {
    fwrite(STDOUT, json_encode(['error' => 'public records with missing or mismatched files', 'problems' => $problems], JSON_UNESCAPED_SLASHES) . "\n");
    exit(1);
}

// --- entities: one page per approved entity of every type
// (Deflock_Reading_Room_Entities::TYPES), as templates/entity-reading-room.php
// renders it: the words are that template's and Deflock_Reading_Room_Template's
// (title, meta description), the lists the plugin's own queries in their order
// (docs_for_entity: agency, then newest, then title; grouped by agency as the
// template groups them). The template builds them inline, so each formula is
// repeated here and named; `roomkit parity --entities` compares the result with
// the live pages. dd has no entity index page and its pages carry no claim
// headings and no JSON-LD (read 2026-10-15 from deflock-reading-room 3ab6ca4), so
// none are exported: roomkit shows only what the site says.
$entities = null;
if (class_exists('Deflock_Reading_Room_Entities')) {
    $EN = 'Deflock_Reading_Room_Entities';
    $ent_pages = [];
    foreach ($EN::TYPES as $etype) {
        foreach ($EN::list_approved($etype) as $ent) {
            $eslug = (string) ($ent['slug'] ?? '');
            $k = $etype . '/' . $eslug;
            if ($eslug === '' || isset($ent_pages[$k])) {
                continue;
            }
            // Template::current_entity_label(); the route 404s without one (is_known_entity_request).
            $label = $EN::entity_label($etype, $eslug);
            if ($label === '') {
                continue;
            }
            $edocs = $EN::docs_for_entity($etype, $eslug);
            $by_agency = [];
            foreach ($edocs as $d) {
                $agency = ($d['agency'] !== '') ? $d['agency'] : 'Other records';
                $by_agency[$agency][] = $d;
            }
            $page = [
                'type' => $etype,
                'slug' => $eslug,
                'url' => home_url('/reading-room/entity/' . rawurlencode($etype) . '/' . rawurlencode($eslug) . '/'),
                // Template::filter_document_title and ::filter_yoast_metadesc.
                'head_title' => $label . ' — Reading Room — ' . get_bloginfo('name'),
                'description' => 'Public records citing ' . $label . ' in the Deflock Dane reading room.',
                'back' => ['label' => '← Back to Reading Room', 'url' => home_url('/reading-room/')],
                'eyebrow' => ucfirst($etype),
                'title' => $label,
                'groups' => array_map(fn($agency, $list) => [
                    'heading' => (string) $agency,
                    'documents' => array_map(fn($d) => array_filter([
                        'slug' => (string) $d['slug'],
                        'title' => (string) $d['title'],
                        'url' => home_url('/reading-room/' . rawurlencode((string) $d['slug']) . '/'),
                        'meta' => (strlen((string) $d['date']) >= 4) ? substr((string) $d['date'], 0, 4) : '',
                    ], fn($v) => $v !== ''), $list),
                ], array_keys($by_agency), array_values($by_agency)),
                'empty_text' => 'No public records are linked to this entity yet.',
            ];
            if (!empty($edocs)) {
                $page['lede'] = sprintf(
                    _n('%1$d released record across %2$d agency.', '%1$d released records across %2$d agencies.', count($edocs), 'deflock-reading-room'),
                    (int) count($edocs),
                    (int) count($by_agency)
                );
            }
            $ent_pages[$k] = $page;
        }
    }
    $entities = [
        'pages' => array_values($ent_pages),
        // The files whose formulas are repeated above, as read on the host, so a
        // change to them can be seen next to the export (not rendered).
        'source' => array_map(fn($f) => is_readable(DEFLOCK_RR_PATH . $f) ? hash_file('sha256', DEFLOCK_RR_PATH . $f) : '', [
            'templates/entity-reading-room.php' => 'templates/entity-reading-room.php',
            'includes/class-deflock-reading-room-entities.php' => 'includes/class-deflock-reading-room-entities.php',
            'includes/class-deflock-reading-room-template.php' => 'includes/class-deflock-reading-room-template.php',
        ]),
    ];
}

$home = untrailingslashit(home_url());
try {
    $json = json_encode([
    'site' => [
        'name' => (string) wp_parse_url($home, PHP_URL_HOST),
        'title' => 'Deflock Dane Reading Room',
        'base_url' => $home,
        'room_path' => '/reading-room/',
        'template' => 'deflockdane',
        'index' => [
            'eyebrow' => 'Reading Room',
            'title' => 'Contract Documents & Public Records Releases',
            'lede' => 'Browse released contracts and related records on Deflock Dane. Each record is meant to resolve to a stable on-site reading page instead of a third-party file host.',
            'groups' => $categories,
            'group_label' => 'Agency',
            'empty_group_text' => 'No records have been released for this agency yet.',
            'facets' => array_merge($status_count['status'] ? [
                ['name' => 'status', 'label' => 'Status'],
                ['name' => 'kind', 'label' => 'Record kind'],
            ] : [], [['name' => 'year', 'label' => 'Year']]),
            // The finder's suggestion panel, from the same payload (manifest site.index.suggest).
            // The counts per group are the archive script's renderEmptyState and
            // renderQueryState (assets/js/deflock-reading-room.js), repeated.
            'suggest' => roomkit_dd_suggest($archive, $status_count),
            // No live page words these; the room's own copy, kept here with the site's.
            'browse' => [
                'heading' => 'Browse records by',
                'facets' => [
                    ['name' => 'agency', 'label' => 'Agency', 'title' => 'Records from {value}'],
                    ['name' => 'type', 'label' => 'Record type', 'title' => 'Record type: {value}'],
                    ['name' => 'vendor', 'label' => 'Vendor', 'title' => 'Records naming {value}'],
                    ['name' => 'year', 'label' => 'Year', 'title' => 'Records from {value}'],
                    ...($status_count['status'] ? [
                        ['name' => 'status', 'label' => 'Status', 'title' => 'Status: {value}', 'room_only' => true],
                        ['name' => 'kind', 'label' => 'Record kind', 'title' => 'Record kind: {value}', 'room_only' => true],
                    ] : []),
                ],
            ],
        ],
    ],
    'exported_by' => 'roomkit/exporters/deflockdane.php',
    'documents' => $docs,
    'excluded' => $problems,
] + ($entities ? ['entities' => $entities] : []), JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR);
} catch (JsonException $e) {
    fwrite(STDERR, 'roomkit exporter: manifest is not encodable as JSON (' . $e->getMessage() . '); nothing written' . "\n");
    exit(1);
}
fwrite(STDOUT, $json . "\n");
