"""GitHub OAuth + account routes — port of worker/auth.mjs.

Outbound HTTP (token exchange, profile fetch) is isolated in _token_exchange
and _fetch_user so tests can monkeypatch them; only cold paths touch requests.
"""
import hashlib
import hmac as hmac_mod
import json
import re
import time
from urllib.parse import urlencode, urlsplit, urlunsplit

import accounts
from db import db_first, env_get
from util import b64url, random_token, sha256_b64url, unb64

AUTH_HEADERS = [
    ('Cache-Control', 'no-store, private'),
    ('Vary', 'Cookie'),
    ('X-Content-Type-Options', 'nosniff'),
    ('Referrer-Policy', 'no-referrer'),
]
IDENTITY_RE = re.compile(r'^([1-9]\d{0,19})\.([A-Za-z0-9_-]{43})$')
LOGIN_RE = re.compile(r'^[a-zA-Z0-9-]{1,39}$')

ROUTES = {
    '/api/auth/session': 'GET',
    '/api/auth/github': 'GET',
    '/api/auth/callback': 'GET',
    '/api/auth/logout': 'POST',
    '/api/user/profile': 'PUT',
    '/api/user/favorites': 'PUT',
    '/api/user/tags': 'PUT',
}
ACTIONS = {
    '/api/auth/session': 'read',
    '/api/auth/logout': 'logout',
    '/api/user/profile': 'profile',
    '/api/user/favorites': 'favorite',
    '/api/user/tags': 'tag',
}


class _Fail(Exception):
    pass


def _json(body, status=200, extra=()):
    return {
        'status': status,
        'headers': [*AUTH_HEADERS, *extra],
        'body': json.dumps(body, ensure_ascii=False, separators=(',', ':')),
    }


def _redirect(location, cookies=()):
    headers = [*AUTH_HEADERS, ('Location', location)]
    headers.extend(('Set-Cookie', value) for value in cookies)
    return {'status': 303, 'headers': headers, 'body': None}


# ---------------------------------------------------------------------------
# Settings & cookies


def settings(env, req):
    app_origin = env_get(env, 'APP_ORIGIN')
    client_id = env_get(env, 'GITHUB_CLIENT_ID')
    client_secret = env_get(env, 'GITHUB_CLIENT_SECRET')
    session_secret = env_get(env, 'SESSION_SECRET')
    if (
        not app_origin or not client_id or not client_secret or not session_secret
        or len(session_secret) < 32
    ):
        return None
    try:
        parts = urlsplit(app_origin)
    except ValueError:
        return None
    host = parts.hostname or ''
    local = parts.scheme == 'http' and host in ('localhost', '127.0.0.1')
    if not local and parts.scheme != 'https':
        return None
    origin = urlunsplit((parts.scheme.lower(), (parts.netloc or '').lower(), '', '', ''))
    if origin != app_origin or origin != req.get('origin'):
        return None
    return {'origin': origin, 'secure': not local}


def cookie_name(cfg, kind):
    return ('__Host-' if cfg['secure'] else '') + 'signal-' + kind


def build_cookie(cfg, kind, value, age):
    cookie = (
        cookie_name(cfg, kind) + '=' + value + '; Path=/; HttpOnly; SameSite=Lax; Max-Age=' + str(age)
    )
    return cookie + ('; Secure' if cfg['secure'] else '')


def read_cookie(header_value, name):
    parts = [
        value.strip()
        for value in (header_value or '').split(';')
        if value.strip().startswith(name + '=')
    ]
    return parts[0][len(name) + 1:] if len(parts) == 1 else ''


# ---------------------------------------------------------------------------
# Signed OAuth state (HMAC-SHA256, 10-minute window in both directions)


def sign_state(value, secret):
    text = b64url(json.dumps(value, separators=(',', ':')).encode('utf-8'))
    signature = b64url(hmac_mod.new(secret.encode('utf-8'), text.encode('utf-8'), hashlib.sha256).digest())
    return text + '.' + signature


