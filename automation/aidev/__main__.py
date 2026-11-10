"""CLI: python -m aidev <plan|feedback|develop|review|report|guard|jscheck|prmeta|gate|gatereport> ..."""
import argparse, json, os, sys, time

from . import budget as B, config, develop, feedback as FB, guardrails as G, jscheck, mergegate as MG, report, repo, review, tasks


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
            if it.get('pull_request') is None and cfg['labels']['approved'] in names:
                events[it['number']] = gh_api.get(f'/repos/{rp}/issues/{it["number"]}/events', token, 'per_page=100')
        rep = next((i for i in items if cfg['labels']['report'] in tasks.label_names(i) and i.get('pull_request') is None), None)
        comments = [c['body'] for c in gh_api.get(f'/repos/{rp}/issues/{rep["number"]}/comments', token, 'per_page=100')] if rep else []
    issues = [i for i in items if i.get('pull_request') is None and cfg['labels']['report'] not in tasks.label_names(i)]
    rep_issue = next((i['number'] for i in items if cfg['labels']['report'] in tasks.label_names(i) and i.get('pull_request') is None), '')
    ran, spent = B.today_status(comments, date)
    plan = {'date': date, 'event': event, 'dry_run': dry, 'note': note, 'report_issue': rep_issue,
            'open_issues': len(issues), 'approved_issues': sum(cfg['labels']['approved'] in tasks.label_names(i) for i in issues),
            'open_prs': [{'number': p['number'], 'title': p['title'], 'head': p['head']['ref'],
                          'ai': p['head']['ref'].startswith('ai/')} for p in prs],
            'budget': {'daily_usd': cfg['limits']['daily_budget_usd'], 'spent_before_usd': spent},
            'task': None, 'considered': [], 'skip_reason': ''}
    if a.backup and dry:
        plan['skip_reason'] = 'Backup trigger while automation is not enabled (dry run): nothing to do.'
        plan['duplicate'] = True
    elif event == 'schedule' and ran:
        plan['skip_reason'] = f'A live run already reported for {date} (Perth); this scheduled trigger (late primary or backup) does nothing.'
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


def cmd_feedback(a, cfg):
    """Write the review/owner feedback an update-mode run must address (see feedback.py)."""
    if a.fixtures:
        fx = _load(a.fixtures)
        comments, reviews, inline = fx.get('comments', []), fx.get('reviews', []), fx.get('review_comments', [])
    else:
        from . import gh_api
        token = os.environ.get('GH_TOKEN') or os.environ['GITHUB_TOKEN']
        comments = gh_api.get(f'/repos/{a.repo}/issues/{a.pr}/comments', token, 'per_page=100')
        reviews = gh_api.get(f'/repos/{a.repo}/pulls/{a.pr}/reviews', token, 'per_page=100')
        inline = gh_api.get(f'/repos/{a.repo}/pulls/{a.pr}/comments', token, 'per_page=100')
    text = FB.build(comments, reviews, inline, cfg, head_sha=a.head_sha or '')
    with open(a.out, 'w') as fh:
        fh.write(text)
    print(f'feedback: {len(text)} chars' + (' (ChatGPT review included)' if 'Latest ChatGPT code review' in text else ' (no ChatGPT review found)'))
    return 0


def cmd_develop(a, cfg):
    plan = _load(a.plan)
    feedback = open(a.feedback).read() if a.feedback and os.path.isfile(a.feedback) else ''
    res = develop.run(plan['task'], cfg, plan['budget']['spent_before_usd'], dry_run=plan['dry_run'] or a.dry_run,
                      root=a.root, feedback=feedback)
    _dump(res, a.out)
    print(json.dumps({k: v for k, v in res.items() if k not in ('js_check',)}, indent=2))
    _out(status=res['status'], cost_usd=res['cost_usd'], calls=res['calls'])
    return 1 if res['status'] in ('failed', 'rejected') else 0


