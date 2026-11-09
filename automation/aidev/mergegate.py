"""Auto-merge gate for AI pull requests.

Auto-merge was enabled at the owner's request on 2026-11-10. It is OFF unless the
repository variable AI_AUTO_MERGE is exactly "true". A PR is merged (squash, pinned
to the tested head SHA) only when EVERY condition below holds; any failure, missing
data or unparseable answer means "do not merge":

  PR shape      open, not draft, base `main`, branch `ai/<role>/issue-<N>-...` in this
                repository (no forks), opened by the workflow (github-actions[bot]),
                label `ai-generated`, no blocking label (ai-revise, ai-blocked, ...),
                the `<!-- aidev-pr issue=N role=R -->` marker matching the branch,
                role grok or claude, every commit a non-merge commit authored by
                `project-aussie-ai-<role>` with the Actions bot e-mail.
  Checks        code validation (unit tests, protected areas, JS syntax, actionlint,
                Gradle wrapper), the Android build + APK verification, and the gate's
                own guardrail re-run all concluded `success` for the tested commit.
  APK           apk-verify.json says ok, the CI package (com.barrarun.game.ci).
  Review        a real ChatGPT review from api.openai.com (response id, gpt/o model)
                of exactly this head SHA whose verdict parses as APPROVE.
  Freshness     the PR head and `main` are still the commits that were tested, and
                GitHub reports the PR mergeable (no conflicts).
"""
import re

from . import tasks

PR_MARKER = re.compile(r'<!--\s*aidev-pr\s+issue=(\d+)\s+role=([a-z]+)\s*-->')
REVIEW_MARKER = re.compile(r'<!--\s*aidev-review\s+([^>]*?)\s*-->')
HEADING = re.compile(r'^\s{0,3}#{1,6}\s*(.*?)\s*#*\s*$')
APPROVE = 'approve'
CHANGES = 'changes'
UNKNOWN = 'unknown'


# --------------------------------------------------------------------------- verdict
def parse_verdict(review_md):
    """(verdict, line). The reviewer must put ONE line under a single '### Verdict'
    heading that starts with APPROVE or CHANGES RECOMMENDED. Anything else -> unknown."""
    lines = (review_md or '').splitlines()
    idx = [i for i, l in enumerate(lines) if HEADING.match(l) and HEADING.match(l).group(1).strip().lower().strip('*: ') == 'verdict']
    if len(idx) != 1:
        return UNKNOWN, ''
    line = ''
    for l in lines[idx[0] + 1:]:
        if HEADING.match(l):
            break
        if l.strip():
            line = l.strip()
            break
    clean = re.sub(r'[*_`>"\u201c\u201d]', '', line).strip().lstrip('-•').strip()
    low = clean.lower()
    if not low:
        return UNKNOWN, line
    if re.match(r'(changes?\s+(recommended|requested|required|needed)|request(ed)?\s+changes|reject|block|do not merge|not ok)\b', low):
        return CHANGES, line
    if re.match(r'approved?\b(?!\s*(with|if|after|once|pending|subject|but|except))', low) or \
            re.match(r'ok (for owner review|to merge)\b(?!\s*(with|if|after|once|pending|subject|but|except))', low):
        return APPROVE, line
    return UNKNOWN, line


# --------------------------------------------------------------------------- markers
def review_marker(head_sha, verdict, status, response_id, model, host=''):
    return (f'<!-- aidev-review head={head_sha} verdict={verdict} status={status} '
            f'response_id={response_id or "-"} model={model or "-"} host={host or "-"} -->')


def find_prior_review(comments, head_sha, cfg):
    """Latest review marker for head_sha posted by the workflow bot (never by a person)."""
    allowed = set(cfg['auto_merge']['allowed_authors'])
    found = None
    for c in comments or []:
        user = c.get('user') or {}
        if user.get('login') not in allowed or user.get('type') != 'Bot':
            continue
        for m in REVIEW_MARKER.finditer(c.get('body') or ''):
            kv = dict(x.split('=', 1) for x in m.group(1).split() if '=' in x)
            if kv.get('head') == head_sha and kv.get('status') in ('reviewed', 'reused'):
                found = {**kv, 'comment_url': c.get('html_url', '')}
    return found


