import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { readFile } from 'node:fs/promises';
const fixture = JSON.parse(
  await readFile(new URL('../../public/data/feed.json', import.meta.url), 'utf8'),
);
async function mock(page, { loggedIn = true, available = true, failWrite = false } = {}) {
  let session = {
    available,
    user: loggedIn ? { id: '123', login: 'reader', displayName: '测试读者' } : null,
    favorites: [],
    tags: [],
    csrf: 'test-csrf',
  };
  const writes = [];
  await page.addInitScript(() =>
    localStorage.setItem('signal-saved', JSON.stringify(['local-only'])),
  );
  await page.route('**/api/feed', (route) => route.fulfill({ json: fixture }));
  await page.route('**/api/auth/session', (route) => route.fulfill({ json: session }));
  await page.route('**/api/user/**', async (route) => {
    const request = route.request();
    const body = request.postDataJSON();
    writes.push({ path: new URL(request.url()).pathname, body });
    expect(request.headers()['x-csrf-token']).toBe('test-csrf');
    if (failWrite) return route.fulfill({ status: 503, json: { error: '同步失败，请重试。' } });
    if (request.url().endsWith('/favorites'))
      session.favorites = body.saved
        ? [...new Set([...session.favorites, body.id])]
        : session.favorites.filter((id) => id !== body.id);
    if (request.url().endsWith('/profile')) session.user.displayName = body.displayName;
    if (request.url().endsWith('/tags'))
      session.tags = body.followed
        ? [...new Set([...session.tags, body.tag])]
        : session.tags.filter((tag) => tag !== body.tag);
    await route.fulfill({ json: session });
  });
  await page.route('**/api/auth/logout', (route) => {
    expect(route.request().method()).toBe('POST');
    session = { available: true, user: null, favorites: [], tags: [] };
    return route.fulfill({ json: {} });
  });
  await page.goto('./');
  await expect(page.locator('#feed-grid')).toHaveAttribute('aria-busy', 'false');
  await expect(page.locator('#account-button')).toHaveText(loggedIn ? '测试读者' : '我的账户');
  return { writes };
}
async function open(page) {
  await page.locator('#account-button').click();
  await expect(page.locator('#account-dialog')).toBeVisible();
}

test('configured guest sees GitHub login and local records are not uploaded', async ({ page }) => {
  const { writes } = await mock(page, { loggedIn: false });
  await open(page);
  await expect(page.getByRole('link', { name: /使用 GitHub 登录/ })).toHaveAttribute(
    'href',
    '/api/auth/github',
  );
  expect(writes).toEqual([]);
  await expect(page.locator('#account-content')).toContainText('不会自动上传');
});
test('unconfigured account is explicit and modal is accessible without horizontal overflow', async ({
  page,
}) => {
  await mock(page, { loggedIn: false, available: false });
  await open(page);
  await expect(page.locator('#account-content')).toContainText('管理员尚未启用');
  await expect(page.getByRole('link', { name: /使用 GitHub 登录/ })).toHaveCount(0);
  expect((await new AxeBuilder({ page }).include('#account-dialog').analyze()).violations).toEqual(
    [],
  );
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.keyboard.press('Escape');
  await expect(page.locator('#account-dialog')).not.toBeVisible();
});
test('cloud favorites wait for server success, persist on refresh, and stay out of localStorage', async ({
  page,
}) => {
  const { writes } = await mock(page);
  const save = page.locator('.news-card button[data-action="save"]').first();
  await save.click();
  await expect(page.locator('#saved-count')).toHaveText('1');
  expect(writes[0].path).toBe('/api/user/favorites');
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('signal-saved')))).toEqual([
    'local-only',
  ]);
  await page.reload();
  await expect(page.locator('#saved-count')).toHaveText('1');
});
test('profile is escaped, followed tags support quick filtering, logout restores local favorites', async ({
  page,
}) => {
  await mock(page);
  await open(page);
  await page.locator('#display-name').fill('<img src=x onerror=alert(1)>');
  await page.locator('#profile-form button').click();
  await expect(page.locator('#account-status')).toHaveText('昵称已保存。');
  await expect(page.locator('#account-content img')).toHaveCount(0);
  await page.locator('#follow-tag').fill('DeepSeek');
  await page.locator('#tag-form button').click();
  await expect(page.locator('#account-status')).toHaveText('已关注标签。');
  await page
    .locator('#account-content')
    .getByRole('button', { name: 'DeepSeek', exact: true })
    .click();
  await expect(page.locator('#active-tag')).toContainText('DeepSeek');
  await open(page);
  await page.getByRole('button', { name: '退出登录' }).click();
  await expect(page.locator('#saved-count')).toHaveText('1');
  await expect(page.locator('#account-button')).toHaveText('我的账户');
});
test('failed cloud writes do not falsely change saved state', async ({ page }) => {
  await mock(page, { failWrite: true });
  await page.locator('.news-card button[data-action="save"]').first().click();
  await expect(page.locator('#toast')).toHaveText('同步失败，请重试。');
  await expect(page.locator('#saved-count')).toHaveText('0');
});
test('authenticated account panel passes accessibility checks', async ({ page }) => {
  await mock(page);
  await open(page);
  await expect(page.locator('#display-name')).toBeVisible();
  expect((await new AxeBuilder({ page }).include('#account-dialog').analyze()).violations).toEqual(
    [],
  );
});
