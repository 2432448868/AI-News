"""API layer tests — routing, validation matrix, and response shapes."""
import json
from urllib.parse import parse_qsl

import api as api
from db import db_batch, db_run, set_meta

from conftest import make_env, run

ORIGIN = 'https://signal.example.com'


def req(method='GET', path='/api/feed', query='', headers=None, body=None):
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


def seed_feed(env):
    """3 items across categories with tags/china flags + 2 sources.

    Uses the real current time so the 48h staleness check stays 'ok'."""
    from util import now_iso

    stamp = now_iso()
    run(set_meta(env, 'generated_at', stamp))
    run(db_batch(env, [
        ("INSERT INTO sources (id, name, homepage, status, last_success_at, item_count, error) "
         "VALUES ('qbitai', '量子位', 'https://www.qbitai.com', 'ok', ?, 2, NULL)", (stamp,)),
        ("INSERT INTO sources (id, name, homepage, status, last_success_at, item_count, error) "
         "VALUES ('hf-models', 'HF', 'https://huggingface.co', 'error', NULL, 1, 'boom')", ()),
        ("INSERT INTO items (id, title, url, summary, source_id, source_name, collected_at, "
         "item_ts, rank_score, is_china, search_text) VALUES "
         "('aa', 'DeepSeek 发布', 'https://a.com/1', 'sum one', 'qbitai', '量子位', "
         "'2025-10-06T00:00:00.000Z', 1759737600000, 90, 1, 'deepseek 发布 模型动态 ai 动态')", ()),
        ("INSERT INTO items (id, title, url, summary, source_id, source_name, collected_at, "
         "item_ts, rank_score, is_china, search_text) VALUES "
         "('bb', 'Plain news', 'https://a.com/2', 'sum two', 'qbitai', '量子位', "
         "'2025-10-06T00:00:00.000Z', 1759651200000, 70, 0, 'plain news 量子位 ai 动态')", ()),
        ("INSERT INTO items (id, title, url, summary, source_id, source_name, collected_at, "
         "item_ts, rank_score, is_china, search_text) VALUES "
         "('cc', 'Llama model', 'https://a.com/3', 'sum three', 'hf-models', 'HF', "
         "'2025-10-06T00:00:00.000Z', 1759564800000, 80, 0, 'llama model hf 模型动态')", ()),
        ("INSERT INTO item_categories VALUES ('aa','news'), ('bb','news'), ('cc','models')", ()),
        ("INSERT INTO item_tags VALUES ('aa','DeepSeek'), ('aa','媒体报道'), ('bb','媒体报道'), ('cc','开源项目')", ()),
    ]))
    return stamp


def body_of(resp):
    return json.loads(resp['body'])


class TestRouting:
    def test_unknown_api_404(self, d1):
        assert run(api.handle_api(req(path='/api/nope'), make_env(d1)))['status'] == 404

    def test_post_405_with_allow(self, d1):
        resp = run(api.handle_api(req('POST', '/api/feed'), make_env(d1)))
        assert resp['status'] == 405
        assert ('Allow', 'GET, HEAD') in resp['headers']

    def test_query_too_long(self, d1):
        resp = run(api.handle_api(req(query='x' * 1001), make_env(d1)))
        assert resp['status'] == 400

    def test_uninitialized_503(self, d1):
        resp = run(api.handle_api(req(), make_env(d1)))
        assert resp['status'] == 503


class TestFeed:
    def test_shape(self, d1):
        env = make_env(d1)
        stamp = seed_feed(env)
        resp = run(api.handle_api(req(), env))
        assert resp['status'] == 200
        feed = body_of(resp)
        assert feed['schemaVersion'] == 1
        assert feed['generatedAt'] == stamp
        assert len(feed['sources']) == 2
        assert feed['sources'][0]['id'] == 'qbitai'
        assert feed['sources'][0]['lastSuccessAt'] == stamp
        ids = [item['id'] for item in feed['items']]
        assert ids == ['aa', 'bb', 'cc']  # item_ts DESC
        assert set(feed['items'][0]['tags']) == {'DeepSeek', '媒体报道'}
        assert feed['items'][0]['categories'] == ['news']

    def test_head_empty_body(self, d1):
        env = make_env(d1)
        seed_feed(env)
        resp = run(api.handle_api(req('HEAD'), env))
        assert resp['status'] == 200 and resp['body'] is None


class TestSources:
    def test_shape(self, d1):
        env = make_env(d1)
        stamp = seed_feed(env)
        payload = body_of(run(api.handle_api(req(path='/api/sources'), env)))
        assert payload['generatedAt'] == stamp
        errored = [s for s in payload['sources'] if s['id'] == 'hf-models'][0]
        assert errored['status'] == 'error' and errored['error'] == 'boom'
        assert set(errored) == {'id', 'name', 'homepage', 'status', 'lastSuccessAt', 'itemCount', 'error'}


