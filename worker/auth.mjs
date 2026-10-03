import { SESSION_SECONDS } from './accounts.mjs';
const encoder = new TextEncoder();
const headers = {
  'Cache-Control': 'no-store, private',
  Vary: 'Cookie',
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
};
const json = (body, status = 200, extra = {}) =>
  Response.json(body, { status, headers: { ...headers, ...extra } });
const b64 = (bytes) =>
  btoa(String.fromCharCode(...new Uint8Array(bytes)))
    .replaceAll('+', '-')
    .replaceAll('/', '_')
    .replaceAll('=', '');
const unb64 = (value) =>
  Uint8Array.from(atob(value.replaceAll('-', '+').replaceAll('_', '/')), (c) => c.charCodeAt(0));
const random = () => b64(crypto.getRandomValues(new Uint8Array(32)));
const digest = async (value) => b64(await crypto.subtle.digest('SHA-256', encoder.encode(value)));
function settings(env, request) {
  try {
    const origin = new URL(env.APP_ORIGIN);
    const local =
      origin.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(origin.hostname);
    if (
      (!local && origin.protocol !== 'https:') ||
      origin.origin !== env.APP_ORIGIN ||
      origin.origin !== new URL(request.url).origin
    )
      return null;
    if (
      !env.GITHUB_CLIENT_ID ||
      !env.GITHUB_CLIENT_SECRET ||
      !env.SESSION_SECRET ||
      env.SESSION_SECRET.length < 32 ||
      !env.USERS
    )
      return null;
    return { origin: origin.origin, secure: !local };
  } catch {
    return null;
  }
}
const cookieName = (cfg, kind) => (cfg.secure ? '__Host-' : '') + 'signal-' + kind;
const cookie = (cfg, kind, value, age) =>
  cookieName(cfg, kind) +
  '=' +
  value +
  '; Path=/; HttpOnly; SameSite=Lax; Max-Age=' +
  age +
  (cfg.secure ? '; Secure' : '');
