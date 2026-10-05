"""notify — daily digest composition, Resend call, and cycle-wrap wiring."""
import json

import pytest

import collector
import notify
from conftest import make_env, run
from db import db_run, set_meta

NOW_MS = 1759737600000  # 2025-10-06T08:00:00Z → Beijing 10-06 16:00


class FakeResponse:
    def __init__(self, status=200, text='{"id":"e1"}'):
        self.status = status
        self._text = text

    async def text(self):
        return self._text


def seed(d1, **values):
    env = make_env(d1, **values)
    run(db_run(
        env,
        "INSERT INTO sources (id, name, homepage, status, last_success_at, item_count, error) VALUES "
        "('github-projects', 'GitHub', 'https://github.com', 'ok', '2026-10-06T00:05:00.000Z', 30, NULL)",
        (),
    ))
    run(db_run(
        env,
        "INSERT INTO sources (id, name, homepage, status, last_success_at, item_count, error) VALUES "
        "('qbitai', '量子位', 'https://www.qbitai.com', 'error', NULL, 12, 'HTTP 403')",
        (),
    ))
    run(db_run(
        env,
        "INSERT INTO items (id, title, url, source_id, source_name, collected_at, rank_score) VALUES "
        "('i1', 't1', 'https://a/1', 'github-projects', 'GitHub', '2026-10-06T00:05:00.000Z', 50)",
        (),
    ))
    run(db_run(
        env,
        "INSERT INTO items (id, title, url, source_id, source_name, collected_at, rank_score) VALUES "
        "('i2', 't2', 'https://a/2', 'qbitai', '量子位', '2026-10-06T00:05:00.000Z', 50)",
        (),
    ))
    run(set_meta(env, 'generated_at', '2026-10-06T00:05:00.000Z'))
    return env


ROWS = [
    {'id': 'github-projects', 'name': 'GitHub', 'status': 'ok',
     'last_success_at': '2026-10-06T00:05:00.000Z', 'item_count': 30, 'error': None},
    {'id': 'qbitai', 'name': '量子位', 'status': 'error', 'last_success_at': None,
     'item_count': 12, 'error': 'HTTP 403'},
]


class TestBuildReport:
    def test_counts_and_failure_detail(self):
        subject, body, html = notify.build_report(ROWS, 42, '2026-10-06T00:05:00.000Z', NOW_MS)
        assert subject == 'signal. 日报 10-06：1/2 成功，42 条信号'
        assert '1 成功 / 1 失败，共 42 条信号' in body
        assert '- 量子位：失败，12 条，最近成功 —' in body
        assert '- 量子位：HTTP 403' in body
        assert '快照生成：10-06 08:05（北京时间）' in body  # UTC → 北京 +8
        assert 'signal. 采集日报' in html
        assert '量子位' in html and 'HTTP 403' in html
        assert '全部来源采集正常' not in html
        assert 'border-bottom:3px double' in html  # 报头双线（与主站同一母题）

    def test_all_ok_no_failure_section(self):
        _, body, html = notify.build_report([dict(ROWS[0])], 30, None, NOW_MS)
        assert '失败详情：无。' in body
        assert '快照生成：—' in body
        assert '全部来源采集正常' in html


