"""Thin async helpers over a D1 binding.

Works against both the real Cloudflare D1 JS object (via FFI) and the
sqlite3-backed shim used by tests: both expose prepare(sql).bind(*params)
with .all()/.first()/.run() and a DB-level .batch([...]).
"""


def _to_py(value):
    to_py = getattr(value, 'to_py', None)
    if callable(to_py):
        try:
            value = to_py()
        except Exception:
            pass
    return value


async def db_all(env, sql, params=()):
    stmt = env.DB.prepare(sql)
    if params:
        stmt = stmt.bind(*params)
    result = _to_py(await stmt.all())
    rows = result.get('results', []) if isinstance(result, dict) else getattr(result, 'results', [])
    return [dict(_to_py(row)) for row in rows]


async def db_first(env, sql, params=()):
    rows = await db_all(env, sql, params)
    return rows[0] if rows else None


async def db_run(env, sql, params=()):
    stmt = env.DB.prepare(sql)
    if params:
        stmt = stmt.bind(*params)
    await stmt.run()


async def db_batch(env, statements):
    """Run [(sql, params), ...] in one transaction."""
    prepared = []
    for sql, params in statements:
        stmt = env.DB.prepare(sql)
        if params:
            stmt = stmt.bind(*params)
        prepared.append(stmt)
    await env.DB.batch(prepared)


def chunk(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def multirow_insert(table, columns, rows, conflict=''):
    """INSERT INTO t (cols) VALUES (?,?),(?,?)... [+ conflict clause]."""
    placeholders = '(' + ','.join('?' * len(columns)) + ')'
    return (
        'INSERT INTO ' + table + ' (' + ','.join(columns) + ') VALUES '
        + ','.join([placeholders] * rows)
        + (' ' + conflict if conflict else '')
    )


async def get_meta(env, key, default=None):
    row = await db_first(env, 'SELECT value FROM meta WHERE key = ?', (key,))
    return row['value'] if row else default


async def set_meta(env, key, value):
    await db_run(
        env,
        'INSERT INTO meta (key, value) VALUES (?, ?) '
        'ON CONFLICT(key) DO UPDATE SET value = excluded.value',
        (key, value),
    )


def env_get(env, name, default=None):
    """Read an optional env var/secret from either a JS env proxy or a test stub."""
    try:
        value = getattr(env, name, None)
    except AttributeError:
        return default
    if value is None or value == '':
        return default
    return str(value)