# --------------------------------------------------------------------------- PR shape
def pr_eligibility(pr, commits, cfg):
    """(info, reasons). commits=None skips the commit checks (used for candidate listing)."""
    am, L = cfg['auto_merge'], cfg['labels']
    reasons = []
    labels = tasks.label_names(pr)
    head, base = pr.get('head') or {}, pr.get('base') or {}
    ref = head.get('ref') or ''
    info = {'number': pr.get('number'), 'title': pr.get('title', ''), 'branch': ref, 'head_sha': head.get('sha', ''),
            'labels': sorted(labels), 'role': '', 'issue': None}
    if pr.get('state') != 'open':
        reasons.append(f'PR is {pr.get("state")}, not open')
    if pr.get('draft'):
        reasons.append('PR is a draft')
    if base.get('ref') != am['base']:
        reasons.append(f'base is {base.get("ref")!r}, not {am["base"]!r}')
    hr, br = (head.get('repo') or {}).get('full_name'), (base.get('repo') or {}).get('full_name')
    if not hr or hr != br:
        reasons.append('head branch is not in this repository (fork or deleted)')
    if not ref.startswith(am['branch_prefix']):
        reasons.append(f'branch {ref!r} is not an {am["branch_prefix"]}* branch')
    login = (pr.get('user') or {}).get('login')
    if login not in am['allowed_authors']:
        reasons.append(f'PR was opened by {login!r}, not by the automation ({", ".join(am["allowed_authors"])})')
    if am['required_label'] not in labels:
        reasons.append(f'missing label `{am["required_label"]}`')
    blocked = labels & set(L.get('merge_block', []))
    if blocked:
        reasons.append(f'blocking label(s) {sorted(blocked)}')
    m = PR_MARKER.search(pr.get('body') or '')
    if not m:
        reasons.append('PR body has no aidev-pr marker')
    else:
        issue, role = int(m.group(1)), m.group(2)
        info.update(issue=issue, role=role)
        rc = cfg['roles'].get(role) or {}
        if not rc.get('label') or rc.get('reviewer'):
            reasons.append(f'role {role!r} is not a developer role')
        elif not ref.startswith(tasks.branch_prefix(role, issue)):
            reasons.append(f'branch {ref!r} does not match the marker (issue #{issue}, role {role})')
        elif rc['label'] not in labels:
            reasons.append(f'missing role label `{rc["label"]}`')
    if commits is not None:
        if not commits:
            reasons.append('PR has no commits')
        if len(commits) > am['max_pr_commits']:
            reasons.append(f'PR has {len(commits)} commits (max {am["max_pr_commits"]})')
        want = am['commit_author_prefix'] + (info['role'] or '?')
        for c in commits:
            sha = (c.get('sha') or '')[:10]
            if len(c.get('parents') or []) > 1:
                reasons.append(f'commit {sha} is a merge commit')
            a = (c.get('commit') or {}).get('author') or {}
            if a.get('name') != want or a.get('email') != am['commit_email']:
                reasons.append(f'commit {sha} was not made by the automation ({a.get("name")!r} <{a.get("email")}>)')
    return info, reasons


def guard_labels(role, issue, issue_events, cfg):
    """Labels handed to the guardrails. Only `audio-approved`, and only when the role is
    Claude (may_touch_audio) and the OWNER applied `audio-approved` to the linked issue.
    PR labels are ignored, so nobody can unlock audio by labelling the PR."""
    L = cfg['labels']
    rc = cfg['roles'].get(role) or {}
    if (issue and rc.get('may_touch_audio') and L['audio_approved'] in tasks.label_names(issue)
            and tasks.last_labeler(issue_events, L['audio_approved']) == cfg['owner']):
        return [L['audio_approved']]
    return []


