"""Minimal read-only GitHub REST client (urllib). Writes are done with `gh` in the workflow."""
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
