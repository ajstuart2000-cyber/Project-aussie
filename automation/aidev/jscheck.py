"""Syntax-check the inline <script> blocks of www/index.html with `node --check`."""
import os, re, subprocess, tempfile

SCRIPT_RE = re.compile(r'<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>', re.S | re.I)


def check_html(path):
    """Return (ok, results). Each result: {index, type, lines, ok, error}."""
    src = open(path, encoding='utf-8').read()
    results = []
    for i, m in enumerate(SCRIPT_RE.finditer(src)):
        attrs = m.group('attrs')
        if 'src=' in attrs:
            continue
        typ = 'module' if re.search(r'type\s*=\s*["\']module["\']', attrs) else \
              'importmap' if 'importmap' in attrs else 'classic'
        body = m.group('body')
        start_line = src.count('\n', 0, m.start('body')) + 1
        if typ == 'importmap':
            import json
            try:
                json.loads(body); results.append({'index': i, 'type': typ, 'line': start_line, 'ok': True, 'error': ''})
            except ValueError as e:
                results.append({'index': i, 'type': typ, 'line': start_line, 'ok': False, 'error': str(e)})
            continue
        # pad with newlines so node's error line numbers match index.html
        with tempfile.NamedTemporaryFile('w', suffix='.mjs' if typ == 'module' else '.js', delete=False) as fh:
            fh.write('\n' * (start_line - 1) + body)
            tmp = fh.name
        try:
            r = subprocess.run(['node', '--check', tmp], capture_output=True, text=True)
            err = (r.stderr or '').replace(tmp, os.path.basename(path)).strip()
            results.append({'index': i, 'type': typ, 'line': start_line, 'ok': r.returncode == 0, 'error': err[:1500]})
        finally:
            os.unlink(tmp)
    return all(r['ok'] for r in results) and bool(results), results
