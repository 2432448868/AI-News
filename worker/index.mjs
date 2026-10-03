import { handleAccountRequest } from './auth.mjs';
export { UserAccount } from './accounts.mjs';
import { CATEGORY_LABELS, filterItems } from '../src/data.mjs';

const KEY = 'feed:latest';
const MAX_BYTES = 2 * 1024 * 1024;
const json = (value, status = 200, extra = {}) =>
  new Response(JSON.stringify(value), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'public, max-age=60',
      'X-Content-Type-Options': 'nosniff',
      ...extra,
    },
  });

// The trusted upstream is this project's Pages build, already fully validated by CI.
// Bound payload size and shape again at the edge; browser performs full validation.
export function parseSnapshot(text) {
  const feed = JSON.parse(text);
  if (
    feed.schemaVersion !== 1 ||
    !Number.isFinite(Date.parse(feed.generatedAt)) ||
    Date.parse(feed.generatedAt) > Date.now() + 300000 ||
    !Array.isArray(feed.items) ||
    !feed.items.length ||
    feed.items.length > 500 ||
    !Array.isArray(feed.sources) ||
    !feed.sources.length ||
    feed.sources.length > 30
  )
    throw new Error('Invalid snapshot');
  return feed;
}

export async function syncSnapshot(env, fetcher = fetch) {
  try {
    const response = await fetcher(env.FEED_URL, {
      signal: AbortSignal.timeout(20000),
      redirect: 'manual',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok || !response.body) throw new Error('Upstream HTTP ' + response.status);
    const reader = response.body.getReader();
    const chunks = [];
    let size = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_BYTES) {
        await reader.cancel();
        throw new Error('Snapshot too large');
      }
      chunks.push(value);
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.length;
    }
    const text = new TextDecoder().decode(bytes);
    const feed = parseSnapshot(text);
    const old = await env.NEWS.getWithMetadata(KEY);
    if (!old.metadata || Date.parse(feed.generatedAt) > Date.parse(old.metadata.generatedAt)) {
      await env.NEWS.put(KEY, text, {
        metadata: { generatedAt: feed.generatedAt, itemCount: feed.items.length },
      });
    }
    await env.NEWS.put(
      'sync:status',
      JSON.stringify({
        ok: true,
        checkedAt: new Date().toISOString(),
        upstreamGeneratedAt: feed.generatedAt,
      }),
    );
  } catch (error) {
    await env.NEWS.put(
      'sync:status',
      JSON.stringify({
        ok: false,
        checkedAt: new Date().toISOString(),
        error: String(error.message).slice(0, 200),
      }),
    );
    throw error;
  }
}

export async function handleRequest(request, env) {
  const url = new URL(request.url);
  if (url.pathname.startsWith('/api/auth/') || url.pathname.startsWith('/api/user/'))
    return handleAccountRequest(request, env);
  if (!url.pathname.startsWith('/api/')) return env.ASSETS.fetch(request);
  if (!['GET', 'HEAD'].includes(request.method))
    return json({ error: 'Method not allowed' }, 405, {
      Allow: 'GET, HEAD',
      'Cache-Control': 'no-store',
    });
  const routes = ['/api/feed', '/api/items', '/api/sources', '/api/health'];
  if (!routes.includes(url.pathname)) return json({ error: 'Not found' }, 404);
  if (url.search.length > 1000) return json({ error: 'Query too long' }, 400);
  try {
    const snapshot = await env.NEWS.getWithMetadata(KEY);
    if (!snapshot.value)
      return json({ error: 'Snapshot not initialized' }, 503, { 'Cache-Control': 'no-store' });
    const headers = {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'public, max-age=60',
      'X-Content-Type-Options': 'nosniff',
    };
    if (request.method === 'HEAD') return new Response(null, { headers });
    if (url.pathname === '/api/feed') return new Response(snapshot.value, { headers });
    const feed = JSON.parse(snapshot.value);
    const stale = Date.now() - Date.parse(feed.generatedAt) > 48 * 3600000;
    if (url.pathname === '/api/health') {
      const sync = await env.NEWS.get('sync:status', 'json');
      return json({
        status: stale ? 'stale' : 'ok',
        generatedAt: feed.generatedAt,
        itemCount: feed.items.length,
        sourceCount: feed.sources.length,
        healthySources: feed.sources.filter((s) => s.status === 'ok').length,
        sync,
        schedule: '15 */6 * * * (UTC)',
        collection: 'GitHub Actions → GitHub Pages → Cloudflare KV',
      });
    }
    if (url.pathname === '/api/sources')
      return json({ generatedAt: feed.generatedAt, sources: feed.sources });
    const p = url.searchParams;
    const category = p.get('category') || 'all';
    const sort = p.get('sort') || 'latest';
    const page = Number(p.get('page') || 1);
    const limit = Number(p.get('limit') || 24);
    const days = Number(p.get('days') || 0);
    if (
      (category !== 'all' && !Object.hasOwn(CATEGORY_LABELS, category)) ||
      !['latest', 'hot'].includes(sort) ||
      !Number.isInteger(page) ||
      page < 1 ||
      page > 500 ||
      !Number.isInteger(limit) ||
      limit < 1 ||
      limit > 100 ||
      !Number.isInteger(days) ||
      days < 0 ||
      days > 365 ||
      !['true', 'false', null].includes(p.get('chinaOnly'))
    )
      return json({ error: 'Invalid query parameters' }, 400);
    const items = filterItems(feed.items, {
      query: p.get('q') || '',
      tag: p.get('tag') || '',
      category,
      sort,
      days,
      chinaOnly: p.get('chinaOnly') === 'true',
    });
    return json({
      generatedAt: feed.generatedAt,
      stale,
      total: items.length,
      page,
      limit,
      items: items.slice((page - 1) * limit, page * limit),
    });
  } catch (error) {
    console.error('API unavailable', error.message);
    return json({ error: 'Service temporarily unavailable' }, 503, { 'Cache-Control': 'no-store' });
  }
}

export default {
  fetch: handleRequest,
  scheduled(_event, env, ctx) {
    ctx.waitUntil(syncSnapshot(env));
  },
};
