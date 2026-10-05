"""RSS 2.0 — full-site feed at /rss (+ /rss.xml alias), hand-built XML.

Every dynamic value goes through html.escape (quote=True) — text nodes and
attribute positions share one paranoid path. Dates are RFC 822 via
email.utils.format_datetime(..., usegmt=True), which is locale-free.
"""
import html
from datetime import datetime, timezone
from email.utils import format_datetime

from db import db_all, get_meta
from util import epoch_ms

SITE_TITLE = 'signal. AI 日报'
SITE_DESC = '每天 08:05（北京时间）出刊的 AI 头版：开源、模型、动态一网打尽'
LANGUAGE = 'zh-cn'
MAX_ITEMS = 50
_HEADERS = [
    ('Content-Type', 'application/rss+xml; charset=utf-8'),
    ('Cache-Control', 'public, max-age=300'),
    ('X-Content-Type-Options', 'nosniff'),
]
_UNREADY_HEADERS = [
    ('Content-Type', 'application/rss+xml; charset=utf-8'),
    ('Cache-Control', 'no-store'),
    ('X-Content-Type-Options', 'nosniff'),
]


def _esc(value):
    return html.escape(value if isinstance(value, str) else '', quote=True)


def _pubdate(item_ts):
    dt = datetime.fromtimestamp((item_ts or 0) / 1000, tz=timezone.utc)
    return format_datetime(dt, usegmt=True)


def build_rss(origin, generated_at, rows):
    """Pure builder. rows = [{title,url,summary,sourceName,itemTs}], newest first."""
    def item_xml(row):
        title = _esc(row.get('title') or '(untitled)')
        link = _esc(row.get('url') or '')
        summary = _esc((row.get('summary') or '')[:300])
        parts = [
            '<item>',
            '<title>' + title + '</title>',
            '<link>' + link + '</link>',
            '<guid isPermaLink="true">' + link + '</guid>',
            '<description>' + summary + '</description>',
        ]
        if row.get('sourceName'):
            parts.append('<category>' + _esc(row['sourceName']) + '</category>')
        parts.append('<pubDate>' + _pubdate(row.get('itemTs')) + '</pubDate>')
        parts.append('</item>')
        return ''.join(parts)

    built = epoch_ms(generated_at)
    channel = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        '<channel>',
        '<title>' + _esc(SITE_TITLE) + '</title>',
        '<link>' + _esc(origin) + '</link>',
        '<description>' + _esc(SITE_DESC) + '</description>',
        '<language>' + LANGUAGE + '</language>',
        '<lastBuildDate>' + _pubdate(built) + '</lastBuildDate>',
    ]
    channel.extend(item_xml(row) for row in rows[:MAX_ITEMS])
    channel.extend(('</channel>', '</rss>'))
    return '\n'.join(channel)


async def handle_rss(env, origin):
    generated_at = await get_meta(env, 'generated_at')
    if not generated_at:
        return {
            'status': 503,
            'headers': list(_UNREADY_HEADERS),
            'body': '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
                    '<title>' + _esc(SITE_TITLE) + '</title></channel></rss>',
        }
    rows = await db_all(
        env,
        'SELECT title, url, summary, source_name, item_ts FROM items '
        'ORDER BY item_ts DESC, rank_score DESC, id ASC LIMIT ?',
        (MAX_ITEMS,),
    )
    items = [{
        'title': row['title'],
        'url': row['url'],
        'summary': row['summary'],
        'sourceName': row['source_name'],
        'itemTs': row['item_ts'],
    } for row in rows]
    return {'status': 200, 'headers': list(_HEADERS), 'body': build_rss(origin, generated_at, items)}
