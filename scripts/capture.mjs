import { chromium } from 'playwright';
const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH || undefined,
  headless: true,
});
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1080 },
    deviceScaleFactor: 1,
  });
  await page.goto('http://127.0.0.1:4173/AI-News/');
  await page.locator('.news-card').first().waitFor();
  await page.screenshot({ path: 'artifacts/desktop-light.png', fullPage: true });
  await page.locator('#theme-toggle').click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: 'artifacts/desktop-dark.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('#theme-toggle').click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: 'artifacts/mobile-light.png', fullPage: true });
  console.log('Captured real snapshot in 3 layouts');
} finally {
  await browser.close();
}
