"""Workers AI — the daily editor's note.

Best-effort by contract: a missing binding or an unusable response means
"no note this edition", never a digest failure. The FFI lives in _ai_run
(monkeypatched in tests) so the rest stays plain Python.
"""
from db import env_get

# qwen1.5-14b-chat-awq left the catalog in the 2026-10 refresh; qwen3-30b-a3b
# is the strongest Chinese text-generation model on the free tier. Override
# without redeploying code via the AI_EDITOR_MODEL var.
DEFAULT_MODEL = '@cf/qwen/qwen3-30b-a3b-fp8'
SYSTEM = '你是 signal. AI 日报的编辑，用中文报纸编者按口吻写作。'
MAX_TITLES = 10
MAX_NOTE_CHARS = 200


async def _ai_run(binding, model, payload):
    """FFI boundary — to_js mirrors collector._http_fetch's proven pattern."""
    import js
    from pyodide.ffi import to_js

    return await binding.run(model, to_js(payload, dict_converter=js.Object.fromEntries))


async def editor_note(env, titles):
    """Today's top titles → a ≤120 字 Chinese editor's note. str | None."""
    binding = getattr(env, 'AI', None)  # env_get() str()-converts; the binding must stay raw
    if binding is None or not titles:
        return None
    model = env_get(env, 'AI_EDITOR_MODEL', DEFAULT_MODEL) or DEFAULT_MODEL
    prompt = (
        '根据今日以下标题，写 3-4 句中文编者按，不超过 120 字，概括今天 AI 领域的重点与基调。'
        '只依据给出的标题，不要编造具体数字或事件：\n'
        + '\n'.join('- ' + title for title in titles[:MAX_TITLES])
    )
    payload = {
        'messages': [
            {'role': 'system', 'content': SYSTEM},
            {'role': 'user', 'content': prompt},
        ],
        'max_tokens': 300,
    }
    result = await _ai_run(binding, model, payload)
    data = result.to_py() if hasattr(result, 'to_py') else result
    text = str((data or {}).get('response') or '').strip()
    if not text:
        raise ValueError('AI 空响应')
    return text[:MAX_NOTE_CHARS]
