"""Thin clients for the three official APIs (stdlib urllib only).

Each call returns a ProviderResult that records WHO actually answered: the
endpoint host that was called, the model name the API reported back, the
response id and the token usage from the API's own usage fields. A response
whose reported model does not belong to the expected provider family is
treated as a failure. There is no fallback between providers.
"""
import json, os, re, sys, urllib.error, urllib.request
from dataclasses import dataclass, asdict
from urllib.parse import urlparse


@dataclass
class ProviderResult:
    provider: str
    endpoint_host: str
    model_requested: str
    model_reported: str
    response_id: str
    text: str
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int = 0   # part of output_tokens (billed); reported by the API when it reasons
    status: str = ''            # xAI response status; 'incomplete' means the answer was cut off

    def public(self):
        d = asdict(self)
        d.pop('text')
        return d


class ProviderError(Exception):
    def __init__(self, msg, result=None):
        super().__init__(msg)
        self.result = result  # set when the API answered (tokens were billed) but the answer was rejected


_SECRETS = []


def register_secret(value):
    """Mask a secret in GitHub logs and in our own error messages."""
    if value:
        _SECRETS.append(value)
        if os.environ.get('GITHUB_ACTIONS'):
            sys.stdout.write(f'::add-mask::{value}\n')


def scrub(text):
    text = str(text)
    for s in _SECRETS:
        text = text.replace(s, '***')
    text = re.sub(r'(sk-[A-Za-z0-9_\-]{6})[A-Za-z0-9_\-]+', r'\1***', text)
    text = re.sub(r'(xai-[A-Za-z0-9]{4})[A-Za-z0-9]+', r'\1***', text)
    return text


def _post(url, headers, body, timeout, transport=None):
    if transport:
        return transport(url, headers, body)
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors='replace')[:800]
        raise ProviderError(scrub(f'HTTP {e.code} from {urlparse(url).netloc}: {detail}'))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ProviderError(scrub(f'network error calling {urlparse(url).netloc}: {e}'))


def _check_family(cfg, provider, reported):
    prefixes = cfg['providers'][provider]['model_prefixes']
    if not reported or not any(reported.lower().startswith(p) for p in prefixes):
        raise ProviderError(f'{provider} response reported model {reported!r}, which is not a {prefixes} model; refusing to attribute it')


def call(cfg, provider, api_key, model, system, user, max_out, transport=None):
    if not api_key:
        raise ProviderError(f'{provider}: no API key configured')
    url = cfg['providers'][provider]['url']
    timeout = cfg['limits']['request_timeout_s']
    if provider == 'xai':
        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        # max_output_tokens caps only the visible answer on xAI; reasoning tokens are billed on top of it.
        # reasoning.effort is what limits them (limits.xai_reasoning_effort, '' = API default 'high').
        body = {'model': model, 'max_output_tokens': max_out, 'store': False,
                'input': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]}
        effort = (cfg['limits'].get('xai_reasoning_effort') or '').strip()
        if effort:
            body['reasoning'] = {'effort': effort}
        r = _post(url, headers, body, timeout, transport)
        text = ''.join(c.get('text', '') for o in r.get('output', []) if o.get('type') == 'message'
                       for c in o.get('content', []) if c.get('type') in ('output_text', 'text'))
        u = r.get('usage') or {}
        res = ProviderResult(provider, urlparse(url).netloc, model, r.get('model', ''), r.get('id', ''), text,
                             int(u.get('input_tokens', 0)), int(u.get('output_tokens', 0)),
                             int((u.get('output_tokens_details') or {}).get('reasoning_tokens', 0) or 0),
                             str(r.get('status') or ''))
    elif provider == 'anthropic':
        headers = {'x-api-key': api_key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'}
        body = {'model': model, 'max_tokens': max_out, 'system': system,
                'messages': [{'role': 'user', 'content': user}]}
        r = _post(url, headers, body, timeout, transport)
        text = ''.join(c.get('text', '') for c in r.get('content', []) if c.get('type') == 'text')
        u = r.get('usage') or {}
        res = ProviderResult(provider, urlparse(url).netloc, model, r.get('model', ''), r.get('id', ''), text,
                             int(u.get('input_tokens', 0)) + int(u.get('cache_read_input_tokens', 0) or 0)
                             + int(u.get('cache_creation_input_tokens', 0) or 0),
                             int(u.get('output_tokens', 0)))
    elif provider == 'openai':
        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        body = {'model': model, 'max_completion_tokens': max_out,
                'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]}
        r = _post(url, headers, body, timeout, transport)
        ch = (r.get('choices') or [{}])[0]
        text = (ch.get('message') or {}).get('content') or ''
        u = r.get('usage') or {}
        res = ProviderResult(provider, urlparse(url).netloc, model, r.get('model', ''), r.get('id', ''), text,
                             int(u.get('prompt_tokens', 0)), int(u.get('completion_tokens', 0)),
                             int((u.get('completion_tokens_details') or {}).get('reasoning_tokens', 0) or 0))
    else:
        raise ProviderError(f'unknown provider {provider}')
    try:
        _check_family(cfg, provider, res.model_reported)
    except ProviderError as e:
        raise ProviderError(str(e), result=res)
    if res.status == 'incomplete':
        why = ((r.get('incomplete_details') or {}).get('reason') or 'unknown reason')
        raise ProviderError(f'{provider} answer was cut off (status incomplete: {why}); raise AI_MAX_OUTPUT_TOKENS '
                            f'if the visible answer needs more than {max_out} tokens', result=res)
    if not res.text.strip():
        raise ProviderError(f'{provider} returned an empty answer (model {res.model_reported})', result=res)
    return res
