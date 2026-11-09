"""Daily development report (format documented in docs/AI_DAILY_REPORT_FORMAT.md)."""

ICON = {'success': '✅', 'failure': '❌', 'cancelled': '⛔', 'skipped': '⏭️', '': '–', None: '–'}
DEV_ICON = {'changed': '✅ changed', 'no-change': '➖ no change', 'rejected': '❌ rejected', 'failed': '❌ failed',
            'skipped': '⏭️ skipped', 'dry-run': '🧪 dry run', None: '⏭️ not run'}
REV_ICON = {'reviewed': '✅ reviewed', 'reused': '♻️ earlier review of this commit reused', 'failed': '❌ failed',
            'skipped': '⏭️ skipped', 'dry-run': '🧪 dry run', None: '⏭️ not run'}


def overall(plan, dev, review, jobs, merge=None):
    bad = [k for k, v in (jobs or {}).items() if v in ('failure', 'cancelled')]
    if (merge or {}).get('error'):
        bad.append('auto-merge')
    if (dev or {}).get('status') in ('failed', 'rejected'):
        bad.append('developer')
    if (review or {}).get('status') == 'failed':
        bad.append('review')
    if bad:
        return 'failure', bad
    if plan.get('dry_run'):
        return 'dry-run', []
    if not plan.get('task'):
        return 'no-task', []
    if (dev or {}).get('status') == 'changed' and (dev or {}).get('pr_url'):
        return 'success', []
    return 'incomplete', []


def _provider_row(role_title, res, icons):
    if not res:
        return f'| {role_title} | – | – | – | – | – | ⏭️ not run |'
    p = res.get('provider') or {}
    called = p.get('endpoint_host') or ('not called' if res.get('status') != 'dry-run' else 'not called (dry run)')
    tok = f'{p.get("input_tokens", 0):,} / {p.get("output_tokens", 0):,}' if p else '–'
    return (f'| {res.get("role_title", role_title)} | {res.get("provider_name", "")} → `{called}` | '
            f'`{p.get("model_reported") or "–"}` (configured `{res.get("model_configured", "")}`) | '
            f'`{p.get("response_id") or "–"}` | {tok} | ${res.get("cost_usd", 0):.4f} | {icons.get(res.get("status"), res.get("status"))} |')


def merge_lines(merge):
    """Auto-merge section shared by the daily report and the merge-gate report."""
    if not merge:
        return ['- The merge gate did not run (no AI pull request in this run).']
    if merge.get('merged'):
        return [f'- ✅ **Merged into `main`** ({merge.get("merge_method", "squash")}) as `{merge.get("merge_commit_sha", "")[:12]}` '
                f'after every gate passed (tested head `{(merge.get("tested_head") or "")[:12]}`).']
    if merge.get('error'):
        return [f'- ❌ Every gate passed but the merge call failed: {merge["error"][:500]}']
    L = ['- ⏸️ **Not merged.** Reasons:']
    L += [f'  - {r}' for r in merge.get('reasons', [])] or ['  - (no reason recorded)']
    return L


