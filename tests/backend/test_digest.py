"""digest — snapshot, editor note, and failure isolation at cycle wrap."""
import json

import digest
import notify
from conftest import make_env, run
from db import db_all, db_run, get_meta

NOW_MS = 1759737600000  # 2025-10-06T08:00Z → Beijing 10-06 16:00 (Monday)


def seed(d1, item_ts=NOW_MS):
    env = make_env(d1)
    run(db_run(
        env,
        "INSERT INTO sources (id, name, homepage, status, last_success_at, item_count) "
        "VALUES ('qbitai', '量子位', 'https://q.com', 'ok', NULL, 1)",
        (),
    ))
    run(db_run(
        env,
        "INSERT INTO items (id, title, url, source_id, source_name, collected_at, item_ts, rank_score) "
        "VALUES ('i1', '标题甲', 'https://a/1', 'qbitai', '量子位', '2025-10-06T00:00:00.000Z', ?, 90)",
        (item_ts,),
    ))
    return env


def snapshot_row(env):
    return run(db_all(env, 'SELECT date, generated_at, payload FROM daily_snapshots'))


class TestRunDigest:
    def test_snapshot_and_note_written(self, d1, monkeypatch):
        env = seed(d1)

        async def fake_note(env, titles):
            return '今日看点：开源模型持续发力。'

        monkeypatch.setattr(digest.ai_module, 'editor_note', fake_note)
        status = run(digest.run_digest(env, NOW_MS))
        assert status['snapshot'] == {'ok': True, 'date': '2025-10-06'}
        assert status['editorNote']['ok'] is True

        rows = snapshot_row(env)
        assert len(rows) == 1
        payload = json.loads(rows[0]['payload'])
        assert payload['stats'] == {'items': 1, 'okSources': 1, 'totalSources': 1}
        assert payload['lead'][0]['title'] == '标题甲'
        assert len(payload['lead']) == 1 and len(payload['trending']) == 1

        note = json.loads(run(get_meta(env, 'editor_note')))
        assert note == {'date': '2025-10-06', 'text': '今日看点：开源模型持续发力。'}

    def test_same_day_overwrites_snapshot(self, d1):
        env = seed(d1)  # no AI binding → note skipped, snapshot still written
        run(digest.run_digest(env, NOW_MS))
        run(digest.run_digest(env, NOW_MS + 3600000))  # same Beijing day

        rows = snapshot_row(env)
        assert len(rows) == 1
        assert json.loads(rows[0]['payload'])['generatedAt']  # refreshed payload won

    def test_ai_failure_isolated_and_meta_cleared(self, d1, monkeypatch):
        env = seed(d1)
        sent = []

        async def fake_report(env, now_ms=None):
            sent.append(now_ms)
            return {'ok': True}

        async def boom(env, titles):
            raise RuntimeError('ai down')

        monkeypatch.setattr(notify, 'send_daily_report', fake_report)
        monkeypatch.setattr(digest.ai_module, 'editor_note', boom)
        status = run(digest.run_digest(env, NOW_MS))
        assert status['snapshot']['ok'] is True
        assert status['editorNote'] == {'ok': False, 'error': 'ai down'}
        assert run(get_meta(env, 'editor_note')) == ''  # yesterday's note must not survive
        assert sent == [NOW_MS]  # mail still attempted
        assert status['mail'] == {'ok': True}

    def test_no_binding_skips_note(self, d1, monkeypatch):
        env = seed(d1)

        async def fake_report(env, now_ms=None):
            return {'ok': True}

        monkeypatch.setattr(notify, 'send_daily_report', fake_report)
        status = run(digest.run_digest(env, NOW_MS))
        assert status['editorNote'] == {'ok': False, 'skipped': True}
        assert run(get_meta(env, 'editor_note')) == ''

    def test_mail_failure_shaped_like_before(self, d1, monkeypatch):
        env = seed(d1)

        async def boom(env, now_ms=None):
            raise RuntimeError('Resend HTTP 500: nope')

        monkeypatch.setattr(notify, 'send_daily_report', boom)
        status = run(digest.run_digest(env, NOW_MS))
        assert status['mail'] == {'ok': False, 'error': 'Resend HTTP 500: nope'}
