"""Public API — port of worker/index.mjs, reading from D1 instead of KV.

Req/Resp are plain dicts so tests never touch the Worker runtime:
  req  = {method, path, raw_query, query, headers, origin, url, body?}
  resp = {status, headers: [(k, v), ...], body: str | None}
"""
import hmac
import json
import time

from db import chunk, db_all, db_first, env_get, get_meta
from util import CATEGORY_LABELS, epoch_ms

PUBLIC_CACHE = ('Cache-Control', 'public, max-age=60')
NO_STORE = ('Cache-Control', 'no-store')
_BASE_HEADERS = [
    ('Content-Type', 'application/json; charset=utf-8'),
    ('X-Content-Type-Options', 'nosniff'),
]
SCHEDULE = '*/30 * * * * (UTC)'
COLLECTION = 'Cloudflare Worker (Python) → D1'
DAY_MS = 86400000


def json_response(value, status=200, extra=()):
    return {
        'status': status,
        'headers': [*_BASE_HEADERS, PUBLIC_CACHE, *extra],
        'body': json.dumps(value, ensure_ascii=False, separators=(',', ':')),
    }


def error_response(message, status, extra=()):
    """404/400 keep the public cache like the JS version; pass NO_STORE for the rest."""
    return {
        'status': status,
        'headers': [*_BASE_HEADERS, PUBLIC_CACHE, *extra],
        'body': json.dumps({'error': message}, ensure_ascii=False, separators=(',', ':')),
    }


# ---------------------------------------------------------------------------
# Row → contract-shape mappers


def _source_out(row):
    return {
        'id': row['id'],
        'name': row['name'],
        'homepage': row['homepage'],
        'status': row['status'],
        'lastSuccessAt': row['last_success_at'],
        'itemCount': row['item_count'],
        'error': row['error'],
    }


_ITEM_COLS = (
    'id, title, url, summary, source_id, source_name, published_at, updated_at, '
    'collected_at, rank_score, metric_label, metric_value'
)


def _row_to_item(row):
    return {
        'id': row['id'],
        'title': row['title'],
        'url': row['url'],
        'summary': row['summary'],
        'sourceId': row['source_id'],
        'sourceName': row['source_name'],
        'publishedAt': row['published_at'],
        'updatedAt': row['updated_at'],
        'collectedAt': row['collected_at'],
        'metricLabel': row['metric_label'],
        'metricValue': row['metric_value'],
        'rankScore': row['rank_score'],
        'categories': [],
        'tags': [],
    }


async def attach_children(env, items):
    """Fill categories/tags in place. Two IN-queries per ≤90 ids."""
    for group in chunk(items, 90):
        by_id = {item['id']: item for item in group}
        marks = ','.join('?' * len(group))
        for row in await db_all(
            env, 'SELECT item_id, category FROM item_categories WHERE item_id IN (' + marks + ')',
            tuple(by_id),
        ):
            by_id[row['item_id']]['categories'].append(row['category'])
        for row in await db_all(
            env, 'SELECT item_id, tag FROM item_tags WHERE item_id IN (' + marks + ')', tuple(by_id)
        ):
            by_id[row['item_id']]['tags'].append(row['tag'])
    return items


async def load_all_items(env):
    rows = await db_all(env, 'SELECT ' + _ITEM_COLS + ' FROM items ORDER BY item_ts DESC, rank_score DESC, id')
    return await attach_children(env, [_row_to_item(row) for row in rows])


# ---------------------------------------------------------------------------
# /api/items — filterItems translated to SQL (parity with src/data.mjs)

_ORDER = {
    'latest': 'item_ts DESC, rank_score DESC, id ASC',
    'hot': 'rank_score DESC, item_ts DESC, id ASC',
}


def _like(term):
    escaped = term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return '%' + escaped + '%'


def _int_param(query, key, default):
    """JS Number(x) semantics: '' → default, '3.0' → 3, garbage → None (→ 400)."""
    raw = query.get(key)
    if raw is None or raw == '':
        return default
    try:
        value = float(raw)
    except ValueError:
        return None
    if value != value or value in (float('inf'), float('-inf')) or not value.is_integer():
        return None
    return int(value)


