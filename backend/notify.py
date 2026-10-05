"""Daily digest email — best-effort, never blocks collection.

Sent through Resend's HTTP API: Python Workers have no raw TCP, so SMTP
(QQ mailbox etc.) is not reachable from this worker. The feature turns on
only when both RESEND_API_KEY and MAIL_TO secrets exist; otherwise
send_daily_report() is a silent no-op.
"""
import json
from datetime import datetime, timedelta, timezone
from html import escape

import collector
from db import db_all, db_first, env_get, get_meta
from util import epoch_ms, iso_date

RESEND_URL = 'https://api.resend.com/emails'
FROM = 'signal. AI 日报 <onboarding@resend.dev>'
BEIJING_MS = 8 * 3600000


def _bj(value):
    """ISO timestamp → 'MM-DD HH:MM' in Beijing time (em dash when absent)."""
    parsed = iso_date(value)
    if not parsed:
        return '—'
    dt = datetime.fromtimestamp((epoch_ms(parsed) + BEIJING_MS) / 1000, tz=timezone.utc)
    return dt.strftime('%m-%d %H:%M')


def build_report(rows, total_items, generated_at, now_ms, *,
                 editor_note=None, followed=None, weekly=None):
    """Compose (subject, text, html) from a sources-table snapshot. Pure, testable."""
    ok_rows = [r for r in rows if r.get('status') == 'ok']
    failed = [r for r in rows if r.get('status') != 'ok']
    date = datetime.fromtimestamp((now_ms + BEIJING_MS) / 1000, tz=timezone.utc)
    day = date.strftime('%m-%d')

    subject = (
        'signal. 日报 ' + day + '：' + str(len(ok_rows)) + '/' + str(len(rows))
        + ' 成功，' + str(total_items) + ' 条信号'
    )
    lines = [
        'signal. 采集日报 ' + day,
        '结果：' + str(len(ok_rows)) + ' 成功 / ' + str(len(failed)) + ' 失败，共 '
        + str(total_items) + ' 条信号',
        '快照生成：' + _bj(generated_at) + '（北京时间）',
    ]
    if editor_note:
        lines += ['', '编者按：' + editor_note]
    lines += ['', '来源状态：']
    for row in rows:
        lines.append(
            '- ' + str(row.get('name') or row.get('id'))
            + '：' + ('ok' if row.get('status') == 'ok' else '失败')
            + '，' + str(row.get('item_count') or 0) + ' 条'
            + '，最近成功 ' + _bj(row.get('last_success_at'))
        )
    lines.append('')
    if failed:
        lines.append('失败详情：')
        for row in failed:
            lines.append('- ' + str(row.get('name') or row.get('id')) + '：' + str(row.get('error') or '未知错误'))
    else:
        lines.append('失败详情：无。')
    if followed:
        lines += ['', '关注命中（近 24 小时）：']
        lines += ['- ' + item['title'] + '（' + item['sourceName'] + '）' for item in followed]
    if weekly:
        lines += ['', '上周回顾：']
        lines += ['- ' + day_row['date'] + '：' + str(day_row['count']) + ' 条' for day_row in weekly['days']]
        if weekly.get('headlines'):
            lines.append('上周同日头条：' + ' / '.join(weekly['headlines']))
    return subject, '\n'.join(lines), _report_html(
        day, rows, ok_rows, failed, total_items, generated_at,
        editor_note=editor_note, followed=followed, weekly=weekly,
    )


# Palette mirrors src/tokens.css (light) so the digest reads as the same product.
_PAPER = '#f7f8fa'
_CARD = '#ffffff'
_INK = '#222823'
_MUTED = '#626b62'
_LINE = '#e5e8e3'
_GREEN = '#427154'
_GREEN_SOFT = '#eef1e9'
_FEATURE = '#203e32'
_AMBER = '#8a6d3b'
_AMBER_SOFT = '#f6f0e3'
_BASE_FONT = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif"
)


def _editor_note_html(text):
    return (
        '<tr><td style="padding:16px 28px 0;"><div style="border-left:3px solid ' + _GREEN
        + ';background:' + _GREEN_SOFT + ';padding:12px 16px;border-radius:0 6px 6px 0;'
        'font-size:13px;line-height:1.8;color:' + _INK + ';">'
        '<span style="font-weight:700;color:' + _GREEN + ';">编者按　</span>'
        + escape(text) + '</div></td></tr>'
    )


