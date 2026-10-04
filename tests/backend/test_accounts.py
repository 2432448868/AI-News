"""Account storage tests — limits, rate window, and view parity with accounts.mjs."""
import time

import accounts as accounts
from db import db_all, db_run
from util import now_iso, sha256_b64url

from conftest import make_env, run

UID = '12345'


def login(env, secret='sessionsecret', csrf='csrf-token', uid=UID, name='牢大', login_name='laoda'):
    run(accounts.login(
        env,
        {'id': uid, 'login': login_name, 'name': name},
        sha256_b64url(secret), csrf,
    ))


class TestLogin:
    def test_creates_user_and_session(self, d1):
        env = make_env(d1)
        login(env)
        users = run(db_all(env, 'SELECT * FROM users'))
        assert users[0]['github_id'] == 12345 and users[0]['display_name'] == '牢大'
        sessions = run(db_all(env, 'SELECT * FROM sessions'))
        assert sessions[0]['token_hash'] == sha256_b64url('sessionsecret')
        assert sessions[0]['csrf'] == 'csrf-token'

    def test_relogin_preserves_display_name(self, d1):
        env = make_env(d1)
        login(env, name='first')
        run(db_run(env, "UPDATE users SET display_name = '自定义昵称' WHERE github_id = ?", (12345,)))
        login(env, secret='second-secret', csrf='csrf2', name='second')
        users = run(db_all(env, 'SELECT display_name FROM users'))
        assert users[0]['display_name'] == '自定义昵称'

    def test_session_cap_8(self, d1):
        env = make_env(d1)
        for i in range(10):
            login(env, secret='secret-%02d' % i, csrf='c%d' % i)
            # Spread created_at: real-time logins can share a millisecond, and
            # the eviction tie-break (token_hash) would make this test flaky.
            run(db_run(env, 'UPDATE sessions SET created_at = ? WHERE token_hash = ?',
                       ('2025-10-06T00:00:%02d.000Z' % i, sha256_b64url('secret-%02d' % i))))
        count = run(db_all(env, 'SELECT COUNT(*) AS n FROM sessions'))[0]['n']
        assert count == accounts.MAX_SESSIONS
        kept = {row['token_hash'] for row in run(db_all(env, 'SELECT token_hash FROM sessions'))}
        assert sha256_b64url('secret-01') not in kept  # oldest evicted
        assert sha256_b64url('secret-09') in kept


class TestDispatch:
    def test_read_view(self, d1):
        env = make_env(d1)
        login(env)
        result = run(accounts.dispatch(env, UID, sha256_b64url('sessionsecret'), 'read', None, {}))
        assert result['status'] == 200
        assert result['user'] == {'id': '12345', 'login': 'laoda', 'displayName': '牢大'}
        assert result['csrf'] == 'csrf-token'

    def test_unknown_session_401(self, d1):
        env = make_env(d1)
        login(env)
        result = run(accounts.dispatch(env, UID, sha256_b64url('wrong'), 'read', None, {}))
        assert result['status'] == 401 and result['error'] == '请重新登录。'

    def test_expired_session_401(self, d1):
        env = make_env(d1)
        login(env)
        run(db_run(env, 'UPDATE sessions SET expires_at = 1'))
        result = run(accounts.dispatch(env, UID, sha256_b64url('sessionsecret'), 'read', None, {}))
        assert result['status'] == 401

    def test_bad_csrf_403(self, d1):
        env = make_env(d1)
        login(env)
        result = run(accounts.dispatch(env, UID, sha256_b64url('sessionsecret'), 'profile', 'nope', {}))
        assert result['status'] == 403

    def test_logout_deletes_only_current(self, d1):
        env = make_env(d1)
        login(env, secret='a-secret')
        login(env, secret='b-secret', csrf='csrf2')
        result = run(accounts.dispatch(env, UID, sha256_b64url('a-secret'), 'logout', 'csrf-token', {}))
        assert result['status'] == 200
        remaining = run(db_all(env, 'SELECT token_hash FROM sessions'))
        assert [row['token_hash'] for row in remaining] == [sha256_b64url('b-secret')]

    def test_rate_limit_30_then_reset(self, d1):
        env = make_env(d1)
        login(env)
        session_hash = sha256_b64url('sessionsecret')
        for _ in range(30):
            result = run(accounts.dispatch(env, UID, session_hash, 'favorite', 'csrf-token',
                                           {'id': 'x', 'saved': False}))
            assert result['status'] == 200
        result = run(accounts.dispatch(env, UID, session_hash, 'favorite', 'csrf-token',
                                       {'id': 'x', 'saved': False}))
        assert result['status'] == 429
        # Window reset unblocks (age the window past 60s).
        run(db_run(env, 'UPDATE sessions SET window_start = ?',
                   (int(time.time() * 1000) - 61000,)))
        result = run(accounts.dispatch(env, UID, session_hash, 'favorite', 'csrf-token',
                                       {'id': 'x', 'saved': False}))
        assert result['status'] == 200


