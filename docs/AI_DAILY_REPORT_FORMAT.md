# Daily development report format

Each run writes one Markdown report:
- in the run's **job summary**;
- as the `daily-report` artifact (kept 90 days);
- **live runs only:** as a comment on the issue **"Daily AI development reports"**
  (label `ai-report`, created automatically on the first live run).

The first line is a machine-readable marker. The workflow uses it to avoid running twice on
the same Perth day and to add up the day's spend:

```
<!-- aidev-report date=YYYY-MM-DD mode=live|dry-run status=<status> cost_usd=<float> run_id=<id> -->
```

Stand-alone merge-gate runs (`ai-pr-gate.yml` by hand or the 05:30 sweep) post a shorter
report whose marker starts `aidev-report kind=gate` with status `merged`, `not-merged`,
`failure`, `dry-run` or `no-pr`. Its cost counts toward the day's budget, but it does not
count as the day's development run.

`status` is one of:
- `success`: a PR was opened or updated.
- `no-task`: nothing was approved.
- `incomplete`: a role was skipped, for example a missing key or the budget ran out.
- `dry-run`.
- `failure`: a job failed, or the patch was rejected or failed. The run is marked failed.

## Sections

1. **Repository status**: open issues, how many are `ai-approved`, and the open PRs.
2. **Task selection**: the chosen issue, role, priority, whether it is an audio task, and
   the branch. Then a table of every issue looked at, with the reason.
3. **AI team (who was actually called)**: one row per role, with provider → endpoint host,
   *the model name the API reported*, the response id, tokens in/out, estimated cost and
   the result (`changed` / `no change` / `rejected` / `failed` / `skipped` / `dry run`). A
   role that wasn't called says so.
4. **Changes**: PR link (merged automatically or not), changed files, the developer's summary, any
   rejection reason (the guardrail rule that failed), and phone test steps for the owner.
5. **Checks**: the conclusion of each job in this run (plan, developer, code validation,
   Android build + APK check, review job, merge-gate guardrail re-check, merge gate) and the APK check numbers (files in the APK vs
   `www/`, package name, size).
6. **Code review (ChatGPT)**: the verdict as parsed by the gate (`approve` / `changes` /
   `unknown`) and the verdict line. The full review is a PR comment.
7. **Auto-merge**: merged (squash commit SHA) or *not merged* with every reason, or the
   merge-call error. Auto-merge was enabled by the owner on 2026-11-10 (`AI_AUTO_MERGE`).
8. **Budget**: the daily budget, what was spent earlier today, this run's cost and what is
   left. These are estimates from API usage.
9. **Needs the owner**: failures, missing keys, and PRs waiting for review.

The footer always says that results come from the run itself, nothing was phone-tested,
AI PRs are merged only by the merge gate, and releases are never published.