function readCookie(request, name) {
  const parts = (request.headers.get('Cookie') || '')
    .split(';')
    .map((v) => v.trim())
    .filter((v) => v.startsWith(name + '='));
  return parts.length === 1 ? parts[0].slice(name.length + 1) : '';
}
async function stateKey(secret) {
  return crypto.subtle.importKey(
    'raw',
    encoder.encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign', 'verify'],
  );
}
async function signState(value, secret) {
  const text = b64(encoder.encode(JSON.stringify(value)));
  return (
    text + '.' + b64(await crypto.subtle.sign('HMAC', await stateKey(secret), encoder.encode(text)))
  );
}
async function verifyState(value, secret) {
  if (value.length > 1500) return null;
  try {
    const [text, sig, extra] = value.split('.');
    if (
      !text ||
      !sig ||
      extra ||
      !(await crypto.subtle.verify(
        'HMAC',
        await stateKey(secret),
        unb64(sig),
        encoder.encode(text),
      ))
    )
      return null;
    const data = JSON.parse(new TextDecoder().decode(unb64(text)));
    return data.expires > Date.now() &&
      data.expires <= Date.now() + 600000 &&
      typeof data.verifier === 'string'
      ? data
      : null;
  } catch {
    return null;
  }
}
async function account(env, id, command) {
  const stub = env.USERS.get(env.USERS.idFromName('github:' + id));
  return stub.fetch(
    new Request('https://account.internal/', { method: 'POST', body: JSON.stringify(command) }),
  );
}
async function identity(request, cfg) {
  const value = readCookie(request, cookieName(cfg, 'session'));
  const match = /^([1-9]\d{0,19})\.([A-Za-z0-9_-]{43})$/.exec(value);
  return match ? { id: match[1], hash: await digest(match[2]) } : null;
}
async function bodyJson(request) {
  if (!request.headers.get('Content-Type')?.toLowerCase().startsWith('application/json'))
    throw new Error('type');
  if (!request.body) throw new Error('body');
  const reader = request.body.getReader();
  let length = 0;
  const chunks = [];
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    length += value.length;
    if (length > 4096) {
      await reader.cancel();
      throw new Error('size');
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  const body = JSON.parse(new TextDecoder().decode(bytes));
  if (!body || typeof body !== 'object' || Array.isArray(body)) throw new Error('body');
  return body;
}
const redirect = (location, cookies = []) => {
  const h = new Headers({ ...headers, Location: location });
  for (const value of cookies) h.append('Set-Cookie', value);
  return new Response(null, { status: 303, headers: h });
};

export async function handleAccountRequest(request, env, fetcher = fetch) {
  const url = new URL(request.url);
  const routes = {
    '/api/auth/session': 'GET',
    '/api/auth/github': 'GET',
    '/api/auth/callback': 'GET',
    '/api/auth/logout': 'POST',
    '/api/user/profile': 'PUT',
    '/api/user/favorites': 'PUT',
    '/api/user/tags': 'PUT',
  };
  if (!Object.hasOwn(routes, url.pathname)) return json({ error: 'Not found' }, 404);
  if (request.method !== routes[url.pathname])
    return json({ error: 'Method not allowed' }, 405, { Allow: routes[url.pathname] });
  if (url.search.length > 2000) return json({ error: 'Query too long' }, 400);
  const cfg = settings(env, request);
  if (!cfg)
    return url.pathname === '/api/auth/session'
      ? json({ available: false, user: null, favorites: [], tags: [] })
      : json({ error: 'GitHub 登录尚未配置，请稍后再试。' }, 503);
  try {
    if (url.pathname === '/api/auth/github') {
      const state = random();
      const verifier = random();
      const auth = new URL('https://github.com/login/oauth/authorize');
      // Empty scope requests only public identity, never repositories or email.
      auth.search = new URLSearchParams({
        client_id: env.GITHUB_CLIENT_ID,
        redirect_uri: cfg.origin + '/api/auth/callback',
        scope: '',
        state,
        code_challenge: await digest(verifier),
        code_challenge_method: 'S256',
      }).toString();
      return redirect(auth.href, [
        cookie(
          cfg,
          'oauth',
          await signState({ state, verifier, expires: Date.now() + 600000 }, env.SESSION_SECRET),
          600,
        ),
      ]);
    }
    if (url.pathname === '/api/auth/callback') {
      const clear = cookie(cfg, 'oauth', '', 0);
      const pending = await verifyState(
        readCookie(request, cookieName(cfg, 'oauth')),
        env.SESSION_SECRET,
      );
      const code = url.searchParams.get('code');
      if (
        !pending ||
        pending.state !== url.searchParams.get('state') ||
        !code ||
        code.length > 512 ||
        url.searchParams.has('error')
      )
        return redirect(cfg.origin + '/?auth=failed', [clear]);
      try {
        const tokenResponse = await fetcher('https://github.com/login/oauth/access_token', {
          method: 'POST',
          redirect: 'manual',
          signal: AbortSignal.timeout(10000),
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded',
          },
          body: new URLSearchParams({
            client_id: env.GITHUB_CLIENT_ID,
            client_secret: env.GITHUB_CLIENT_SECRET,
            code,
            redirect_uri: cfg.origin + '/api/auth/callback',
            code_verifier: pending.verifier,
          }),
        });
        if (!tokenResponse.ok) throw new Error('token');
        const token = await tokenResponse.json();
        if (
          typeof token.access_token !== 'string' ||
          token.error ||
          token.token_type?.toLowerCase() !== 'bearer'
        )
          throw new Error('token');
        const userResponse = await fetcher('https://api.github.com/user', {
          redirect: 'manual',
          signal: AbortSignal.timeout(10000),
          headers: {
            Accept: 'application/vnd.github+json',
            Authorization: 'Bearer ' + token.access_token,
            'User-Agent': 'signal-ai-news',
          },
        });
        if (!userResponse.ok) throw new Error('profile');
        const user = await userResponse.json();
        if (
          !Number.isSafeInteger(user.id) ||
          user.id < 1 ||
          typeof user.login !== 'string' ||
          !/^[a-zA-Z0-9-]{1,39}$/.test(user.login)
        )
          throw new Error('profile');
        const secret = random();
        const csrf = random();
        const profile = {
          id: String(user.id),
          login: user.login,
          name: typeof user.name === 'string' ? user.name.slice(0, 60) : user.login,
        };
        const response = await account(env, profile.id, {
          action: 'login',
          profile,
          hash: await digest(secret),
          csrf,
        });
        if (!response.ok) throw new Error('store');
        return redirect(cfg.origin + '/?auth=success', [
          clear,
          cookie(cfg, 'session', profile.id + '.' + secret, SESSION_SECONDS),
        ]);
      } catch {
        return redirect(cfg.origin + '/?auth=failed', [clear]);
      }
    }
    const who = await identity(request, cfg);
    if (!who)
      return url.pathname === '/api/auth/session'
        ? json({ available: true, user: null, favorites: [], tags: [] })
        : json({ error: '请先登录。' }, 401);
    if (
      request.method !== 'GET' &&
      (request.headers.get('Origin') !== cfg.origin || !request.headers.get('X-CSRF-Token'))
    )
      return json({ error: '安全校验失败，请刷新后重试。' }, 403);
    let body = {};
    if (request.method === 'PUT') {
      try {
        body = await bodyJson(request);
      } catch {
        return json({ error: '请求需为有效 JSON，且不超过 4KB。' }, 400);
      }
    }
    const action = {
      '/api/auth/session': 'read',
      '/api/auth/logout': 'logout',
      '/api/user/profile': 'profile',
      '/api/user/favorites': 'favorite',
      '/api/user/tags': 'tag',
    }[url.pathname];
    // Authenticate before consulting the public snapshot for additions.
    if (action === 'favorite' && body.saved === true) {
      const check = await account(env, who.id, { action: 'read', hash: who.hash });
      if (!check.ok) return json({ error: '请重新登录。' }, 401);
      const feed = await env.NEWS.get('feed:latest', 'json');
      if (!feed?.items?.some((item) => item.id === body.id))
        return json({ error: '该资讯已不在当前快照中。' }, 400);
    }
    const response = await account(env, who.id, {
      action,
      hash: who.hash,
      csrf: request.headers.get('X-CSRF-Token'),
      body,
    });
    const result = await response.json();
    delete result.status;
    if (response.status === 401)
      return json({ error: '请重新登录。' }, 401, { 'Set-Cookie': cookie(cfg, 'session', '', 0) });
    return json(
      result,
      response.status,
      action === 'logout' && response.ok ? { 'Set-Cookie': cookie(cfg, 'session', '', 0) } : {},
    );
  } catch {
    return json({ error: '账号服务暂时不可用，请稍后重试。' }, 503);
  }
}