def render(plan, dev=None, review=None, apk=None, jobs=None, run_url='', run_id='', event='', merge=None):
    status, bad = overall(plan, dev, review, jobs, merge)
    mode = 'dry-run' if plan.get('dry_run') else 'live'
    cost = round((dev or {}).get('cost_usd', 0) + (review or {}).get('cost_usd', 0), 6)
    date = plan.get('date', '')
    L = [f'<!-- aidev-report date={date} mode={mode} status={status} cost_usd={cost:.6f} run_id={run_id} -->',
         f'# Project Aussie — daily AI development report — {date} (Perth, AWST)', '',
         f'**Run:** [{run_id or "local"}]({run_url or "#"}) · **Trigger:** {event or plan.get("event", "")} · '
         f'**Mode:** {mode} · **Overall:** {status}', '']
    if plan.get('note'):
        L += [f'> {plan["note"]}', '']
    L += ['## 1. Repository status',
          f'- Open issues: {plan.get("open_issues", 0)} (with `ai-approved`: {plan.get("approved_issues", 0)})',
          f'- Open pull requests: {len(plan.get("open_prs", []))}']
    for pr in plan.get('open_prs', [])[:20]:
        L.append(f'  - #{pr["number"]} {pr["title"]} (`{pr["head"]}`){" — AI" if pr.get("ai") else ""}')
    L += ['', '## 2. Task selection']
    t = plan.get('task')
    if t:
        L.append(f'- **Selected:** #{t["number"]} {t["title"]} → **{t["role"]}** · priority P{t["priority"] if t["priority"] < 9 else "–"} · '
                 f'audio task: {"yes (audio-approved)" if t.get("audio") else "no"} · {t["mode"]} `{t["branch"]}`')
    else:
        L.append('- **No task selected.** ' + (plan.get('skip_reason') or 'No issue met the approval rules.'))
    cons = plan.get('considered', [])
    if cons:
        L += ['', '| Issue | Labels | Decision |', '|---|---|---|']
        for c in cons[:30]:
            L.append(f'| #{c["number"]} {c["title"][:60]} | {", ".join(c["labels"])} | {c["reason"]} |')
    L += ['', '## 3. AI team (who was actually called)',
          '| Role | Provider → endpoint | Model reported by API | Response id | Tokens in / out | Est. cost | Result |',
          '|---|---|---|---|---|---|---|',
          _provider_row('Developer', dev, DEV_ICON), _provider_row('Code reviewer (ChatGPT)', review, REV_ICON)]
    if t:
        other = 'Claude' if t['role'] == 'grok' else 'Grok'
        L.append(f'\n_{other} was not scheduled today: one development task per run._')
    L += ['', '## 4. Changes']
    if dev:
        if dev.get('pr_url'):
            L.append(f'- Pull request: {dev["pr_url"]} (branch `{dev.get("branch")}`) — '
                     + ('**merged automatically** (see Auto-merge)' if (merge or {}).get('merged') else 'not merged (see Auto-merge)'))
        if dev.get('changed_files'):
            L.append('- Files: ' + ', '.join(f'`{f}`' for f in dev['changed_files']))
        if dev.get('summary'):
            L.append(f'- Developer summary: {dev["summary"]}')
        if dev.get('error'):
            L += ['- Problem:', '', '```', dev['error'][:3000], '```']
        if dev.get('owner_test_steps'):
            L.append('- Owner phone test steps (not done by CI):')
            L += [f'  - [ ] {s}' for s in dev['owner_test_steps']]
    else:
        L.append('- No developer step ran.')
    L += ['', '## 5. Checks (results from this run)', '| Check | Result |', '|---|---|']
    for k, v in (jobs or {}).items():
        L.append(f'| {k} | {ICON.get(v, v)} {v} |')
    if apk:
        L.append(f'| APK contents | {"✅" if apk.get("ok") else "❌"} {apk.get("apk_asset_files")} / {apk.get("www_files")} game files, '
                 f'package `{apk.get("package")}`, {apk.get("apk_bytes", 0):,} bytes |')
    L += ['', '## 6. Code review (ChatGPT via OpenAI API)']
    if review and review.get('review_md'):
        L.append(f'- Posted on the PR. Verdict parsed as **{review.get("verdict") or "unknown"}**: '
                 + (review.get('verdict_line') or next((l for l in review['review_md'].splitlines()[::-1] if l.strip()), ''))[:300])
    elif review:
        L.append(f'- {REV_ICON.get(review.get("status"))}: {review.get("error") or "no review text"}')
    else:
        L.append('- Not run.')
    L += ['', '## 7. Auto-merge (owner-enabled 2026-11-10, `AI_AUTO_MERGE`)'] + merge_lines(merge)
    b = plan.get('budget', {})
    L += ['', '## 8. Budget',
          f'- Daily budget ${b.get("daily_usd", 0):.2f} · spent earlier today ${b.get("spent_before_usd", 0):.4f} · '
          f'this run ${cost:.4f} (estimated from API usage fields) · remaining ${b.get("daily_usd", 0) - b.get("spent_before_usd", 0) - cost:.4f}']
    L += ['', '## 9. Needs the owner']
    needs = []
    if bad:
        needs.append('Failures in: ' + ', '.join(bad) + '. The run stopped there; see the run log.')
    if dev and dev.get('pr_url') and not (merge or {}).get('merged'):
        needs.append(f'{dev["pr_url"]} was not auto-merged (reasons above). Merge it yourself if happy, or add `ai-revise` with comments.')
    if (merge or {}).get('merged'):
        needs.append('Play-test the merged change on the phone (CI cannot do that).')
    for r in (dev, review):
        if r and r.get('status') == 'skipped' and r.get('error'):
            needs.append(r['error'])
    L += [f'- {n}' for n in needs] or ['- Nothing.']
    L += ['', '_Every result above comes from this run\'s logs and API responses. Nothing was tested on a phone. '
          'AI PRs are merged into `main` only by the merge gate (all checks + ChatGPT APPROVE, `AI_AUTO_MERGE=true`); '
          'releases are never published._']
    return '\n'.join(L), status