async def list_items(env, query, generated_at, stale):
    category = query.get('category') or 'all'
    sort = query.get('sort') or 'latest'
    page = _int_param(query, 'page', 1)
    limit = _int_param(query, 'limit', 24)
    days = _int_param(query, 'days', 0)
    china_raw = query.get('chinaOnly')
    text = query.get('q') or ''
    tag = query.get('tag') or ''
    if (
        page is None or limit is None or days is None
        or (category != 'all' and category not in CATEGORY_LABELS)
        or sort not in _ORDER
        or page < 1 or page > 500
        or limit < 1 or limit > 100
        or days < 0 or days > 365
        or china_raw not in (None, 'true', 'false')
    ):
        return error_response('Invalid query parameters', 400)

    where = []
    params = []
    if category != 'all':
        where.append('EXISTS (SELECT 1 FROM item_categories c WHERE c.item_id = items.id AND c.category = ?)')
        params.append(category)
    if tag:
        where.append('EXISTS (SELECT 1 FROM item_tags t WHERE t.item_id = items.id AND t.tag = ?)')
        params.append(tag)
    if china_raw == 'true':
        where.append('is_china = 1')
    if days:
        where.append('item_ts >= ?')
        params.append(int(time.time() * 1000) - days * DAY_MS)
    for term in text.lower().split():
        where.append("search_text LIKE ? ESCAPE '\\'")
        params.append(_like(term))
    clause = ' AND '.join(where) if where else '1=1'

    total = await db_first(env, 'SELECT COUNT(*) AS n FROM items WHERE ' + clause, tuple(params))
    offset = (page - 1) * limit
    rows = await db_all(
        env,
        'SELECT ' + _ITEM_COLS + ' FROM items WHERE ' + clause
        + ' ORDER BY ' + _ORDER[sort] + ' LIMIT ? OFFSET ?',
        (*params, limit, offset),
    )
    items = await attach_children(env, [_row_to_item(row) for row in rows])
    return json_response({
        'generatedAt': generated_at,
        'stale': stale,
        'total': total['n'],
        'page': page,
        'limit': limit,
        'items': items,
    })


# ---------------------------------------------------------------------------
# Admin sync


async def handle_sync(req, env):
    if req['method'] != 'POST':
        return error_response('Method not allowed', 405, [('Allow', 'POST'), NO_STORE])
    expected = env_get(env, 'ADMIN_TOKEN')
    if not expected:
        return error_response('Not found', 404, [NO_STORE])
    provided = req['headers'].get('x-admin-token', '')
    if not provided or not hmac.compare_digest(provided, expected):
        return error_response('Forbidden', 403, [NO_STORE])
    from collector import run_collection

    # Free-plan CPU cap: manual sync follows the same cursor batching as cron.
    status = await run_collection(env, allow_cursor=True)
    return json_response(status, extra=[NO_STORE])


# ---------------------------------------------------------------------------
# Router (auth/user paths are dispatched by entry.py before this)


async def handle_api(req, env):
    path = req['path']
    if path == '/api/sync':
        return await handle_sync(req, env)
    if req['method'] not in ('GET', 'HEAD'):
        return error_response('Method not allowed', 405, [('Allow', 'GET, HEAD'), NO_STORE])
    if path not in ('/api/feed', '/api/items', '/api/sources', '/api/health'):
        return error_response('Not found', 404)
    if len(req['raw_query']) > 1000:
        return error_response('Query too long', 400)
    try:
        generated_at = await get_meta(env, 'generated_at')
        if not generated_at:
            return error_response('Snapshot not initialized', 503, [NO_STORE])
        stale = int(time.time() * 1000) - epoch_ms(generated_at) > 48 * 3600000
        if req['method'] == 'HEAD':
            return {'status': 200, 'headers': [*_BASE_HEADERS, PUBLIC_CACHE], 'body': None}
        if path == '/api/feed':
            from collector import source_order

            order = {sid: i for i, sid in enumerate(source_order())}
            source_rows = await db_all(env, 'SELECT * FROM sources')
            source_rows.sort(key=lambda row: (order.get(row['id'], 99), row['id']))
            feed = {
                'schemaVersion': 1,
                'generatedAt': generated_at,
                'sources': [_source_out(row) for row in source_rows],
                'items': await load_all_items(env),
            }
            return json_response(feed)
        if path == '/api/sources':
            source_rows = await db_all(env, 'SELECT * FROM sources')
            return json_response({
                'generatedAt': generated_at,
                'sources': [_source_out(row) for row in source_rows],
            })
        if path == '/api/health':
            sync_raw = await get_meta(env, 'sync_status')
            try:
                sync = json.loads(sync_raw) if sync_raw else None
            except ValueError:
                sync = None
            item_count = await db_first(env, 'SELECT COUNT(*) AS n FROM items')
            source_rows = await db_all(env, 'SELECT status FROM sources')
            return json_response({
                'status': 'stale' if stale else 'ok',
                'generatedAt': generated_at,
                'itemCount': item_count['n'],
                'sourceCount': len(source_rows),
                'healthySources': sum(1 for row in source_rows if row['status'] == 'ok'),
                'sync': sync,
                'schedule': SCHEDULE,
                'collection': COLLECTION,
            })
        return await list_items(env, req['query'], generated_at, stale)
    except Exception as error:  # noqa: BLE001 — surface as 503 like the JS worker
        print('API unavailable:', error)
        return error_response('Service temporarily unavailable', 503, [NO_STORE])
