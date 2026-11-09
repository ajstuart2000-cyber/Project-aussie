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
4. **Changes**: PR link (*not merged*), changed files, the developer's summary, any
   rejection reason (the guardrail rule that failed), and phone test steps for the owner.
5. **Checks**: the conclusion of each job in this run (plan, developer, code validation,
   Android build + APK check, review job) and the APK check numbers (files in the APK vs
   `www/`, package name, size).
6. **Code review (ChatGPT)**: the verdict line. The full review is a PR comment.
7. **Budget**: the daily budget, what was spent earlier today, this run's cost and what is
   left. These are estimates from API usage.
8. **Needs the owner**: failures, missing keys, and PRs waiting for review.

The footer always says that results come from the run itself, nothing was phone-tested,
and automation never merges or releases.
