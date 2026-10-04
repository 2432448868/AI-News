from util import (
    b64url,
    canonical_url,
    date_within,
    epoch_ms,
    iso_date,
    item_id,
    item_time,
    now_iso,
    plain_text,
    unb64,
)


class TestCanonicalUrl:
    def test_drops_tracking_params_and_sorts(self):
        assert canonical_url('https://a.com/p?utm_source=x&b=2&a=1') == 'https://a.com/p?a=1&b=2'

    def test_strips_one_trailing_slash(self):
        assert canonical_url('https://a.com/p/') == 'https://a.com/p'
        assert canonical_url('https://a.com') == 'https://a.com/'

    def test_rejects_http_and_credentials(self):
        assert canonical_url('http://a.com') is None
        assert canonical_url('https://user:pw@a.com') is None
        assert canonical_url('not a url') is None

    def test_keeps_port(self):
        assert canonical_url('https://a.com:8443/p') == 'https://a.com:8443/p'


class TestPlainText:
    def test_strips_tags_and_scripts(self):
        assert plain_text('<script>bad()</script><p>Hello <b>world</b></p>') == 'Hello world'

    def test_decodes_entities(self):
        assert plain_text('a&amp;b&#39;c&#x44;d&nbsp;e') == "a&b'cDd e"

    def test_caps_length(self):
        assert len(plain_text('x' * 500, 240)) == 240

    def test_non_string_returns_empty(self):
        assert plain_text(None) == ''
        assert plain_text(123) == ''


class TestIsoDate:
    def test_rfc2822(self):
        assert iso_date('Mon, 06 Oct 2025 08:00:00 GMT') == '2025-10-06T08:00:00.000Z'

    def test_iso_z(self):
        assert iso_date('2025-10-06T08:00:00Z') == '2025-10-06T08:00:00.000Z'

    def test_invalid(self):
        assert iso_date('garbage') is None
        assert iso_date('') is None
        assert iso_date(None) is None

    def test_naive_treated_as_utc(self):
        assert iso_date('2025-10-06T08:00:00') == '2025-10-06T08:00:00.000Z'


def test_now_iso_roundtrip():
    stamp = now_iso(1759800000123)
    assert stamp == '2025-10-07T01:20:00.123Z'
    assert epoch_ms(stamp) == 1759800000123


def test_date_within_rejects_far_future():
    now = now_iso(1759800000000)
    assert date_within('2025-10-06T00:00:00Z', now) == '2025-10-06T00:00:00.000Z'
    assert date_within('2030-01-01T00:00:00Z', now) is None
    assert date_within('garbage', now) is None


def test_item_time_prefers_updated():
    assert item_time({'updatedAt': '2025-10-06T00:00:00.000Z',
                      'publishedAt': '2025-10-01T00:00:00.000Z'}) == 1759708800000
    assert item_time({'publishedAt': '2025-10-01T00:00:00.000Z'}) == 1759276800000
    assert item_time({}) == 0


def test_item_id_is_sha256_prefix():
    assert item_id('https://a.com/x') == item_id('https://a.com/x')
    assert len(item_id('https://a.com/x')) == 20


def test_b64url_roundtrip():
    raw = b'\xff\xfe\x00abc'
    assert unb64(b64url(raw)) == raw
