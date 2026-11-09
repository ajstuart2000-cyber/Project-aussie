"""Task selection and approval rules.

An issue is eligible only if ALL of these hold:
  1. it is an open issue (not a pull request);
  2. it carries `ai-approved`, and the most recent time that label was added it
     was added by the repository owner (checked against the issue's label events);
  3. it carries exactly one developer role label: `ai:grok` or `ai:claude`;
  4. it carries none of the blocking labels (ai-blocked, ai-done, wontfix, ...);
  5. if it is an audio/sound task (label `audio`/`sound`, or audio words in the
     title/body), it must be assigned to Claude (`ai:claude`) AND carry
     `audio-approved` added by the owner. Audio tasks are never given to Grok;
  6. there is no open AI pull request for it awaiting the owner, unless the
     owner put `ai-revise` on that PR (then the run updates the same PR).
Eligible issues are ordered by `priority:P0`..`priority:P3` (unlabelled last),
then oldest first. Exactly one task is chosen per run.
"""
import re

AUDIO_WORDS = re.compile(r'\b(audio|sounds?|engine note|exhaust note|siren|wav|sfx|volume|limiter sound|backfire sound|AudioContext)\b', re.I)


def label_names(item):
    return {(l['name'] if isinstance(l, dict) else l) for l in item.get('labels', [])}


def last_labeler(events, label):
    who = None
    for e in events or []:
        if e.get('event') == 'labeled' and (e.get('label') or {}).get('name') == label:
            who = (e.get('actor') or {}).get('login')
    return who


def is_audio_task(issue, cfg):
    labels = label_names(issue)
    if labels & set(cfg['labels']['audio_topic']):
        return True
    return bool(AUDIO_WORDS.search((issue.get('title') or '') + '\n' + (issue.get('body') or '')))


def priority_of(labels, cfg):
    pre = cfg['labels']['priority_prefix']
    best = 9
    for l in labels:
        if l.startswith(pre):
            m = re.match(r'[Pp](\d)', l[len(pre):])
            if m:
                best = min(best, int(m.group(1)))
    return best


def branch_prefix(role, number):
    return f'ai/{role}/issue-{number}-'


def slug(title):
    s = re.sub(r'[^a-z0-9]+', '-', (title or '').lower()).strip('-')
    return s[:40].strip('-') or 'task'


def evaluate(issue, events, open_prs, cfg):
    """Return (eligible: bool, info: dict)."""
    L, owner = cfg['labels'], cfg['owner']
    labels = label_names(issue)
    info = {'number': issue['number'], 'title': issue.get('title', ''), 'labels': sorted(labels)}
    if 'pull_request' in issue:
        return False, {**info, 'reason': 'is a pull request'}
    if L['approved'] not in labels:
        return False, {**info, 'reason': f'no `{L["approved"]}` label'}
    who = last_labeler(events, L['approved'])
    if who != owner:
        return False, {**info, 'reason': f'`{L["approved"]}` was not applied by the owner ({owner}); applied by {who or "unknown"}'}
    blocked = labels & set(L['blocked'])
    if blocked:
        return False, {**info, 'reason': f'blocked by label(s) {sorted(blocked)}'}
    roles = [r for r, rc in cfg['roles'].items() if rc.get('label') and rc['label'] in labels]
    if len(roles) != 1:
        return False, {**info, 'reason': 'needs exactly one role label (ai:grok or ai:claude)' if not roles else f'has several role labels {roles}'}
    role = roles[0]
    audio = is_audio_task(issue, cfg)
    if audio:
        if not cfg['roles'][role].get('may_touch_audio'):
            return False, {**info, 'role': role, 'audio': True,
                           'reason': 'audio/sound task assigned to Grok - audio work is Claude-only (relabel ai:claude + audio-approved)'}
        if L['audio_approved'] not in labels:
            return False, {**info, 'role': role, 'audio': True, 'reason': f'audio is frozen: needs the owner\'s `{L["audio_approved"]}` label'}
        who_a = last_labeler(events, L['audio_approved'])
        if who_a != owner:
            return False, {**info, 'role': role, 'audio': True,
                           'reason': f'`{L["audio_approved"]}` was not applied by the owner; applied by {who_a or "unknown"}'}
    pre = branch_prefix(role, issue['number'])
    pr = next((p for p in open_prs if (p.get('head') or {}).get('ref', '').startswith(pre)), None)
    mode, branch = 'create', pre + slug(issue.get('title'))
    if pr:
        if L['revise'] in label_names(pr):
            mode, branch = 'update', pr['head']['ref']
        else:
            return False, {**info, 'role': role, 'audio': audio,
                           'reason': f'AI PR #{pr["number"]} is waiting for owner review (add `{L["revise"]}` to request changes)'}
    return True, {**info, 'role': role, 'audio': audio, 'audio_approved': audio and L['audio_approved'] in labels,
                  'priority': priority_of(labels, cfg), 'created_at': issue.get('created_at', ''),
                  'mode': mode, 'branch': branch, 'pr_number': pr['number'] if pr else None,
                  'body': issue.get('body') or '', 'reason': 'eligible'}


def select(issues, events_by_number, open_prs, cfg, only_issue=None):
    considered, eligible = [], []
    for it in issues:
        if only_issue and it['number'] != only_issue:
            continue
        ok, info = evaluate(it, events_by_number.get(it['number'], []), open_prs, cfg)
        considered.append(info)
        if ok:
            eligible.append(info)
    eligible.sort(key=lambda t: (t['priority'], t['created_at'], t['number']))
    chosen = eligible[0] if eligible else None
    for c in considered:
        if chosen and c['number'] == chosen['number']:
            c['reason'] = 'SELECTED'
        elif c['reason'] == 'eligible':
            c['reason'] = 'eligible, lower priority than the selected task'
    return chosen, [{k: v for k, v in c.items() if k != 'body'} for c in considered]