def _review_comment(res):
    p = res.get('provider') or {}
    mk = MG.review_marker(res.get('head_sha', ''), res.get('verdict') or MG.UNKNOWN, res['status'], p.get('response_id'),
                          p.get('model_reported'), p.get('endpoint_host'))
    return (f'## 🤖 ChatGPT code review (OpenAI API · model `{p.get("model_reported")}` · response `{p.get("response_id")}`)\n\n'
            f'Reviewed head `{res.get("head_sha", "")[:12]}`.\n\n{res["review_md"]}\n\n'
            f'_Verdict parsed by the merge gate as **{res.get("verdict")}**. Auto-merge (owner-enabled 2026-11-10, '
            f'repo variable `AI_AUTO_MERGE`) only merges on APPROVE with every check green._\n\n{mk}\n')


def cmd_review(a, cfg):
    if a.pr_meta:
        meta = _load(a.pr_meta)
        head = meta['head_sha']
        prior = meta.get('prior_review')
        if prior and not a.force:
            # Already reviewed by the workflow for this exact head: reuse it, no new API call / cost.
            res = {'status': 'reused', 'role': 'chatgpt', 'role_title': cfg['roles']['chatgpt']['title'],
                   'provider_name': cfg['providers'][cfg['roles']['chatgpt']['provider']]['name'],
                   'model_configured': cfg['roles']['chatgpt']['model'], 'cost_usd': 0.0, 'review_md': '', 'error': '',
                   'provider': {'endpoint_host': prior.get('host', ''), 'response_id': '' if prior.get('response_id') == '-' else prior.get('response_id', ''),
                                'model_reported': '' if prior.get('model') == '-' else prior.get('model', '')},
                   'head_sha': head, 'verdict': prior.get('verdict'), 'verdict_line': f'(reused review {prior.get("comment_url", "")})'}
            _dump(res, a.out)
            print(json.dumps(res, indent=2))
            _out(status='reused', verdict=res['verdict'])
            return 0
        ctx = (f'Pull request #{meta["number"]}: {meta["title"]}\nAuthor role: {meta["role"]} (issue #{meta["issue"]}). '
               f'Audio-approved by the owner on the issue: {bool(meta["guard_labels"])}\n'
               f'PR description (written by the automation):\n{(meta.get("body") or "")[:4000]}\nCI results: {a.ci_results}\n')
        res = review.run(cfg, open(a.diff).read() if a.diff and os.path.isfile(a.diff) else '', ctx,
                         spent_today=meta['spent_before_usd'], calls_used=meta.get('calls_used', 0),
                         dry_run=meta['dry_run'], head_sha=head)
    else:
        plan, dev = _load(a.plan), _load(a.dev_result, {})
        diff_text = open(a.diff).read() if a.diff and os.path.isfile(a.diff) else ''
        ctx = (f'Issue #{plan["task"]["number"]}: {plan["task"]["title"]}\nAuthor role: {plan["task"]["role"]} '
               f'({dev.get("provider_name", "")}). Audio-approved: {plan["task"].get("audio_approved", False)}\n'
               f'Developer summary: {dev.get("summary", "")}\nCI results: {a.ci_results}\n')
        spent = plan['budget']['spent_before_usd'] + dev.get('cost_usd', 0)
        res = review.run(cfg, diff_text, ctx, spent_today=spent, calls_used=dev.get('calls', 0), dry_run=plan['dry_run'],
                         head_sha=a.head_sha or '')
    _dump(res, a.out)
    if res.get('review_md'):
        with open(a.out + '.md', 'w') as fh:
            fh.write(_review_comment(res))
    print(json.dumps({k: v for k, v in res.items() if k != 'review_md'}, indent=2))
    _out(status=res['status'], verdict=res.get('verdict') or '')
    return 1 if res['status'] == 'failed' else 0


def _get_pr_settled(gh_api, rp, num, token, tries=12, wait=5):
    pr = gh_api.get(f'/repos/{rp}/pulls/{num}', token)
    for _ in range(tries):
        if pr.get('mergeable') is not None:
            break
        time.sleep(wait)
        pr = gh_api.get(f'/repos/{rp}/pulls/{num}', token)
    return pr


