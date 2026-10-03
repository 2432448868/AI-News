import { readFile, writeFile, mkdir, rename } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  fetchText,
  normalizeGithub,
  normalizeHf,
  normalizeRss,
  mergeResults,
} from './collector-core.mjs';
import { validateFeed } from '../src/data.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const output = resolve(root, 'public/data/feed.json');
const cache = resolve(root, '.cache/feed.json');
const now = new Date().toISOString();
const recent = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
const ghQuery = (q) =>
  'https://api.github.com/search/repositories?' +
  new URLSearchParams({ q, sort: 'stars', order: 'desc', per_page: '30' });
const sources = [
  {
    id: 'github-projects',
    name: 'GitHub',
    homepage: 'https://github.com/topics/llm',
    kind: 'github',
    url: ghQuery('topic:llm pushed:>=' + recent + ' archived:false fork:false stars:>50'),
  },
  {
    id: 'github-skills',
    name: 'GitHub Skills',
    homepage: 'https://github.com/topics/agent-skills',
    kind: 'github',
    url: ghQuery('topic:agent-skills pushed:>=' + recent + ' archived:false fork:false stars:>5'),
  },
  {
    id: 'github-apps',
    name: 'GitHub Demos',
    homepage: 'https://github.com/topics/gradio',
    kind: 'github',
    url: ghQuery(
      'topic:gradio pushed:>=' +
        recent +
        ' archived:false fork:false stars:>50 -repo:gradio-app/gradio',
    ),
  },
  {
    id: 'hf-models',
    name: 'Hugging Face Models',
    homepage: 'https://huggingface.co/models',
    kind: 'hf',
    url: 'https://huggingface.co/api/models?sort=trendingScore&limit=30&full=true',
  },
  {
    id: 'hf-spaces',
    name: 'Hugging Face Spaces',
    homepage: 'https://huggingface.co/spaces',
    kind: 'hf',
    url: 'https://huggingface.co/api/spaces?sort=trendingScore&limit=30&full=true',
  },
  {
    id: 'hf-blog',
    name: 'Hugging Face Blog',
    homepage: 'https://huggingface.co/blog',
    kind: 'rss',
    url: 'https://huggingface.co/blog/feed.xml',
  },
  {
    id: 'github-blog',
    name: 'GitHub Blog',
    homepage: 'https://github.blog/ai-and-ml/',
    kind: 'rss',
    url: 'https://github.blog/ai-and-ml/feed/',
  },
];
let previous = null;
for (const path of [cache, output]) {
  try {
    previous = validateFeed(JSON.parse(await readFile(path, 'utf8')));
    break;
  } catch (error) {
    if (error.code !== 'ENOENT') console.warn('忽略无效快照：' + path);
  }
}
const results = [];
// Two API searches are sequential to avoid search endpoint burst limits.
for (const source of sources) {
  try {
    const headers =
      source.kind === 'github'
        ? {
            Accept: 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            ...(process.env.GITHUB_TOKEN
              ? { Authorization: 'Bearer ' + process.env.GITHUB_TOKEN }
              : {}),
          }
        : {};
    const raw = await fetchText(source.url, { headers });
    const items =
      source.kind === 'rss'
        ? normalizeRss(raw, source, now)
        : source.kind === 'github'
          ? normalizeGithub(JSON.parse(raw), source, now)
          : normalizeHf(JSON.parse(raw), source, now);
    if (!items.length) throw new Error('本次没有有效条目');
    results.push({ source, ok: true, items });
    console.log(source.id + ': ' + items.length + ' 条');
  } catch (error) {
    results.push({ source, ok: false, items: [], error: error.message });
    console.warn(source.id + ': ' + error.message);
  }
}
const feed = mergeResults(previous, results, now);
for (const path of [output, cache]) {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path + '.tmp', JSON.stringify(feed, null, 2) + '\n');
  await rename(path + '.tmp', path);
}
console.log(
  '快照已更新：' +
    feed.items.length +
    ' 条；' +
    feed.sources.filter((s) => s.status === 'ok').length +
    '/' +
    sources.length +
    ' 来源成功',
);
if (process.env.GITHUB_STEP_SUMMARY) {
  await writeFile(
    process.env.GITHUB_STEP_SUMMARY,
    '## 采集状态\n\n' +
      feed.sources
        .map(
          (s) =>
            '- ' +
            s.name +
            ': ' +
            s.status +
            ' (' +
            s.itemCount +
            ' 条)' +
            (s.error ? ' — ' + s.error : ''),
        )
        .join('\n') +
      '\n',
    { flag: 'a' },
  );
}
