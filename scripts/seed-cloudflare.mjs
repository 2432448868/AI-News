import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { validateFeed } from '../src/data.mjs';
const config = JSON.parse(await readFile(new URL('../wrangler.json', import.meta.url), 'utf8'));
const response = await fetch(config.vars.FEED_URL, { signal: AbortSignal.timeout(30000) });
if (!response.ok) throw new Error('Upstream HTTP ' + response.status);
const feed = validateFeed(await response.json());
if (!feed.items.length) throw new Error('Empty snapshot');
await mkdir('.cache', { recursive: true });
await writeFile('.cache/cloudflare-seed.json', JSON.stringify(feed));
execFileSync(
  process.execPath,
  [
    'node_modules/wrangler/bin/wrangler.js',
    'kv',
    'key',
    'put',
    'feed:latest',
    '--path',
    '.cache/cloudflare-seed.json',
    '--binding',
    'NEWS',
    '--remote',
    '--metadata',
    JSON.stringify({ generatedAt: feed.generatedAt, itemCount: feed.items.length }),
  ],
  { stdio: 'inherit' },
);
console.log('Seeded ' + feed.items.length + ' items; generatedAt=' + feed.generatedAt);