def cmd_prmeta(a, cfg):
    """Collect everything the merge gate needs about one AI PR (or pick the oldest candidate)."""
    from . import gh_api
    token, rp = os.environ['GITHUB_TOKEN'], a.repo
    date = B.perth_date(offset_hours=cfg['utc_offset_hours'])
    items = gh_api.get(f'/repos/{rp}/issues', token, f'state=open&labels={cfg["labels"]["report"]}&per_page=100')
    rep = next((i for i in items if i.get('pull_request') is None), None)
    rep_comments = [c['body'] for c in gh_api.get(f'/repos/{rp}/issues/{rep["number"]}/comments', token, 'per_page=100')] if rep else []
    _, spent = B.today_status(rep_comments, date)
    meta = {'date': date, 'event': os.environ.get('GITHUB_EVENT_NAME', 'local'), 'dry_run': a.dry_run,
            'spent_before_usd': round(spent + float(a.extra_spent or 0), 6), 'calls_used': int(a.calls_used or 0),
            'daily_budget_usd': cfg['limits']['daily_budget_usd'], 'report_issue': rep['number'] if rep else '',
            'considered': [], 'found': False}
    num = a.pr
    if not num:
        prs = [p for p in gh_api.get(f'/repos/{rp}/pulls', token, 'state=open&per_page=100')
               if (p.get('head') or {}).get('ref', '').startswith(cfg['auto_merge']['branch_prefix'])]
        comments_by = {p['number']: gh_api.get(f'/repos/{rp}/issues/{p["number"]}/comments', token, 'per_page=100') for p in prs}
        num, meta['considered'] = MG.select_candidate(prs, comments_by, cfg)
    if num:
        pr = _get_pr_settled(gh_api, rp, num, token)
        main_sha = gh_api.get(f'/repos/{rp}/branches/{cfg["auto_merge"]["base"]}', token)['commit']['sha']
        head = pr['head']['sha']
        updated = ''
        behind = gh_api.get(f'/repos/{rp}/compare/{main_sha}...{head}', token).get('behind_by', 1)
        if behind and not a.dry_run and pr.get('mergeable') is True and not MG.pr_eligibility(pr, None, cfg)[1]:
            # Bring the AI branch up to date with main ("Update branch"), so the checks test exactly
            # what the squash merge will produce. Live runs only; conflicts leave it behind (no merge).
            try:
                gh_api.put(f'/repos/{rp}/pulls/{num}/update-branch', token, {'expected_head_sha': head})
                for _ in range(24):
                    time.sleep(5)
                    pr = _get_pr_settled(gh_api, rp, num, token)
                    if pr['head']['sha'] != head:
                        break
                updated = f'updated {head[:10]} -> {pr["head"]["sha"][:10]}'
                head = pr['head']['sha']
                behind = gh_api.get(f'/repos/{rp}/compare/{main_sha}...{head}', token).get('behind_by', 1)
            except Exception as e:  # noqa: BLE001 - reported, never fatal; the gate then refuses
                updated = f'update-branch failed: {e}'
        commits = gh_api.get(f'/repos/{rp}/pulls/{num}/commits', token, 'per_page=100')
        anc = set()
        for c in commits:
            for p in [x['sha'] for x in c.get('parents', [])][1:]:
                if gh_api.get(f'/repos/{rp}/compare/{p}...{main_sha}', token).get('behind_by', 1) == 0:
                    anc.add(p)
        comments = gh_api.get(f'/repos/{rp}/issues/{num}/comments', token, 'per_page=100')
        info, reasons = MG.pr_eligibility(pr, commits, cfg, anc)
        issue, events = None, []
        if info['issue']:
            issue = gh_api.get(f'/repos/{rp}/issues/{info["issue"]}', token)
            events = gh_api.get(f'/repos/{rp}/issues/{info["issue"]}/events', token, 'per_page=100')
        check_ref, tested_base = head, (main_sha if behind == 0 else '')
        meta['main_ancestors'] = sorted(anc)
        meta['branch_update'] = updated
        meta.update(found=True, number=num, title=pr.get('title', ''), body=pr.get('body') or '', branch=pr['head']['ref'],
                    head_sha=head, check_ref=check_ref, tested_base=tested_base, role=info['role'], issue=info['issue'],
                    guard_labels=MG.guard_labels(info['role'], issue, events, cfg),
                    prior_review=MG.find_prior_review(comments, head, cfg), eligibility_reasons=reasons,
                    url=pr.get('html_url', ''))
    _dump(meta, a.out)
    print(json.dumps({k: v for k, v in meta.items() if k != 'body'}, indent=2))
    _out(found=meta['found'], pr_number=meta.get('number', ''), head_sha=meta.get('head_sha', ''),
         check_ref=meta.get('check_ref', ''), branch=meta.get('branch', ''), guard_labels=','.join(meta.get('guard_labels', [])),
         eligible=meta['found'] and not meta.get('eligibility_reasons'), report_issue=meta['report_issue'])


