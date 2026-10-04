"""OAuth + account routing tests — port of auth.mjs behavior."""
import json
import time
from urllib.parse import parse_qsl, urlsplit

import auth as auth
from accounts import SESSION_SECONDS
from db import db_all, db_run
from util import now_iso, random_token, sha256_b64url

from conftest import make_env, run

ORIGIN = 'https://signal.example.com'
SECRET = 's' * 48


def req(method='GET', path='/api/auth/session', query='', headers=None, body=None):
    return {
        'method': method,
        'path': path,
        'raw_query': query,
        'query': dict(parse_qsl(query, keep_blank_values=True)),
        'headers': {'origin': ORIGIN, **(headers or {})},
        'origin': ORIGIN,
        'url': ORIGIN + path + ('?' + query if query else ''),
        'body': body,
    }


def body_of(resp):
    return json.loads(resp['body'])


def header_values(resp, name):
    return [v for k, v in resp['headers'] if k.lower() == name.lower()]


class TestSettings:
    def test_full_config_ok(self, d1):
        assert auth.settings(make_env(d1), req()) == {'origin': ORIGIN, 'secure': True}

    def test_missing_secret_returns_none(self, d1):
        assert auth.settings(make_env(d1, SESSION_SECRET=None), req()) is None

    def test_short_secret_rejected(self, d1):
        assert auth.settings(make_env(d1, SESSION_SECRET='short'), req()) is None

    def test_origin_mismatch_rejected(self, d1):
        # JS compares APP_ORIGIN against the request URL's origin, not the header.
        other = req()
        other['origin'] = 'https://evil.com'
        assert auth.settings(make_env(d1), other) is None

    def test_local_http_allowed(self, d1):
        env = make_env(d1, APP_ORIGIN='http://127.0.0.1:8787')
        local_req = req()
        local_req['origin'] = 'http://127.0.0.1:8787'
        assert auth.settings(env, local_req) == {'origin': 'http://127.0.0.1:8787', 'secure': False}


class TestStateCookie:
    def test_roundtrip(self):
        token = auth.sign_state({'state': 'a', 'verifier': 'b', 'expires': int(time.time() * 1000) + 300000}, SECRET)
        assert auth.verify_state(token, SECRET) is not None

    def test_tamper_rejected(self):
        token = auth.sign_state({'state': 'a', 'verifier': 'b', 'expires': int(time.time() * 1000) + 300000}, SECRET)
        assert auth.verify_state(token[:-3] + 'xxx', SECRET) is None
        assert auth.verify_state(token + '.extra', SECRET) is None

    def test_expired_rejected_both_directions(self):
        now = int(time.time() * 1000)
        assert auth.verify_state(auth.sign_state({'verifier': 'v', 'expires': now - 1}, SECRET), SECRET) is None
        assert auth.verify_state(auth.sign_state({'verifier': 'v', 'expires': now + 601000}, SECRET), SECRET) is None

    def test_wrong_secret_rejected(self):
        token = auth.sign_state({'verifier': 'v', 'expires': int(time.time() * 1000) + 300000}, SECRET)
        assert auth.verify_state(token, 't' * 48) is None


class TestRouting:
    def test_unknown_404(self, d1):
        assert run(auth.handle_account_request(req(path='/api/auth/nope'), make_env(d1)))['status'] == 404

    def test_wrong_method_405(self, d1):
        resp = run(auth.handle_account_request(req('POST', '/api/auth/github'), make_env(d1)))
        assert resp['status'] == 405

    def test_unconfigured_session_endpoint(self, d1):
        resp = run(auth.handle_account_request(req(), make_env(d1, SESSION_SECRET=None)))
        assert resp['status'] == 200
        assert body_of(resp)['available'] is False

    def test_unconfigured_others_503(self, d1):
        resp = run(auth.handle_account_request(req(path='/api/auth/github'), make_env(d1, SESSION_SECRET=None)))
        assert resp['status'] == 503

    def test_query_too_long(self, d1):
        resp = run(auth.handle_account_request(req(query='x=' + 'a' * 2100), make_env(d1)))
        assert resp['status'] == 400


