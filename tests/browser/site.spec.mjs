import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
const now = new Date().toISOString();
const categories = ['news', 'projects', 'skills', 'models', 'tips', 'apps', 'dev'];
const fixture = {
  schemaVersion: 1,
  generatedAt: now,
  sources: [
    {
      id: 'test-source',
      name: 'Fixture Source',
      homepage: 'https://example.com',
      status: 'ok',
      lastSuccessAt: now,
      itemCount: 28,
      error: null,
    },
  ],
  items: Array.from({ length: 28 }, (_, i) => ({
    id: 'test-' + i,
    title:
      i === 0 ? 'How to build a useful AI project' : 'Test signal ' + String(i).padStart(2, '0'),
    summary: 'Test-only content for deterministic interaction checks.',
    url: 'https://example.com/news/' + i,
    sourceId: 'test-source',
    sourceName: 'Fixture Source',
    categories: [categories[i % 7]],
    tags: ['test'],
    publishedAt: new Date(Date.now() - i * 12 * 3600000).toISOString(),
    updatedAt: null,
    collectedAt: now,
    rankScore: 100 - i,
    metricValue: i % 7 === 1 ? 1000 + i : null,
    metricLabel: i % 7 === 1 ? 'stars' : null,
  })),
};
async function mock(page, data = fixture) {
  await page.route('**/data/feed.json', (route) => route.fulfill({ json: data }));
  await page.goto('./');
  await expect(page.locator('#feed-grid')).toHaveAttribute('aria-busy', 'false');
}

test('real snapshot loads under the GitHub Pages project subpath without missing assets or runtime errors', async ({
  page,
}) => {
  const errors = [];
  const bad = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('response', (r) => {
    if (r.url().startsWith('http://127.0.0.1') && r.status() >= 400) bad.push(r.url());
  });
  await page.goto('./');
  await expect(page.locator('.news-card').first()).toBeVisible();
  await expect(page.locator('#updated-at')).toContainText('快照生成于');
  expect(errors).toEqual([]);
  expect(bad).toEqual([]);
  for (const link of await page
    .locator('.card-title')
    .evaluateAll((nodes) => nodes.map((n) => ({ href: n.href, rel: n.rel, target: n.target })))) {
    expect(link.href).toMatch(/^https:\/\//);
    expect(link.rel).toContain('noopener');
    expect(link.target).toBe('_blank');
  }
});
test('category, search, time filter and clear can be combined', async ({ page }) => {
  await mock(page);
  await page.locator('[data-category="skills"]').click();
  await expect(page.locator('.news-card')).toHaveCount(4);
  await page.locator('#search').fill('Test signal 02');
  await expect(page.locator('.news-card')).toHaveCount(1);
  await page.locator('#time-filter').selectOption('1');
  await expect(page.locator('.empty-state')).toBeVisible();
  await page.getByRole('button', { name: '清除筛选，查看全部' }).click();
  await expect(page.locator('.news-card')).toHaveCount(12);
  await expect(page.locator('#search')).toHaveValue('');
});
test('pagination appends results and category changes reset the page size', async ({ page }) => {
  await mock(page);
  await page.locator('#load-more').click();
  await expect(page.locator('.news-card')).toHaveCount(24);
  await page.locator('[data-category="news"]').click();
  await expect(page.locator('.news-card')).toHaveCount(4);
  await page.locator('[data-category="all"]').click();
  await expect(page.locator('.news-card')).toHaveCount(12);
});
test('sorting shows ranking disclaimer', async ({ page }) => {
  await mock(page);
  await page.locator('#sort').selectOption('hot');
  await expect(page.locator('#sort-note')).toBeVisible();
  await page.locator('#sort').selectOption('latest');
  await expect(page.locator('#sort-note')).toBeHidden();
});
test('bookmark persists after reload and can be removed from saved view', async ({ page }) => {
  await mock(page);
  await page.locator('.news-card .save-button').first().click();
  await expect(page.locator('#saved-count')).toHaveText('1');
  await page.reload();
  await expect(page.locator('#saved-count')).toHaveText('1');
  await page.locator('.top-nav [data-action="saved"]').click();
  await expect(page.locator('.news-card')).toHaveCount(1);
  await page.locator('.news-card .save-button').click();
  await expect(page.locator('.empty-state h3')).toContainText('收藏');
  await expect(page.locator('#saved-count')).toHaveText('0');
});
test('theme follows system initially, toggles, and persists across reload', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' });
  await mock(page);
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await page.locator('#theme-toggle').click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(page.locator('#theme-toggle')).toHaveAttribute('aria-label', '切换浅色模式');
});
test('source dialog opens and escape closes it', async ({ page }) => {
  await mock(page);
  await page.locator('#edition-status').click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.locator('#source-list')).toContainText('Fixture Source');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toBeHidden();
});
test('partial failure and stale snapshot are visible', async ({ page }) => {
  const data = structuredClone(fixture);
  data.generatedAt = '2025-01-01T00:00:00Z';
  data.sources[0].status = 'error';
  data.sources[0].error = 'Network unavailable';
  await mock(page, data);
  await expect(page.locator('#health-notice')).toContainText('36 小时');
  await page.locator('#edition-status').click();
  await expect(page.locator('#source-list')).toContainText('Network unavailable');
  await expect(page.locator('.source-status')).toContainText('暂未同步');
});
test('failed first load offers a working retry', async ({ page }) => {
  let fail = true;
  await page.route('**/data/feed.json', (route) =>
    fail ? route.fulfill({ status: 503, body: 'unavailable' }) : route.fulfill({ json: fixture }),
  );
  await page.goto('./');
  await expect(page.locator('.empty-state')).toContainText('信号暂时没有抵达');
  fail = false;
  await page.locator('.empty-state button').click();
  await expect(page.locator('.news-card')).toHaveCount(12);
});
test('malicious feed text is inert and unsafe URLs reject the snapshot', async ({ page }) => {
  const data = structuredClone(fixture);
  data.items[0].title = '<img src=x onerror="window.injected=true">';
  await mock(page, data);
  await expect(page.locator('.card-title').first()).toContainText('<img');
  expect(await page.evaluate(() => window.injected)).toBeUndefined();
  expect(await page.locator('.news-card img').count()).toBe(0);
  data.items[0].url = 'javascript:alert(1)';
  await page.reload();
  await expect(page.locator('.empty-state')).toContainText('信号暂时没有抵达');
});
test('corrupt or blocked storage does not prevent rendering', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('signal-saved', '{bad');
    localStorage.setItem('signal-theme', 'invalid');
  });
  await mock(page);
  await expect(page.locator('#saved-count')).toHaveText('0');
  await page.evaluate(() => {
    Storage.prototype.setItem = () => {
      throw new Error('blocked');
    };
  });
  await page.locator('.news-card .save-button').first().click();
  await expect(page.locator('#toast')).toContainText('无法持久保存');
});
test('empty valid feed has an honest empty state', async ({ page }) => {
  await mock(page, { ...fixture, items: [] });
  await expect(page.locator('.empty-state')).toBeVisible();
  await expect(page.locator('#load-more')).toBeHidden();
});
test('mobile widths never overflow and reduced motion is respected', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await mock(page);
  for (const width of [360, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
  }
  expect(
    await page
      .locator('.hero-paper .live-dot')
      .evaluate((el) => getComputedStyle(el).animationName),
  ).toBe('none');
});
test('keyboard search shortcut and dialog accessibility', async ({ page }) => {
  await mock(page);
  await page.keyboard.press('/');
  await expect(page.locator('#search')).toBeFocused();
  await page.locator('#edition-status').click();
  await expect(page.getByRole('dialog')).toHaveAttribute('aria-labelledby', 'sources-title');
  await page.keyboard.press('Escape');
  await expect(page.locator('#edition-status')).toBeFocused();
});
test('light and dark views pass automated WCAG A/AA checks', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' });
  await mock(page);
  let result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(result.violations).toEqual([]);
  await page.locator('#theme-toggle').click();
  await page.waitForTimeout(350);
  result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(result.violations).toEqual([]);
});