def _followed_html(items):
    rows = ''.join(
        '<div style="font-size:12px;line-height:1.9;color:' + _INK + ';">'
        '<a href="' + escape(item['url']) + '" style="color:' + _INK + ';text-decoration:none;">'
        + escape(item['title']) + '</a>'
        '<span style="color:' + _MUTED + ';">　' + escape(item['sourceName']) + '</span></div>'
        for item in items
    )
    return (
        '<tr><td style="padding:4px 28px;"><div style="margin-top:8px;border-top:1px solid ' + _LINE
        + ';padding-top:12px;"><div style="font-size:12px;font-weight:700;color:' + _GREEN
        + ';margin-bottom:4px;">关注命中 · 近 24 小时</div>' + rows + '</div></td></tr>'
    )


def _weekly_html(weekly):
    day_cells = ''.join(
        '<td style="padding:6px 0;text-align:center;width:14%;">'
        '<div style="font-size:15px;font-weight:700;color:' + _INK + ';">' + str(day_row['count']) + '</div>'
        '<div style="font-size:10px;color:' + _MUTED + ';">' + escape(day_row['date'][5:]) + '</div></td>'
        for day_row in weekly['days']
    )
    headlines = ''
    if weekly.get('headlines'):
        headlines = (
            '<div style="font-size:12px;line-height:1.8;color:' + _MUTED + ';margin-top:8px;">'
            '上周同日头条：' + ' / '.join(escape(title) for title in weekly['headlines']) + '</div>'
        )
    return (
        '<tr><td style="padding:4px 28px 26px;"><div style="margin-top:8px;border-top:1px solid ' + _LINE
        + ';padding-top:12px;"><div style="font-size:12px;font-weight:700;color:' + _INK
        + ';margin-bottom:6px;">上周回顾</div>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>' + day_cells
        + '</tr></table>' + headlines + '</div></td></tr>'
    )


def _report_html(day, rows, ok_rows, failed, total_items, generated_at, *,
                 editor_note=None, followed=None, weekly=None):
    stats = (
        ('成功', str(len(ok_rows)), _GREEN if ok_rows else _AMBER),
        ('失败', str(len(failed)), _AMBER if failed else _MUTED),
        ('信号总数', str(total_items), _INK),
    )
    stat_cells = ''.join(
        '<td style="padding:14px 0;text-align:center;width:33%;">'
        '<div style="font-size:24px;font-weight:700;line-height:1.2;color:' + color + ';">' + value + '</div>'
        '<div style="font-size:11px;color:' + _MUTED + ';margin-top:3px;">' + label + '</div></td>'
        for label, value, color in stats
    )
    source_rows = ''.join(
        '<tr>'
        '<td style="padding:9px 0;border-bottom:1px solid ' + _LINE + ';font-size:13px;color:' + _INK + ';">'
        + escape(str(row.get('name') or row.get('id'))) + '</td>'
        '<td style="padding:9px 0;border-bottom:1px solid ' + _LINE + ';text-align:right;white-space:nowrap;">'
        '<span style="font-size:11px;padding:2px 8px;border-radius:6px;'
        + ('background:' + _GREEN_SOFT + ';color:' + _GREEN + ';">ok' if row.get('status') == 'ok'
           else 'background:' + _AMBER_SOFT + ';color:' + _AMBER + ';">失败')
        + '</span>'
        '<span style="font-size:11px;color:' + _MUTED + ';"> '
        + str(row.get('item_count') or 0) + ' 条 · ' + _bj(row.get('last_success_at')) + '</span></td>'
        '</tr>'
        for row in rows
    )
    if failed:
        failure_html = ''.join(
            '<div style="font-size:12px;line-height:1.9;color:' + _AMBER + ';">'
            + escape(str(row.get('name') or row.get('id'))) + '：'
            + escape(str(row.get('error') or '未知错误')) + '</div>'
            for row in failed
        )
        failure_block = (
            '<tr><td style="padding:4px 28px 26px;"><div style="border-left:3px solid ' + _AMBER
            + ';background:' + _AMBER_SOFT + ';padding:12px 16px;border-radius:0 6px 6px 0;">'
            '<div style="font-size:12px;font-weight:700;color:' + _AMBER + ';margin-bottom:4px;">失败详情</div>'
            + failure_html + '</div></td></tr>'
        )
    else:
        failure_block = (
            '<tr><td style="padding:4px 28px 26px;font-size:12px;color:' + _MUTED + ';">'
            '全部来源采集正常。</td></tr>'
        )
    return (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width"></head>'
        '<body style="margin:0;padding:24px;background:' + _PAPER + ';font-family:' + _BASE_FONT + ';">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;margin:0 auto;">'
        '<tr><td style="background:' + _FEATURE + ';border-radius:10px 10px 0 0;padding:20px 28px;">'
        '<div style="font-size:16px;font-weight:700;color:#f0f4ed;letter-spacing:0.3px;">signal. 采集日报</div>'
        '<div style="font-size:11px;color:#b9cabc;margin-top:5px;">'
        + day + ' · 快照生成 ' + _bj(generated_at) + '（北京时间）</div></td></tr>'
        '<tr><td style="background:' + _CARD + ';border:1px solid ' + _LINE + ';border-top:0;'
        'border-radius:0 0 10px 10px;padding:0 28px;">'
        + (_editor_note_html(editor_note) if editor_note else '') +
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="border-bottom:3px double ' + _INK + ';">'  # 报头双线，与主站要目卡同一母题
        '<tr>' + stat_cells + '</tr></table>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
        + source_rows + '</table>'
        + (_followed_html(followed) if followed else '')
        + failure_block
        + (_weekly_html(weekly) if weekly else '') +
        '</td></tr>'
        '<tr><td style="text-align:center;padding:16px 0 4px;font-size:11px;color:' + _MUTED + ';">'
        '此邮件由 signal. AI 日报自动发送 · No hype, just signal.</td></tr>'
        '</table></body></html>'
    )