class TestOAuthFlow:
    def test_github_redirect(self, d1):
        resp = run(auth.handle_account_request(req(path='/api/auth/github'), make_env(d1)))
        assert resp['status'] == 303
        location = header_values(resp, 'Location')[0]
        assert location.startswith('https://github.com/login/oauth/authorize')
        params = dict(parse_qsl(urlsplit(location).query, keep_blank_values=True))
        assert params['scope'] == '' and params['code_challenge_method'] == 'S256'
        assert len(params['code_challenge']) == 43 and len(params['state']) == 43
        cookies = header_values(resp, 'Set-Cookie')
        assert any(c.startswith('__Host-signal-oauth=') and 'Max-Age=600' in c for c in cookies)

    def _state_cookie(self, state, verifier):
        token = auth.sign_state(
            {'state': state, 'verifier': verifier, 'expires': int(time.time() * 1000) + 300000}, SECRET)
        return '__Host-signal-oauth=' + token

    def test_callback_success(self, d1, monkeypatch):
        env = make_env(d1)

        async def fake_exchange(payload):
            return {'access_token': 'atk', 'token_type': 'bearer'}

        async def fake_user(token):
            return {'id': 99, 'login': 'octocat', 'name': 'Octo Cat'}

        monkeypatch.setattr(auth, '_token_exchange', fake_exchange)
        monkeypatch.setattr(auth, '_fetch_user', fake_user)
        query = 'code=abc&state=st1'
        resp = run(auth.handle_account_request(
            req(path='/api/auth/callback', query=query,
                headers={'cookie': self._state_cookie('st1', 'verifier-1')}),
            env))
        assert resp['status'] == 303
        assert header_values(resp, 'Location') == [ORIGIN + '/?auth=success']
        cookies = header_values(resp, 'Set-Cookie')
        session_cookie = [c for c in cookies if c.startswith('__Host-signal-session=')][0]
        assert 'Max-Age=%d' % SESSION_SECONDS in session_cookie
        sessions = run(db_all(env, 'SELECT github_id, csrf FROM sessions'))
        assert sessions and len(sessions[0]['csrf']) == 43

    def test_callback_bad_state_redirects_failed(self, d1):
        env = make_env(d1)
        resp = run(auth.handle_account_request(
            req(path='/api/auth/callback', query='code=abc&state=wrong',
                headers={'cookie': self._state_cookie('st1', 'v')}),
            env))
        assert resp['status'] == 303
        assert header_values(resp, 'Location') == [ORIGIN + '/?auth=failed']

    def test_callback_exchange_failure(self, d1, monkeypatch):
        async def boom(payload):
            raise RuntimeError('network down')

        monkeypatch.setattr(auth, '_token_exchange', boom)
        resp = run(auth.handle_account_request(
            req(path='/api/auth/callback', query='code=abc&state=st1',
                headers={'cookie': self._state_cookie('st1', 'v')}),
            make_env(d1)))
        assert header_values(resp, 'Location') == [ORIGIN + '/?auth=failed']

    def test_callback_github_error_param(self, d1):
        resp = run(auth.handle_account_request(
            req(path='/api/auth/callback', query='error=access_denied',
                headers={'cookie': self._state_cookie('st1', 'v')}),
            make_env(d1)))
        assert header_values(resp, 'Location') == [ORIGIN + '/?auth=failed']


def make_session(env, secret='s' * 43, csrf='csrf-token', uid='12345', item_id=None):
    run(db_run(
        env,
        'INSERT INTO users (github_id, login, display_name, created_at) VALUES (?, ?, ?, ?)',
        (int(uid), 'laoda', '牢大', now_iso()),
    ))
    run(db_run(
        env,
        'INSERT INTO sessions (token_hash, github_id, csrf, created_at, expires_at, window_start, writes_count) '
        'VALUES (?, ?, ?, ?, ?, ?, 0)',
        (sha256_b64url(secret), int(uid), csrf, now_iso(),
         now_iso(int(time.time() * 1000) + 7 * 86400000), int(time.time() * 1000)),
    ))
    if item_id:
        run(db_run(env, "INSERT INTO sources (id, name, homepage, status, item_count) "
                        "VALUES ('qbitai', 'n', 'https://s.com', 'ok', 0)"))
        run(db_run(env, "INSERT INTO items (id, title, url, source_id, source_name, collected_at, rank_score) "
                        "VALUES (?, 't', 'https://a.com/1', 'qbitai', 'n', ?, 50)", (item_id, now_iso())))
    cookie = '__Host-signal-session=%s.%s' % (uid, secret)
    return cookie


