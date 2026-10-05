import { initAccount } from './account';
import './style.css';
import './motion.css';
import { initMotion } from './motion';
import shell from './shell.html?raw';
import { CATEGORY_LABELS, escapeHtml as esc, filterItems, validateFeed } from './data.mjs';
import type { Category, Feed, Item } from './types';

const paths = {
  arrow: '<path d="M7 17 17 7M7 7h10v10"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
  moon: '<path d="M20.8 13.2A9 9 0 0 1 10.8 3.1 9 9 0 1 0 20.8 13.2Z"/>',
  bookmark: '<path d="M6 4h12v17l-6-4-6 4Z"/>',
  star: '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2-5.5-2.9-5.5 2.9 1-6.2L3 9.6l6.2-.9Z"/>',
  code: '<path d="m8 7-5 5 5 5m8-10 5 5-5 5m-3-13-2 16"/>',
  cube: '<path d="m12 3 9 5-9 5-9-5 9-5Zm-9 5v9l9 5 9-5V8m-9 5v9"/>',
  spark: '<path d="m12 3 2.6 6.4L21 12l-6.4 2.6L12 21l-2.6-6.4L3 12l6.4-2.6Z"/>',
  book: '<path d="M12 6c-4-3-8-2-9-1v15c2-2 6-2 9 0 3-2 7-2 9 0V5c-1-1-5-2-9 1Zm0 0v14"/>',
  bolt: '<path d="m13 2-9 12h7l-1 8 10-13h-8Z"/>',
  globe:
    '<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/>',
  refresh: '<path d="M20 7v5h-5M4 17v-5h5M5.5 7a8 8 0 0 1 13-1L20 9M4 15l1.5 3a8 8 0 0 0 13-1"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',
} as const;
type IconName = keyof typeof paths;
const icon = (name: IconName, cls = '') =>
  '<svg class="icon ' +
  cls +
  '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  paths[name] +
  '</svg>';
const categoryIcons: Record<Category, IconName> = {
  news: 'globe',
  projects: 'code',
  skills: 'bolt',
  models: 'cube',
  tips: 'book',
  apps: 'spark',
  dev: 'code',
};
const labels: Record<Category, string> = CATEGORY_LABELS;
const get = <T extends HTMLElement>(selector: string): T => {
  const el = document.querySelector<T>(selector);
  if (!el) throw new Error('Missing element ' + selector);
  return el;
};
function readStorage(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function writeStorage(key: string, value: string): boolean {
  try {
    localStorage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}
function readSaved(): Set<string> {
  try {
    const raw: unknown = JSON.parse(readStorage('signal-saved') || '[]');
    return new Set(
      Array.isArray(raw)
        ? raw.filter((v): v is string => typeof v === 'string').slice(0, 1000)
        : [],
    );
  } catch {
    return new Set();
  }
}
let saved = readSaved();
let feed: Feed | null = null;
let category: Category | 'all' = 'all';
let query = '';
let tag = '';
let chinaOnly = false;
let days = 0;
let sort = 'latest';
let savedOnly = false;
let limit = 12;
let loading = false;
let toastTimeout: ReturnType<typeof setTimeout> | undefined;
const dateFormat = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  month: '2-digit',
  day: '2-digit',
});
const fullDate = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});
const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 });
const stampTime = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});
const dateText = (date: string | null) => (date ? dateFormat.format(new Date(date)) : '日期未提供');
const stamp = (date: string | null) =>
  date ? fullDate.format(new Date(date)) + ' 北京时间' : '尚无成功记录';
const metric = (i: Item) =>
  i.metricValue === null
    ? ''
    : compact.format(i.metricValue) +
      ' ' +
      (i.metricLabel === 'stars' ? 'stars' : i.metricLabel === 'downloads' ? 'downloads' : 'likes');
const logo =
  '<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M6 20h7L21 7h5M6 26h7l8-13h5" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>';
get('#app').innerHTML = shell
  .replaceAll('{{logo}}', logo)
  .replace(/\{\{icon:(\w+)\}\}/g, (_, name: IconName) => icon(name));
