import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { safeUrl, canonicalUrl, escapeHtml, validateFeed, filterItems } from '../src/data.mjs';
import {
  plainText,
  normalizeGithub,
  normalizeHf,
  normalizeRss,
  mergeResults,
  deduplicate,
  fetchText,
  MAX_BYTES,
} from '../scripts/collector-core.mjs';
const now = '2026-10-03T00:23:00.000Z';
const github = {
  id: 'github-projects',
  name: 'GitHub',
  kind: 'github',
  homepage: 'https://github.com',
};
const blog = {
  id: 'github-blog',
  name: 'GitHub Blog',
  kind: 'rss',
  homepage: 'https://github.blog',
};
const hf = { id: 'hf-models', name: 'HF Models', kind: 'hf', homepage: 'https://huggingface.co' };
const make = (patch = {}) => ({
  id: '1',
  title: 'Agent project',
  summary: 'Build useful tools',
  url: 'https://github.com/example/agent',
  sourceId: github.id,
  sourceName: github.name,
  categories: ['projects'],
  tags: ['agent'],
  publishedAt: '2026-10-01T00:00:00.000Z',
  updatedAt: null,
  collectedAt: now,
  rankScore: 90,
  metricValue: 100,
  metricLabel: 'stars',
  ...patch,
});
const success = (source, items) => ({ source, ok: true, items });
const failure = (source) => ({ source, ok: false, items: [], error: 'network failed' });
const xml =
  '<rss><channel><item><title>How to build an agent</title><link>https://github.blog/tutorial</link><description><![CDATA[<p>Use <b>agents</b> safely.</p>]]></description><pubDate>Fri, 02 Oct 2026 15:00:00 GMT</pubDate></item></channel></rss>';

test('only public HTTPS URL syntax is accepted, never credentials or executable schemes', () => {
  for (const value of [
    'javascript:alert(1)',
    'data:text/html,x',
    'http://example.com',
    'https://user:pass@example.com',
    '//example.com',
    null,
  ])
    assert.equal(safeUrl(value), null);
  assert.equal(safeUrl('https://example.com/a'), 'https://example.com/a');
});
test('tracking variants canonicalize to a stable URL', () => {
  assert.equal(
    canonicalUrl('https://example.com/a/?utm_source=x&b=2&a=1#x'),
    'https://example.com/a?a=1&b=2',
  );
});
test('HTML is escaped for text and attribute contexts', () =>
  assert.equal(
    escapeHtml('<img src="x" onerror=\'bad\'>&'),
    '&lt;img src=&quot;x&quot; onerror=&#39;bad&#39;&gt;&amp;',
  ));
test('plain text drops markup, script contents and truncates', () => {
  assert.equal(plainText('<script>x()</script><p> hello &amp; world </p>'), 'hello & world');
  assert.equal(plainText('abcdef', 3), 'abc');
  assert.equal(plainText('&#999999999;'), '');
});
test('GitHub normalization retains true creation and push dates, rejects forks', () => {
  const payload = {
    items: [
      {
        full_name: 'org/repo',
        html_url: 'https://github.com/org/repo',
        description: '<b>AI</b>',
        created_at: '2025-01-01',
        pushed_at: '2026-10-02',
        stargazers_count: 123,
        topics: ['llm'],
      },
      { full_name: 'fork', fork: true },
    ],
  };
  const [item] = normalizeGithub(payload, github, now);
  assert.equal(item.summary, 'AI');
  assert.equal(item.publishedAt, '2025-01-01T00:00:00.000Z');
  assert.equal(item.updatedAt, '2026-10-02T00:00:00.000Z');
  assert.equal(item.collectedAt, now);
  assert.equal(item.metricValue, 123);
});
test('GitHub incomplete search cannot replace a good snapshot', () =>
  assert.throws(() => normalizeGithub({ items: [], incomplete_results: true }, github, now)));
