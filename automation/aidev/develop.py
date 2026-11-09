"""Run one AI developer (Grok via xAI or Claude via Anthropic) on the selected issue.

The model must answer with JSON search/replace edits. The orchestrator applies
them, then rejects the whole patch if it breaks any guardrail or the JS syntax
check. Nothing is committed here; the workflow commits only a clean result.
"""
import json, os, re

from . import budget as B, guardrails as G, jscheck, providers as P, repo

INDEX = 'www/index.html'

SYSTEM = """You are {title} for "Project Aussie", an offline Australian street-driving game
(one big www/index.html using Three.js 0.170, packaged as an Android WebView app, package com.barrarun.game).
Your areas: {areas}.

Hard rules (patches that break them are rejected automatically):
- Do not change existing gameplay unless the issue asks for it; never change graphics assets, vehicle models,
  textures, www/assets/**, www/vendor/**, the Android package id, signing config, or build files.
- Keep the BF Falcon XR6 Turbo (VEHICLES.falcon) and the AU Falcons (VEHICLES.au, VEHICLES.auute) as separate entries/models.
- Keep every existing localStorage save key (barra.*) readable; never rename or remove one.
- {audio_rule}
- You may only edit these paths: {paths}.
- Make the smallest change that completes the task. No placeholder code, no invented test results, no brand logos.

Answer with ONE JSON object and nothing else:
{{"summary": "one paragraph: what you changed and why",
  "edits": [{{"path": "www/index.html", "search": "exact text copied from the file, unique, include enough context", "replace": "new text"}}],
  "new_files": [{{"path": "docs/...md", "content": "..."}}],
  "owner_test_steps": ["what the owner should check on the phone"],
  "risks": "anything the reviewer should look at",
  "blocked_reason": "fill this and leave edits empty if the task cannot be done safely within the rules"}}
Every "search" string must appear exactly once in the current file. Use only text you can see in the excerpts."""

AUDIO_FROZEN = ('The audio system is FROZEN: do not touch getPack, setEngineSound, sirenOn, thud, loadSoundData, '
                'the "audio" section, AudioContext/volume/sfx code or any sound file.')
AUDIO_OPEN = ('The owner approved audio work on THIS issue (audio-approved). You may change audio code needed for the task, '
              'but keep every other sound working exactly as before and do not add, remove or replace .wav files.')


def _sections(src):
    out = []
    for m in re.finditer(r'/\* ={5,} (.+?) ={5,} \*/', src):
        out.append(f'L{src.count(chr(10), 0, m.start()) + 1}: {m.group(1)}')
    return out


def _functions(src):
    return {m.group(1): src.count('\n', 0, m.start()) + 1 for m in re.finditer(r'\bfunction\s+([A-Za-z0-9_$]+)\s*\(', src)}


def _excerpt_lines(lines, a, b):
    a, b = max(1, a), min(len(lines), b)
    return '\n'.join(f'{n}| {lines[n - 1][:4000]}' for n in range(a, b + 1))