class TestHealth:
    def test_shape(self, d1):
        env = make_env(d1)
        seed_feed(env)
        run(set_meta(env, 'sync_status', json.dumps({'ranAt': '2025-10-06T00:00:00.000Z', 'ok': 2, 'failed': 0})))
        payload = body_of(run(api.handle_api(req(path='/api/health'), env)))
        assert payload['status'] == 'ok'
        assert payload['itemCount'] == 3
        assert payload['sourceCount'] == 2
        assert payload['healthySources'] == 1
        assert payload['sync']['ok'] == 2
        assert 'D1' in payload['collection']


def seed_snapshot(env, date, items=42, lead_title='头条'):
    payload = json.dumps({
        'stats': {'items': items, 'okSources': 11, 'totalSources': 12},
        'lead': [{'title': lead_title, 'url': 'https://a/1', 'sourceName': 'GitHub'}],
        'trending': [],
    })
    run(db_run(
        env,
        'INSERT INTO daily_snapshots (date, generated_at, payload) VALUES (?, ?, ?)',
        (date, '2025-10-06T00:05:00.000Z', payload),
    ))


class TestArchive:
    def test_list_shape(self, d1):
        env = make_env(d1)
        seed_feed(env)
        seed_snapshot(env, '2025-10-06', 42)
        seed_snapshot(env, '2025-10-05', 41)
        payload = body_of(run(api.handle_api(req(path='/api/archive'), env)))
        assert [day['date'] for day in payload['days']] == ['2025-10-06', '2025-10-05']  # newest first
        assert payload['days'][0]['stats']['items'] == 42

    def test_single_edition(self, d1):
        env = make_env(d1)
        seed_feed(env)
        seed_snapshot(env, '2025-10-06', 42, lead_title='大新闻')
        payload = body_of(run(api.handle_api(req(path='/api/archive', query='date=2025-10-06'), env)))
        assert payload['lead'][0]['title'] == '大新闻'
        assert payload['stats']['totalSources'] == 12
        assert payload['generatedAt'] == '2025-10-06T00:05:00.000Z'

    def test_bad_date_400_missing_404(self, d1):
        env = make_env(d1)
        seed_feed(env)
        assert run(api.handle_api(req(path='/api/archive', query='date=2025-13-99'), env))['status'] == 400
        assert run(api.handle_api(req(path='/api/archive', query='date=2020-01-01'), env))['status'] == 404

    def test_empty_list(self, d1):
        env = make_env(d1)
        seed_feed(env)
        payload = body_of(run(api.handle_api(req(path='/api/archive'), env)))
        assert payload['days'] == []


class TestStats:
    def test_shape(self, d1):
        env = make_env(d1)
        seed_feed(env)
        seed_snapshot(env, '2025-10-06', 42)
        payload = body_of(run(api.handle_api(req(path='/api/stats'), env)))
        assert payload['days'] == [{'date': '2025-10-06', 'items': 42}]
        assert payload['categories'] == [{'category': 'news', 'n': 2}, {'category': 'models', 'n': 1}]
        tags = {row['tag']: row['n'] for row in payload['tags']}
        assert tags['DeepSeek'] == 1 and len(payload['tags']) <= 10
        assert {s['id'] for s in payload['sources']} == {'qbitai', 'hf-models'}


class TestFeedEditorNote:
    def test_note_surface(self, d1):
        env = make_env(d1)
        seed_feed(env)
        run(set_meta(env, 'editor_note', json.dumps({'date': '2025-10-06', 'text': '看点：开源发力。'})))
        feed = body_of(run(api.handle_api(req(), env)))
        assert feed['editorNote'] == {'date': '2025-10-06', 'text': '看点：开源发力。'}

    def test_absent_or_garbage_is_none(self, d1):
        env = make_env(d1)
        seed_feed(env)
        assert body_of(run(api.handle_api(req(), env)))['editorNote'] is None
        run(set_meta(env, 'editor_note', 'garbage{{'))
        assert body_of(run(api.handle_api(req(), env)))['editorNote'] is None
        run(set_meta(env, 'editor_note', ''))  # cleared by digest on failure
        assert body_of(run(api.handle_api(req(), env)))['editorNote'] is None


