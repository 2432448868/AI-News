"""ai — editor's note composition through the _ai_run FFI seam."""
import pytest

import ai as ai_module
from conftest import make_env, run

TITLES = ['DeepSeek 发布新模型', 'Llama 5 开源', '量子位报道']

NOW_BINDING = object()  # any truthy stand-in for env.AI


class FakeProxy:
    """js-side result shape: to_py() instead of a plain dict."""

    def __init__(self, data):
        self._data = data

    def to_py(self):
        return self._data


def patch_ai(monkeypatch, response='今日 AI 圈稳中带热。', error=None):
    calls = []

    async def fake_run(binding, model, payload):
        calls.append((model, payload))
        if error:
            raise error
        return FakeProxy({'response': response})

    monkeypatch.setattr(ai_module, '_ai_run', fake_run)
    return calls


class TestEditorNote:
    def test_returns_text(self, d1, monkeypatch):
        calls = patch_ai(monkeypatch, '注意：开源榜大变动。')
        result = run(ai_module.editor_note(make_env(d1, AI=NOW_BINDING), TITLES))
        assert result == '注意：开源榜大变动。'
        model, payload = calls[0]
        assert model == ai_module.DEFAULT_MODEL
        assert payload['messages'][0]['role'] == 'system'
        user = payload['messages'][1]['content']
        assert 'DeepSeek 发布新模型' in user and '不要编造' in user

    def test_no_binding_is_none(self, d1):
        assert run(ai_module.editor_note(make_env(d1), TITLES)) is None

    def test_no_titles_is_none(self, d1, monkeypatch):
        calls = patch_ai(monkeypatch)
        assert run(ai_module.editor_note(make_env(d1, AI=NOW_BINDING), [])) is None
        assert calls == []

    def test_empty_response_raises(self, d1, monkeypatch):
        patch_ai(monkeypatch, response=None)
        with pytest.raises(ValueError, match='空响应'):
            run(ai_module.editor_note(make_env(d1, AI=NOW_BINDING), TITLES))

    def test_model_override(self, d1, monkeypatch):
        calls = patch_ai(monkeypatch)
        run(ai_module.editor_note(
            make_env(d1, AI=NOW_BINDING, AI_EDITOR_MODEL='@cf/meta/llama-3.1-8b-instruct'), TITLES))
        assert calls[0][0] == '@cf/meta/llama-3.1-8b-instruct'

    def test_titles_capped_at_ten(self, d1, monkeypatch):
        calls = patch_ai(monkeypatch)
        run(ai_module.editor_note(make_env(d1, AI=NOW_BINDING), ['t%d' % i for i in range(11)]))
        user = calls[0][1]['messages'][1]['content']
        assert user.count('- t') == ai_module.MAX_TITLES
        assert '- t10' not in user

    def test_long_text_truncated(self, d1, monkeypatch):
        patch_ai(monkeypatch, response='长' * 500)
        result = run(ai_module.editor_note(make_env(d1, AI=NOW_BINDING), TITLES))
        assert len(result) == ai_module.MAX_NOTE_CHARS

    def test_no_think_switch_and_budget(self, d1, monkeypatch):
        calls = patch_ai(monkeypatch)
        run(ai_module.editor_note(make_env(d1, AI=NOW_BINDING), TITLES))
        system = calls[0][1]['messages'][0]['content']
        assert system.endswith('/no_think')
        assert calls[0][1]['max_tokens'] == 1024

    def test_think_block_is_stripped(self, d1, monkeypatch):
        patch_ai(monkeypatch, response='<think>推理过程</think>今日看点：开源强势。')
        result = run(ai_module.editor_note(make_env(d1, AI=NOW_BINDING), TITLES))
        assert result == '今日看点：开源强势。'

    def test_truncated_think_falls_back_to_choices(self, d1, monkeypatch):
        async def fake_run(binding, model, payload):
            return FakeProxy({
                'response': '<think>没想完就被截断',
                'choices': [{'message': {'content': '编者按正文。'}}],
            })
        monkeypatch.setattr(ai_module, '_ai_run', fake_run)
        result = run(ai_module.editor_note(make_env(d1, AI=NOW_BINDING), TITLES))
        assert result == '编者按正文。'
