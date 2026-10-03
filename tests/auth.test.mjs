import test from 'node:test';
import assert from 'node:assert/strict';
import { UserAccount } from '../worker/accounts.mjs';
import { handleAccountRequest } from '../worker/auth.mjs';
const origin = 'https://example.com';
function environment() {
  const objects = new Map();
  const stores = new Map();
  return {
    stores,
    APP_ORIGIN: origin,
    GITHUB_CLIENT_ID: 'test-client',
    GITHUB_CLIENT_SECRET: 'test-only-not-real',
    SESSION_SECRET: 'test-only-session-secret-at-least-32-characters',
    NEWS: { get: async () => ({ items: [{ id: 'news-1' }, { id: 'news-2' }] }) },
    USERS: {
      idFromName: (id) => id,
      get(id) {
        if (!objects.has(id)) {
          const data = new Map();
          stores.set(id, data);
          let queue = Promise.resolve();
          const store = {
            get: async (key) => structuredClone(data.get(key)),
            put: async (key, value) => data.set(key, structuredClone(value)),
          };
          const ctx = {
            storage: {
              transaction(fn) {
                const next = queue.then(() => fn(store));
                queue = next.catch(() => {});
                return next;
              },
            },
          };
          objects.set(id, new UserAccount(ctx));
        }
        return objects.get(id);
      },
    },
  };
}
const req = (path, options = {}) => new Request(origin + path, options);
async function login(env, id = 123, mode = 'ok') {
  const start = await handleAccountRequest(req('/api/auth/github'), env);
  assert.equal(start.status, 303);
  const authorize = new URL(start.headers.get('Location'));
  assert.equal(authorize.origin, 'https://github.com');
  assert.equal(authorize.searchParams.get('scope'), '');
  assert.equal(authorize.searchParams.get('code_challenge_method'), 'S256');
  const pending = start.headers.getSetCookie()[0].split(';')[0];
  const response = await handleAccountRequest(
    req(
      '/api/auth/callback?state=' + authorize.searchParams.get('state') + '&code=single-use-code',
      { headers: { Cookie: pending } },
    ),
    env,
    async (url, options) => {
      assert.equal(options.redirect, 'manual');
      if (url.endsWith('access_token')) {
        const verifier = options.body.get('code_verifier');
        assert.equal(
          Buffer.from(
            await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier)),
          ).toString('base64url'),
          authorize.searchParams.get('code_challenge'),
        );
        if (mode === 'fail') return Response.json({ error: 'bad_verification_code' });
        return Response.json({ access_token: 'test-token-never-persist', token_type: 'bearer' });
      }
      assert.equal(url, 'https://api.github.com/user');
      return Response.json({ id, login: 'reader-' + id, name: 'Reader' });
    },
  );
  const sessionCookie = response.headers
    .getSetCookie()
    .find((v) => v.startsWith('__Host-signal-session='));
  return { response, cookie: sessionCookie?.split(';')[0], env };
}
async function read(who) {
  return handleAccountRequest(
    req('/api/auth/session', { headers: { Cookie: who.cookie } }),
    who.env,
  );
}
async function write(who, route, body, overrides = {}) {
  const view = await (await read(who)).json();
  return handleAccountRequest(
    req(route, {
      method: route.endsWith('logout') ? 'POST' : 'PUT',
      headers: {
        Cookie: who.cookie,
        Origin: origin,
        'Content-Type': 'application/json',
        'X-CSRF-Token': view.csrf || '',
        ...overrides,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
    who.env,
  );
}

test('auth is safely disabled without secrets; route and method allowlists are enforced', async () => {
  const env = environment();
  delete env.GITHUB_CLIENT_SECRET;
  assert.equal(
    (await (await handleAccountRequest(req('/api/auth/session'), env)).json()).available,
    false,
  );
  assert.equal((await handleAccountRequest(req('/api/auth/github'), env)).status, 503);
  assert.equal((await handleAccountRequest(req('/api/auth/admin'), env)).status, 404);
  assert.equal((await handleAccountRequest(req('/api/auth/logout'), env)).status, 405);
  assert.equal(
    (await handleAccountRequest(req('/api/user/profile', { method: 'PUT' }), environment())).status,
    401,
  );
});
test('GitHub PKCE login creates only a public profile and hashed HttpOnly session', async () => {
  const who = await login(environment());
  assert.equal(who.response.headers.get('Location'), origin + '/?auth=success');
  const cookie = who.response.headers
    .getSetCookie()
    .find((c) => c.startsWith('__Host-signal-session='));
  for (const flag of ['HttpOnly', 'Secure', 'SameSite=Lax', 'Path=/'])
    assert.ok(cookie.includes(flag));
  const response = await read(who);
  const data = await response.json();
  assert.equal(response.headers.get('Cache-Control'), 'no-store, private');
  assert.equal(data.user.id, '123');
  assert.equal(data.csrf.length, 43);
  const stored = JSON.stringify([...who.env.stores.get('github:123').values()]);
  assert.ok(!stored.includes('test-token-never-persist'));
  assert.ok(!stored.includes(who.cookie.split('.')[1]));
});
test('callback rejects tampered/missing state and upstream token failures without persisting users', async () => {
  const env = environment();
  let calls = 0;
  const response = await handleAccountRequest(
    req('/api/auth/callback?state=fake&code=fake'),
    env,
    () => {
      calls++;
    },
  );
  assert.equal(calls, 0);
  assert.ok(response.headers.get('Location').endsWith('auth=failed'));
  const start = await handleAccountRequest(req('/api/auth/github'), env);
  const auth = new URL(start.headers.get('Location'));
  const bad = start.headers.getSetCookie()[0].split(';')[0] + 'tamper';
  const tampered = await handleAccountRequest(
    req('/api/auth/callback?state=' + auth.searchParams.get('state') + '&code=fake', {
      headers: { Cookie: bad },
    }),
    env,
    () => {
      calls++;
    },
  );
  assert.ok(tampered.headers.get('Location').endsWith('auth=failed'));
  assert.equal(calls, 0);
  const failed = await login(env, 123, 'fail');
  assert.ok(failed.response.headers.get('Location').endsWith('auth=failed'));
  assert.equal(env.stores.size, 0);
});
test('favorites, nickname, tags persist with strict account isolation and no client-selected user ID', async () => {
  const env = environment();
  const a = await login(env, 123);
  const b = await login(env, 456);
  assert.equal(
    (await write(a, '/api/user/favorites', { id: 'news-1', saved: true, userId: '456' })).status,
    200,
  );
  assert.equal((await write(a, '/api/user/profile', { displayName: '牢大' })).status, 200);
  assert.equal((await write(a, '/api/user/tags', { tag: 'DeepSeek', followed: true })).status, 200);
  const av = await (await read(a)).json();
  const bv = await (await read(b)).json();
  assert.deepEqual(av.favorites, ['news-1']);
  assert.deepEqual(av.tags, ['DeepSeek']);
  assert.equal(av.user.displayName, '牢大');
  assert.deepEqual(bv.favorites, []);
  assert.deepEqual(bv.tags, []);
  assert.equal(bv.user.displayName, 'Reader');
  await write(a, '/api/user/favorites', { id: 'news-1', saved: true });
  assert.deepEqual((await (await read(a)).json()).favorites, ['news-1']);
  await write(a, '/api/user/favorites', { id: 'news-1', saved: false });
  assert.deepEqual((await (await read(a)).json()).favorites, []);
});
test('CSRF, foreign origins, payload size and unsupported values are rejected', async () => {
  const who = await login(environment());
  assert.equal(
    (
      await write(
        who,
        '/api/user/profile',
        { displayName: 'bad' },
        { Origin: 'https://evil.example' },
      )
    ).status,
    403,
  );
  assert.equal(
    (await write(who, '/api/user/profile', { displayName: 'bad' }, { 'X-CSRF-Token': 'invalid' }))
      .status,
    403,
  );
  for (const name of ['', 'x'.repeat(61), '\u0000'])
    assert.equal((await write(who, '/api/user/profile', { displayName: name })).status, 400);
  assert.equal(
    (await write(who, '/api/user/profile', { displayName: 'x'.repeat(5000) })).status,
    400,
  );
  assert.equal(
    (await write(who, '/api/user/favorites', { id: 'missing', saved: true })).status,
    400,
  );
  assert.equal(
    (await write(who, '/api/user/favorites', { id: 'news-1', saved: 'true' })).status,
    400,
  );
  assert.equal(
    (await write(who, '/api/user/tags', { tag: 'x'.repeat(41), followed: true })).status,
    400,
  );
});
test('logout revokes immediately, clears cookie, and cannot be used cross-site', async () => {
  const who = await login(environment());
  assert.equal(
    (await write(who, '/api/auth/logout', undefined, { Origin: 'https://evil.example' })).status,
    403,
  );
  assert.equal((await read(who)).status, 200);
  const response = await write(who, '/api/auth/logout');
  assert.equal(response.status, 200);
  assert.ok(response.headers.get('Set-Cookie').includes('Max-Age=0'));
  assert.equal((await read(who)).status, 401);
});
test('session expiry, session cap and per-session write throttling are enforced', async () => {
  const env = environment();
  const first = await login(env);
  const store = env.stores.get('github:123');
  const data = store.get('account');
  data.sessions[0].expiresAt = Date.now() - 1;
  store.set('account', data);
  assert.equal((await read(first)).status, 401);
  const old = await login(env);
  for (let i = 0; i < 8; i++) await login(env);
  assert.equal((await read(old)).status, 401);
  const last = await login(env);
  for (let i = 0; i < 30; i++)
    assert.equal((await write(last, '/api/user/tags', { tag: 'AI', followed: true })).status, 200);
  assert.equal((await write(last, '/api/user/tags', { tag: 'AI', followed: true })).status, 429);
  assert.equal((await write(last, '/api/auth/logout')).status, 200);
});
test('bounded favorites and tags cannot grow past account limits', async () => {
  const who = await login(environment());
  const store = who.env.stores.get('github:123');
  const data = store.get('account');
  data.favorites = Array.from({ length: 200 }, (_, i) => 'old-' + i);
  data.tags = Array.from({ length: 30 }, (_, i) => 'tag-' + i);
  store.set('account', data);
  assert.equal(
    (await write(who, '/api/user/favorites', { id: 'news-1', saved: true })).status,
    409,
  );
  assert.equal((await write(who, '/api/user/tags', { tag: 'new', followed: true })).status, 409);
  assert.equal(
    (await write(who, '/api/user/favorites', { id: 'old-1', saved: false })).status,
    200,
  );
  assert.equal((await write(who, '/api/user/tags', { tag: 'tag-1', followed: false })).status, 200);
});
test('concurrent item mutations do not overwrite unrelated favorites', async () => {
  const who = await login(environment());
  const responses = await Promise.all(
    ['news-1', 'news-2'].map((id) => write(who, '/api/user/favorites', { id, saved: true })),
  );
  assert.ok(responses.every((r) => r.status === 200));
  assert.deepEqual((await (await read(who)).json()).favorites.sort(), ['news-1', 'news-2']);
});