test('reading progress follows scrolling without blocking content', async ({ page }) => {
  await mock(page);
  const progress = page.locator('.reading-progress');
  await expect(progress).toHaveAttribute('aria-hidden', 'true');
  await page.evaluate(() =>
    window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' }),
  );
  await expect
    .poll(() =>
      progress.evaluate((el) =>
        Number(getComputedStyle(el).transform.split('(')[1]?.split(',')[0]),
      ),
    )
    .toBeGreaterThan(0.9);
  await expect(page.locator('.site-header')).toHaveClass(/is-scrolled/);
});
test('pointer decoration respects touch and reduced-motion preferences', async ({
  page,
  isMobile,
}) => {
  await mock(page);
  const hero = page.locator('.hero');
  await hero.hover();
  if (!isMobile) await expect(hero).toHaveClass(/pointer-active/);
  else await expect(hero).not.toHaveClass(/pointer-active/);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect(hero).not.toHaveClass(/pointer-active/);
  expect(
    await page
      .locator('.hero-paper .live-dot')
      .evaluate((el) => getComputedStyle(el).animationName),
  ).toBe('none');
  expect(
    await page.evaluate(
      () => document.getAnimations().filter((a) => a.playState === 'running').length,
    ),
  ).toBe(0);
  await expect(page.locator('.news-card').first()).toBeVisible();
});

test('entity tags and China focus combine, clear and preserve keyboard focus', async ({ page }) => {
  const data = structuredClone(fixture);
  data.items[0].title = 'ChatGPT 发布编程教程';
  data.items[1].title = 'DeepSeek 新模型';
  data.items[2].title = 'Qwen3 Agent Skills';
  await mock(page, data);
  await expect(page.locator('#featured .topic-tag').first()).toHaveText('ChatGPT');
  await page.locator('#china-filter').click();
  await expect(page.locator('.news-card')).toHaveCount(2);
  await page.locator('#feed-grid [data-tag="DeepSeek"]').click();
  await expect(page.locator('.news-card')).toHaveCount(1);
  await expect(page.locator('#active-tag')).toBeFocused();
  await page.locator('[data-category="skills"]').click();
  await expect(page.locator('.empty-state')).toBeVisible();
  await page.locator('#active-tag').click();
  await expect(page.locator('.news-card')).toHaveCount(1);
  await page.locator('#clear-filters').click();
  await expect(page.locator('.news-card')).toHaveCount(12);
  await expect(page.locator('#china-filter')).toHaveAttribute('aria-pressed', 'false');
  await expect(page.locator('#active-tag')).toBeHidden();
});
