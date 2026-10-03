import { createHash } from 'node:crypto';
import { XMLParser, XMLValidator } from 'fast-xml-parser';
import { canonicalUrl, isoDate, validateFeed, itemTime } from '../src/data.mjs';

export const MAX_BYTES = 2 * 1024 * 1024;
const parser = new XMLParser({
  ignoreAttributes: false,
  processEntities: true,
  htmlEntities: true,
  trimValues: true,
});
export function plainText(value, max = 240) {
  if (typeof value !== 'string') return '';
  return value
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, '')
    .replace(/<[^>]*>/g, ' ')
    .replace(/&#(x[\da-f]+|\d+);/gi, (_, n) => {
      const code = n[0].toLowerCase() === 'x' ? parseInt(n.slice(1), 16) : Number(n);
      return code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : '';
    })
    .replace(
      /&(amp|lt|gt|quot|apos|nbsp|#39);/g,
      (_, n) => ({ amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", '#39': "'", nbsp: ' ' })[n],
    )
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, max);
}
function date(value, now) {
  const d = isoDate(value);
  return d && Date.parse(d) <= Date.parse(now) + 86400000 ? d : null;
}
function base(source, url, title, now, index) {
  const safe = canonicalUrl(url);
  const clean = plainText(title, 240);
  if (!safe || !clean) return null;
  return {
    id: createHash('sha256').update(safe).digest('hex').slice(0, 20),
    title: clean,
    url: safe,
    sourceId: source.id,
    sourceName: source.name,
    summary: '',
    categories: [],
    tags: [],
    publishedAt: null,
    updatedAt: null,
    collectedAt: now,
    metricLabel: null,
    metricValue: null,
    rankScore: Math.max(0, 100 - index * 3),
  };
}
export function normalizeGithub(payload, source, now) {
  if (!payload || !Array.isArray(payload.items) || payload.incomplete_results === true)
    throw new Error('GitHub 返回不完整或无效数据');
  return payload.items.flatMap((r, index) => {
    if (r.archived || r.fork || r.private) return [];
    const i = base(source, r.html_url, r.full_name, now, index);
    if (!i) return [];
    return [
      {
        ...i,
        summary: plainText(r.description) || '该项目暂未提供描述，访问仓库了解详情。',
        categories:
          source.id === 'github-skills'
            ? ['skills']
            : source.id === 'github-apps'
              ? ['apps']
              : ['projects'],
        tags: (Array.isArray(r.topics) ? r.topics : [])
          .filter((t) => typeof t === 'string')
          .slice(0, 4),
        publishedAt: date(r.created_at, now),
        updatedAt: date(r.pushed_at, now),
        metricLabel: 'stars',
        metricValue: Number.isFinite(r.stargazers_count) ? Math.max(0, r.stargazers_count) : null,
      },
    ];
  });
}
export function normalizeHf(payload, source, now) {
  if (!Array.isArray(payload)) throw new Error('Hugging Face 返回无效数据');
  const models = source.id === 'hf-models';
  return payload.flatMap((r, index) => {
    const id = r.id || r.modelId;
    if (typeof id !== 'string' || !/^[\w.\-/]+$/.test(id)) return [];
    const i = base(
      source,
      'https://huggingface.co/' + (models ? '' : 'spaces/') + id,
      id,
      now,
      index,
    );
    if (!i) return [];
    const task =
      typeof r.pipeline_tag === 'string'
        ? r.pipeline_tag
        : typeof r.sdk === 'string'
          ? r.sdk
          : null;
    return [
      {
        ...i,
        summary:
          plainText(r.cardData?.short_description || r.cardData?.description || '') ||
          (models
            ? '来自 Hugging Face 热门模型榜。查看模型卡、适用任务与使用限制。'
            : '来自 Hugging Face Spaces 的 AI 应用。前往原站体验，可用性以作者维护为准。'),
        categories: [models ? 'models' : 'apps'],
        tags: [
          task,
          ...(Array.isArray(r.tags)
            ? r.tags.filter((t) => typeof t === 'string' && !t.includes(':')).slice(0, 2)
            : []),
        ].filter(Boolean),
        publishedAt: date(r.createdAt, now),
        updatedAt: date(r.lastModified, now),
        metricLabel: models ? 'downloads' : 'likes',
        metricValue: models
          ? Number.isFinite(r.downloads)
            ? Math.max(0, r.downloads)
            : null
          : Number.isFinite(r.likes)
            ? Math.max(0, r.likes)
            : null,
      },
    ];
  });
}
export function normalizeRss(text, source, now) {
  if (
    typeof text !== 'string' ||
    /<!DOCTYPE|<!ENTITY/i.test(text.replace(/<!\[CDATA\[[\s\S]*?\]\]>/g, '')) ||
    XMLValidator.validate(text) !== true
  )
    throw new Error('RSS 不是安全有效的 XML');
  const doc = parser.parse(text);
  const raw = doc.rss?.channel?.item ?? doc.feed?.entry;
  if (!raw) throw new Error('RSS 缺少文章条目');
  const entries = Array.isArray(raw) ? raw : [raw];
  return entries.slice(0, 30).flatMap((r, index) => {
    const links = Array.isArray(r.link) ? r.link : [r.link];
    const link = links.find(
      (l) => typeof l === 'string' || (l && (!l['@_rel'] || l['@_rel'] === 'alternate')),
    );
    const url = typeof link === 'string' ? link : link?.['@_href'];
    const title = typeof r.title === 'string' ? r.title : r.title?.['#text'];
    const i = base(source, url, title, now, index);
    if (!i) return [];
    const rawSummary = r.description ?? r.summary ?? '';
    const summary = plainText(typeof rawSummary === 'string' ? rawSummary : rawSummary['#text']);
    const textForRules = i.title.toLowerCase();
    const categories = ['news'];
    if (source.id === 'github-blog') categories.push('dev');
    if (
      /\b(how to|guide|tips|tutorial|learn|skills|best practices|build|building)\b/.test(
        textForRules,
      )
    )
      categories.push('tips');
    if (/\b(model|models|release|releases|introducing|llm)\b/.test(textForRules))
      categories.push('models');
    const publishedAt = date(r.pubDate ?? r.published ?? r.updated, now);
    if (publishedAt && Date.parse(publishedAt) < Date.parse(now) - 30 * 86400000) return [];
    return [
      {
        ...i,
        summary: summary || '查看官方原文，了解完整背景与细节。',
        categories,
        tags: ['官方博客'],
        publishedAt,
        updatedAt: date(r.updated, now),
        rankScore: Math.max(0, 95 - index * 3),
      },
    ];
  });
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
export async function fetchText(
  url,
  { headers = {}, fetchImpl = fetch, sleepImpl = sleep, timeout = 15000, attempts = 3 } = {},
) {
  for (let attempt = 0; attempt < attempts; attempt++) {
    let delay = 500 * 2 ** attempt;
    try {
      const response = await fetchImpl(url, {
        headers: { 'User-Agent': 'Signal-AI-News/1.0 (+public-news-aggregator)', ...headers },
        signal: AbortSignal.timeout(timeout),
      });
      if (!response.ok) {
        const retryable = [408, 429, 500, 502, 503, 504].includes(response.status);
        const raw = response.headers.get('retry-after');
        if (raw) {
          const seconds = Number(raw);
          delay = Number.isFinite(seconds) ? seconds * 1000 : Date.parse(raw) - Date.now();
          delay = Math.max(0, delay);
        }
        await response.body?.cancel();
        const error = new Error('HTTP ' + response.status);
        error.retryable = retryable && delay <= 10000;
        throw error;
      }
      if (Number(response.headers.get('content-length')) > MAX_BYTES) {
        await response.body?.cancel();
        const error = new Error('响应超过 2MB');
        error.retryable = false;
        throw error;
      }
      if (!response.body) throw new Error('响应为空');
      const reader = response.body.getReader();
      const chunks = [];
      let size = 0;
      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          size += value.byteLength;
          if (size > MAX_BYTES) {
            await reader.cancel();
            const error = new Error('响应超过 2MB');
            error.retryable = false;
            throw error;
          }
          chunks.push(value);
        }
      } finally {
        reader.releaseLock();
      }
      return Buffer.concat(chunks).toString('utf8');
    } catch (error) {
      if (attempt === attempts - 1 || error.retryable === false) throw error;
      await sleepImpl(delay);
    }
  }
  throw new Error('请求失败');
}
export function deduplicate(items) {
  const map = new Map();
  for (const item of items) {
    const url = canonicalUrl(item.url);
    if (!url) continue;
    const existing = map.get(url);
    if (existing) {
      const newer =
        Date.parse(item.collectedAt) >= Date.parse(existing.collectedAt) ? item : existing;
      map.set(url, {
        ...newer,
        categories: [...new Set([...existing.categories, ...item.categories])],
      });
    } else map.set(url, item);
  }
  return [...map.values()].sort((a, b) => itemTime(b) - itemTime(a)).slice(0, 500);
}
export function mergeResults(previous, results, now) {
  if (!results.some((r) => r.ok && r.items.length))
    throw new Error('全部来源采集失败；未覆盖上次快照。');
  const old = previous?.items ?? [];
  const items = [];
  const sources = [];
  for (const result of results) {
    const source = result.source;
    const oldSource = previous?.sources?.find((s) => s.id === source.id);
    const successful = result.ok && result.items.length > 0;
    let next = successful ? result.items : old.filter((i) => i.sourceId === source.id);
    if (successful && source.kind === 'rss')
      next = [
        ...old.filter(
          (i) =>
            i.sourceId === source.id &&
            i.publishedAt &&
            Date.parse(i.publishedAt) >= Date.parse(now) - 30 * 86400000,
        ),
        ...next,
      ];
    next = deduplicate(next);
    items.push(...next);
    sources.push({
      id: source.id,
      name: source.name,
      homepage: source.homepage,
      status: successful ? 'ok' : 'error',
      lastSuccessAt: successful ? now : (oldSource?.lastSuccessAt ?? null),
      itemCount: next.length,
      error: successful ? null : plainText(result.error || '本次没有有效条目', 180),
    });
  }
  const merged = deduplicate(items);
  for (const source of sources)
    source.itemCount = merged.filter((i) => i.sourceId === source.id).length;
  return validateFeed({ schemaVersion: 1, generatedAt: now, sources, items: merged });
}
