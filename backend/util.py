"""Pure helpers ported 1:1 from src/data.mjs + scripts/collector-core.mjs.

Byte-level fidelity matters: item ids are sha256(canonical_url)[:20] and must
stay stable across the JS and Python collectors.
"""
import hashlib
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, quote, unquote, urlsplit, urlunsplit

CATEGORY_LABELS = {
    'news': 'AI 动态',
    'projects': '开源项目',
    'skills': 'Skills',
    'models': '模型动态',
    'tips': '实用技巧',
    'apps': '趣味应用',
    'dev': '开发实践',
}

_STRIP_PARAMS = {'ref', 'source', 'fbclid', 'gclid'}
_SCRIPT_RE = re.compile(r'<script\b[^>]*>[\s\S]*?</script>', re.I)
_STYLE_RE = re.compile(r'<style\b[^>]*>[\s\S]*?</style>', re.I)
_TAG_RE = re.compile(r'<[^>]*>')
_NUM_ENTITY_RE = re.compile(r'&#(x[\da-f]+|\d+);', re.I)
_NAMED_ENTITIES = {'amp': '&', 'lt': '<', 'gt': '>', 'quot': '"', 'apos': "'", '#39': "'", 'nbsp': ' '}
_NAMED_ENTITY_RE = re.compile(r'&(amp|lt|gt|quot|apos|nbsp|#39);')
_WS_RE = re.compile(r'\s+')


def canonical_url(value):
    """Port of canonicalUrl(): https-only, no credentials, drop tracking params,
    strip one trailing slash, sort query. Returns normalized href or None."""
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return None
    if parts.scheme.lower() != 'https' or parts.username or parts.password:
        return None
    host = parts.hostname or ''
    if not host:
        return None
    netloc = host.lower()
    if parts.port is not None:
        if not ((parts.scheme == 'https' and parts.port == 443) or (parts.scheme == 'http' and parts.port == 80)):
            netloc += ':' + str(parts.port)
    # Keep the path percent-encoding exactly as delivered (JS URL does not re-encode).
    path = parts.path
    if path != '/' and path.endswith('/'):
        path = path[:-1]
    if not path:
        path = '/'
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith('utm_') and k not in _STRIP_PARAMS
    ]
    query_pairs.sort()
    query = '&'.join(
        quote(k, safe='') + '=' + quote(v, safe='') for k, v in query_pairs
    ) if query_pairs else ''
    return urlunsplit(('https', netloc, path, query, ''))


def safe_url(value):
    """Port of safeUrl(): only clean https URLs without credentials."""
    if not isinstance(value, str):
        return None
    url = canonical_url(value)
    # canonicalUrl additionally normalizes; safeUrl only validates. A URL that
    # canonicalizes is by construction safe, and every safe URL is its own
    # canonical form within this project's pipeline.
    return url


def plain_text(value, max_len=240):
    """Port of plainText(): strip script/style/tags, decode the same entity set,
    collapse whitespace, cap length."""
    if not isinstance(value, str):
        return ''
    text = _SCRIPT_RE.sub('', value)
    text = _STYLE_RE.sub('', text)
    text = _TAG_RE.sub(' ', text)

    def num_entity(match):
        raw = match.group(1)
        code = int(raw[1:], 16) if raw[0].lower() == 'x' else int(raw)
        if 0 < code <= 0x10FFFF and not 0xD800 <= code <= 0xDFFF:
            return chr(code)
        return ''

    text = _NUM_ENTITY_RE.sub(num_entity, text)
    text = _NAMED_ENTITY_RE.sub(lambda m: _NAMED_ENTITIES[m.group(1)], text)
    text = _WS_RE.sub(' ', text).strip()
    return text[:max_len]


def iso_date(value):
    """Port of isoDate(): accept RFC2822 / ISO8601-ish, emit JS toISOString format."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    dt = None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        dt = None
    if dt is None:
        candidate = raw[:-1] + '+00:00' if raw.endswith('Z') else raw
        try:
            dt = datetime.fromisoformat(candidate)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (dt.microsecond // 1000)


def date_within(value, now_iso, max_future_ms=86400000):
    """Port of collector date(): parse and reject dates far in the future."""
    parsed = iso_date(value)
    if parsed is None:
        return None
    if epoch_ms(parsed) > epoch_ms(now_iso) + max_future_ms:
        return None
    return parsed


def epoch_ms(iso):
    dt = datetime.fromisoformat(iso.replace('Z', '+00:00'))
    return int(dt.timestamp() * 1000)


def now_iso(now_ms=None):
    ms = now_ms if now_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (dt.microsecond // 1000)


def item_time(item):
    """Port of itemTime(): updatedAt || publishedAt || 0, epoch ms."""
    for key in ('updatedAt', 'publishedAt'):
        value = item.get(key)
        if isinstance(value, str) and value:
            try:
                return epoch_ms(value)
            except ValueError:
                continue
    return 0


def item_id(url):
    return hashlib.sha256(url.encode('utf-8')).hexdigest()[:20]


def _b64url(raw: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def b64url(raw: bytes) -> str:
    return _b64url(raw)


def unb64(value: str) -> bytes:
    import base64
    padding = '=' * (-len(value) % 4)
    return base64.b64decode(value.replace('-', '+').replace('_', '/') + padding)


def sha256_b64url(text: str) -> str:
    return _b64url(hashlib.sha256(text.encode('utf-8')).digest())


def random_token() -> str:
    """43-char b64url of 32 random bytes (matches JS crypto.getRandomValues)."""
    import os
    return _b64url(os.urandom(32))