class TestItems:
    def test_all_defaults(self, d1):
        env = make_env(d1)
        seed_feed(env)
        payload = body_of(run(api.handle_api(req(path='/api/items'), env)))
        assert payload['total'] == 3
        assert payload['page'] == 1 and payload['limit'] == 24
        assert payload['stale'] is False

    def test_category_and_tag(self, d1):
        env = make_env(d1)
        seed_feed(env)
        payload = body_of(run(api.handle_api(req(path='/api/items', query='category=models'), env)))
        assert payload['total'] == 1 and payload['items'][0]['id'] == 'cc'
        payload = body_of(run(api.handle_api(req(path='/api/items', query='tag=DeepSeek'), env)))
        assert payload['total'] == 1 and payload['items'][0]['id'] == 'aa'

    def test_china_only(self, d1):
        env = make_env(d1)
        seed_feed(env)
        payload = body_of(run(api.handle_api(req(path='/api/items', query='chinaOnly=true'), env)))
        assert [i['id'] for i in payload['items']] == ['aa']

    def test_search_and_escape(self, d1):
        env = make_env(d1)
        seed_feed(env)
        payload = body_of(run(api.handle_api(req(path='/api/items', query='q=deepseek'), env)))
        assert payload['total'] == 1
        payload = body_of(run(api.handle_api(req(path='/api/items', query='q=%25'), env)))
        assert payload['total'] == 0  # literal % must not act as a wildcard

    def test_sort_hot_and_paging(self, d1):
        env = make_env(d1)
        seed_feed(env)
        payload = body_of(run(api.handle_api(req(path='/api/items', query='sort=hot'), env)))
        assert [i['id'] for i in payload['items']] == ['aa', 'cc', 'bb']  # rank 90/80/70
        payload = body_of(run(api.handle_api(req(path='/api/items', query='page=2&limit=2'), env)))
        assert [i['id'] for i in payload['items']] == ['cc']
        assert payload['total'] == 3

    def test_sort_growth(self, d1):
        env = make_env(d1)
        seed_feed(env)
        run(db_batch(env, [
            ("UPDATE items SET metric_value = 180, metric_prev = 100 WHERE id = 'aa'", ()),
            ("UPDATE items SET metric_value = 500, metric_prev = 50 WHERE id = 'cc'", ()),
        ]))
        payload = body_of(run(api.handle_api(req(path='/api/items', query='sort=growth'), env)))
        # delta 450 (cc) → 80 (aa) → NULL diff sinks last (bb, no metrics)
        assert [i['id'] for i in payload['items']] == ['cc', 'aa', 'bb']
        assert payload['items'][0]['metricPrev'] == 50

    def test_days_zero_no_filter(self, d1):
        env = make_env(d1)
        seed_feed(env)
        payload = body_of(run(api.handle_api(req(path='/api/items', query='days=0'), env)))
        assert payload['total'] == 3

    def test_invalid_matrix_400(self, d1):
        env = make_env(d1)
        seed_feed(env)
        for query in (
            'category=bogus', 'sort=weird', 'page=0', 'page=501', 'page=1.5', 'page=abc',
            'limit=0', 'limit=101', 'days=-1', 'days=366', 'chinaOnly=yes', 'chinaOnly=1',
        ):
            resp = run(api.handle_api(req(path='/api/items', query=query), env))
            assert resp['status'] == 400, query

    def test_page_float_integer_form_ok(self, d1):
        env = make_env(d1)
        seed_feed(env)
        resp = run(api.handle_api(req(path='/api/items', query='page=2.0'), env))
        assert resp['status'] == 200  # JS Number('2.0') === 2 is an integer


class TestSync:
    def test_missing_token_config_404(self, d1):
        resp = run(api.handle_api(req('POST', '/api/sync'), make_env(d1, ADMIN_TOKEN=None)))
        assert resp['status'] == 404

    def test_wrong_token_403(self, d1):
        resp = run(api.handle_api(req('POST', '/api/sync', headers={'x-admin-token': 'bad'}),
                                  make_env(d1)))
        assert resp['status'] == 403

    def test_get_405(self, d1):
        assert run(api.handle_api(req('GET', '/api/sync'), make_env(d1)))['status'] == 405

    def test_valid_token_runs_collection(self, d1, monkeypatch):
        import collector as collector

        monkeypatch.setattr(collector, 'run_collection',
                            lambda env, only=None, allow_cursor=True: _ok_status())
        resp = run(api.handle_api(req('POST', '/api/sync', headers={'x-admin-token': 'admintoken'}),
                                  make_env(d1)))
        assert resp['status'] == 200
        assert body_of(resp)['ok'] == 1


async def _ok_status():
    return {'ranAt': '2025-10-06T00:00:00.000Z', 'ok': 1, 'failed': 0, 'sources': []}
