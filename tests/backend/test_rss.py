"""rss — XML shape, escaping, date round-trip, caps, and the 503 guard."""
from email.utils import parsedate_to_datetime

import rss
from conftest import make_env, run
from db import db_run, set_meta
from util import now_iso

NOW_MS = 1759737600000


def seed(env, n=1, title='标题甲', url=None):
    stamp = now_iso(NOW_MS)
    run(set_meta(env, 'generated_at', stamp))
    run(db_run(
        env,
        "INSERT INTO sources (id, name, homepage, status, last_success_at, item_count) "
        "VALUES ('qbitai', '量子位', 'https://q.com', 'ok', NULL, 1)",
        (),
    ))
    for i in range(n):
        run(db_run(
            env,
            "INSERT INTO items (id, title, url, summary, source_id, source_name, collected_at, "
            "item_ts, rank_score) VALUES (?, ?, ?, '摘要', 'qbitai', '量子位', ?, ?, 90)",
            ('i%d' % i, title if n == 1 else '%s %d' % (title, i),
             url or ('https://a.com/%d' % i), stamp, NOW_MS - i * 60000),
        ))
    return stamp


class TestHandleRss:
    def test_shape_and_headers(self, d1):
        env = make_env(d1)
        stamp = seed(env)
        resp = run(rss.handle_rss(env, 'https://signal.example.com'))
        assert resp['status'] == 200
        assert ('Content-Type', 'application/rss+xml; charset=utf-8') in resp['headers']
        assert ('Cache-Control', 'public, max-age=300') in resp['headers']
        xml = resp['body']
        assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
        assert '<rss version="2.0">' in xml
        assert '<title>signal. AI 日报</title>' in xml
        assert '<language>zh-cn</language>' in xml
        assert xml.count('<item>') == 1
        assert '<category>量子位</category>' in xml  # CJK passes through, not entity-mangled
        assert '<guid isPermaLink="true">https://a.com/0</guid>' in xml

    def test_caps_at_fifty(self, d1):
        env = make_env(d1)
        seed(env, n=60)
        xml = run(rss.handle_rss(env, 'https://signal.example.com'))['body']
        assert xml.count('<item>') == rss.MAX_ITEMS

    def test_escapes_hostile_title(self, d1):
        env = make_env(d1)
        seed(env, title='<b>&"quotes"</b>')
        xml = run(rss.handle_rss(env, 'https://signal.example.com'))['body']
        assert '<b>&' not in xml  # raw markup never reaches the document
        assert '&lt;b&gt;&amp;&quot;quotes&quot;&lt;/b&gt;' in xml

    def test_pubdate_round_trip(self, d1):
        import re

        env = make_env(d1)
        seed(env)
        xml = run(rss.handle_rss(env, 'https://signal.example.com'))['body']
        rfc822 = re.search(r'<pubDate>([^<]+)</pubDate>', xml).group(1)
        assert int(parsedate_to_datetime(rfc822).timestamp() * 1000) == NOW_MS

    def test_last_build_date_from_generated_at(self, d1):
        env = make_env(d1)
        seed(env)
        xml = run(rss.handle_rss(env, 'https://signal.example.com'))['body']
        assert '<lastBuildDate>Mon, 06 Oct 2025 08:00:00 GMT</lastBuildDate>' in xml

    def test_empty_db_is_empty_channel(self, d1):
        env = make_env(d1)
        run(set_meta(env, 'generated_at', now_iso(NOW_MS)))
        resp = run(rss.handle_rss(env, 'https://signal.example.com'))
        assert resp['status'] == 200
        assert resp['body'].count('<item>') == 0
        assert resp['body'].rstrip().endswith('</channel>\n</rss>')  # complete document

    def test_uninitialized_503(self, d1):
        env = make_env(d1)
        resp = run(rss.handle_rss(env, 'https://signal.example.com'))
        assert resp['status'] == 503
        assert ('Cache-Control', 'no-store') in resp['headers']
        assert '<item>' not in resp['body']


class TestBuildRss:
    def test_summary_truncated_to_300(self):
        xml = rss.build_rss('https://s.example', now_iso(NOW_MS), [{
            'title': 't', 'url': 'https://a/1', 'summary': 'x' * 500,
            'sourceName': 'S', 'itemTs': NOW_MS,
        }])
        assert 'x' * 300 in xml and 'x' * 301 not in xml

    def test_missing_fields_never_crash(self):
        xml = rss.build_rss('https://s.example', now_iso(NOW_MS), [{}])
        assert '<title>(untitled)</title>' in xml
        assert '<category>' not in xml  # absent sourceName omits the element
        assert '<pubDate>Thu, 01 Jan 1970 00:00:00 GMT</pubDate>' in xml  # itemTs 0
