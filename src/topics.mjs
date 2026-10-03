/** Deterministic, free tagging. Labels describe mentions, not endorsements or origin. */
const entities = [
  ['ChatGPT', /\bchatgpt\b/i, false],
  ['OpenAI', /\bopenai\b/i, false],
  ['Claude', /\bclaude\b/i, false],
  ['Anthropic', /\banthropic\b/i, false],
  ['Gemini', /\bgemini\b/i, false],
  ['DeepMind', /\bdeepmind\b/i, false],
  ['DeepSeek', /\bdeepseek(?:[-_][\w.-]+)?\b|深度求索/i, true],
  ['通义千问', /\bqwen(?:[\d._-][\w.-]*)?\b|\bqwenlm\b|通义|千问/i, true],
  ['Kimi', /\b(?:kimi|moonshotai|moonshot)(?:[-_][\w.-]+)?\b|月之暗面/i, true],
  ['智谱 GLM', /\b(?:glm[-_]?\d[\w.-]*|chatglm[\w.-]*|zhipu|zai-org)\b|智谱/i, true],
  ['MiniMax', /\bminimax(?:[-_][\w.-]+)?\b|海螺/i, true],
  ['豆包', /\bdoubao\b|豆包/i, true],
  ['Seedance', /\bseedance\b/i, true],
  ['字节跳动', /\bbytedance\b|字节跳动/i, true],
  ['腾讯混元', /\bhunyuan\b|混元/i, true],
  ['腾讯', /\btencent\b|腾讯/i, true],
  ['文心 ERNIE', /\bernie\b|文心/i, true],
  ['百度', /\b(?:paddlepaddle|baidu)\b|百度/i, true],
  ['可灵', /\bkling\b|可灵/i, true],
  ['宇树', /\bunitree\b|宇树/i, true],
  ['科大讯飞', /\biflytek\b|科大讯飞|讯飞星火/i, true],
  ['昇腾', /\bascend\b|昇腾|华为/i, true],
];
const topics = [
  ['Agent', /\bagents?\b|智能体/i],
  ['Skills', /\bskills?\b/i],
  ['MCP', /\bmcp\b|model context protocol/i],
  ['AI 编程', /\bcoding\b|\bcode assistant\b|编程|代码助手/i],
  ['图像生成', /text-to-image|image generation|文生图|图像生成/i],
  ['视频生成', /text-to-video|video generation|视频生成|文生视频/i],
  ['语音', /text-to-speech|speech|语音/i],
  ['多模态', /multimodal|多模态/i],
  ['研究进展', /\barxiv\b|\bresearch\b|论文/i],
  ['访谈', /\binterview\b|访谈/i],
  ['教程', /\btutorial\b|\bhow to\b|教程|实战指南/i],
];
function evidence(item) {
  return [item.title, item.summary, ...item.tags].join(' ');
}
export function isChinaRelated(item) {
  return (
    /^cn-official-/.test(item.sourceId) ||
    entities.some(([, rule, china]) => china && rule.test(evidence(item)))
  );
}
export function enrichItem(item) {
  const text = evidence(item);
  const brands = entities.filter(([, rule]) => rule.test(text)).map(([label]) => label);
  const focus = topics.filter(([, rule]) => rule.test(text)).map(([label]) => label);
  if (
    item.categories.includes('news') &&
    /发布|首发|上新|\b(?:launch|launches|released|introducing)\b/i.test(item.title)
  )
    focus.push('发布动态');
  const context = item.categories.includes('projects')
    ? ['开源项目']
    : item.categories.includes('models')
      ? ['模型动态']
      : [];
  return {
    ...item,
    tags: [...new Set([...brands, ...focus, ...context, ...item.tags])].slice(0, 16),
  };
}