def verify_state(value, secret):
    if not isinstance(value, str) or len(value) > 1500:
        return None
    parts = value.split('.')
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    text, signature = parts
    expected = b64url(hmac_mod.new(secret.encode('utf-8'), text.encode('utf-8'), hashlib.sha256).digest())
    if not hmac_mod.compare_digest(signature, expected):
        return None
    try:
        data = json.loads(unb64(text))
    except Exception:  # noqa: BLE001 — any decode failure means rejection
        return None
    now = int(time.time() * 1000)
    if not isinstance(data, dict):
        return None
    expires = data.get('expires')
    if (
        not isinstance(expires, int)
        or expires <= now
        or expires > now + 600000
        or not isinstance(data.get('verifier'), str)
    ):
        return None
    return data


def identity(req, cfg):
    value = read_cookie(req['headers'].get('cookie', ''), cookie_name(cfg, 'session'))
    match = IDENTITY_RE.match(value)
    if not match:
        return None
    return {'id': match.group(1), 'hash': sha256_b64url(match.group(2))}


def body_json(req):
    content_type = req['headers'].get('content-type', '')
    if not content_type.lower().startswith('application/json'):
        raise _Fail('type')
    body = req.get('body')
    if not body:
        raise _Fail('body')
    if len(body) > 4096:
        raise _Fail('size')
    try:
        parsed = json.loads(body.decode('utf-8'))
    except Exception:  # noqa: BLE001 — malformed JSON is a client error, not a 503
        raise _Fail('body')
    if not isinstance(parsed, dict):
        raise _Fail('body')
    return parsed


# ---------------------------------------------------------------------------
# Outbound GitHub calls (cold path only; monkeypatched in tests)


async def _platform_fetch(url, init):
    """js.fetch FFI — same cold-start CPU rationale as collector._http_fetch."""
    import js
    from pyodide.ffi import to_js

    options = dict(init)
    options['signal'] = js.AbortSignal.timeout(options.pop('timeoutMs', 10000))
    return await js.fetch(url, to_js(options, dict_converter=js.Object.fromEntries))


async def _token_exchange(payload):
    response = await _platform_fetch('https://github.com/login/oauth/access_token', {
        'method': 'POST',
        'body': urlencode(payload),
        'headers': {'Accept': 'application/json', 'Content-Type': 'application/x-www-form-urlencoded'},
    })
    if int(response.status) != 200:
        raise _Fail('token')
    return (await response.json()).to_py()


async def _fetch_user(token):
    response = await _platform_fetch('https://api.github.com/user', {
        'method': 'GET',
        'headers': {
            'Accept': 'application/vnd.github+json',
            'Authorization': 'Bearer ' + token,
            'User-Agent': 'signal-ai-news',
        },
    })
    if int(response.status) != 200:
        raise _Fail('profile')
    return (await response.json()).to_py()


# ---------------------------------------------------------------------------
# Route handler


