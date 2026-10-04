from topics import enrich_item, is_china_related, search_text
from util import CATEGORY_LABELS


def item(**overrides):
    base = {
        'id': 'x', 'title': '', 'url': 'https://a.com/x', 'summary': '',
        'sourceId': 'qbitai', 'sourceName': '量子位', 'categories': ['news'],
        'tags': ['媒体报道'], 'publishedAt': None, 'updatedAt': None,
        'collectedAt': '2025-10-06T00:00:00.000Z', 'metricLabel': None,
        'metricValue': None, 'rankScore': 90,
    }
    base.update(overrides)
    return base


def test_brand_and_launch_tag():
    out = enrich_item(item(title='OpenAI 发布新模型'))
    assert 'OpenAI' in out['tags']
    assert '发布动态' in out['tags']


def test_launch_rule_only_for_news():
    out = enrich_item(item(title='发布', categories=['projects']))
    assert '发布动态' not in out['tags']
    assert '开源项目' in out['tags']


def test_models_context_tag():
    out = enrich_item(item(title='whatever', categories=['models']))
    assert '模型动态' in out['tags']


def test_china_entity_detected():
    assert is_china_related(item(title='DeepSeek 新模型')) is True
    assert is_china_related(item(sourceId='cn-official-deepseek-ai', title='irrelevant')) is True
    assert is_china_related(item(title='random news')) is False


def test_tag_cap_16_and_dedupe():
    raw = ['t%d' % i for i in range(20)] + ['媒体报道']
    out = enrich_item(item(tags=raw))
    assert len(out['tags']) == 16
    assert len(set(out['tags'])) == 16
    assert out['tags'][0] == raw[0]


def test_topic_rules():
    out = enrich_item(item(title='New MCP server for agents'))
    assert 'MCP' in out['tags']
    assert 'Agent' in out['tags']


def test_search_text_contains_label_and_lowercased():
    blob = search_text(item(title='Hello', sourceName='量子位', tags=['媒体报道'], categories=['news']))
    assert 'hello' in blob
    assert '量子位' in blob
    assert '媒体报道' in blob
    assert CATEGORY_LABELS['news'].lower() in blob