class TestReportSections:
    def test_editor_note_renders(self):
        _, body, html = notify.build_report(
            ROWS, 42, '2026-10-06T00:05:00.000Z', NOW_MS, editor_note='今日看点：开源持续发力。')
        assert '编者按：今日看点：开源持续发力。' in body
        assert '编者按' in html and '今日看点：开源持续发力。' in html

    def test_followed_section(self):
        followed = [{'title': 'DeepSeek R2', 'url': 'https://a/9', 'sourceName': 'GitHub'}]
        _, body, html = notify.build_report(
            ROWS, 42, '2026-10-06T00:05:00.000Z', NOW_MS, followed=followed)
        assert '关注命中（近 24 小时）：' in body
        assert '- DeepSeek R2（GitHub）' in body
        assert 'DeepSeek R2' in html

    def test_sections_omitted_by_default(self):
        _, body, html = notify.build_report(ROWS, 42, '2026-10-06T00:05:00.000Z', NOW_MS)
        assert '编者按' not in body and '关注命中' not in body and '上周回顾' not in body
        assert '编者按' not in html and '关注命中' not in html and '上周回顾' not in html

    def test_weekly_section(self):
        weekly = {'days': [{'date': '2025-09-29', 'count': 42}], 'headlines': ['t1', 't2', 't3']}
        _, body, html = notify.build_report(
            ROWS, 42, '2026-10-06T00:05:00.000Z', NOW_MS, weekly=weekly)
        assert '- 2025-09-29：42 条' in body
        assert '上周同日头条：t1 / t2 / t3' in body
        assert '上周回顾' in html and 't1 / t2 / t3' in html

    def test_weekly_without_headlines(self):
        weekly = {'days': [{'date': '2025-09-29', 'count': 42}], 'headlines': []}
        _, body, _ = notify.build_report(ROWS, 42, None, NOW_MS, weekly=weekly)
        assert '上周同日头条' not in body
        assert '- 2025-09-29：42 条' in body


class TestSendDailyReport:
    def test_disabled_without_secrets(self, d1):
        assert run(notify.send_daily_report(make_env(d1))) is None

    def test_posts_to_resend(self, d1, monkeypatch):
        env = seed(d1, RESEND_API_KEY='re_key', MAIL_TO='me@example.com')
        calls = []

        async def fake_fetch(url, init):
            calls.append((url, init))
            return FakeResponse()

        monkeypatch.setattr(collector, '_http_fetch', fake_fetch)
        result = run(notify.send_daily_report(env, NOW_MS))
        assert result == {'ok': True, 'to': env.MAIL_TO,
                          'subject': 'signal. 日报 10-06：1/2 成功，2 条信号'}
        url, init = calls[0]
        assert url == notify.RESEND_URL
        assert init['headers']['Authorization'] == 'Bearer re_key'
        payload = json.loads(init['body'])
        assert payload['to'] == ['me@example.com']
        assert payload['from'] == notify.FROM
        assert 'HTTP 403' in payload['text']
        assert 'signal. 采集日报' in payload['html']

    def test_non_200_raises(self, d1, monkeypatch):
        env = seed(d1, RESEND_API_KEY='re_key', MAIL_TO='me@example.com')

        async def fake_fetch(url, init):
            return FakeResponse(422, '{"message":"bad"}')

        monkeypatch.setattr(collector, '_http_fetch', fake_fetch)
        with pytest.raises(RuntimeError, match='422'):
            run(notify.send_daily_report(env, NOW_MS))

    def _capture(self, monkeypatch):
        calls = []

        async def fake_fetch(url, init):
            calls.append((url, init))
            return FakeResponse()

        monkeypatch.setattr(collector, '_http_fetch', fake_fetch)
        return calls

    def test_monday_attaches_weekly(self, d1, monkeypatch):
        import datetime as dt

        env = seed(d1, RESEND_API_KEY='re_key', MAIL_TO='me@example.com')
        base = dt.datetime.fromtimestamp((NOW_MS + notify.BEIJING_MS) / 1000, tz=dt.timezone.utc)
        for offset in range(7, 0, -1):  # last week's seven Beijing days
            day = (base - dt.timedelta(days=offset)).strftime('%Y-%m-%d')
            payload = json.dumps({
                'stats': {'items': 40 + offset},
                'lead': [{'title': '头条' + day}],
            })
            run(db_run(
                env,
                'INSERT INTO daily_snapshots (date, generated_at, payload) VALUES (?, ?, ?)',
                (day, '2025-10-01T00:00:00.000Z', payload),
            ))

        calls = self._capture(monkeypatch)
        run(notify.send_daily_report(env, NOW_MS))  # NOW_MS is a Beijing Monday
        body = json.loads(calls[0][1]['body'])
        assert '上周回顾' in body['text']
        assert '- 2025-09-29：47 条' in body['text']  # offset 7 → 40+7
        assert '头条2025-09-29' in body['text']
        assert '上周回顾' in body['html']

    def test_non_monday_has_no_weekly(self, d1, monkeypatch):
        env = seed(d1, RESEND_API_KEY='re_key', MAIL_TO='me@example.com')
        run(db_run(
            env,
            "INSERT INTO daily_snapshots (date, generated_at, payload) VALUES ('2025-10-04', 'x', '{}')",
            (),
        ))
        calls = self._capture(monkeypatch)
        run(notify.send_daily_report(env, NOW_MS - 2 * 86400000))  # Saturday
        body = json.loads(calls[0][1]['body'])
        assert '上周回顾' not in body['text'] and '上周回顾' not in body['html']

    def test_followed_hits_included(self, d1, monkeypatch):
        env = seed(d1, RESEND_API_KEY='re_key', MAIL_TO='me@example.com')
        run(db_run(env, "INSERT INTO users (github_id, login, display_name, created_at) "
                        "VALUES (1, 'lao', 'lao', '2025-10-01T00:00:00.000Z')", ()))
        run(db_run(env, "INSERT INTO followed_tags (github_id, tag, followed_at) "
                        "VALUES (1, 'DeepSeek', '2025-10-01T00:00:00.000Z')", ()))
        run(db_run(env, "INSERT INTO item_tags (item_id, tag) VALUES ('i1', 'DeepSeek')", ()))
        run(db_run(env, 'UPDATE items SET item_ts = ?', (NOW_MS - 3600000,)))  # within 24h

        calls = self._capture(monkeypatch)
        run(notify.send_daily_report(env, NOW_MS))
        body = json.loads(calls[0][1]['body'])
        assert '关注命中（近 24 小时）：' in body['text']
        assert '- t1（GitHub）' in body['text']
        assert '关注命中' in body['html']

    def test_stale_editor_note_meta_ignored(self, d1, monkeypatch):
        env = seed(d1, RESEND_API_KEY='re_key', MAIL_TO='me@example.com')
        run(set_meta(env, 'editor_note', 'not-json{{'))
        calls = self._capture(monkeypatch)
        run(notify.send_daily_report(env, NOW_MS))
        body = json.loads(calls[0][1]['body'])
        assert '编者按' not in body['text']


