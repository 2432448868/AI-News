"""Account storage — port of worker/accounts.mjs on D1 tables.

Each dispatch call is one batch transaction, mirroring the DO's transaction().
Return values mimic the DO result shape: {'status': int, ...payload}.
"""
import re
import time

from db import db_all, db_batch, db_first, db_run
from util import now_iso

MAX_FAVORITES = 200
MAX_TAGS = 30
MAX_SESSIONS = 8
SESSION_MS = 7 * 24 * 3600000
SESSION_SECONDS = SESSION_MS // 1000
WINDOW_MS = 60000
WRITES_PER_WINDOW = 30

_CONTROL_CHARS = re.compile(r'[\x00-\x1f\x7f]')


def _now_ms():
    return int(time.time() * 1000)


async def login(env, profile, session_hash, csrf):
    now_ms = _now_ms()
    now = now_iso(now_ms)
    github_id = profile['id']
    await db_batch(
        env,
        [
            # Login never overwrites a nickname the user chose themselves.
            (
                'INSERT INTO users (github_id, login, display_name, created_at) VALUES (?, ?, ?, ?) '
                'ON CONFLICT(github_id) DO UPDATE SET login = excluded.login',
                (github_id, profile['login'], profile['name'], now),
            ),
            ('DELETE FROM sessions WHERE expires_at < ?', (now,)),
            (
                'INSERT INTO sessions (token_hash, github_id, csrf, created_at, expires_at, '
                'window_start, writes_count) VALUES (?, ?, ?, ?, ?, ?, 0)',
                (session_hash, github_id, csrf, now, now_iso(now_ms + SESSION_MS), now_ms),
            ),
            # Keep the newest MAX_SESSIONS sessions (DO sliced the tail of the list).
            (
                'DELETE FROM sessions WHERE github_id = ? AND token_hash NOT IN ('
                'SELECT token_hash FROM sessions WHERE github_id = ? '
                'ORDER BY created_at DESC, token_hash LIMIT ' + str(MAX_SESSIONS) + ')',
                (github_id, github_id),
            ),
        ],
    )
    return {'status': 200}


async def _session(env, github_id, session_hash, now_ms):
    return await db_first(
        env,
        'SELECT * FROM sessions WHERE token_hash = ? AND github_id = ? AND expires_at > ?',
        (session_hash, github_id, now_iso(now_ms)),
    )


async def _view(env, github_id, session):
    user = await db_first(env, 'SELECT * FROM users WHERE github_id = ?', (github_id,))
    favorites = await db_all(
        env, 'SELECT item_id FROM favorites WHERE github_id = ? ORDER BY saved_at, item_id', (github_id,)
    )
    tags = await db_all(
        env, 'SELECT tag FROM followed_tags WHERE github_id = ? ORDER BY followed_at, tag', (github_id,)
    )
    return {
        'status': 200,
        'available': True,
        'user': {
            'id': str(user['github_id']),
            'login': user['login'],
            'displayName': user['display_name'],
        },
        'favorites': [row['item_id'] for row in favorites],
        'tags': [row['tag'] for row in tags],
        'csrf': session['csrf'],
    }


async def dispatch(env, github_id, session_hash, action, csrf, body):
    """Order mirrors accounts.mjs exactly: read → csrf → logout → window → limit → mutate."""
    now_ms = _now_ms()
    session = await _session(env, github_id, session_hash, now_ms)
    if session is None:
        return {'status': 401, 'error': '请重新登录。'}
    if action == 'read':
        return await _view(env, github_id, session)
    if csrf != session['csrf']:
        return {'status': 403, 'error': '安全校验失败，请刷新后重试。'}
    if action == 'logout':
        await db_run(env, 'DELETE FROM sessions WHERE token_hash = ?', (session_hash,))
        return {'status': 200}

    statements = []
    if now_ms - session['window_start'] >= WINDOW_MS:
        session['window_start'] = now_ms
        session['writes_count'] = 0
        statements.append(
            ('UPDATE sessions SET window_start = ?, writes_count = 0 WHERE token_hash = ?', (now_ms, session_hash))
        )
    if session['writes_count'] >= WRITES_PER_WINDOW:
        if statements:
            await db_batch(env, statements)
        return {'status': 429, 'error': '操作太频繁，请稍后重试。'}

    if action == 'profile':
        name = body.get('displayName')
        trimmed = name.strip() if isinstance(name, str) else ''
        if not trimmed or len(trimmed) > 60 or _CONTROL_CHARS.search(name):
            return {'status': 400, 'error': '昵称需为 1–60 个字符。'}
        statements.append(
            ('UPDATE users SET display_name = ? WHERE github_id = ?', (trimmed, github_id))
        )
    elif action == 'favorite':
        item_id = body.get('id')
        saved = body.get('saved')
        if not isinstance(item_id, str) or not item_id or len(item_id) > 200 or not isinstance(saved, bool):
            return {'status': 400, 'error': '收藏参数无效。'}
        if saved:
            existing = await db_first(
                env, 'SELECT 1 AS hit FROM favorites WHERE github_id = ? AND item_id = ?', (github_id, item_id)
            )
            if existing is None:
                count = await db_first(
                    env, 'SELECT COUNT(*) AS n FROM favorites WHERE github_id = ?', (github_id,)
                )
                if count['n'] >= MAX_FAVORITES:
                    return {'status': 409, 'error': '最多收藏 200 条资讯。'}
                statements.append(
                    ('INSERT OR IGNORE INTO favorites (github_id, item_id, saved_at) VALUES (?, ?, ?)',
                     (github_id, item_id, now_iso(now_ms)))
                )
        else:
            statements.append(
                ('DELETE FROM favorites WHERE github_id = ? AND item_id = ?', (github_id, item_id))
            )
    elif action == 'tag':
        tag = body.get('tag')
        followed = body.get('followed')
        trimmed = tag.strip() if isinstance(tag, str) else ''
        if (
            not trimmed
            or len(trimmed) > 40
            or _CONTROL_CHARS.search(tag)
            or not isinstance(followed, bool)
        ):
            return {'status': 400, 'error': '标签需为 1–40 个字符。'}
        if followed:
            existing = await db_first(
                env, 'SELECT 1 AS hit FROM followed_tags WHERE github_id = ? AND tag = ?', (github_id, trimmed)
            )
            if existing is None:
                count = await db_first(
                    env, 'SELECT COUNT(*) AS n FROM followed_tags WHERE github_id = ?', (github_id,)
                )
                if count['n'] >= MAX_TAGS:
                    return {'status': 409, 'error': '最多关注 30 个标签。'}
                statements.append(
                    ('INSERT OR IGNORE INTO followed_tags (github_id, tag, followed_at) VALUES (?, ?, ?)',
                     (github_id, trimmed, now_iso(now_ms)))
                )
        else:
            statements.append(
                ('DELETE FROM followed_tags WHERE github_id = ? AND tag = ?', (github_id, trimmed))
            )
    else:
        return {'status': 404, 'error': 'Not found'}

    statements.append(
        ('UPDATE sessions SET writes_count = writes_count + 1 WHERE token_hash = ?', (session_hash,))
    )
    await db_batch(env, statements)
    return await _view(env, github_id, session)