test('Skills topic source uses the Skills category', () => {
  const [item] = normalizeGithub(
    { items: [{ full_name: 'org/skills', html_url: 'https://github.com/org/skills' }] },
    { ...github, id: 'github-skills' },
    now,
  );
  assert.deepEqual(item.categories, ['skills']);
});
test('Hugging Face model metadata is not mislabeled as release date', () => {
  const [i] = normalizeHf(
    [
      {
        id: 'org/model',
        lastModified: '2026-10-02',
        downloads: 42,
        pipeline_tag: 'text-generation',
      },
    ],
    hf,
    now,
  );
  assert.equal(i.publishedAt, null);
  assert.equal(i.updatedAt, '2026-10-02T00:00:00.000Z');
  assert.equal(i.metricValue, 42);
  assert.deepEqual(i.categories, ['models']);
});
test('Spaces map to apps and preserve likes', () => {
  const [i] = normalizeHf(
    [{ id: 'org/demo', likes: 8, sdk: 'gradio' }],
    { ...hf, id: 'hf-spaces' },
    now,
  );
  assert.equal(i.url, 'https://huggingface.co/spaces/org/demo');
  assert.deepEqual(i.categories, ['apps']);
  assert.equal(i.metricLabel, 'likes');
});
test('RSS extracts short descriptions, not full article HTML', () => {
  const [i] = normalizeRss(xml, blog, now);
  assert.equal(i.summary, 'Use agents safely.');
  assert.deepEqual(i.categories, ['news', 'dev', 'tips']);
});
test('HTML DOCTYPE inside CDATA is inert content and does not reject valid feeds', () => {
  const [i] = normalizeRss(
    xml.replace(
      '</item>',
      '<content><![CDATA[<!DOCTYPE html><html><body>story</body></html>]]></content></item>',
    ),
    blog,
    now,
  );
  assert.ok(i);
});
test('DTD, entity declarations, malformed XML and unsafe links are rejected', () => {
  assert.throws(() =>
    normalizeRss('<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///etc/passwd">]>' + xml, blog, now),
  );
  assert.throws(() => normalizeRss('<rss><channel>', blog, now));
  assert.deepEqual(
    normalizeRss(xml.replace('https://github.blog/tutorial', 'javascript:alert(1)'), blog, now),
    [],
  );
});
test('Atom alternate links and dates normalize', () => {
  const atom =
    '<feed><entry><title>New model</title><link rel="self" href="https://example.com/api"/><link rel="alternate" href="https://example.com/post"/><updated>2026-10-02T12:00:00Z</updated><summary>Model details</summary></entry></feed>';
  const [i] = normalizeRss(atom, blog, now);
  assert.equal(i.url, 'https://example.com/post');
  assert.ok(i.categories.includes('models'));
});
test('old RSS stories are removed and absent dates are never replaced by collection time', () => {
  assert.equal(normalizeRss(xml.replace('02 Oct 2026', '02 Jan 2026'), blog, now).length, 0);
  const [i] = normalizeRss(xml.replace(/<pubDate>.*?<\/pubDate>/, ''), blog, now);
  assert.equal(i.publishedAt, null);
});
test('URL dedup preserves multiple categories', () => {
  const items = deduplicate([
    make(),
    make({
      id: '2',
      categories: ['skills'],
      url: 'https://github.com/example/agent?utm_source=feed',
    }),
  ]);
  assert.equal(items.length, 1);
  assert.deepEqual(items[0].categories, ['projects', 'skills']);
});
test('single-source failure retains previous records and success time', () => {
  const old = mergeResults(
    null,
    [
      success(github, [make()]),
      success(blog, [
        make({ id: '2', url: 'https://github.blog/post', sourceId: blog.id, categories: ['news'] }),
      ]),
    ],
    now,
  );
  const next = mergeResults(
    old,
    [
      failure(github),
      success(blog, [
        make({ id: '3', url: 'https://github.blog/new', sourceId: blog.id, categories: ['news'] }),
      ]),
    ],
    '2026-10-04T00:23:00.000Z',
  );
  assert.equal(next.sources[0].status, 'error');
  assert.equal(next.sources[0].lastSuccessAt, now);
  assert.ok(next.items.some((i) => i.id === '1'));
});
test('all sources failing refuses to generate a new snapshot', () =>
  assert.throws(() => mergeResults(null, [failure(github)], now), /全部来源/));
test('empty source is a failure, not a successful replacement', () =>
  assert.throws(() => mergeResults(null, [success(github, [])], now)));
