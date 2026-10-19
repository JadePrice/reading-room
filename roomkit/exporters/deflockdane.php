<?php
/**
 * roomkit manifest exporter for deflockdane.org (plugin deflock-reading-room).
 *
 * READ-ONLY. Run from the Mac, script on stdin, nothing copied to the host:
 *
 *   ssh gg-shared '~/bin/wp --path=$HOME/domains/deflockdane.org/public_html eval-file -' \
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

function roomkit_dd_view_url(array $doc, string $inline_url): string {
    // get_view_copy() without its transient: same conditions, hashed every time.
    $sha = strtolower((string) ($doc['file_sha256'] ?? ''));
    $dir = Deflock_Reading_Room_Storage::private_storage_dir();
    if (!preg_match('/^[a-f0-9]{64}$/', $sha) || $dir === '' || $inline_url === '') {
        return '';
    }
    $base = trailingslashit($dir) . 'view/' . $sha;
    $path = $base . '.pdf';
    if (!is_file($base . '.json') || !is_readable($path)) {
        return '';
    }
    $meta = json_decode((string) file_get_contents($base . '.json'), true);
    if (!is_array($meta) || empty($meta['ok']) || ($meta['source_sha256'] ?? '') !== $sha) {
        return '';
    }
    $view = strtolower((string) ($meta['view_sha256'] ?? ''));
    if (!preg_match('/^[a-f0-9]{64}$/', $view) || (int) filesize($path) !== (int) ($meta['view_bytes'] ?? -1)
        || !hash_equals($view, (string) hash_file('sha256', $path))) {
        return '';
    }
    return add_query_arg(['v' => substr($view, 0, 12), 'view' => '1'], remove_query_arg('v', $inline_url));
}

// The archive shortcode's helpers are private; reflection reads them without
// copying their logic (the card date).
$SC = 'Deflock_Reading_Room_Shortcode';
$card_date = new ReflectionMethod($SC, 'format_date');
$card_date->setAccessible(true);
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

$docs = [];
$problems = [];
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
        $view = roomkit_dd_view_url($doc, $inline);
        if ($view !== '') {
            $file['view_url'] = $view;
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
    $row_display = [
        'released' => $date !== '' && $date !== '0000-00-00' ? $T::format_display_date($date) : '',
        'details' => [
            ['label' => 'Agency', 'value' => (string) ($doc['agency'] ?: 'Not listed yet')],
            ['label' => 'Document date', 'value' => $T::format_display_date($date)],
            ['label' => 'Contract start', 'value' => $T::format_display_date((string) ($doc['contract_start'] ?? ''))],
            ['label' => 'Contract end', 'value' => $T::format_display_date((string) ($doc['contract_end'] ?? ''))],
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
        'card_date' => $date !== '' && $date !== '0000-00-00' ? $card_date->invoke(null, $date) : '',
        'thumb_url' => (int) ($doc['attachment_id'] ?? 0) > 0 ? $S::get_thumbnail_url($doc, 'thumbnail') : '',
    ];
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
            'facets' => [['name' => 'year', 'label' => 'Year']],
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
