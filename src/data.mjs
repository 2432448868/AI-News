/** Shared data contract; kept dependency-free for browser and Node. */
export const CATEGORY_LABELS = Object.freeze({
  news: 'AI 动态',
  projects: '开源项目',
  skills: 'Skills',
  models: '模型动态',
  tips: '实用技巧',
  apps: '趣味应用',
  dev: '开发实践',
});
export function safeUrl(value) {
  if (typeof value !== 'string') return null;
  try {
    const u = new URL(value);
    return u.protocol === 'https:' && !u.username && !u.password ? u.href : null;
  } catch {
    return null;
  }
}
export function canonicalUrl(value) {
  const safe = safeUrl(value);
  if (!safe) return null;
  const u = new URL(safe);
  u.hash = '';
  for (const key of [...u.searchParams.keys()])
    if (/^utm_/i.test(key) || ['ref', 'source', 'fbclid', 'gclid'].includes(key))
      u.searchParams.delete(key);
  u.pathname = u.pathname.replace(/\/$/, '') || '/';
  u.searchParams.sort();
  return u.href;
}
export function isoDate(value) {
  if (typeof value !== 'string' || !value.trim()) return null;
  const d = new Date(value);
  return Number.isFinite(d.getTime()) ? d.toISOString() : null;
}
export function itemTime(item) {
  return Date.parse(item.updatedAt || item.publishedAt || '') || 0;
}
export function escapeHtml(value) {
  return String(value).replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
  );
}
export function validateFeed(value) {
  const fail = () => {
    throw new Error('数据格式校验失败，请稍后重新加载。');
  };
  if (
    !value ||
    value.schemaVersion !== 1 ||
    !isoDate(value.generatedAt) ||
    !Array.isArray(value.sources) ||
    !Array.isArray(value.items) ||
    value.items.length > 500 ||
    value.sources.length > 30
  )
    fail();
  const sources = new Set();
  const ids = new Set();
  for (const s of value.sources) {
    if (
      !s ||
      typeof s.id !== 'string' ||
      !s.id ||
      sources.has(s.id) ||
      typeof s.name !== 'string' ||
      !safeUrl(s.homepage) ||
      !['ok', 'error'].includes(s.status) ||
      !Number.isInteger(s.itemCount) ||
      s.itemCount < 0 ||
      !(s.lastSuccessAt === null || isoDate(s.lastSuccessAt)) ||
      !(s.error === null || typeof s.error === 'string')
    )
      fail();
    sources.add(s.id);
  }
  for (const i of value.items) {
    if (
      !i ||
      typeof i.id !== 'string' ||
      !i.id ||
      ids.has(i.id) ||
      typeof i.title !== 'string' ||
      !i.title.trim() ||
      typeof i.summary !== 'string' ||
      typeof i.sourceName !== 'string' ||
      !sources.has(i.sourceId) ||
      !safeUrl(i.url) ||
      !Array.isArray(i.categories) ||
      !i.categories.length ||
      i.categories.some((c) => !Object.hasOwn(CATEGORY_LABELS, c)) ||
      !Array.isArray(i.tags) ||
      i.tags.some((t) => typeof t !== 'string') ||
      !isoDate(i.collectedAt) ||
      !(i.publishedAt === null || isoDate(i.publishedAt)) ||
      !(i.updatedAt === null || isoDate(i.updatedAt)) ||
      !Number.isFinite(i.rankScore) ||
      i.rankScore < 0 ||
      i.rankScore > 100 ||
      !(i.metricValue === null || (Number.isFinite(i.metricValue) && i.metricValue >= 0)) ||
      !(i.metricLabel === null || typeof i.metricLabel === 'string')
    )
      fail();
    ids.add(i.id);
  }
  return value;
}
export function filterItems(
  items,
  {
    query = '',
    category = 'all',
    days = 0,
    sort = 'latest',
    savedOnly = false,
    saved = new Set(),
    now = Date.now(),
  } = {},
) {
  const terms = query.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
  return items
    .filter(
      (i) =>
        (category === 'all' || i.categories.includes(category)) &&
        (!savedOnly || saved.has(i.id)) &&
        (!days || itemTime(i) >= now - days * 86400000) &&
        terms.every((term) =>
          [
            i.title,
            i.summary,
            i.sourceName,
            ...i.tags,
            ...i.categories.map((c) => CATEGORY_LABELS[c]),
          ]
            .join(' ')
            .toLocaleLowerCase()
            .includes(term),
        ),
    )
    .sort((a, b) =>
      sort === 'hot'
        ? b.rankScore - a.rankScore || itemTime(b) - itemTime(a) || a.id.localeCompare(b.id)
        : itemTime(b) - itemTime(a) || b.rankScore - a.rankScore || a.id.localeCompare(b.id),
    );
}
