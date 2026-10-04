"""Worker entry — the ONLY JS/FFI boundary.

Everything below the request/response dicts is pure Python (backend.api,
backend.auth, backend.collector) so the whole app is testable off-platform.
"""
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from workers import WorkerEntrypoint

import js
from js import Headers, Response
from pyodide.ffi import to_js

from api import handle_api
from auth import handle_account_request
from collector import run_collection

_INTERNAL_ERROR = {
    'status': 500,
    'headers': [('Content-Type', 'application/json; charset=utf-8'), ('Cache-Control', 'no-store')],
    'body': '{"error":"Internal error"}',
}


def parse_query(raw):
    query = {}
    for key, value in parse_qsl(raw, keep_blank_values=True):
        query.setdefault(key, value)  # JS URLSearchParams.get() returns the first
    return query


def headers_to_dict(raw_headers):
    """workers-py maps request.headers to HTTPMessageMapping (email.message
    style: .items()); fall back to js.Headers.entries() if that ever changes."""
    result = {}
    items = None
    for candidate in ('items', 'entries'):
        try:
            accessor = getattr(raw_headers, candidate)
            items = accessor()
            break
        except AttributeError:
            continue
    if items is None:
        return result
    for entry in items:
        pair = entry.to_py() if hasattr(entry, 'to_py') else entry
        result[str(pair[0]).lower()] = str(pair[1])
    return result


def build_response(resp, method):
    """dict → js.Response. js.Headers.append() keeps duplicate Set-Cookie alive."""
    headers = Headers.new()
    for key, value in resp.get('headers', []):
        headers.append(key, value)
    body = resp.get('body')
    init = to_js(
        {'status': resp.get('status', 200), 'headers': headers},
        dict_converter=js.Object.fromEntries,
    )
    if method == 'HEAD' or body is None:
        return Response.new(None, init)
    return Response.new(body, init)


class Default(WorkerEntrypoint):
    async def fetch(self, request, env=None, ctx=None):
        try:
            env = env if env is not None else self.env
            url = str(request.url)
            parts = urlsplit(url)
            method = str(request.method).upper()
            req = {
                'method': method,
                'path': parts.path,
                'raw_query': parts.query,
                'query': parse_query(parts.query),
                'headers': headers_to_dict(request.headers),
                'origin': urlunsplit((parts.scheme.lower(), (parts.netloc or '').lower(), '', '', '')),
                'url': url,
            }
            if method in ('POST', 'PUT'):
                req['body'] = (await request.text()).encode('utf-8')

            path = req['path']
            if path.startswith('/api/auth/') or path.startswith('/api/user/'):
                resp = await handle_account_request(req, env)
            elif not path.startswith('/api/'):
                # Static assets (dist/) served by the platform binding.
                return await env.ASSETS.fetch(request)
            else:
                resp = await handle_api(req, env)
            return build_response(resp, method)
        except Exception as error:  # noqa: BLE001 — never leak a stack trace
            print('worker error:', error)
            return build_response(_INTERNAL_ERROR, 'GET')

    async def scheduled(self, controller, env=None, ctx=None):
        env = env if env is not None else self.env
        await run_collection(env)