def build_context(task, cfg, root='.', feedback=''):
    role = cfg['roles'][task['role']]
    src = repo.read_worktree(INDEX, root) or ''
    lines = src.split('\n')
    funcs = _functions(src)
    budget_chars = cfg['limits']['max_input_chars']
    parts = [f'# Task: issue #{task["number"]} - {task["title"]}\nLabels: {", ".join(task["labels"])}\n\n{task.get("body", "")[:20000]}']
    if feedback:
        parts.append('# Owner feedback on the existing AI pull request (address it)\n' + feedback[:15000])
    files = [f for f in repo.git('ls-files', cwd=root).split('\n') if f and not f.startswith('www/assets/') and not f.startswith('www/vendor/')]
    parts.append('# Repository files (www/assets/** and www/vendor/** omitted; they are protected)\n' + '\n'.join(files))
    parts.append(f'# {INDEX}: {len(lines)} lines. Section markers:\n' + '\n'.join(_sections(src)))
    text = task['title'] + '\n' + task.get('body', '') + '\n' + feedback
    wanted = []
    for ident in dict.fromkeys(re.findall(r'[A-Za-z_$][A-Za-z0-9_$]{3,}', text)):
        if ident in funcs:
            wanted.append((funcs[ident], ident))
    for m in re.finditer(r'\bL(\d{2,5})(?:\s*[-\u2013]\s*L?(\d{2,5}))?', text):
        a = int(m.group(1)); b = int(m.group(2) or a)
        wanted.append((a, f'L{a}-{b}'))
    used = sum(len(p) for p in parts)
    shown = set()
    for line_no, label in sorted(wanted):
        if line_no in shown:
            continue
        # show from the line to the end of the function (or +40 lines), capped
        end = min(len(lines), line_no + 60)
        chunk = f'# Excerpt {label} (line numbers are for orientation only; do not include them in "search")\n' + _excerpt_lines(lines, line_no - 3, end)
        if used + len(chunk) > budget_chars * 0.8:
            break
        parts.append(chunk); used += len(chunk); shown.update(range(line_no, end))
    if task['role'] == 'claude':
        for f in ('android/app/src/main/java/com/barrarun/game/MainActivity.java', 'android/app/src/main/AndroidManifest.xml'):
            c = repo.read_worktree(f, root)
            if c and used + len(c) < budget_chars:
                parts.append(f'# {f}\n{c}'); used += len(c)
    # fill the remaining room with the top of the module script (settings/store/builds)
    if used < budget_chars * 0.9:
        room = int(budget_chars * 0.95) - used
        start = next((i for i, l in enumerate(lines) if '<script type="module">' in l), 0) + 1
        chunk, n = [], start
        while n < len(lines) and room > 0:
            piece = f'{n + 1}| {lines[n][:4000]}'
            room -= len(piece) + 1
            if room > 0:
                chunk.append(piece)
            n += 1
        parts.append('# index.html from the start of the module script\n' + '\n'.join(chunk))
    audio_open = task.get('audio_approved') and role.get('may_touch_audio')
    paths = list(role['allowed_paths']) + (role.get('audio_extra_paths', []) if audio_open else [])
    system = SYSTEM.format(title=role['title'], areas=', '.join(role['areas']),
                           audio_rule=AUDIO_OPEN if audio_open else AUDIO_FROZEN, paths=', '.join(paths))
    user = '\n\n'.join(parts)[:budget_chars]
    return system, user


def parse_answer(text):
    t = text.strip()
    t = re.sub(r'^```(?:json)?\s*|\s*```$', '', t)
    a, b = t.find('{'), t.rfind('}')
    if a < 0 or b < a:
        raise ValueError('answer contained no JSON object')
    obj = json.loads(t[a:b + 1])
    if not isinstance(obj, dict):
        raise ValueError('answer JSON is not an object')
    obj.setdefault('edits', []); obj.setdefault('new_files', [])
    return obj


def _safe_path(p):
    if not isinstance(p, str) or not p or p.startswith('/') or '\\' in p or any(s in ('..', '') for s in p.split('/')):
        raise ValueError(f'unsafe path {p!r}')
    return p


def apply_edits(answer, root='.'):
    """Apply all edits in memory first; write only if every edit is valid."""
    pending = {}
    for e in answer.get('edits', []):
        path = _safe_path(e.get('path'))
        if path not in pending:
            cur = repo.read_worktree(path, root)
            if cur is None:
                raise ValueError(f'edit targets a file that does not exist: {path}')
            pending[path] = cur
        s, r = e.get('search'), e.get('replace')
        if not isinstance(s, str) or not s or not isinstance(r, str):
            raise ValueError(f'edit for {path} needs non-empty "search" and a "replace" string')
        n = pending[path].count(s)
        if n != 1:
            raise ValueError(f'"search" text for {path} matched {n} times (must be exactly once): {s[:120]!r}')
        pending[path] = pending[path].replace(s, r, 1)
    for nf in answer.get('new_files', []):
        path = _safe_path(nf.get('path'))
        if repo.read_worktree(path, root) is not None or path in pending:
            raise ValueError(f'new_files entry already exists: {path}')
        if not isinstance(nf.get('content'), str):
            raise ValueError(f'new file {path} has no content')
        pending[path] = nf['content']
    for path, content in pending.items():
        full = os.path.join(root, path)
        os.makedirs(os.path.dirname(full) or '.', exist_ok=True)
        with open(full, 'w', encoding='utf-8', newline='') as fh:
            fh.write(content)
    return sorted(pending)


