"""Collector tests: normalization ports, fetch retry, and D1 write semantics."""
import json
import types

import pytest

import collector as collector
from collector import (
    FetchError,
    build_sources,
    normalize_github,
    normalize_hf,
    normalize_rss,
    run_collection,
)
from db import db_all, get_meta, set_meta

from conftest import make_env, run

NOW = '2025-10-06T00:00:00.000Z'
NOW_MS = 1759737600000


def rss_source(**overrides):
    base = {'id': 'qbitai', 'name': '量子位', 'homepage': 'https://www.qbitai.com',
            'kind': 'rss', 'media': True, 'url': 'https://www.qbitai.com/feed'}
    base.update(overrides)
    return base


def gh_source(**overrides):
    base = {'id': 'github-projects', 'name': 'GitHub', 'homepage': 'https://github.com',
            'kind': 'github', 'url': 'https://api.github.com/search/repositories?q=x'}
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# normalize_rss

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>t</title>
<item><title>OpenAI 发布新模型</title><link>https://a.com/1?utm_source=x</link>
<description>&lt;p&gt;hello &amp;amp; world&lt;/p&gt;</description>
<pubDate>Mon, 06 Oct 2025 00:00:00 GMT</pubDate></item>
<item><title>Old piece</title><link>https://a.com/2</link>
<pubDate>Mon, 01 Sep 2025 00:00:00 GMT</pubDate></item>
<item><title>No date</title><link>https://a.com/3</link></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Atom entry</title>
<link rel="alternate" href="https://b.com/1"/><updated>2025-10-05T00:00:00Z</updated>
<summary>sum</summary></entry>
</feed>"""


class TestNormalizeRss:
    def test_basic_filter_and_categories(self):
        items = normalize_rss(RSS, rss_source(), NOW)
        assert [i['title'] for i in items] == ['OpenAI 发布新模型', 'No date']
        first = items[0]
        assert first['url'] == 'https://a.com/1'
        assert first['id'] == collector.item_id('https://a.com/1')
        assert 'news' in first['categories']
        assert '媒体报道' in first['tags']
        assert first['publishedAt'] == '2025-10-06T00:00:00.000Z'
        assert first['rankScore'] == 95

    def test_atom(self):
        items = normalize_rss(ATOM, rss_source(id='hf-blog', kind='rss', media=False), NOW)
        assert items and items[0]['url'] == 'https://b.com/1'
        assert '官方博客' in items[0]['tags']

    def test_rejects_doctype_and_entity(self):
        with pytest.raises(ValueError):
            normalize_rss('<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><rss/>',
                          rss_source(), NOW)
        with pytest.raises(ValueError):
            normalize_rss('<!ENTITY a "b"><rss/>', rss_source(), NOW)

    def test_rejects_garbage(self):
        with pytest.raises(ValueError):
            normalize_rss('not xml at all', rss_source(), NOW)
        with pytest.raises(ValueError):
            normalize_rss('<html><body></body></html>', rss_source(), NOW)


# ---------------------------------------------------------------------------
# normalize_github / normalize_hf

def repo(n, **overrides):
    base = {
        'full_name': 'org/' + n, 'html_url': 'https://github.com/org/' + n,
        'description': 'desc ' + n, 'archived': False, 'fork': False, 'private': False,
        'created_at': '2025-10-01T00:00:00Z', 'pushed_at': '2025-10-05T00:00:00Z',
        'stargazers_count': 100, 'topics': ['llm', 'agent', 'a', 'b', 'c'],
    }
    base.update(overrides)
    return base


class TestNormalizeGithub:
    def test_search(self):
        items = normalize_github({'items': [repo('one'), repo('x', archived=True)]}, gh_source(), NOW)
        assert len(items) == 1
        assert items[0]['categories'] == ['projects']
        assert items[0]['metricLabel'] == 'stars'
        assert items[0]['metricValue'] == 100
        assert len(items[0]['tags']) == 4  # topics capped at 4

    def test_incomplete_raises(self):
        with pytest.raises(ValueError):
            normalize_github({'items': [], 'incomplete_results': True}, gh_source(), NOW)
        with pytest.raises(ValueError):
            normalize_github({}, gh_source(), NOW)

    def test_org_30d_window(self):
        source = gh_source(id='cn-official-deepseek-ai', kind='github-org')
        fresh = normalize_github({'items': [repo('new', pushed_at='2025-10-05T00:00:00Z')]}, source, NOW)
        stale = normalize_github({'items': [repo('old', pushed_at='2025-08-01T00:00:00Z')]}, source, NOW)
        assert len(fresh) == 1
        assert stale == []


class TestNormalizeHf:
    def test_models(self):
        payload = [
            {'id': 'org/model-1', 'pipeline_tag': 'text-generation', 'downloads': 10,
             'createdAt': '2025-10-01T00:00:00Z', 'lastModified': '2025-10-05T00:00:00Z',
             'tags': ['transformers', 'license:apache', 'ok']},
            {'id': 'bad id with spaces'},
        ]
        items = normalize_hf(payload, gh_source(id='hf-models', kind='hf'), NOW)
        assert len(items) == 1
        assert items[0]['url'] == 'https://huggingface.co/org/model-1'
        assert items[0]['categories'] == ['models']
        assert items[0]['metricLabel'] == 'downloads'
        assert items[0]['metricValue'] == 10

    def test_spaces(self):
        payload = [{'modelId': 'org/space-1', 'sdk': 'gradio', 'likes': 5}]
        items = normalize_hf(payload, gh_source(id='hf-spaces', kind='hf'), NOW)
        assert items[0]['url'] == 'https://huggingface.co/spaces/org/space-1'
        assert items[0]['metricLabel'] == 'likes'


# ---------------------------------------------------------------------------
# fetch_text (fake platform fetch monkeypatched onto collector._http_fetch)


class FakeResponse:
    def __init__(self, status=200, text='{}', headers=None):
        self.status = status
        self._text = text
        self.headers = headers or {}

    async def text(self):
        return self._text


def install_fetch(monkeypatch, responses):
    calls = []
    queue = list(responses)

    async def fake_fetch(url, init):
        calls.append(url)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(collector, '_http_fetch', fake_fetch)
    return calls


async def _no_sleep(seconds):
    pass


class TestFetchText:
    def test_ok(self, monkeypatch):
        install_fetch(monkeypatch, [FakeResponse(200, 'hello')])
        assert run(collector.fetch_text('https://a.com', sleep=_no_sleep)) == 'hello'

    def test_retry_then_ok(self, monkeypatch):
        install_fetch(monkeypatch, [
            FakeResponse(500), FakeResponse(200, 'good'),
        ])
        assert run(collector.fetch_text('https://a.com', sleep=_no_sleep)) == 'good'

    def test_429_with_huge_retry_after_is_final(self, monkeypatch):
        install_fetch(monkeypatch, [FakeResponse(429, headers={'retry-after': '3600'})])
        with pytest.raises(FetchError):
            run(collector.fetch_text('https://a.com', sleep=_no_sleep))

    def test_oversize_rejected_without_retry(self, monkeypatch):
        install_fetch(monkeypatch, [FakeResponse(200, 'x' * (collector.MAX_BYTES + 1))])
        with pytest.raises(FetchError):
            run(collector.fetch_text('https://a.com', sleep=_no_sleep))


# ---------------------------------------------------------------------------
# run_collection — write semantics against the sqlite double


def seed_item(env, item_id, source_id, published_at, collected_at='2025-09-01T00:00:00.000Z'):
    from db import db_batch

    run(db_batch(env, [
        ("INSERT OR IGNORE INTO sources (id, name, homepage, status, item_count) VALUES (?, 'n', 'https://s.com', 'ok', 1)",
         (source_id,)),
        ('INSERT INTO items (id, title, url, source_id, source_name, collected_at, published_at, item_ts, rank_score) '
         "VALUES (?, 'old', ?, ?, 'n', ?, ?, 1, 50)", (item_id, 'https://old.com/' + item_id, source_id, collected_at, published_at)),
    ]))


def patch_sources(monkeypatch, sources):
    monkeypatch.setattr(collector, 'build_sources', lambda now_ms=None: sources)


def patch_fetch(monkeypatch, payloads):
    async def fake_fetch(url, headers=None):
        for prefix, payload in payloads.items():
            if url.startswith(prefix):
                return payload
        raise FetchError('no payload for ' + url)

    monkeypatch.setattr(collector, 'fetch_text', fake_fetch)


class TestCollectSource:
    def test_org_bare_list_is_wrapped(self, d1, monkeypatch):
        from collector import collect_source

        async def fake_fetch(url, headers=None):
            return json.dumps([repo('one', pushed_at='2025-10-05T00:00:00Z')])

        monkeypatch.setattr(collector, 'fetch_text', fake_fetch)
        items = run(collect_source(
            make_env(d1),
            gh_source(id='cn-official-x', kind='github-org', url='https://api.github.com/orgs/x/repos'),
            NOW,
        ))
        assert len(items) == 1
        assert items[0]['id'] == collector.item_id('https://github.com/org/one')


class TestMetricPrev:
    def test_second_pass_carries_previous_metric(self, d1, monkeypatch):
        env = make_env(d1)
        payloads = {'https://api.github.com/search': json.dumps({'items': [repo('one')]})}
        patch_sources(monkeypatch, [gh_source()])
        patch_fetch(monkeypatch, payloads)

        run(run_collection(env, now_ms=NOW_MS))
        row = run(db_all(env, 'SELECT metric_value, metric_prev FROM items'))[0]
        assert row['metric_value'] == 100 and row['metric_prev'] is None  # first sighting

        payloads['https://api.github.com/search'] = json.dumps(
            {'items': [repo('one', stargazers_count=180)]}
        )
        run(run_collection(env, now_ms=NOW_MS))
        row = run(db_all(env, 'SELECT metric_value, metric_prev FROM items'))[0]
        assert row['metric_value'] == 180 and row['metric_prev'] == 100  # delta +80

    def test_rss_items_never_get_metric_prev(self, d1, monkeypatch):
        env = make_env(d1)
        patch_sources(monkeypatch, [rss_source()])
        patch_fetch(monkeypatch, {'https://www.qbitai.com/feed': RSS})
        run(run_collection(env, now_ms=NOW_MS))
        rows = run(db_all(env, 'SELECT metric_prev FROM items'))
        assert rows and all(row['metric_prev'] is None for row in rows)

    def test_param_budget_under_d1_cap(self):
        assert len(collector._ITEM_COLUMNS) * collector._ITEM_ROWS_PER_STMT <= 100


class TestRunCollection:
    def test_rss_success_replaces_out_of_window(self, d1, monkeypatch):
        env = make_env(d1)
        source = rss_source()
        patch_sources(monkeypatch, [source])
        patch_fetch(monkeypatch, {'https://www.qbitai.com/feed': RSS})
        seed_item(env, 'fresh-in-window', 'qbitai', '2025-10-05T00:00:00.000Z')
        seed_item(env, 'too-old', 'qbitai', '2025-08-01T00:00:00.000Z')

        status = run(run_collection(env, now_ms=NOW_MS))
        assert status['ok'] == 1
        rows = run(db_all(env, 'SELECT id FROM items WHERE source_id = ? ORDER BY id', ('qbitai',)))
        ids = {row['id'] for row in rows}
        # RSS gave 2 fresh (1 + no-date), plus the kept in-window old row; the August row is gone.
        assert 'too-old' not in ids
        assert 'fresh-in-window' in ids
        assert collector.item_id('https://a.com/1') in ids
        source_row = run(db_all(env, 'SELECT * FROM sources WHERE id = ?', ('qbitai',)))[0]
        assert source_row['status'] == 'ok'
        assert source_row['item_count'] == len(ids)
        assert run(get_meta(env, 'generated_at'))

    def test_github_full_replace(self, d1, monkeypatch):
        env = make_env(d1)
        source = gh_source()
        patch_sources(monkeypatch, [source])
        payload = json.dumps({'items': [repo('one'), repo('two')]})
        patch_fetch(monkeypatch, {'https://api.github.com/search': payload})
        seed_item(env, 'stale-gh', 'github-projects', '2025-10-01T00:00:00.000Z')

        status = run(run_collection(env, now_ms=NOW_MS))
        assert status['ok'] == 1
        ids = {row['id'] for row in run(db_all(env, 'SELECT id FROM items'))}
        assert 'stale-gh' not in ids
        assert collector.item_id('https://github.com/org/one') in ids
        cats = run(db_all(env, 'SELECT category FROM item_categories'))
        assert all(row['category'] == 'projects' for row in cats)

    def test_failure_downgrades_and_keeps_rows(self, d1, monkeypatch):
        env = make_env(d1)
        patch_sources(monkeypatch, [rss_source()])
        patch_fetch(monkeypatch, {})
        seed_item(env, 'keep-me', 'qbitai', '2025-10-05T00:00:00.000Z')
        run(set_meta(env, 'generated_at', '2025-10-01T00:00:00.000Z'))

        status = run(run_collection(env, now_ms=NOW_MS))
        assert status['ok'] == 0 and status['failed'] == 1
        assert run(db_all(env, "SELECT id FROM items WHERE id = 'keep-me'"))
        source_row = run(db_all(env, 'SELECT * FROM sources'))[0]
        assert source_row['status'] == 'error' and source_row['error']
        assert run(get_meta(env, 'generated_at')) == '2025-10-01T00:00:00.000Z'  # untouched on total failure

    def test_global_cap_500(self, d1, monkeypatch):
        from db import chunk, db_batch

        env = make_env(d1)
        patch_sources(monkeypatch, [gh_source()])
        payload = json.dumps({'items': [repo('r%03d' % i) for i in range(120)]})
        patch_fetch(monkeypatch, {'https://api.github.com/search': payload})

        statements = [
            ("INSERT INTO sources (id, name, homepage, status, item_count) "
             "VALUES ('old-src', 'n', 'https://s.com', 'ok', 420)", ()),
        ]
        rows = [('https://old.com/%d' % i, 1700000000000 + i * 1000) for i in range(420)]
        for group in chunk(rows, 50):
            statements.append(
                ('INSERT INTO items (id, title, url, source_id, source_name, collected_at, item_ts, rank_score) VALUES '
                 + ','.join("(?, 'old', ?, 'old-src', 'n', '2025-09-01T00:00:00.000Z', ?, 50)" for _ in group),
                 tuple(v for url, ts in group for v in (collector.item_id(url), url, ts))),
            )
        run(db_batch(env, statements))

        status = run(run_collection(env, now_ms=NOW_MS))
        assert status['ok'] == 1
        total = run(db_all(env, 'SELECT COUNT(*) AS n FROM items'))[0]['n']
        assert total <= 500

    def test_cursor_batching(self, d1, monkeypatch):
        env = make_env(d1, COLLECT_SOURCES_PER_RUN='2')
        sources = [rss_source(id='s%d' % i) for i in range(5)]
        patch_sources(monkeypatch, sources)
        seen = []

        async def fake_fetch(url, headers=None):
            seen.append(url)
            raise FetchError('offline')

        monkeypatch.setattr(collector, 'fetch_text', fake_fetch)
        run(run_collection(env))
        assert len(seen) == 2
        assert run(get_meta(env, 'collect_cursor')) == '2'
        run(run_collection(env))
        assert run(get_meta(env, 'collect_cursor')) == '4'
        run(run_collection(env))
        assert run(get_meta(env, 'collect_cursor')) == '1'  # wraps

    def test_only_subset(self, d1, monkeypatch):
        env = make_env(d1)
        patch_sources(monkeypatch, [rss_source(), gh_source()])
        patch_fetch(monkeypatch, {'https://www.qbitai.com/feed': RSS})
        status = run(run_collection(env, only=['qbitai']))
        assert [s['id'] for s in status['sources']] == ['qbitai']