def cmd_gate(a, cfg):
    """Final merge decision, taken against the PR's CURRENT state on GitHub."""
    from . import gh_api
    token, rp = os.environ['GITHUB_TOKEN'], a.repo
    meta, rev, apk = _load(a.pr_meta), _load(a.review), _load(a.apk)
    checks = json.loads(a.checks or '{}')
    pr = _get_pr_settled(gh_api, rp, meta['number'], token)
    commits = gh_api.get(f'/repos/{rp}/pulls/{meta["number"]}/commits', token, 'per_page=100')
    main_sha = gh_api.get(f'/repos/{rp}/branches/{cfg["auto_merge"]["base"]}', token)['commit']['sha']
    enabled = os.environ.get(cfg['auto_merge']['enabled_var'], '').strip().lower() == 'true'
    dec = MG.decide(pr, commits, checks, apk, rev, cfg, enabled=enabled, dry_run=bool(meta.get('dry_run')),
                    tested_head=meta.get('head_sha'), tested_base=meta.get('tested_base'), current_base=main_sha,
                    main_ancestors=frozenset(meta.get('main_ancestors') or []))
    dec.update(checks=checks, auto_merge_enabled=enabled, url=meta.get('url', ''), merged=False, merge_commit_sha='', error='')
    _dump(dec, a.out)
    print(json.dumps(dec, indent=2))
    _out(merge=dec['merge'], head_sha=meta.get('head_sha', ''), reason=(dec['reasons'] or ['all gates passed'])[0][:140])
    return 0


def cmd_gatereport(a, cfg):
    meta, rev, dec = _load(a.pr_meta, {}), _load(a.review), _load(a.decision)
    md, status = report.render_gate(meta, rev, dec, a.run_url, a.run_id, a.event)
    with open(a.out, 'w') as fh:
        fh.write(md + '\n')
    print(md)
    _out(status=status)
    return 1 if status == 'failure' else 0


def cmd_report(a, cfg):
    plan = _load(a.plan)
    dev, rev, apk = _load(a.dev_result), _load(a.review), _load(a.apk)
    if dev is not None and a.pr_url:
        dev['pr_url'] = a.pr_url
    jobs = json.loads(a.jobs) if a.jobs else {}
    md, status = report.render(plan, dev, rev, apk, jobs, a.run_url, a.run_id, a.event, merge=_load(a.merge))
    with open(a.out, 'w') as fh:
        fh.write(md + '\n')
    print(md)
    _out(status=status)
    return 1 if status == 'failure' else 0


