"""Build the feedback text that an update-mode (ai-revise) run gives the AI developer.

Before this module the workflow kept only PR comments whose author was NOT github-actions.
The ChatGPT review is posted by github-actions, so it was always dropped and Claude/Grok
revised the PR without ever seeing the review it was meant to address (PR #5, 2026-11-10).

What goes in, newest review first:
  1. The latest ChatGPT review comment (posted by the workflow bot, carrying an aidev-review
     marker). Comments that merely *contain* a marker but come from a person are ignored.
  2. Comments, PR review bodies and inline review comments from the repository owner.
     Other accounts are ignored: the repo is public and anyone can comment, so their text
     must not reach the model as instructions.
"""
import re

from . import mergegate as MG

REVIEW_MAX = 9000
OWNER_MAX = 6000
FOOTER_RE = re.compile(r'\n_Verdict parsed by the merge gate.*', re.S)


def _login(item):
    return ((item or {}).get('user') or {}).get('login', '')


def _is_bot(item, cfg):
    u = (item or {}).get('user') or {}
    return u.get('type') == 'Bot' and u.get('login') in set(cfg['auto_merge']['allowed_authors'])


def latest_review(comments, cfg):
    """(head_sha, verdict, body) of the newest bot-posted ChatGPT review, or None."""
    best = None
    for c in comments or []:
        if not _is_bot(c, cfg):
            continue
        body = c.get('body') or ''
        m = None
        for m in MG.REVIEW_MARKER.finditer(body):
            pass
        if not m:
            continue
        kv = dict(x.split('=', 1) for x in m.group(1).split() if '=' in x)
        if kv.get('status') not in ('reviewed', 'reused'):
            continue
        key = c.get('created_at') or ''
        if best is None or key >= best[0]:
            best = (key, kv.get('head', ''), kv.get('verdict', ''), body)
    if not best:
        return None
    body = FOOTER_RE.sub('', MG.REVIEW_MARKER.sub('', best[3])).strip()
    return best[1], best[2], body


def build(comments, reviews, review_comments, cfg, head_sha=''):
    """Markdown feedback for develop.build_context (empty string when there is nothing to address)."""
    owner = cfg['owner']
    parts = []
    rv = latest_review(comments, cfg)
    if rv:
        head, verdict, body = rv
        note = ''
        if head_sha and head and head != head_sha:
            note = f' (it reviewed `{head[:12]}`; the branch head is now `{head_sha[:12]}`)'
        parts.append(f'## Latest ChatGPT code review: verdict {verdict or "unknown"}{note}\n'
                     'Fix every integration problem and recommended fix below, and keep the change limited to the issue.\n\n'
                     + body[:REVIEW_MAX])
    own = []
    items = [('comment', c) for c in comments or []] + [('review', r) for r in reviews or []] + \
            [('inline', r) for r in review_comments or []]
    items.sort(key=lambda kc: kc[1].get('created_at') or kc[1].get('submitted_at') or '')
    for kind, it in items:
        if _login(it) != owner or ((it.get('user') or {}).get('type') == 'Bot'):
            continue
        body = (it.get('body') or '').strip()
        if not body:
            continue
        where = f' on `{it.get("path")}` line {it.get("line") or it.get("original_line") or "?"}' if kind == 'inline' else ''
        own.append(f'### {owner} ({kind}{where})\n{body}')
    if own:
        txt = '\n\n'.join(own)
        parts.append('## Comments from the owner\n' + txt[-OWNER_MAX:])
    return '\n\n'.join(parts)
