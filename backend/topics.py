"""Port of src/topics.mjs — deterministic, free tagging.

Labels describe mentions, not endorsements or origin.
"""
import re

from util import CATEGORY_LABELS

# (label, rule, china) — identical order and semantics to the JS source.
ENTITIES = [
    ('ChatGPT', re.compile(r'\bchatgpt\b', re.I), False),
    ('OpenAI', re.compile(r'\bopenai\b', re.I), False),
    ('Claude', re.compile(r'\bclaude\b', re.I), False),
    ('Anthropic', re.compile(r'\banthropic\b', re.I), False),
    ('Gemini', re.compile(r'\bgemini\b', re.I), False),
    ('DeepMind', re.compile(r'\bdeepmind\b', re.I), False),
    ('DeepSeek', re.compile(r'\bdeepseek(?:[-_][\w.-]+)?\b|深度求索', re.I), True),
    ('通义千问', re.compile(r'\bqwen(?:[\d._-][\w.-]*)?\b|\bqwenlm\b|通义|千问', re.I), True),
    ('Kimi', re.compile(r'\b(?:kimi|moonshotai|moonshot)(?:[-_][\w.-]+)?\b|月之暗面', re.I), True),
    ('智谱 GLM', re.compile(r'\b(?:glm[-_]?\d[\w.-]*|chatglm[\w.-]*|zhipu|zai-org)\b|智谱', re.I), True),
    ('MiniMax', re.compile(r'\bminimax(?:[-_][\w.-]+)?\b|海螺', re.I), True),
    ('豆包', re.compile(r'\bdoubao\b|豆包', re.I), True),
    ('Seedance', re.compile(r'\bseedance\b', re.I), True),
    ('字节跳动', re.compile(r'\bbytedance\b|字节跳动', re.I), True),
    ('腾讯混元', re.compile(r'\bhunyuan\b|混元', re.I), True),
    ('腾讯', re.compile(r'\btencent\b|腾讯', re.I), True),
    ('文心 ERNIE', re.compile(r'\bernie\b|文心', re.I), True),
    ('百度', re.compile(r'\b(?:paddlepaddle|baidu)\b|百度', re.I), True),
    ('可灵', re.compile(r'\bkling\b|可灵', re.I), True),
    ('宇树', re.compile(r'\bunitree\b|宇树', re.I), True),
    ('科大讯飞', re.compile(r'\biflytek\b|科大讯飞|讯飞星火', re.I), True),
    ('昇腾', re.compile(r'\bascend\b|昇腾|华为', re.I), True),
]

TOPICS = [
    ('Agent', re.compile(r'\bagents?\b|智能体', re.I)),
    ('Skills', re.compile(r'\bskills?\b', re.I)),
    ('MCP', re.compile(r'\bmcp\b|model context protocol', re.I)),
    ('AI 编程', re.compile(r'\bcoding\b|\bcode assistant\b|编程|代码助手', re.I)),
    ('图像生成', re.compile(r'text-to-image|image generation|文生图|图像生成', re.I)),
    ('视频生成', re.compile(r'text-to-video|video generation|视频生成|文生视频', re.I)),
    ('语音', re.compile(r'text-to-speech|speech|语音', re.I)),
    ('多模态', re.compile(r'multimodal|多模态', re.I)),
    ('研究进展', re.compile(r'\barxiv\b|\bresearch\b|论文', re.I)),
    ('访谈', re.compile(r'\binterview\b|访谈', re.I)),
    ('教程', re.compile(r'\btutorial\b|\bhow to\b|教程|实战指南', re.I)),
]

_LAUNCH_RE = re.compile(r'发布|首发|上新|\b(?:launch|launches|released|introducing)\b', re.I)


def _evidence(item):
    return ' '.join([item.get('title', '') or '', item.get('summary', '') or '', *item.get('tags', [])])


def is_china_related(item):
    if str(item.get('sourceId', '')).startswith('cn-official-'):
        return True
    text = _evidence(item)
    return any(rule.search(text) for _, rule, china in ENTITIES if china)


def enrich_item(item):
    text = _evidence(item)
    brands = [label for label, rule, _ in ENTITIES if rule.search(text)]
    focus = [label for label, rule in TOPICS if rule.search(text)]
    categories = item.get('categories', [])
    if 'news' in categories and _LAUNCH_RE.search(item.get('title', '') or ''):
        focus.append('发布动态')
    if 'projects' in categories:
        context = ['开源项目']
    elif 'models' in categories:
        context = ['模型动态']
    else:
        context = []
    merged = dict.fromkeys([*brands, *focus, *context, *item.get('tags', [])])
    return {**item, 'tags': list(merged)[:16]}


def search_text(item):
    """Precomputed lowercase blob for SQL LIKE search (mirrors filterItems' join)."""
    parts = [
        item.get('title', '') or '',
        item.get('summary', '') or '',
        item.get('sourceName', '') or '',
        *item.get('tags', []),
        *[CATEGORY_LABELS.get(c, c) for c in item.get('categories', [])],
    ]
    return ' '.join(parts).lower()