async def handle_account_request(req, env):
    path = req['path']
    if path not in ROUTES:
        return _json({'error': 'Not found'}, 404)
    if req['method'] != ROUTES[path]:
        return _json({'error': 'Method not allowed'}, 405, [('Allow', ROUTES[path])])
    if len(req['raw_query']) > 2000:
        return _json({'error': 'Query too long'}, 400)
    cfg = settings(env, req)
    if not cfg:
        if path == '/api/auth/session':
            return _json({'available': False, 'user': None, 'favorites': [], 'tags': []})
        return _json({'error': 'GitHub 登录尚未配置，请稍后再试。'}, 503)

    try:
        if path == '/api/auth/github':
            state = random_token()
            verifier = random_token()
            # Empty scope: only public identity, never repositories or email.
            authorize = 'https://github.com/login/oauth/authorize?' + urlencode({
                'client_id': env_get(env, 'GITHUB_CLIENT_ID'),
                'redirect_uri': cfg['origin'] + '/api/auth/callback',
                'scope': '',
                'state': state,
                'code_challenge': sha256_b64url(verifier),
                'code_challenge_method': 'S256',
            })
            cookie = build_cookie(
                cfg, 'oauth',
                sign_state({'state': state, 'verifier': verifier, 'expires': int(time.time() * 1000) + 600000},
                           env_get(env, 'SESSION_SECRET')),
                600,
            )
            return _redirect(authorize, [cookie])

        if path == '/api/auth/callback':
            clear = build_cookie(cfg, 'oauth', '', 0)
            pending = verify_state(
                read_cookie(req['headers'].get('cookie', ''), cookie_name(cfg, 'oauth')),
                env_get(env, 'SESSION_SECRET'),
            )
            code = req['query'].get('code')
            if (
                pending is None
                or pending.get('state') != req['query'].get('state')
                or not code
                or len(code) > 512
                or 'error' in req['query']
            ):
                return _redirect(cfg['origin'] + '/?auth=failed', [clear])
            try:
                token = await _token_exchange({
                    'client_id': env_get(env, 'GITHUB_CLIENT_ID'),
                    'client_secret': env_get(env, 'GITHUB_CLIENT_SECRET'),
                    'code': code,
                    'redirect_uri': cfg['origin'] + '/api/auth/callback',
                    'code_verifier': pending['verifier'],
                })
                if (
                    not isinstance(token.get('access_token'), str)
                    or token.get('error')
                    or str(token.get('token_type', '')).lower() != 'bearer'
                ):
                    raise _Fail('token')
                user = await _fetch_user(token['access_token'])
                user_id = user.get('id')
                login = user.get('login')
                if (
                    not isinstance(user_id, int)
                    or isinstance(user_id, bool)
                    or not 1 <= user_id < 2 ** 53
                    or not isinstance(login, str)
                    or not LOGIN_RE.fullmatch(login)
                ):
                    raise _Fail('profile')
                secret = random_token()
                csrf = random_token()
                profile = {
                    'id': str(user_id),
                    'login': login,
                    'name': login if not isinstance(user.get('name'), str) else user['name'][:60],
                }
                await accounts.login(env, profile, sha256_b64url(secret), csrf)
                return _redirect(cfg['origin'] + '/?auth=success', [
                    clear,
                    build_cookie(cfg, 'session', profile['id'] + '.' + secret, accounts.SESSION_SECONDS),
                ])
            except Exception:  # noqa: BLE001 — any failure (incl. network) redirects like the JS port
                return _redirect(cfg['origin'] + '/?auth=failed', [clear])

        who = identity(req, cfg)
        if not who:
            if path == '/api/auth/session':
                return _json({'available': True, 'user': None, 'favorites': [], 'tags': []})
            return _json({'error': '请先登录。'}, 401)
        if (
            req['method'] != 'GET'
            and (req['headers'].get('origin') != cfg['origin'] or not req['headers'].get('x-csrf-token'))
        ):
            return _json({'error': '安全校验失败，请刷新后重试。'}, 403)
        body = {}
        if req['method'] == 'PUT':
            try:
                body = body_json(req)
            except _Fail:
                return _json({'error': '请求需为有效 JSON，且不超过 4KB。'}, 400)

        action = ACTIONS[path]
        # Authenticate before consulting the item table for additions.
        if action == 'favorite' and body.get('saved') is True:
            probe = await accounts.dispatch(env, who['id'], who['hash'], 'read', None, {})
            if probe['status'] != 200:
                return _json({'error': '请重新登录。'}, 401)
            item = await db_first(env, 'SELECT 1 AS hit FROM items WHERE id = ?', (body.get('id'),))
            if item is None:
                return _json({'error': '该资讯已不在当前快照中。'}, 400)

        result = await accounts.dispatch(
            env, who['id'], who['hash'], action, req['headers'].get('x-csrf-token'), body
        )
        status = result.get('status', 200)
        result.pop('status', None)
        if status == 401:
            return _json({'error': '请重新登录。'}, 401,
                         [('Set-Cookie', build_cookie(cfg, 'session', '', 0))])
        extra = (
            [('Set-Cookie', build_cookie(cfg, 'session', '', 0))]
            if action == 'logout' and status == 200
            else []
        )
        return _json(result, status, extra)
    except Exception:  # noqa: BLE001 — account layer must never 500 with a stack trace
        return _json({'error': '账号服务暂时不可用，请稍后重试。'}, 503)