def render_gate(meta, review=None, decision=None, run_url='', run_id='', event=''):
    """Report for a stand-alone merge-gate run (dispatch or the daily sweep). kind=gate markers
    count toward the day's spend but do not count as the day's development run."""
    dry = bool(meta.get('dry_run'))
    cost = round((review or {}).get('cost_usd', 0) or 0, 6)
    d = decision or {}
    if not meta.get('found'):
        status = 'no-pr'
    elif d.get('merged'):
        status = 'merged'
    elif d.get('error') or (review or {}).get('status') == 'failed' or any(
            v in ('failure', 'cancelled') for v in (d.get('checks') or {}).values()):
        status = 'failure'
    elif dry:
        status = 'dry-run'
    else:
        status = 'not-merged'
    mode = 'dry-run' if dry else 'live'
    L = [f'<!-- aidev-report kind=gate date={meta.get("date", "")} mode={mode} status={status} cost_usd={cost:.6f} run_id={run_id} -->',
         f'# Project Aussie — AI PR merge gate — {meta.get("date", "")} (Perth, AWST)', '',
         f'**Run:** [{run_id or "local"}]({run_url or "#"}) · **Trigger:** {event or meta.get("event", "")} · **Mode:** {mode} · **Result:** {status}', '']
    if not meta.get('found'):
        L.append('- No open AI pull request needed the gate.')
        for c in meta.get('considered', []):
            L.append(f'  - #{c["number"]} {c["title"][:60]}: {c["reason"]}')
        return '\n'.join(L), status
    L += [f'- Pull request: {meta.get("url") or "#" + str(meta.get("number"))} · branch `{meta.get("branch")}` · head `{meta.get("head_sha", "")[:12]}` '
          f'· role {meta.get("role")} · issue #{meta.get("issue")}', '', '## Checks (this run)', '| Check | Result |', '|---|---|']
    for k, v in (d.get('checks') or {}).items():
        L.append(f'| {k} | {ICON.get(v, v)} {v} |')
    L += ['', '## ChatGPT review (OpenAI API)',
          '| Role | Provider → endpoint | Model reported by API | Response id | Tokens in / out | Est. cost | Result |',
          '|---|---|---|---|---|---|---|', _provider_row('Code reviewer (ChatGPT)', review, REV_ICON)]
    if review:
        L.append(f'- Verdict: **{review.get("verdict") or "–"}** {(review.get("verdict_line") or "")[:300]}')
        if review.get('error'):
            L.append(f'- Problem: {review["error"][:1000]}')
    L += ['', '## Auto-merge'] + merge_lines(d)
    L += ['', f'Estimated cost of this run: ${cost:.4f} (counted toward the daily budget).', '',
          '_Results come from this run only. Nothing was tested on a phone. Releases are never published._']
    return '\n'.join(L), status