def revert(root='.'):
    repo.git('reset', '-q', cwd=root, check=False)
    repo.git('checkout', '--', '.', cwd=root, check=False)
    repo.git('clean', '-fdq', '--', 'www', 'docs', 'android/app/src', cwd=root, check=False)


def run(task, cfg, spent_today=0.0, dry_run=False, root='.', feedback='', transport=None, env=None):
    env = env if env is not None else os.environ
    role = cfg['roles'][task['role']]
    provider = role['provider']
    pname = cfg['providers'][provider]['name']
    res = {'status': None, 'role': task['role'], 'role_title': role['title'], 'provider_name': pname,
           'model_configured': role['model'], 'issue': task['number'], 'branch': task['branch'],
           'provider': None, 'cost_usd': 0.0, 'calls': 0, 'summary': '', 'owner_test_steps': [], 'risks': '',
           'changed_files': [], 'violations': [], 'js_check': None, 'error': ''}
    key = env.get(role['secret'], '')
    P.register_secret(key)
    system, user = build_context(task, cfg, root, feedback)
    bud = B.Budget(cfg, spent_today)
    max_out = cfg['limits']['max_output_tokens']
    res['prompt_chars'] = len(system) + len(user)
    res['worst_case_usd'] = bud.worst_case(provider, role['model'], res['prompt_chars'], max_out)
    if dry_run:
        res.update(status='dry-run', key_configured=bool(key),
                   summary=f'Dry run: would call {pname} model {role["model"]} with a {res["prompt_chars"]:,}-char prompt '
                           f'(worst case ${res["worst_case_usd"]:.4f}). No API call made.')
        return res
    if not key:
        res.update(status='skipped', error=f'{role["secret"]} is not set; {role["title"]} ({pname}) was not called. '
                                            'No other provider was used instead.')
        return res
    try:
        bud.authorize(provider, role['model'], res['prompt_chars'], max_out)
    except B.BudgetExceeded as e:
        res.update(status='skipped', error=f'budget: {e}')
        return res
    res['calls'] = 1
    try:
        pr = P.call(cfg, provider, key, role['model'], system, user, max_out, transport=transport)
    except P.ProviderError as e:
        if e.result:
            res['provider'] = e.result.public()
            res['cost_usd'] = bud.record(provider, e.result.model_reported or role['model'], e.result.input_tokens, e.result.output_tokens)
        res.update(status='failed', error=P.scrub(e))
        return res
    res['provider'] = pr.public()
    res['cost_usd'] = bud.record(provider, pr.model_reported, pr.input_tokens, pr.output_tokens)
    try:
        ans = parse_answer(pr.text)
    except ValueError as e:
        res.update(status='failed', error=f'could not parse the {pname} answer as JSON edits: {e}')
        return res
    res['summary'] = str(ans.get('summary', ''))[:3000]
    res['owner_test_steps'] = [str(s)[:300] for s in ans.get('owner_test_steps', [])][:15]
    res['risks'] = str(ans.get('risks', ''))[:2000]
    if not ans['edits'] and not ans['new_files']:
        res.update(status='no-change', error=str(ans.get('blocked_reason') or 'the model proposed no edits')[:2000])
        return res
    try:
        res['changed_files'] = apply_edits(ans, root)
    except ValueError as e:
        revert(root)
        res.update(status='rejected', error=f'patch could not be applied: {e}')
        return res
    changes = G.parse_unified_diff(repo.diff('HEAD', cwd=root))
    ctx = G.Context(mode='ai', role=task['role'], labels=frozenset(task['labels']), branch=task['branch'])
    viol = G.check(changes, lambda p: repo.show('HEAD', p, root), lambda p: repo.read_worktree(p, root), cfg, ctx)
    res['violations'] = viol
    if INDEX in res['changed_files']:
        ok, detail = jscheck.check_html(os.path.join(root, INDEX))
        res['js_check'] = {'ok': ok, 'detail': detail}
        if not ok:
            viol.append({'rule': 'js_syntax', 'path': INDEX, 'detail': '; '.join(d['error'] for d in detail if not d['ok'])[:1500]})
    if viol:
        revert(root)
        res.update(status='rejected', error='patch rejected by guardrails:\n' + G.format_violations(viol))
        return res
    repo.git('reset', '-q', cwd=root, check=False)  # undo intent-to-add; workflow stages explicitly
    res['status'] = 'changed'
    return res
