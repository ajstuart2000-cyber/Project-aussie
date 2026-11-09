"""Diff-based protection checks for Project Aussie.

Used in two modes:
  * mode "ai": a patch produced by an AI developer (branch ai/<role>/...). Strict:
    path allow-lists per role, no binaries, no deletions, size cap, and the
    protected areas below can never be overridden - except that Claude may change
    audio code when the issue/PR carries the owner's `audio-approved` label.
  * mode "pr": any other pull request. The same protected areas fail the check
    unless the owner has applied the override label (`audio-approved` for audio,
    `protected-change-approved` for package/signing/models/save keys).

Protected areas: audio system (frozen), vehicle models / graphics assets / vendor
three.js, Android package id + signing, save keys (barra.*), and the separation
of the BF Falcon XR6 Turbo (VEHICLES.falcon) from the AU Falcons (au, auute).
"""
import bisect, re
from dataclasses import dataclass, field

from .globmatch import match


@dataclass
class FileChange:
    path: str
    status: str = 'M'          # A, D, M
    binary: bool = False
    added: list = field(default_factory=list)    # (new_lineno, text)
    removed: list = field(default_factory=list)  # (old_lineno, text)


def parse_unified_diff(text):
    """Parse `git diff --no-renames -U0` output."""
    files, cur = [], None
    old_ln = new_ln = 0
    for line in text.splitlines():
        if line.startswith('diff --git '):
            m = re.match(r'diff --git a/(.*) b/(.*)$', line)
            cur = FileChange(path=m.group(2) if m else line.split()[-1][2:])
            files.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith('new file mode'):
            cur.status = 'A'
        elif line.startswith('deleted file mode'):
            cur.status = 'D'
        elif line.startswith('Binary files') or line.startswith('GIT binary patch'):
            cur.binary = True
        elif line.startswith('--- ') or line.startswith('+++ '):
            if line.startswith('--- a/') and cur.status == 'D':
                cur.path = line[6:]
            continue
        elif line.startswith('@@'):
            m = re.match(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
            old_ln, new_ln = int(m.group(1)), int(m.group(2))
        elif line.startswith('+'):
            cur.added.append((new_ln, line[1:])); new_ln += 1
        elif line.startswith('-'):
            cur.removed.append((old_ln, line[1:])); old_ln += 1
        elif line.startswith(' '):
            old_ln += 1; new_ln += 1
    return files


# ---------------------------------------------------------------- JS scanning

def _line_starts(src):
    starts = [0]
    for m in re.finditer('\n', src):
        starts.append(m.end())
    return starts


def _lineno(starts, offset):
    return bisect.bisect_right(starts, offset)  # 1-based


def _scan_end(src, i, mode):
    """From offset i, return offset where the declaration ends.
    mode 'function': after the first {...} block closes. mode 'stmt': at ';' depth 0."""
    depth, seen_brace, n = 0, False, len(src)
    limit = min(n, i + 400000)
    while i < limit:
        c = src[i]
        if c in '\'"`':
            q = c; i += 1
            while i < limit and src[i] != q:
                if src[i] == '\\':
                    i += 1
                i += 1
        elif c == '/' and i + 1 < n and src[i + 1] == '/':
            j = src.find('\n', i)
            i = limit if j < 0 else j
            continue
        elif c == '/' and i + 1 < n and src[i + 1] == '*':
            j = src.find('*/', i + 2)
            i = limit if j < 0 else j + 2
            continue
        elif c in '([{':
            depth += 1
            if c == '{':
                seen_brace = True
        elif c in ')]}':
            depth -= 1
            if mode == 'function' and seen_brace and depth == 0 and c == '}':
                return i + 1
        elif c == ';' and depth == 0 and mode == 'stmt':
            return i + 1
        i += 1
    return limit


def audio_protected_lines(src, cfg):
    """Set of 1-based line numbers in `src` that belong to the frozen audio system."""
    p = cfg['protect']
    starts = _line_starts(src)
    lines = set()
    marker = p['audio_section_marker']
    k = src.find(marker)
    if k >= 0:
        nxt = re.compile(r'/\* ={5,} .+? ={5,} \*/').search(src, k + len(marker))
        end = nxt.start() if nxt else len(src)
        lines.update(range(_lineno(starts, k), _lineno(starts, max(k, end - 1)) + 1))
    for name in p['audio_functions']:
        for m in re.finditer(r'\bfunction\s+%s\s*\(' % re.escape(name), src):
            e = _scan_end(src, m.start(), 'function')
            lines.update(range(_lineno(starts, m.start()), _lineno(starts, e - 1) + 1))
        for m in re.finditer(r'\b(?:const|let|var)\s+%s\s*=' % re.escape(name), src):
            e = _scan_end(src, m.start(), 'stmt')
            lines.update(range(_lineno(starts, m.start()), _lineno(starts, e - 1) + 1))
    return lines


def save_keys(src, cfg):
    return set(re.findall(cfg['protect']['save_key_regex'], src or ''))


def vehicle_entries(src):
    """Return {key: {'base':..,'swap':..,'partsDir':..}} for the VEHICLES table."""
    out = {}
    k = (src or '').find('const VEHICLES')
    if k < 0:
        return out
    block = src[k:k + 20000]
    for m in re.finditer(r'^\s*([A-Za-z0-9_]+)\s*:\s*\{\s*name\s*:([^\n]*)', block, re.M):
        line = m.group(2)
        ent = {'name': (re.search(r"^\s*'([^']*)'", line) or [None, None])[1]}
        for f in ('base', 'swap', 'partsDir'):
            mm = re.search(r"\b%s\s*:\s*'([^']*)'" % f, line)
            ent[f] = mm.group(1) if mm else None
        out[m.group(1)] = ent
    return out


# ---------------------------------------------------------------- checker

@dataclass
class Context:
    mode: str = 'pr'           # 'ai' or 'pr'
    role: str = ''             # grok / claude (ai mode)
    labels: frozenset = frozenset()
    branch: str = ''

    @staticmethod
    def from_branch(branch, labels=(), mode=None, role=None):
        labels = frozenset(l.strip() for l in labels if l and l.strip())
        if mode is None:
            mode = 'ai' if branch.startswith('ai/') else 'pr'
        if mode == 'ai' and not role:
            parts = branch.split('/')
            role = parts[1] if len(parts) > 1 else ''
        return Context(mode=mode, role=role or '', labels=labels, branch=branch)


def _v(rule, path, detail):
    return {'rule': rule, 'path': path, 'detail': detail}


def check(changes, read_base, read_head, cfg, ctx):
    """Return a list of violations. read_base/read_head(path) -> str or None."""
    p, L = cfg['protect'], cfg['labels']
    viol = []
    audio_label = L['audio_approved'] in ctx.labels
    if ctx.mode == 'ai':
        role_cfg = cfg['roles'].get(ctx.role)
        audio_ok = bool(role_cfg and role_cfg.get('may_touch_audio') and audio_label)
        protected_ok = False
    else:
        role_cfg = None
        audio_ok = audio_label
        protected_ok = L['protected_change_approved'] in ctx.labels

    def audio_violation(path, detail):
        if ctx.mode == 'ai' and ctx.role != 'claude':
            viol.append(_v('audio_claude_only', path,
                           f'{detail}. Audio/sound changes may only come from Claude on an owner-approved '
                           f'({L["audio_approved"]}) issue; {ctx.role or "this role"} may never change audio.'))
        else:
            need = 'Claude on an issue labelled ' if ctx.mode == 'ai' else 'the PR to carry the owner label '
            viol.append(_v('audio_frozen', path, f'{detail}. Audio is frozen; needs {need}`{L["audio_approved"]}`.'))

    # --- AI-mode structural limits
    if ctx.mode == 'ai':
        if role_cfg is None or role_cfg.get('reviewer'):
            viol.append(_v('ai_unknown_role', '*', f'role {ctx.role!r} is not an AI developer role; it may not write code'))
            return viol
        allowed = list(role_cfg['allowed_paths'])
        if audio_ok:
            allowed += role_cfg.get('audio_extra_paths', [])
        total = sum(len(c.added) + len(c.removed) for c in changes)
        if total > cfg['limits']['max_changed_lines']:
            viol.append(_v('ai_too_large', '*', f'{total} changed lines > limit {cfg["limits"]["max_changed_lines"]}'))
        for c in changes:
            extra_ok = audio_ok and match(c.path, role_cfg.get('audio_extra_paths', []))
            if c.binary:
                viol.append(_v('ai_binary', c.path, 'AI patches may not add or change binary files'))
            if c.status == 'D':
                viol.append(_v('ai_delete', c.path, 'AI patches may not delete files'))
            if match(c.path, p['ai_forbidden_paths']) and not extra_ok:
                viol.append(_v('ai_forbidden_path', c.path, 'path is off-limits to AI developers'))
            elif not match(c.path, allowed):
                viol.append(_v('ai_path_not_allowed', c.path, f'{ctx.role} may only change: {", ".join(allowed)}'))

    for c in changes:
        path = c.path
        changed = [t for _, t in c.added] + [t for _, t in c.removed]
        # signing material: never overridable
        if match(path, p['signing_files']) or match(path.split('/')[-1], p['signing_files']):
            viol.append(_v('signing_material', path, 'keystores / signing secrets must never be committed'))
        # Android package id + signing config
        if path.startswith('android/') and path.endswith('.gradle'):
            rx = re.compile(p['gradle_protected_line'])
            hits = [t.strip() for t in changed if rx.search(t)]
            if hits and not protected_ok:
                viol.append(_v('signing_or_package', path, f'changes package id / signing config lines: {hits[:3]}'))
        if path.endswith('AndroidManifest.xml'):
            rx = re.compile(p['manifest_protected_line'])
            hits = [t.strip() for t in changed if rx.search(t)]
            if hits and not protected_ok:
                viol.append(_v('signing_or_package', path, f'changes manifest package/sharedUserId: {hits[:3]}'))
        if path.startswith('android/') and path.endswith('.java'):
            hits = [t.strip() for t in changed if t.lstrip().startswith('package ')]
            if hits and not protected_ok:
                viol.append(_v('signing_or_package', path, f'changes Java package line: {hits[:2]}'))
        # audio files
        if match(path, p['audio_paths']):
            if not audio_ok or c.binary:
                if c.binary and audio_ok:
                    viol.append(_v('ai_binary' if ctx.mode == 'ai' else 'audio_frozen', path, 'binary audio files are not changed by automation'))
                else:
                    audio_violation(path, 'changes an audio file')
            continue
        # vehicle models / graphics assets / vendor
        if match(path, p['protected_asset_paths']) and not protected_ok:
            viol.append(_v('protected_asset', path, 'vehicle models, textures and vendor three.js are protected'))

    # --- index.html content rules
    idx = [c for c in changes if c.path == 'www/index.html']
    head_build = read_head('android/app/build.gradle')
    if head_build is not None and not protected_ok:
        if not re.search(r'applicationId\s+["\']%s["\']' % re.escape(p['package_id']), head_build):
            viol.append(_v('package_id', 'android/app/build.gradle', f'applicationId must stay {p["package_id"]}'))
    if idx:
        c = idx[0]
        base, head = read_base('www/index.html') or '', read_head('www/index.html') or ''
        if c.status == 'D' or not head:
            viol.append(_v('index_deleted', c.path, 'www/index.html must not be deleted'))
            return viol
        # audio code
        if not audio_ok:
            rx = re.compile(p['audio_line_regex'])
            b_lines, h_lines = audio_protected_lines(base, cfg), audio_protected_lines(head, cfg)
            hits = [f'+L{n}' for n, t in c.added if n in h_lines or rx.search(t)]
            hits += [f'-L{n}' for n, t in c.removed if n in b_lines or rx.search(t)]
            if p['audio_section_marker'] in base and p['audio_section_marker'] not in head:
                hits.append('audio section marker removed')
            if hits:
                audio_violation(c.path, f'changes frozen audio code ({", ".join(hits[:8])}{" ..." if len(hits) > 8 else ""})')
        # save keys
        lost = sorted(save_keys(base, cfg) - save_keys(head, cfg))
        if lost and not protected_ok:
            viol.append(_v('save_keys', c.path, f'existing save keys removed/renamed: {lost}'))
        # BF Falcon XR6 Turbo vs AU Falcons
        if not protected_ok:
            ents = vehicle_entries(head)
            for key, want in p['vehicles'].items():
                got = ents.get(key)
                if not got:
                    viol.append(_v('falcon_separation', c.path, f'VEHICLES.{key} is missing'))
                    continue
                for f, val in want.items():
                    if got.get(f) != val:
                        viol.append(_v('falcon_separation', c.path, f'VEHICLES.{key}.{f} is {got.get(f)!r}, must stay {val!r}'))
            bases = [ents[k]['base'] for k in p['vehicles'] if k in ents]
            if len(bases) != len(set(bases)):
                viol.append(_v('falcon_separation', c.path, 'BF Falcon and AU Falcon entries must keep separate models'))
    return viol


def format_violations(viol):
    if not viol:
        return 'No protected-area violations.'
    return '\n'.join(f'- **{v["rule"]}** `{v["path"]}`: {v["detail"]}' for v in viol)
