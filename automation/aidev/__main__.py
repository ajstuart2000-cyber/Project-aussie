"""CLI: python -m aidev <plan|develop|review|report|guard|jscheck> ..."""
import argparse, json, os, sys

from . import budget as B, config, develop, guardrails as G, jscheck, report, repo, review, tasks


def _out(**kv):
    path = os.environ.get('GITHUB_OUTPUT')
    for k, v in kv.items():
        v = '' if v is None else (str(v).lower() if isinstance(v, bool) else str(v))
        print(f'{k}={v}')
        if path:
            with open(path, 'a') as fh:
                fh.write(f'{k}={v}\n')


def _load(p, default=None):
    if p and os.path.isfile(p):
        with open(p) as fh:
            return json.load(fh)
    return default


def _dump(obj, p):
    with open(p, 'w') as fh:
        json.dump(obj, fh, indent=2)


def cmd_plan(a, cfg):
    date = B.perth_date(offset_hours=cfg['utc_offset_hours'])
    event = a.event or os.environ.get('GITHUB_EVENT_NAME', 'local')
    dry = a.dry_run
    note = ''
    if event == 'schedule' and os.environ.get('AI_DEV_ENABLED', '').lower() != 'true':
        dry, note = True, 'Repository variable AI_DEV_ENABLED is not "true", so this scheduled run is a dry run (no AI calls).'
    if a.fixtures:
        fx = _load(a.fixtures)
        items, prs, events, comments = fx['issues'], fx['pulls'], {int(k): v for k, v in fx.get('events', {}).items()}, fx.get('report_comments', [])
    else:
        from . import gh_api
        token, rp = os.environ['GITHUB_TOKEN'], a.repo
        items = gh_api.get(f'/repos/{rp}/issues', token, 'state=open&per_page=100')
        prs = gh_api.get(f'/repos/{rp}/pulls', token, 'state=open&per_page=100')
        events = {}
        for it in items:
            names = tasks.label_names(it)
            if not it.get('pull_request') and cfg['labels']['approved'] in names:
                events[it['number']] = gh_api.get(f'/repos/{rp}/issues/{it["number"]}/events', token, 'per_page=100')
        rep = next((i for i in items if cfg['labels']['report'] in tasks.label_names(i) and not i.get('pull_request')), None)
        comments = [c['body'] for c in gh_api.get(f'/repos/{rp}/issues/{rep["number"]}/comments', token, 'per_page=100')] if rep else []
    issues = [i for i in items if not i.get('pull_request') and cfg['labels']['report'] not in tasks.label_names(i)]
    rep_issue = next((i['number'] for i in items if cfg['labels']['report'] in tasks.label_names(i) and not i.get('pull_request')), '')
    ran, spent = B.today_status(comments, date)
    plan = {'date': date, 'event': event, 'dry_run': dry, 'note': note, 'report_issue': rep_issue,
            'open_issues': len(issues), 'approved_issues': sum(cfg['labels']['approved'] in tasks.label_names(i) for i in issues),
            'open_prs': [{'number': p['number'], 'title': p['title'], 'head': p['head']['ref'],
                          'ai': p['head']['ref'].startswith('ai/')} for p in prs],
            'budget': {'daily_usd': cfg['limits']['daily_budget_usd'], 'spent_before_usd': spent},
            'task': None, 'considered': [], 'skip_reason': ''}
    if event == 'schedule' and ran and not dry:
        plan['skip_reason'] = f'A live run already reported for {date} (Perth); this later trigger is the backup and does nothing.'
        plan['duplicate'] = True
    elif spent >= cfg['limits']['daily_budget_usd'] and not dry:
        plan['skip_reason'] = f'Daily budget already used (${spent:.4f} of ${cfg["limits"]["daily_budget_usd"]:.2f}).'
    else:
        chosen, considered = tasks.select(issues, events, prs, cfg, only_issue=a.issue or None)
        plan['considered'] = considered
        if chosen:
            plan['task'] = chosen
        else:
            plan['skip_reason'] = 'No open issue meets the approval rules (needs owner-applied `ai-approved` + one of `ai:grok`/`ai:claude`).'
    _dump(plan, a.out)
    t = plan['task'] or {}
    _out(should_run=bool(t), dry_run=dry, duplicate=bool(plan.get('duplicate')), role=t.get('role', ''),
         issue=t.get('number', ''), branch=t.get('branch', ''), mode=t.get('mode', ''),
         pr_number=t.get('pr_number') or '', audio_approved=bool(t.get('audio_approved')),
         report_issue=rep_issue, date=date, spent_usd=spent)


def cmd_develop(a, cfg):
    plan = _load(a.plan)
    feedback = open(a.feedback).read() if a.feedback and os.path.isfile(a.feedback) else ''
    res = develop.run(plan['task'], cfg, plan['budget']['spent_before_usd'], dry_run=plan['dry_run'] or a.dry_run,
                      root=a.root, feedback=feedback)
    _dump(res, a.out)
    print(json.dumps({k: v for k, v in res.items() if k not in ('js_check',)}, indent=2))
    _out(status=res['status'], cost_usd=res['cost_usd'], calls=res['calls'])
    return 1 if res['status'] in ('failed', 'rejected') else 0