def cmd_prbody(a, cfg):
    plan, dev = _load(a.plan), _load(a.dev_result)
    t = plan['task']
    p = dev.get('provider') or {}
    who = {'grok': 'Grok', 'claude': 'Claude'}[t['role']]
    title = f'[AI · {who}] {t["title"]} (#{t["number"]})'[:200]
    body = [f'Automated change for #{t["number"]} by **{who} — {dev["role_title"]}**, generated through the '
            f'{dev["provider_name"]} API (`{p.get("endpoint_host")}`, model reported by the API: `{p.get("model_reported")}`, '
            f'response id `{p.get("response_id")}`).', '',
            '> ℹ️ Auto-merge (enabled by the owner on 2026-11-10, repo variable `AI_AUTO_MERGE`): this PR is squash-merged '
            'into `main` only if code validation, the Android build + APK check and the protected-area check pass and '
            'ChatGPT\'s review verdict is APPROVE. Add `ai-revise` or `do-not-merge` to stop it. Releases are never published.', '',
            '### Summary', dev.get('summary') or '–', '',
            '### Files', *[f'- `{f}`' for f in dev.get('changed_files', [])], '',
            '### Owner test steps (not done by CI)', *([f'- [ ] {s}' for s in dev.get('owner_test_steps', [])] or ['- [ ] Play-test the change on the phone']), '',
            '### Risks noted by the developer model', dev.get('risks') or '–', '',
            '### Guardrails at generation time',
            f'- Protected-area check: passed (role `{t["role"]}`, audio-approved: {bool(t.get("audio_approved"))})',
            '- JS syntax check of www/index.html: ' + ('passed' if (dev.get('js_check') or {}).get('ok') else 'not applicable'),
            '- CI checks, the Android build, the ChatGPT review and the merge gate are run by the workflow; see its run and report.', '',
            f'Closes nothing automatically. Related: #{t["number"]}', '',
            f'<!-- aidev-pr issue={t["number"]} role={t["role"]} -->']
    with open(a.out, 'w') as fh:
        fh.write('\n'.join(body) + '\n')
    _out(title=title)


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
    p.add_argument('--backup', action='store_true', help='this is the later backup schedule trigger')
    p = sub.add_parser('feedback'); p.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY', ''))
    p.add_argument('--pr', type=int); p.add_argument('--head-sha', default=''); p.add_argument('--out', default='feedback.md')
    p.add_argument('--fixtures')
    p = sub.add_parser('develop'); p.add_argument('--plan', default='plan.json'); p.add_argument('--out', default='dev-result.json')
    p.add_argument('--root', default='.'); p.add_argument('--feedback'); p.add_argument('--dry-run', action='store_true')
    p = sub.add_parser('review'); p.add_argument('--plan', default='plan.json'); p.add_argument('--dev-result', default='dev-result.json')
    p.add_argument('--diff'); p.add_argument('--ci-results', default=''); p.add_argument('--out', default='review.json')
    p.add_argument('--pr-meta'); p.add_argument('--head-sha'); p.add_argument('--force', action='store_true')
    p = sub.add_parser('report'); p.add_argument('--plan', default='plan.json'); p.add_argument('--dev-result'); p.add_argument('--review')
    p.add_argument('--apk'); p.add_argument('--jobs'); p.add_argument('--run-url', default=''); p.add_argument('--run-id', default='')
    p.add_argument('--event', default=''); p.add_argument('--pr-url', default=''); p.add_argument('--out', default='report.md')
    p.add_argument('--merge')
    p = sub.add_parser('guard'); p.add_argument('--base', required=True); p.add_argument('--head', default='HEAD')
    p.add_argument('--branch', default=''); p.add_argument('--labels', default=''); p.add_argument('--summary')
    p = sub.add_parser('prbody'); p.add_argument('--plan', default='plan.json'); p.add_argument('--dev-result', default='dev-result.json')
    p.add_argument('--out', default='pr-body.md')
    p = sub.add_parser('jscheck'); p.add_argument('--file', default='www/index.html')
    p = sub.add_parser('prmeta'); p.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY', ''))
    p.add_argument('--pr', type=int); p.add_argument('--out', default='pr-meta.json'); p.add_argument('--dry-run', action='store_true')
    p.add_argument('--extra-spent', default='0'); p.add_argument('--calls-used', default='0')
    p = sub.add_parser('gate'); p.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY', ''))
    p.add_argument('--pr-meta', required=True); p.add_argument('--review'); p.add_argument('--apk'); p.add_argument('--checks')
    p.add_argument('--out', default='merge-result.json')
    p = sub.add_parser('gatereport'); p.add_argument('--pr-meta'); p.add_argument('--review'); p.add_argument('--decision')
    p.add_argument('--run-url', default=''); p.add_argument('--run-id', default=''); p.add_argument('--event', default='')
    p.add_argument('--out', default='gate-report.md')
    a = ap.parse_args(argv)
    cfg = config.load_config(a.config)
    return {'plan': cmd_plan, 'feedback': cmd_feedback, 'develop': cmd_develop, 'review': cmd_review, 'report': cmd_report,
            'guard': cmd_guard, 'prbody': cmd_prbody, 'jscheck': cmd_jscheck, 'prmeta': cmd_prmeta, 'gate': cmd_gate,
            'gatereport': cmd_gatereport}[a.cmd](a, cfg) or 0


if __name__ == '__main__':
    sys.exit(main())
