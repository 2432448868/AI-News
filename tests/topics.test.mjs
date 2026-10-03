import test from 'node:test';
import assert from 'node:assert/strict';
import { enrichItem, isChinaRelated } from '../src/topics.mjs';
import { filterItems } from '../src/data.mjs';
import { normalizeGithub, normalizeRss } from '../scripts/collector-core.mjs';
const item = (title, extra = {}) => ({
  id: title,
  title,
  summary: '',
  tags: [],
  categories: ['news'],
  sourceId: 'media',
  sourceName: '媒体',
  publishedAt: '2026-10-03T00:00:00Z',
  updatedAt: null,
  rankScore: 1,
  ...extra,
});
test('entity and focus labels use evidence and are idempotent', () => {
  const tagged = enrichItem(item('ChatGPT 发布编程教程'));
  assert.deepEqual(tagged.tags, ['ChatGPT', 'AI 编程', '教程', '发布动态']);
  assert.deepEqual(enrichItem(tagged), tagged);
  assert.equal(isChinaRelated(tagged), false);
  assert.ok(enrichItem(item('unknown', { tags: ['chatgpt'] })).tags.includes('ChatGPT'));
});
test('Chinese aliases and model versions match without generic false positives', () => {
  for (const title of [
    'DeepSeek-V3',
    'Qwen3.5',
    'QwenLM/qwen-code',
    'MoonshotAI/Kimi-K2',
    'GLM-4.6',
    '智谱新模型',
  ])
    assert.equal(isChinaRelated(item(title)), true, title);
  for (const title of [
    '中文新闻 OpenAI 发布模型',
    'generalized linear model glm',
    'climimax',
    'GPT tool',
    'deepseekish',
  ])
    assert.equal(isChinaRelated(item(title)), false, title);
  assert.equal(isChinaRelated(item('helper', { sourceId: 'cn-official-deepseek-ai' })), true);
});
test('tag China category saved and search filters combine', () => {
  const items = [
    enrichItem(item('DeepSeek coding', { categories: ['projects'] })),
    enrichItem(item('ChatGPT coding')),
  ];
  assert.equal(
    filterItems(items, {
      chinaOnly: true,
      tag: 'AI 编程',
      category: 'projects',
      query: 'deepseek',
      savedOnly: true,
      saved: new Set(['DeepSeek coding']),
    }).length,
    1,
  );
  assert.equal(filterItems(items, { chinaOnly: true, tag: 'ChatGPT' }).length, 0);
  assert.equal(filterItems(items).length, 2);
});
test('official repositories retain project semantics and exclude stale forks', () => {
  const repo = {
    html_url: 'https://github.com/QwenLM/test',
    full_name: 'QwenLM/test',
    pushed_at: '2026-10-02T00:00:00Z',
  };
  const result = normalizeGithub(
    { items: [repo, { ...repo, fork: true }, { ...repo, pushed_at: '2020-01-01T00:00:00Z' }] },
    { id: 'cn-official-QwenLM', name: 'QwenLM', kind: 'github-org' },
    '2026-10-03T00:00:00Z',
  );
  assert.equal(result.length, 1);
  assert.deepEqual(result[0].categories, ['projects']);
});
test('Chinese media is never mislabeled as official blog', () => {
  const rows = normalizeRss(
    '<rss><channel><item><title>智谱模型更新</title><link>https://example.com/news</link><pubDate>2026-10-02</pubDate></item></channel></rss>',
    { id: 'qbitai', name: '量子位', media: true },
    '2026-10-03T00:00:00Z',
  );
  assert.deepEqual(rows[0].tags, ['媒体报道']);
  assert.ok(rows[0].categories.includes('models'));
});

test('company mentions do not imply a specific product', () => {
  const tagged = enrichItem(item('bytedance/deer-flow and Anthropic research'));
  assert.ok(tagged.tags.includes('字节跳动'));
  assert.ok(tagged.tags.includes('Anthropic'));
  assert.ok(!tagged.tags.includes('豆包'));
  assert.ok(!tagged.tags.includes('Claude'));
});
