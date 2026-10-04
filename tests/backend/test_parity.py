"""Parity gate: Python id derivation must match the JS pipeline for every real URL.

public/data/feed.json was produced by the JS collector; if canonical_url or
item_id drifts, these ids stop matching and D1 rows would fork.
"""
import json
from pathlib import Path

from util import canonical_url, item_id

ROOT = Path(__file__).resolve().parents[2]
FEED = json.loads((ROOT / 'public' / 'data' / 'feed.json').read_text(encoding='utf-8'))


def test_ids_survive_python_normalization():
    assert FEED['items'], 'feed.json has no items'
    for entry in FEED['items']:
        canonical = canonical_url(entry['url'])
        assert canonical is not None, entry['url']
        assert canonical == entry['url'], ('URL already canonical in snapshot', entry['url'])
        assert item_id(canonical) == entry['id'], ('id drift', entry['url'], entry['id'])


def test_feed_contract_shape():
    assert FEED['schemaVersion'] == 1
    assert len(FEED['sources']) <= 30
    assert len(FEED['items']) <= 500
