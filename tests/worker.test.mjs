import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { handleRequest, syncSnapshot } from '../worker/index.mjs';
const fixture = JSON.parse(
  await readFile(new URL('../public/data/feed.json', import.meta.url), 'utf8'),
);
function environment() {
  const data = new Map([
    [
      'feed:latest',
      { value: JSON.stringify(fixture), metadata: { generatedAt: fixture.generatedAt } },
    ],
  ]);
  return {
    data,
    FEED_URL: 'https://example.com/feed.json',
    NEWS: {
      async getWithMetadata(key) {
        return data.get(key) || { value: null, metadata: null };
      },
      async get(key, type) {
        const v = data.get(key)?.value || null;
        return type === 'json' && v ? JSON.parse(v) : v;
      },
      async put(key, value, options) {
        data.set(key, { value, metadata: options?.metadata });
      },
    },
    ASSETS: { fetch: async () => new Response('static') },
  };
}
const req = (path, method = 'GET') => new Request('https://example.com' + path, { method });
test('public API feed, pagination, filters, health, sources and assets', async () => {
  const env = environment();
  assert.equal(
    (await (await handleRequest(req('/api/feed'), env)).json()).items.length,
    fixture.items.length,
  );
  const list = await (
    await handleRequest(req('/api/items?category=models&limit=2&chinaOnly=true'), env)
  ).json();
  assert.ok(list.items.length <= 2);
  assert.ok(list.items.every((i) => i.categories.includes('models')));
  assert.equal(
    (await (await handleRequest(req('/api/sources'), env)).json()).sources.length,
    fixture.sources.length,
  );
  assert.equal(
    (await (await handleRequest(req('/api/health'), env)).json()).itemCount,
    fixture.items.length,
  );
  assert.equal(await (await handleRequest(req('/'), env)).text(), 'static');
  assert.equal(await (await handleRequest(req('/api/feed', 'HEAD'), env)).text(), '');
});
test('reject invalid queries, writes, missing routes and uninitialized snapshots', async () => {
  const env = environment();
  for (const query of [
    'page=-1',
    'limit=101',
    'days=NaN',
    'category=unknown',
    'sort=random',
    'chinaOnly=1',
  ])
    assert.equal((await handleRequest(req('/api/items?' + query), env)).status, 400);
  assert.equal((await handleRequest(req('/api/feed', 'POST'), env)).status, 405);
  assert.equal((await handleRequest(req('/api/admin'), env)).status, 404);
  env.data.clear();
  assert.equal((await handleRequest(req('/api/feed'), env)).status, 503);
});
test('cron advances snapshot, never rolls back and preserves data on upstream errors', async () => {
  const env = environment();
  const newer = { ...fixture, generatedAt: new Date().toISOString() };
  await syncSnapshot(env, async () => Response.json(newer));
  const saved = env.data.get('feed:latest').value;
  assert.equal(JSON.parse(saved).generatedAt, newer.generatedAt);
  await syncSnapshot(env, async () => Response.json(fixture));
  assert.equal(env.data.get('feed:latest').value, saved);
  for (const response of [
    new Response('', { status: 503 }),
    Response.json({}),
    new Response('x'.repeat(2 * 1024 * 1024 + 1)),
    Response.json({ ...newer, items: [] }),
  ]) {
    await assert.rejects(syncSnapshot(env, async () => response));
    assert.equal(env.data.get('feed:latest').value, saved);
    assert.equal(JSON.parse(env.data.get('sync:status').value).ok, false);
  }
});