def cmd_review(a, cfg):
    plan, dev = _load(a.plan), _load(a.dev_result, {})
    diff_text = open(a.diff).read() if a.diff and os.path.isfile(a.diff) else ''
    ctx = (f'Issue #{plan["task"]["number"]}: {plan["task"]["title"]}\nAuthor role: {plan["task"]["role"]} '
           f'({dev.get("provider_name", "")}). Audio-approved: {plan["task"].get("audio_approved", False)}\n'
           f'Developer summary: {dev.get("summary", "")}\nCI results: {a.ci_results}\n')
    spent = plan['budget']['spent_before_usd'] + dev.get('cost_usd', 0)
    res = review.run(cfg, diff_text, ctx, spent_today=spent, calls_used=dev.get('calls', 0), dry_run=plan['dry_run'])
    _dump(res, a.out)
    if res.get('review_md'):
        p = res.get('provider') or {}
        with open(a.out + '.md', 'w') as fh:
            fh.write(f'## 🤖 ChatGPT code review (OpenAI API · model `{p.get("model_reported")}` · response `{p.get("response_id")}`)\n\n'
                     f'{res["review_md"]}\n\n_Advisory review only. Automation never merges; the owner decides._\n')
    print(json.dumps({k: v for k, v in res.items() if k != 'review_md'}, indent=2))
    _out(status=res['status'])
    return 1 if res['status'] == 'failed' else 0


def cmd_report(a, cfg):
    plan = _load(a.plan)
    dev, rev, apk = _load(a.dev_result), _load(a.review), _load(a.apk)
    if dev is not None and a.pr_url:
        dev['pr_url'] = a.pr_url
    jobs = json.loads(a.jobs) if a.jobs else {}
    md, status = report.render(plan, dev, rev, apk, jobs, a.run_url, a.run_id, a.event)
    with open(a.out, 'w') as fh:
        fh.write(md + '\n')
    print(md)
    _out(status=status)
    return 1 if status == 'failure' else 0


def cmd_guard(a, cfg):
    labels = [l for l in (a.labels or '').split(',') if l.strip()]
    ctx = G.Context.from_branch(a.branch or '', labels)
    d = repo.diff(a.base, a.head)
    changes = G.parse_unified_diff(d)
    viol = G.check(changes, lambda p: repo.show(a.base, p), lambda p: repo.show(a.head, p), cfg, ctx)
    md = (f'### Protected-area check ({ctx.mode} mode{", role " + ctx.role if ctx.role else ""})\n'
          f'Changed files: {len(changes)} · labels: {", ".join(sorted(ctx.labels)) or "none"}\n\n' + G.format_violations(viol))
    print(md)
    if a.summary:
        with open(a.summary, 'a') as fh:
            fh.write(md + '\n')
    for v in viol:
        print(f'::error file={v["path"]}::{v["rule"]}: {v["detail"]}')
    return 1 if viol else 0


def cmd_jscheck(a, cfg):
    ok, res = jscheck.check_html(a.file)
    for r in res:
        print(f'{"OK  " if r["ok"] else "FAIL"} <script> #{r["index"]} ({r["type"]}, starts line {r["line"]}) {r["error"]}')
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog='aidev')
    ap.add_argument('--config')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('plan'); p.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY', ''))
    p.add_argument('--out', default='plan.json'); p.add_argument('--dry-run', action='store_true')
    p.add_argument('--issue', type=int); p.add_argument('--event'); p.add_argument('--fixtures')
    p = sub.add_parser('develop'); p.add_argument('--plan', default='plan.json'); p.add_argument('--out', default='dev-result.json')
    p.add_argument('--root', default='.'); p.add_argument('--feedback'); p.add_argument('--dry-run', action='store_true')
    p = sub.add_parser('review'); p.add_argument('--plan', default='plan.json'); p.add_argument('--dev-result', default='dev-result.json')
    p.add_argument('--diff'); p.add_argument('--ci-results', default=''); p.add_argument('--out', default='review.json')
    p = sub.add_parser('report'); p.add_argument('--plan', default='plan.json'); p.add_argument('--dev-result'); p.add_argument('--review')
    p.add_argument('--apk'); p.add_argument('--jobs'); p.add_argument('--run-url', default=''); p.add_argument('--run-id', default='')
    p.add_argument('--event', default=''); p.add_argument('--pr-url', default=''); p.add_argument('--out', default='report.md')
    p = sub.add_parser('guard'); p.add_argument('--base', required=True); p.add_argument('--head', default='HEAD')
    p.add_argument('--branch', default=''); p.add_argument('--labels', default=''); p.add_argument('--summary')
    p = sub.add_parser('jscheck'); p.add_argument('--file', default='www/index.html')
    a = ap.parse_args(argv)
    cfg = config.load_config(a.config)
    return {'plan': cmd_plan, 'develop': cmd_develop, 'review': cmd_review, 'report': cmd_report,
            'guard': cmd_guard, 'jscheck': cmd_jscheck}[a.cmd](a, cfg) or 0


if __name__ == '__main__':
    sys.exit(main())
