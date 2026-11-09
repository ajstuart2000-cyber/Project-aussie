"""Minimal GitHub REST client (urllib). The only write here is put() for "update branch" on an
AI PR (bringing ai/* up to date with main). Merging is done by the gated step in ai-pr-gate.yml."""
import json, os, re, urllib.request

API = os.environ.get('GITHUB_API_URL', 'https://api.github.com')


def get(path, token, params=''):
    url = f'{API}{path}{"?" + params if params else ""}'
    out = []
    while url:
        req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json',
                                                   'X-GitHub-Api-Version': '2022-11-28'})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode())
            link = r.headers.get('Link', '')
        if isinstance(data, list):
            out.extend(data)
        else:
            return data
        m = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = m.group(1) if m else None
        if len(out) > 2000:
            break
    return out


def put(path, token, body):
    req = urllib.request.Request(f'{API}{path}', data=json.dumps(body).encode(), method='PUT',
                                 headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json',
                                          'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode() or '{}')