class TestCycleWrapWiring:
    def _stub(self, monkeypatch):
        async def fake_collect(env, source, now):
            return []

        async def fake_write(env, source, items, now, now_ms):
            return 0

        monkeypatch.setattr(collector, 'collect_source', fake_collect)
        monkeypatch.setattr(collector, 'write_source_success', fake_write)
        sent = []

        async def fake_report(env, now_ms=None):
            sent.append(now_ms)
            return {'ok': True, 'stub': True}

        monkeypatch.setattr(notify, 'send_daily_report', fake_report)
        return sent

    def _run_at_cursor(self, d1, cursor):
        env = make_env(d1, COLLECT_SOURCES_PER_RUN='1')

        async def scenario():
            await set_meta(env, 'collect_cursor', cursor)
            return await collector.run_collection(env, allow_cursor=True, now_ms=NOW_MS)

        return env, run(scenario())

    def test_wrap_sends_once(self, d1, monkeypatch):
        sent = self._stub(monkeypatch)
        _, status = self._run_at_cursor(d1, '11')
        assert len(sent) == 1
        assert sent[0] == NOW_MS
        assert status['mail'] == {'ok': True, 'stub': True}

    def test_mid_cycle_does_not_send(self, d1, monkeypatch):
        sent = self._stub(monkeypatch)
        _, status = self._run_at_cursor(d1, '5')
        assert sent == []
        assert 'mail' not in status

    def test_mail_failure_does_not_break_collection(self, d1, monkeypatch):
        self._stub(monkeypatch)

        async def boom(env, now_ms=None):
            raise RuntimeError('Resend HTTP 500: nope')

        monkeypatch.setattr(notify, 'send_daily_report', boom)
        _, status = self._run_at_cursor(d1, '11')
        assert status['mail'] == {'ok': False, 'error': 'Resend HTTP 500: nope'}
        assert status['ok'] == 1