test('successful repository refresh replaces, rather than appends, the old ranking', () => {
  const old = mergeResults(null, [success(github, [make()])], now);
  const next = mergeResults(
    old,
    [success(github, [make({ id: '2', url: 'https://github.com/another/repo' })])],
    now,
  );
  assert.equal(next.items.length, 1);
  assert.equal(next.items[0].id, '2');
});
test('schema validation rejects unsafe links, invalid category, duplicate IDs and malformed metrics', () => {
  const good = mergeResults(null, [success(github, [make()])], now);
  for (const patch of [
    { url: 'javascript:x' },
    { categories: ['other'] },
    { rankScore: NaN },
    { publishedAt: 'not-date' },
    { metricValue: -1 },
  ])
    assert.throws(() => validateFeed({ ...good, items: [{ ...good.items[0], ...patch }] }));
  assert.throws(() => validateFeed({ ...good, items: [...good.items, ...good.items] }));
});
test('search/category/date/saved filters combine and latest sorting ignores collection time', () => {
  const items = [
    make(),
    make({
      id: '2',
      title: 'Different',
      categories: ['skills'],
      updatedAt: '2026-10-02T23:00:00Z',
      rankScore: 95,
    }),
  ];
  assert.equal(
    filterItems(items, {
      query: 'Agent GitHub',
      category: 'projects',
      savedOnly: true,
      saved: new Set(['1']),
    }).length,
    1,
  );
  assert.equal(filterItems(items, { days: 1, now: Date.parse(now) })[0].id, '2');
  assert.equal(filterItems(items, { sort: 'hot' })[0].id, '2');
  assert.equal(filterItems(items, { query: 'not found' }).length, 0);
});
test('fetch retries transient HTTP failures with a bounded backoff', async () => {
  let calls = 0;
  const delays = [];
  const result = await fetchText('https://example.com', {
    fetchImpl: async () =>
      ++calls < 3 ? new Response('busy', { status: 503 }) : new Response('ok'),
    sleepImpl: async (ms) => delays.push(ms),
  });
  assert.equal(result, 'ok');
  assert.equal(calls, 3);
  assert.deepEqual(delays, [500, 1000]);
});
test('permanent failures and long Retry-After do not hammer the source', async () => {
  for (const response of [
    new Response('no', { status: 404 }),
    new Response('rate limited', { status: 429, headers: { 'retry-after': '120' } }),
  ]) {
    let calls = 0;
    await assert.rejects(() =>
      fetchText('https://example.com', {
        fetchImpl: async () => {
          calls++;
          return response;
        },
        sleepImpl: async () => {},
      }),
    );
    assert.equal(calls, 1);
  }
});
test('429 honors a short Retry-After before retrying', async () => {
  let calls = 0;
  const waits = [];
  await fetchText('https://example.com', {
    fetchImpl: async () =>
      ++calls === 1
        ? new Response('slow', { status: 429, headers: { 'retry-after': '2' } })
        : new Response('ok'),
    sleepImpl: async (ms) => waits.push(ms),
  });
  assert.deepEqual(waits, [2000]);
});
test('oversized streams and content-length are rejected', async () => {
  for (const response of [
    new Response('x', { headers: { 'content-length': String(MAX_BYTES + 1) } }),
    new Response('x'.repeat(MAX_BYTES + 1)),
  ])
    await assert.rejects(
      () =>
        fetchText('https://example.com', {
          fetchImpl: async () => response,
          sleepImpl: async () => {},
        }),
      /2MB/,
    );
});
test('checked-in snapshot contains real valid source-backed records', async () => {
  const feed = validateFeed(
    JSON.parse(await readFile(new URL('../public/data/feed.json', import.meta.url), 'utf8')),
  );
  assert.ok(feed.items.length > 0);
  assert.ok(feed.sources.some((s) => s.status === 'ok'));
  assert.ok(feed.items.every((i) => !i.url.includes('example.com')));
});

test('GitHub demo discovery maps to apps independently of model availability', () => {
  const [item] = normalizeGithub(
    {
      items: [
        {
          html_url: 'https://github.com/example/demo',
          full_name: 'example/demo',
          topics: ['gradio'],
          stargazers_count: 123,
        },
      ],
    },
    { ...github, id: 'github-apps' },
    now,
  );
  assert.deepEqual(item.categories, ['apps']);
  assert.equal(item.metricValue, 123);
});
