"""Shared fixtures: D1 double + env stub + asyncio driver (no plugin needed)."""
import asyncio
import sys
from pathlib import Path

import pytest

from d1shim import D1

ROOT = Path(__file__).resolve().parents[2]
# Backend modules are flat top-level modules (Cloudflare loads entry.py that
# way), so tests import them the same way: api, util, collector, ...
sys.path.insert(0, str(ROOT / 'backend'))
SCHEMA = (ROOT / 'migrations' / '0001_init.sql').read_text(encoding='utf-8')

BASE_ENV = {
    'APP_ORIGIN': 'https://signal.example.com',
    'GITHUB_CLIENT_ID': 'cid',
    'GITHUB_CLIENT_SECRET': 'csecret',
    'SESSION_SECRET': 's' * 48,
    'ADMIN_TOKEN': 'admintoken',
    'COLLECT_SOURCES_PER_RUN': '0',
}


class EnvStub:
    def __init__(self, db, **values):
        self.DB = db
        self._values = values

    def __getattr__(self, name):
        values = object.__getattribute__(self, '_values')
        if name in values:
            return values[name]
        raise AttributeError(name)


def run(coro):
    """Drive async handlers from sync tests."""
    return asyncio.run(coro)


def make_env(db=None, **overrides):
    values = {**BASE_ENV, **overrides}
    for key, value in list(values.items()):
        if value is None:
            del values[key]
    return EnvStub(db, **values)


@pytest.fixture
def d1():
    return D1(SCHEMA)


@pytest.fixture
def env(d1):
    return make_env(d1)