def select_candidate(prs, comments_by_pr, cfg):
    """Oldest open AI PR whose current head has not already been reviewed with a
    non-APPROVE verdict (so a rejected head is not re-reviewed and re-billed every day)."""
    considered, pick = [], None
    for pr in sorted(prs, key=lambda p: p['number']):
        info, reasons = pr_eligibility(pr, None, cfg)
        prior = find_prior_review(comments_by_pr.get(pr['number'], []), info['head_sha'], cfg)
        if not reasons and prior and prior.get('verdict') != APPROVE:
            reasons.append(f'this head was already reviewed: verdict {prior.get("verdict")} (push a fix or add ai-revise)')
        considered.append({'number': pr['number'], 'title': pr.get('title', ''), 'reason': '; '.join(reasons) or 'candidate'})
        if not reasons and pick is None:
            pick = pr['number']
    return pick, considered


# --------------------------------------------------------------------------- decision
def review_ok(review, head_sha, cfg):
    reasons = []
    am = cfg['auto_merge']
    if not review:
        return ['no ChatGPT review result']
    st = review.get('status')
    if st not in ('reviewed', 'reused'):
        reasons.append(f'ChatGPT review status is {st!r} ({(review.get("error") or "").strip()[:200]})'.replace(' ()', ''))
        return reasons
    p = review.get('provider') or {}
    if p.get('endpoint_host') != am['reviewer_endpoint_host']:
        reasons.append(f'review did not come from {am["reviewer_endpoint_host"]}')
    if not p.get('response_id'):
        reasons.append('review has no OpenAI response id')
    prefixes = cfg['providers'][cfg['roles']['chatgpt']['provider']]['model_prefixes']
    if not any((p.get('model_reported') or '').lower().startswith(x) for x in prefixes):
        reasons.append(f'review model {p.get("model_reported")!r} is not an OpenAI model')
    if review.get('head_sha') != head_sha:
        reasons.append('review was for a different commit')
    if review.get('verdict') != APPROVE:
        reasons.append(f'ChatGPT verdict is {review.get("verdict") or UNKNOWN!r}: {(review.get("verdict_line") or "").strip()[:200]}')
    return reasons


def decide(pr, commits, checks, apk, review, cfg, *, enabled, dry_run, tested_head, tested_base, current_base):
    """Return {'merge': bool, 'reasons': [...], ...}. Pure function; unit-tested."""
    info, reasons = pr_eligibility(pr, commits, cfg)
    if dry_run:
        reasons.append('dry run: never merges')
    if not enabled:
        reasons.append(f'auto-merge is off (repository variable {cfg["auto_merge"]["enabled_var"]} is not "true")')
    head = (pr.get('head') or {}).get('sha')
    if not tested_head or head != tested_head:
        reasons.append('the PR head changed after the checks ran')
    if not tested_base or not current_base or current_base != tested_base:
        reasons.append('main moved after the checks ran (re-checked on the next run)')
    if pr.get('mergeable') is not True or pr.get('mergeable_state') == 'dirty':
        reasons.append(f'GitHub does not report the PR as mergeable (mergeable={pr.get("mergeable")}, state={pr.get("mergeable_state")})')
    for name in cfg['auto_merge']['required_checks']:
        if (checks or {}).get(name) != 'success':
            reasons.append(f'required check {name!r} is {(checks or {}).get(name) or "missing"}')
    if not apk or apk.get('ok') is not True:
        reasons.append('APK verification did not pass')
    elif apk.get('package') != cfg['protect']['package_id'] + '.ci':
        reasons.append(f'APK package is {apk.get("package")!r}, expected the CI package')
    reasons += review_ok(review, head, cfg)
    return {**info, 'merge': not reasons, 'reasons': reasons, 'tested_head': tested_head, 'tested_base': tested_base,
            'merge_method': cfg['auto_merge']['merge_method']}
