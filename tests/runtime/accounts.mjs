// Real local workerd + SQLite-backed Durable Objects. GitHub is a deterministic mock.
import assert from 'node:assert/strict';
import { Miniflare, Response, convertV4MiniflareOptions } from 'miniflare';
import { fileURLToPath } from 'node:url';
const origin = 'https://example.com';
const mf = new Miniflare(
  convertV4MiniflareOptions({
    modulesRoot: fileURLToPath(new URL('../../', import.meta.url)),
    modules: [
      'worker/index.mjs',
      'worker/auth.mjs',
      'worker/accounts.mjs',
      'src/data.mjs',
      'src/topics.mjs',
    ].map((path) => ({
      type: 'ESModule',
      path: fileURLToPath(new URL('../../' + path, import.meta.url)),
    })),
    compatibilityDate: '2026-10-03',
    bindings: {
      APP_ORIGIN: origin,
      GITHUB_CLIENT_ID: 'runtime-test',
      GITHUB_CLIENT_SECRET: 'test-only',
      SESSION_SECRET: 'runtime-test-only-secret-at-least-32-characters',
    },
    kvNamespaces: ['NEWS'],
    durableObjects: { USERS: { className: 'UserAccount', useSQLite: true } },
    outboundService: async (request) => {
      if (request.url === 'https://github.com/login/oauth/access_token')
        return Response.json({ access_token: 'local-test-only', token_type: 'bearer' });
      if (request.url === 'https://api.github.com/user')
        return Response.json({ id: 123, login: 'runtime-reader', name: 'Runtime Reader' });
      throw new Error('Unexpected external request: ' + request.url);
    },
  }),
);
try {
  const news = await mf.getKVNamespace('NEWS');
  await news.put('feed:latest', JSON.stringify({ items: [{ id: 'one' }, { id: 'two' }] }));
  const start = await mf.dispatchFetch(origin + '/api/auth/github', { redirect: 'manual' });
  assert.equal(start.status, 303);
  const state = new URL(start.headers.get('Location')).searchParams.get('state');
  const pending = start.headers.getSetCookie()[0].split(';')[0];
  const callback = await mf.dispatchFetch(
    origin + '/api/auth/callback?state=' + state + '&code=local-code',
    { redirect: 'manual', headers: { Cookie: pending } },
  );
  assert.equal(callback.headers.get('Location'), origin + '/?auth=success');
  const cookie = callback.headers
    .getSetCookie()
    .find((v) => v.startsWith('__Host-signal-session='))
    .split(';')[0];
  const session = await mf.dispatchFetch(origin + '/api/auth/session', {
    headers: { Cookie: cookie },
  });
  const view = await session.json();
  assert.equal(view.user.login, 'runtime-reader');
  const headers = {
    Cookie: cookie,
    Origin: origin,
    'Content-Type': 'application/json',
    'X-CSRF-Token': view.csrf,
  };
  const results = await Promise.all(
    ['one', 'two'].map((id) =>
      mf.dispatchFetch(origin + '/api/user/favorites', {
        method: 'PUT',
        headers,
        body: JSON.stringify({ id, saved: true }),
      }),
    ),
  );
  assert.ok(results.every((r) => r.status === 200));
  const final = await (await mf.dispatchFetch(origin + '/api/auth/session', { headers })).json();
  assert.deepEqual(final.favorites.sort(), ['one', 'two']);
  const logout = await mf.dispatchFetch(origin + '/api/auth/logout', { method: 'POST', headers });
  assert.equal(logout.status, 200);
  assert.equal((await mf.dispatchFetch(origin + '/api/auth/session', { headers })).status, 401);
  console.log(
    'PASS: real workerd OAuth callback (mock GitHub), SQLite DO persistence, concurrent favorites, logout revocation',
  );
} finally {
  await mf.dispose();
}