class TestSessionRoutes:
    def test_anonymous_session(self, d1):
        resp = run(auth.handle_account_request(req(), make_env(d1)))
        payload = body_of(resp)
        assert payload == {'available': True, 'user': None, 'favorites': [], 'tags': []}

    def test_logged_in_session(self, d1):
        env = make_env(d1)
        cookie = make_session(env)
        resp = run(auth.handle_account_request(
            req(headers={'cookie': cookie}), env))
        payload = body_of(resp)
        assert payload['user'] == {'id': '12345', 'login': 'laoda', 'displayName': '牢大'}
        assert payload['csrf'] == 'csrf-token'

    def test_malformed_cookie_treated_anonymous(self, d1):
        env = make_env(d1)
        resp = run(auth.handle_account_request(
            req(headers={'cookie': '__Host-signal-session=garbage'}), env))
        assert body_of(resp)['user'] is None

    def test_put_requires_origin_and_csrf(self, d1):
        env = make_env(d1)
        cookie = make_session(env)
        body = json.dumps({'displayName': 'x'}).encode()
        # Missing CSRF header
        resp = run(auth.handle_account_request(
            req('PUT', '/api/user/profile', headers={'cookie': cookie, 'origin': ORIGIN}, body=body), env))
        assert resp['status'] == 403
        # Wrong origin
        resp = run(auth.handle_account_request(
            req('PUT', '/api/user/profile',
                headers={'cookie': cookie, 'origin': 'https://evil.com', 'x-csrf-token': 'csrf-token'},
                body=body),
            env))
        assert resp['status'] == 403

    def test_put_profile_roundtrip(self, d1):
        env = make_env(d1)
        cookie = make_session(env)
        resp = run(auth.handle_account_request(
            req('PUT', '/api/user/profile',
                headers={'cookie': cookie, 'origin': ORIGIN, 'x-csrf-token': 'csrf-token',
                         'content-type': 'application/json'},
                body=json.dumps({'displayName': '新名字'}).encode()),
            env))
        assert resp['status'] == 200
        assert body_of(resp)['user']['displayName'] == '新名字'

    def test_put_bad_body_400(self, d1):
        env = make_env(d1)
        cookie = make_session(env)
        resp = run(auth.handle_account_request(
            req('PUT', '/api/user/profile',
                headers={'cookie': cookie, 'origin': ORIGIN, 'x-csrf-token': 'csrf-token',
                         'content-type': 'application/json'},
                body=b'{not json'),
            env))
        assert resp['status'] == 400
        resp = run(auth.handle_account_request(
            req('PUT', '/api/user/profile',
                headers={'cookie': cookie, 'origin': ORIGIN, 'x-csrf-token': 'csrf-token',
                         'content-type': 'application/json'},
                body=b'x' * 4097),
            env))
        assert resp['status'] == 400

    def test_put_wrong_content_type_400(self, d1):
        env = make_env(d1)
        cookie = make_session(env)
        resp = run(auth.handle_account_request(
            req('PUT', '/api/user/profile',
                headers={'cookie': cookie, 'origin': ORIGIN, 'x-csrf-token': 'csrf-token',
                         'content-type': 'text/plain'},
                body=b'{}'),
            env))
        assert resp['status'] == 400

    def test_logout_clears_cookie(self, d1):
        env = make_env(d1)
        cookie = make_session(env)
        resp = run(auth.handle_account_request(
            req('POST', '/api/auth/logout',
                headers={'cookie': cookie, 'origin': ORIGIN, 'x-csrf-token': 'csrf-token'}),
            env))
        assert resp['status'] == 200
        clear = [c for c in header_values(resp, 'Set-Cookie') if 'signal-session' in c][0]
        assert 'Max-Age=0' in clear

    def test_favorite_unknown_item_400(self, d1):
        env = make_env(d1)
        cookie = make_session(env)
        resp = run(auth.handle_account_request(
            req('PUT', '/api/user/favorites',
                headers={'cookie': cookie, 'origin': ORIGIN, 'x-csrf-token': 'csrf-token',
                         'content-type': 'application/json'},
                body=json.dumps({'id': 'ghost', 'saved': True}).encode()),
            env))
        assert resp['status'] == 400
        assert body_of(resp)['error'] == '该资讯已不在当前快照中。'

    def test_favorite_existing_item_ok(self, d1):
        env = make_env(d1)
        cookie = make_session(env, item_id='item-9')
        resp = run(auth.handle_account_request(
            req('PUT', '/api/user/favorites',
                headers={'cookie': cookie, 'origin': ORIGIN, 'x-csrf-token': 'csrf-token',
                         'content-type': 'application/json'},
                body=json.dumps({'id': 'item-9', 'saved': True}).encode()),
            env))
        assert resp['status'] == 200
        assert body_of(resp)['favorites'] == ['item-9']

    def test_write_requires_login_401(self, d1):
        env = make_env(d1)
        resp = run(auth.handle_account_request(
            req('PUT', '/api/user/profile',
                headers={'origin': ORIGIN, 'x-csrf-token': 'csrf-token',
                         'content-type': 'application/json'},
                body=json.dumps({'displayName': 'x'}).encode()),
            env))
        assert resp['status'] == 401