get('#edition-date').textContent = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  month: 'long',
  day: 'numeric',
  weekday: 'long',
}).format(new Date());
function syncTheme() {
  const dark = document.documentElement.dataset.theme === 'dark';
  get('#theme-toggle').innerHTML = icon(dark ? 'sun' : 'moon');
  get('#theme-toggle').setAttribute('aria-label', dark ? '切换浅色模式' : '切换深色模式');
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute('content', dark ? '#141917' : '#f7f8fa');
}
function toast(message: string) {
  get('#toast').textContent = message;
  get('#toast').classList.add('visible');
  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => get('#toast').classList.remove('visible'), 2400);
}
function syncSaved() {
  get('#saved-count').textContent = String(saved.size);
  document.querySelectorAll<HTMLButtonElement>('[data-action="saved"]').forEach((b) => {
    b.classList.toggle('active', savedOnly);
    b.setAttribute('aria-pressed', String(savedOnly));
  });
}
function renderTabs() {
  get('#categories').innerHTML = [['all', '全部'], ...Object.entries(labels)]
    .map(
      ([key, label]) =>
        '<button class="category-tab ' +
        (category === key ? 'selected' : '') +
        '" data-action="category" data-category="' +
        key +
        '" aria-pressed="' +
        (category === key) +
        '">' +
        (key === 'all' ? '' : icon(categoryIcons[key as Category])) +
        label +
        '</button>',
    )
    .join('');
}
function saveButton(item: Item) {
  const active = saved.has(item.id);
  return (
    '<button class="save-button ' +
    (active ? 'is-saved' : '') +
    '" data-action="save" data-id="' +
    esc(item.id) +
    '" aria-pressed="' +
    active +
    '" aria-label="' +
    (active ? '取消收藏：' : '收藏：') +
    esc(item.title) +
    '">' +
    icon('bookmark') +
    '</button>'
  );
}
function tagButtons(item: Item) {
  return item.tags
    .slice(0, 4)
    .map(
      (t) =>
        '<button class="topic-tag" data-action="tag" data-tag="' +
        esc(t) +
        '" aria-pressed="' +
        (tag === t) +
        '" title="筛选标签：' +
        esc(t) +
        '">' +
        esc(t) +
        '</button>',
    )
    .join('');
}
function card(item: Item) {
  const primary = item.categories[0] ?? 'news';
  return (
    '<article class="news-card" data-item-id="' +
    esc(item.id) +
    '"><div class="card-top"><span class="category-badge badge-' +
    primary +
    '">' +
    icon(categoryIcons[primary]) +
    labels[primary] +
    '</span>' +
    saveButton(item) +
    '</div><a class="card-title" href="' +
    esc(item.url) +
    '" target="_blank" rel="noopener noreferrer"><h3>' +
    esc(item.title) +
    '</h3>' +
    icon('arrow') +
    '</a><p class="card-summary">' +
    esc(item.summary) +
    '</p><div class="card-tags">' +
    tagButtons(item) +
    '</div><div class="card-bottom"><span class="source-name"><span class="source-dot source-' +
    primary +
    '"></span>' +
    esc(item.sourceName) +
    '</span><span title="' +
    esc(stamp(item.updatedAt || item.publishedAt)) +
    '">' +
    (item.updatedAt ? '更新 ' : item.publishedAt ? '发布 ' : '') +
    dateText(item.updatedAt || item.publishedAt) +
    '</span></div>' +
    (item.metricValue !== null
      ? '<div class="metric-line">' +
        icon(item.metricLabel === 'stars' ? 'star' : 'bolt') +
        esc(metric(item)) +
        '<span>' +
        (item.metricLabel === 'stars'
          ? '累计关注'
          : item.metricLabel === 'downloads'
            ? '源站下载统计'
            : '源站点赞统计') +
        '</span></div>'
      : '') +
    '</article>'
  );
}
function renderPaper(featuredId?: string, excludeIds: string[] = []) {
  if (!feed) return;
  get('#paper-stamp').textContent = feed.generatedAt
    ? '付印 ' + stampTime.format(new Date(feed.generatedAt))
    : '';
  // 头条卡与开源榜已各自展示的条目不再上要目，避免同屏重复
  const picks = (filterItems(feed.items, { sort: 'latest' }) as Item[]).filter(
    (i) => i.id !== featuredId && !excludeIds.includes(i.id),
  );
  const lead = picks[0];
  const rest = picks.slice(1, 5);
  get('#paper-list').innerHTML = lead
    ? '<li class="paper-lead"><a href="' +
      esc(lead.url) +
      '" target="_blank" rel="noopener noreferrer"><span class="paper-flag">头条</span><strong>' +
      esc(lead.title) +
      '</strong><span class="paper-meta">' +
      esc(lead.sourceName) +
      ' ' +
      dateText(lead.publishedAt) +
      '</span></a></li>' +
      rest
        .map(
          (i) =>
            '<li><a class="paper-item" href="' +
            esc(i.url) +
            '" target="_blank" rel="noopener noreferrer"><span class="paper-item-title">' +
            esc(i.title) +
            '</span><span class="paper-item-src">' +
            esc(i.sourceName) +
            '</span></a></li>',
        )
        .join('')
    : '<li class="paper-empty">今日要目暂无可读内容。</li>';
  get('#paper-foot').textContent =
    feed.sources.length + ' 个公开来源，共 ' + feed.items.length + ' 条信号';
}
function renderHighlights() {
  if (!feed) return;
  const featured = filterItems(feed.items, { category: 'news', sort: 'latest' })[0] as
    Item | undefined;
  const feature = get('#featured');
  feature.classList.remove('skeleton');
  feature.setAttribute('aria-busy', 'false');
  if (featured) {
    feature.innerHTML =
      '<div class="feature-top"><span class="feature-eyebrow"><span class="live-dot"></span> 本期值得一读</span>' +
      saveButton(featured) +
      '</div><a class="feature-title" href="' +
      esc(featured.url) +
      '" target="_blank" rel="noopener noreferrer"><h2>' +
      esc(featured.title) +
      '</h2></a><p>' +
      esc(featured.summary) +
      '</p><div class="card-tags">' +
      tagButtons(featured) +
      '</div><div class="feature-bottom"><span>' +
      esc(featured.sourceName) +
      '<span class="feature-separator">/</span>' +
      dateText(featured.publishedAt) +
      '</span><a href="' +
      esc(featured.url) +
      '" target="_blank" rel="noopener noreferrer" class="feature-read" aria-label="阅读原文：' +
      esc(featured.title) +
      '">阅读原文 ' +
      icon('arrow') +
      '</a></div>';
  } else {
    feature.innerHTML =
      '<span class="feature-eyebrow">本期值得一读</span><h2>好内容，值得等一等。</h2><p>新闻来源暂时没有可用内容。下方仍可发现已成功采集的项目，或查看来源状态。</p><button class="feature-read" data-action="sources">查看来源状态 ' +
      icon('arrow') +
      '</button>';
  }
  const trending = feed.items
    .filter((i) => i.sourceId === 'github-projects')
    .sort((a, b) => (b.metricValue ?? 0) - (a.metricValue ?? 0))
    .slice(0, 3);
  get('#trending').innerHTML = trending.length
    ? trending
        .map(
          (item, index) =>
            '<a class="trending-item" href="' +
            esc(item.url) +
            '" target="_blank" rel="noopener noreferrer"><span class="rank">0' +
            (index + 1) +
            '</span><span class="trending-info"><strong>' +
            esc(item.title.split('/').pop() || item.title) +
            '</strong><span>' +
            esc(item.title.split('/')[0] || 'GitHub') +
            '</span></span><span class="trending-stars">' +
            icon('star') +
            compact.format(item.metricValue ?? 0) +
            '</span></a>',
        )
        .join('')
    : '<p class="empty-trending">开源榜暂未同步，稍后再来看看。</p>';
  renderPaper(
    featured?.id,
    trending.map((i) => i.id),
  );
}
function renderResults() {
  get('#follow-active-tag').hidden = !tag;
  renderTabs();
  syncSaved();
  get('#china-filter').setAttribute('aria-pressed', String(chinaOnly));
  get('#active-tag').hidden = !tag;
  get('#active-tag').textContent = tag ? '标签：' + tag + ' ×' : '';
  get('#clear-filters').hidden = !(
    tag ||
    chinaOnly ||
    query ||
    category !== 'all' ||
    days ||
    savedOnly
  );
  get('#sort-note').hidden = sort !== 'hot';
  if (!feed) return;
  const filtered = filterItems(feed.items, {
    query,
    tag,
    chinaOnly,
    category,
    days,
    sort,
    savedOnly,
    saved,
  }) as Item[];
  get('#discover-title').innerHTML =
    (savedOnly ? '我的收藏' : '发现新鲜事') + '<span class="heading-dot">.</span>';
  get('#result-count').textContent =
    (savedOnly ? '收藏，' : '') +
    filtered.length +
    ' 条值得探索的信号' +
    (query ? '，搜索「' + query + '」' : '') +
    (chinaOnly ? '，中国 AI 相关' : '') +
    (tag ? '，' + tag : '');
  const grid = get('#feed-grid');
  grid.setAttribute('aria-busy', 'false');
  grid.innerHTML = filtered.length
    ? filtered.slice(0, limit).map(card).join('')
    : '<div class="empty-state">' +
      icon(savedOnly ? 'bookmark' : 'search') +
      '<h3>' +
      (savedOnly ? '还没有符合条件的收藏' : '暂时没有找到这条信号') +
      '</h3><p>' +
      (savedOnly
        ? '点击卡片右上角的书签，把感兴趣的内容留给以后。'
        : '试试其他关键词或分类；部分来源可能暂未同步。') +
      '</p><button class="secondary-button" data-action="reset">清除筛选，查看全部</button></div>';
  get('#load-more').hidden = filtered.length <= limit;
  get('#end-note').hidden = filtered.length === 0 || filtered.length > limit;
}
function renderHealth() {
  if (!feed) return;
  const failed = feed.sources.filter((s) => s.status === 'error');
  const stale = Date.now() - Date.parse(feed.generatedAt) > 36 * 3600000;
  const oldSources = feed.sources.filter(
    (s) => s.lastSuccessAt && Date.now() - Date.parse(s.lastSuccessAt) > 36 * 3600000,
  );
  get('#edition-status').innerHTML =
    (stale
      ? '快照等待更新'
      : feed.sources.length - failed.length + ' / ' + feed.sources.length + ' 来源已同步') +
    icon('chevron');
  const notice = get('#health-notice');
  notice.hidden = !failed.length && !stale && !oldSources.length;
  notice.innerHTML =
    icon('info') +
    '<span>' +
    (stale
      ? '当前快照已超过 36 小时未更新，请留意来源时间。'
      : failed.length
        ? '部分信号暂时离线：' + failed.length + ' 个来源本轮未同步，已保留可用快照。'
        : '部分来源的数据已超过 36 小时未更新。') +
    '</span><button data-action="sources">查看状态 ' +
    icon('chevron') +
    '</button>';
  get('#updated-at').textContent = '快照生成于 ' + stamp(feed.generatedAt);
  get('#source-list').innerHTML = feed.sources
    .map(
      (s) =>
        '<div class="source-row"><span class="source-avatar">' +
        icon(s.id.includes('github') ? 'code' : 'cube') +
        '</span><div class="source-detail"><a href="' +
        esc(s.homepage) +
        '" target="_blank" rel="noopener noreferrer">' +
        esc(s.name) +
        ' ' +
        icon('arrow') +
        '</a><span>最近成功：' +
        esc(stamp(s.lastSuccessAt)) +
        '</span>' +
        (s.error ? '<span class="source-error">' + esc(s.error) + '</span>' : '') +
        '</div><span class="source-status ' +
        (s.status === 'ok' ? 'success' : 'error') +
        '">' +
        (s.status === 'ok' ? s.itemCount + ' 条已同步' : '暂未同步') +
        '</span></div>',
    )
    .join('');
}
async function load() {
  if (loading) return;
  loading = true;
  const reload = document.querySelector<HTMLButtonElement>('[data-action="reload"]');
  if (reload) reload.disabled = true;
  try {
    const response = await fetch(
      import.meta.env.VITE_FEED_URL || import.meta.env.BASE_URL + 'data/feed.json',
      {
        cache: 'no-cache',
        signal: AbortSignal.timeout(15000),
      },
    );
    if (!response.ok) throw new Error('HTTP ' + response.status);
    feed = validateFeed(await response.json());
    renderHealth();
    renderHighlights();
    renderResults();
  } catch (error) {
    if (feed) {
      toast('重新加载失败，保留当前快照。');
    } else {
      get('#feed-grid').setAttribute('aria-busy', 'false');
      get('#feed-grid').innerHTML =
        '<div class="empty-state">' +
        icon('globe') +
        '<h3>信号暂时没有抵达</h3><p>网站数据加载失败，请检查网络后重试。</p><button class="secondary-button" data-action="reload">重新加载</button></div>';
      get('#result-count').textContent = '暂时无法读取数据';
      get('#edition-status').textContent = '数据加载失败';
      get('#featured').classList.remove('skeleton');
      get('#featured').setAttribute('aria-busy', 'false');
      get('#featured').innerHTML = '<h2>稍等，好内容正在路上。</h2><p>请重新加载网站快照。</p>';
      get('#trending').innerHTML = '<p class="empty-trending">等待数据加载。</p>';
      get('#paper-list').innerHTML = '<li class="paper-empty">要目暂未送达，请重新加载。</li>';
      get('#paper-foot').textContent = '';
      get('#source-list').textContent = '无法读取来源状态，请重新加载。';
      get('#updated-at').textContent = '尚未读取到可用快照';
    }
    console.error('Feed load failed', error);
  } finally {
    loading = false;
    if (reload) reload.disabled = false;
  }
}
function reset() {
  category = 'all';
  query = '';
  tag = '';
  chinaOnly = false;
  days = 0;
  sort = 'latest';
  savedOnly = false;
  limit = 12;
  get<HTMLInputElement>('#search').value = '';
  get<HTMLSelectElement>('#time-filter').value = '0';
  get<HTMLSelectElement>('#sort').value = 'latest';
  renderResults();
}
function scrollToDiscover() {
  get('#discover').scrollIntoView({
    behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
  });
}
document.addEventListener('click', (event) => {
  const target =
    event.target instanceof Element
      ? event.target.closest<HTMLButtonElement>('button[data-action]')
      : null;
  if (!target) return;
  switch (target.dataset.action) {
    case 'follow-tag':
      account.follow(tag);
      break;
    case 'china':
      chinaOnly = !chinaOnly;
      limit = 12;
      renderResults();
      break;
    case 'tag':
      tag = target.dataset.tag || '';
      limit = 12;
      renderResults();
      get('#active-tag').focus({ preventScroll: true });
      scrollToDiscover();
      break;
    case 'clear-tag':
      tag = '';
      limit = 12;
      renderResults();
      get('#china-filter').focus({ preventScroll: true });
      break;
    case 'theme':
      document.documentElement.dataset.theme =
        document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      if (!writeStorage('signal-theme', document.documentElement.dataset.theme))
        toast('主题已切换；当前浏览器无法保存偏好。');
      syncTheme();
      break;
    case 'sources':
      get<HTMLDialogElement>('#sources-dialog').showModal();
      break;
    case 'close-dialog':
      get<HTMLDialogElement>('#sources-dialog').close();
      break;
    case 'reload':
      void load();
      break;
    case 'category': {
      const next = target.dataset.category;
      if (next === 'all' || (next && Object.hasOwn(labels, next))) {
        category = next as Category | 'all';
        limit = 12;
        renderResults();
        get<HTMLButtonElement>('[data-category="' + category + '"]').focus({ preventScroll: true });
      }
      break;
    }
    case 'saved':
      if (account.requireAuth('登录后才能查看收藏。')) break;
      savedOnly = !savedOnly;
      limit = 12;
      renderResults();
      scrollToDiscover();
      break;
    case 'projects':
      reset();
      category = 'projects';
      sort = 'hot';
      get<HTMLSelectElement>('#sort').value = 'hot';
      renderResults();
      scrollToDiscover();
      break;
    case 'save': {
      const id = target.dataset.id;
      if (!id) break;
      if (account.save(id)) break;
      const saveScope = target.closest('#featured') ? '#featured' : '#feed-grid';
      if (saved.has(id)) saved.delete(id);
      else saved.add(id);
      const persisted = writeStorage('signal-saved', JSON.stringify([...saved]));
      renderHighlights();
      renderResults();
      document
        .querySelector<HTMLButtonElement>(
          saveScope + ' [data-action="save"][data-id="' + CSS.escape(id) + '"]',
        )
        ?.focus({ preventScroll: true });
      toast(
        persisted
          ? saved.has(id)
            ? '已收藏，留给有空的自己。'
            : '已取消收藏。'
          : '已更新；当前浏览器无法持久保存收藏。',
      );
      break;
    }
    case 'more': {
      const oldLimit = limit;
      limit += 12;
      renderResults();
      document
        .querySelector<HTMLAnchorElement>(
          '.news-card:nth-child(' + (oldLimit + 1) + ') .card-title',
        )
        ?.focus({ preventScroll: true });
      break;
    }
    case 'reset':
      reset();
      break;
  }
});
get<HTMLInputElement>('#search').addEventListener('input', (event) => {
  query = (event.target as HTMLInputElement).value;
  limit = 12;
  renderResults();
});
get<HTMLSelectElement>('#time-filter').addEventListener('change', (event) => {
  days = Number((event.target as HTMLSelectElement).value);
  limit = 12;
  renderResults();
});
get<HTMLSelectElement>('#sort').addEventListener('change', (event) => {
  sort = (event.target as HTMLSelectElement).value;
  limit = 12;
  renderResults();
});
document.addEventListener('keydown', (event) => {
  if (
    event.key === '/' &&
    !event.ctrlKey &&
    !event.metaKey &&
    !event.altKey &&
    !get<HTMLDialogElement>('#sources-dialog').open &&
    !get<HTMLDialogElement>('#account-dialog').open &&
    !(event.target instanceof HTMLInputElement) &&
    !(event.target instanceof HTMLTextAreaElement) &&
    !(event.target instanceof HTMLSelectElement)
  ) {
    event.preventDefault();
    get<HTMLInputElement>('#search').focus();
  }
});
get<HTMLDialogElement>('#sources-dialog').addEventListener('click', (event) => {
  const dialog = get<HTMLDialogElement>('#sources-dialog');
  if (event.target === dialog) {
    const rect = dialog.getBoundingClientRect();
    if (
      event.clientX < rect.left ||
      event.clientX > rect.right ||
      event.clientY < rect.top ||
      event.clientY > rect.bottom
    )
      dialog.close();
  }
});
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (event) => {
  if (!['dark', 'light'].includes(readStorage('signal-theme') || '')) {
    document.documentElement.dataset.theme = event.matches ? 'dark' : 'light';
    syncTheme();
  }
});
syncTheme();
renderTabs();
syncSaved();
initMotion();
const account = initAccount({
  saved(ids) {
    saved = ids === null ? readSaved() : new Set(ids);
    renderHighlights();
    renderResults();
    syncSaved();
  },
  tag(value) {
    tag = value;
    limit = 12;
    renderResults();
    scrollToDiscover();
  },
  toast,
});
void load();