async def _last_week(env, now_ms):
    """Monday-only recap from daily_snapshots: per-day counts + the top
    headlines of exactly one week ago."""
    bj = datetime.fromtimestamp((now_ms + BEIJING_MS) / 1000, tz=timezone.utc)
    if bj.weekday() != 0:
        return None
    start = (bj - timedelta(days=7)).strftime('%Y-%m-%d')
    end = (bj - timedelta(days=1)).strftime('%Y-%m-%d')
    days = []
    for row in await db_all(
        env,
        'SELECT date, payload FROM daily_snapshots WHERE date >= ? AND date <= ? ORDER BY date',
        (start, end),
    ):
        try:
            count = (json.loads(row['payload']).get('stats') or {}).get('items') or 0
        except ValueError:
            count = 0
        days.append({'date': row['date'], 'count': count})
    headlines = []
    row = await db_first(env, 'SELECT payload FROM daily_snapshots WHERE date = ?', (start,))
    if row:
        try:
            headlines = [item['title'] for item in (json.loads(row['payload']).get('lead') or [])[:3]]
        except (ValueError, KeyError, TypeError):
            headlines = []
    return {'days': days, 'headlines': headlines} if days or headlines else None


async def send_daily_report(env, now_ms=None):
    """POST the digest via Resend. Returns {'ok': bool} or None when disabled."""
    api_key = env_get(env, 'RESEND_API_KEY')
    recipient = env_get(env, 'MAIL_TO')
    if not api_key or not recipient:
        return None
    now_ms = now_ms if now_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)

    rows = await db_all(
        env,
        'SELECT id, name, status, last_success_at, item_count, error FROM sources ORDER BY id',
    )
    total = await db_all(env, 'SELECT COUNT(*) AS n FROM items')

    # Editor's note was just generated by digest.run_digest for this edition.
    note_raw = await get_meta(env, 'editor_note')
    try:
        note = json.loads(note_raw) if note_raw else None
    except ValueError:
        note = None

    # 关注命中 — single-user site: the whole followed_tags table is one person.
    followed = None
    tags = [row['tag'] for row in await db_all(env, 'SELECT tag FROM followed_tags')]
    if tags:
        followed = [
            {'title': row['title'], 'url': row['url'], 'sourceName': row['source_name']}
            for row in await db_all(
                env,
                'SELECT title, url, source_name FROM items WHERE item_ts >= ? AND EXISTS ('
                'SELECT 1 FROM item_tags t WHERE t.item_id = items.id AND t.tag IN ('
                + ','.join('?' * len(tags)) + ')) ORDER BY item_ts DESC LIMIT 5',
                (now_ms - 86400000, *tags),
            )
        ]

    subject, text, html = build_report(
        rows, total[0]['n'] if total else 0, await get_meta(env, 'generated_at'), now_ms,
        editor_note=(note or {}).get('text') or None,
        followed=followed,
        weekly=await _last_week(env, now_ms),
    )

    response = await collector._http_fetch(RESEND_URL, {
        'method': 'POST',
        'timeoutMs': 15000,
        'headers': {
            'Authorization': 'Bearer ' + api_key,
            'Content-Type': 'application/json',
        },
        'body': json.dumps(
            {'from': FROM, 'to': [recipient], 'subject': subject, 'text': text, 'html': html},
            ensure_ascii=False,
        ),
    })
    status = int(response.status)
    text = await response.text()
    if status not in (200, 201):
        raise RuntimeError('Resend HTTP ' + str(status) + ': ' + text[:200])
    return {'ok': True, 'to': recipient, 'subject': subject}