class TestProfile:
    def test_rename(self, d1):
        env = make_env(d1)
        login(env)
        result = run(accounts.dispatch(env, UID, sha256_b64url('sessionsecret'), 'profile',
                                       'csrf-token', {'displayName': '新昵称'}))
        assert result['user']['displayName'] == '新昵称'

    def test_invalid_names_400(self, d1):
        env = make_env(d1)
        login(env)
        session_hash = sha256_b64url('sessionsecret')
        for bad in ({'displayName': '  '}, {'displayName': 'x' * 61},
                    {'displayName': 'a\x01b'}, {'displayName': 5}, {}):
            result = run(accounts.dispatch(env, UID, session_hash, 'profile', 'csrf-token', bad))
            assert result['status'] == 400, bad


class TestFavorites:
    def _seed_item(self, env):
        run(db_run(env, "INSERT INTO sources (id, name, homepage, status, item_count) "
                        "VALUES ('qbitai', 'n', 'https://s.com', 'ok', 1)"))
        run(db_run(env, "INSERT INTO items (id, title, url, source_id, source_name, collected_at, rank_score) "
                        "VALUES ('item-1', 't', 'https://a.com/1', 'qbitai', 'n', ?, 50)",
                   (now_iso(),)))

    def test_add_and_remove(self, d1):
        env = make_env(d1)
        login(env)
        self._seed_item(env)
        session_hash = sha256_b64url('sessionsecret')
        result = run(accounts.dispatch(env, UID, session_hash, 'favorite', 'csrf-token',
                                       {'id': 'item-1', 'saved': True}))
        assert result['favorites'] == ['item-1']
        result = run(accounts.dispatch(env, UID, session_hash, 'favorite', 'csrf-token',
                                       {'id': 'item-1', 'saved': True}))
        assert result['favorites'] == ['item-1']  # idempotent, no dupes
        result = run(accounts.dispatch(env, UID, session_hash, 'favorite', 'csrf-token',
                                       {'id': 'item-1', 'saved': False}))
        assert result['favorites'] == []

    def test_cap_200(self, d1):
        env = make_env(d1)
        login(env)
        session_hash = sha256_b64url('sessionsecret')
        for i in range(200):
            run(db_run(env, 'INSERT OR IGNORE INTO favorites (github_id, item_id, saved_at) VALUES (?, ?, ?)',
                       (12345, 'it-%03d' % i, now_iso())))
        result = run(accounts.dispatch(env, UID, session_hash, 'favorite', 'csrf-token',
                                       {'id': 'new-one', 'saved': True}))
        assert result['status'] == 409 and result['error'] == '最多收藏 200 条资讯。'

    def test_invalid_400(self, d1):
        env = make_env(d1)
        login(env)
        result = run(accounts.dispatch(env, UID, sha256_b64url('sessionsecret'), 'favorite',
                                       'csrf-token', {'id': 'x', 'saved': 'yes'}))
        assert result['status'] == 400


class TestTags:
    def test_follow_and_unfollow(self, d1):
        env = make_env(d1)
        login(env)
        session_hash = sha256_b64url('sessionsecret')
        result = run(accounts.dispatch(env, UID, session_hash, 'tag', 'csrf-token',
                                       {'tag': ' DeepSeek ', 'followed': True}))
        assert result['tags'] == ['DeepSeek']  # trimmed
        result = run(accounts.dispatch(env, UID, session_hash, 'tag', 'csrf-token',
                                       {'tag': 'DeepSeek', 'followed': False}))
        assert result['tags'] == []

    def test_cap_30(self, d1):
        env = make_env(d1)
        login(env)
        session_hash = sha256_b64url('sessionsecret')
        for i in range(30):
            run(db_run(env, 'INSERT OR IGNORE INTO followed_tags (github_id, tag, followed_at) VALUES (?, ?, ?)',
                       (12345, 'tag-%02d' % i, now_iso())))
        result = run(accounts.dispatch(env, UID, session_hash, 'tag', 'csrf-token',
                                       {'tag': 'extra', 'followed': True}))
        assert result['status'] == 409 and result['error'] == '最多关注 30 个标签。'

    def test_invalid_400(self, d1):
        env = make_env(d1)
        login(env)
        session_hash = sha256_b64url('sessionsecret')
        for bad in ({'tag': 'x' * 41, 'followed': True}, {'tag': 'ok', 'followed': 1},
                    {'tag': 'a\x00b', 'followed': True}):
            result = run(accounts.dispatch(env, UID, session_hash, 'tag', 'csrf-token', bad))
            assert result['status'] == 400, bad
