# Project Aussie — automated AI development

> **Status: NOT ACTIVE YET.** The infrastructure is in place but daily AI development is
> not running. It only counts as active after a real scheduled or manually started run has
> called the configured AI APIs, opened a development pull request and finished the
> required checks. Until the API keys are added and `AI_DEV_ENABLED` is set to `true`,
> scheduled runs are dry runs: they plan, run the checks and build the test APK, and they
> make no AI calls.

> **Auto-merge is ON by the owner's decision (2026-11-10).** The owner (ajstuart2000-cyber)
> asked for all updates to be approved automatically. AI pull requests are now squash-merged
> into `main` by the merge gate when **every** check passes and ChatGPT's review verdict is
> APPROVE. This replaces the earlier "never merge automatically" rule. Releases are still
> never published. **To turn auto-merge off**, set the repository variable
> `AI_AUTO_MERGE` to `false` (or delete it) under Settings → Secrets and variables →
> Actions → *Variables*. AI PRs then wait for you again; nothing else changes. To stop a
> single PR, add the label `do-not-merge` (or `ai-revise`).
>
> An `ai-revise` run gives the developer the latest ChatGPT review on the PR and your own
> comments on it (`automation/aidev/feedback.py`). Comments from other accounts are ignored.

## What runs

| Workflow | When | What it does | Needs keys? |
|---|---|---|---|
| `.github/workflows/ai-daily-dev.yml` | 02:00 AWST daily (+04:00 backup), or by hand | Checks issues and PRs, picks **one** approved task, runs Grok or Claude, applies guardrails, commits to `ai/<role>/issue-N-…`, opens/updates a PR, runs validation + Android build, gets a ChatGPT review, publishes the daily report | Yes, for the AI steps |
| `.github/workflows/ai-pr-gate.yml` | Called by the daily run for the PR it opened or updated; a sweep at 05:30 AWST for older AI PRs; or by hand | Brings the AI branch up to date with `main`, runs code validation and the Android build on it, gets the ChatGPT review, then the **merge gate** decides: squash-merge into `main` only if every gate below passes and `AI_AUTO_MERGE` is `true`. Posts commit statuses *AI gate / checks* and *AI gate / merge* on the PR | `OPENAI_API_KEY` for the review |
| `.github/workflows/pr-checks.yml` | Every PR into `main` (and called by the daily run and the gate) | Unit tests, protected-area guardrails, JS syntax check, actionlint, Gradle wrapper validation | No |
| `.github/workflows/android-build.yml` | Every PR, every push to `main` (and called by the daily run and the gate) | Copies `www/` into the APK assets, builds a debug **test** APK, checks it contains all game files, uploads it as an artifact | No |

Nothing publishes releases. The only code that can merge is the single merge step in
`ai-pr-gate.yml`; a unit test (`automation/tests/test_workflows.py`) fails if a merge call
appears anywhere else, if that step stops being pinned to the tested head SHA or squash, or
if a release or force-push command shows up anywhere.

## Auto-merge gate (owner-enabled 2026-11-10)

`automation/aidev/mergegate.py` decides; `automation/tests/test_mergegate.py` covers each
rule with passing and failing cases. A PR is merged only when **all** of these hold, checked
against the PR's state on GitHub right before merging:

| Gate | Rule |
|---|---|
| Switch | Repository variable `AI_AUTO_MERGE` is exactly `true`. Dry runs never merge. |
| Made by the automation | Opened by `github-actions[bot]`; label `ai-generated` and the role label; branch `ai/<role>/issue-<N>-…` in this repository (no forks); the `<!-- aidev-pr issue=N role=R -->` marker matches the branch; role is `grok` or `claude`; every commit is by `project-aussie-ai-<role>` with the Actions bot e-mail (plus "Update branch" merge commits by the bot that only bring in `main`); at most 20 commits. PRs from people are never merged by the gate. |
| Not stopped | Open, not a draft, base `main`, none of `ai-revise`, `ai-blocked`, `do-not-merge`, `wontfix`. |
| Checks | Code validation (unit tests, protected areas, JS syntax, actionlint, Gradle wrapper), the Android build with APK verification (`apk-verify.json` ok, package `com.barrarun.game.ci`) and a guardrail re-run in the gate job all concluded `success`. They run on the PR head, which must contain the current `main`: live gate runs first press GitHub's "Update branch" on the AI PR (a merge commit by the workflow bot; the gate accepts merge commits only when their extra parents are already in `main`). |
| Protected areas | The guardrails run in strict AI mode. Audio is unlocked only if the **owner** put `audio-approved` on the linked issue **and** the role is Claude (labels on the PR itself don't count). Models, assets, package id, signing, save keys and the Falcon split can never be changed by an AI PR. |
| Review | A real ChatGPT review: status `reviewed` (or a reused earlier review of the same commit posted by the workflow bot), endpoint `api.openai.com`, an OpenAI response id, a `gpt`/`o` model reported by the API, for exactly the tested head SHA, and a verdict that parses as **APPROVE**. The reviewer is told to write one line under `### Verdict` starting with `APPROVE` or `CHANGES RECOMMENDED`. `CHANGES RECOMMENDED`, "approve with/if/after …", a missing or duplicated Verdict heading, or anything else unparseable means **no merge**. A failed, skipped (no key, no budget) or dry-run review means no merge. |
| Fresh and clean | GitHub reports the PR mergeable (no conflicts); the PR head and `main` are still the commits that were tested. Otherwise the next run re-checks. |

The merge is `PUT /repos/…/pulls/N/merge` with `merge_method=squash` and `sha=<tested head>`,
using the workflow's own `GITHUB_TOKEN` (`contents: write`, `pull-requests: write`). It is
recorded in the daily report (section *Auto-merge*), in a PR comment and as the *AI gate /
merge* status. A merge-call failure fails the run.

**Re-reviews and cost.** Each review comment carries an `aidev-review` marker with the head
SHA and verdict. The gate reuses an earlier review of the same commit instead of paying for
a new one, and the 05:30 sweep skips PRs whose current commit was already reviewed with a
non-APPROVE verdict, until new commits are pushed. To force a fresh review, run the gate by
hand with *force_review*. Gate runs add a `kind=gate` report comment so their cost counts
toward the daily budget (they don't count as the day's development run).

**Checks without manual approval.** PRs opened with `GITHUB_TOKEN` get `pull_request` runs
that GitHub holds as "approval required". The gate doesn't depend on them: it runs the same
checks itself through `workflow_call`, which never waits for approval, and posts the
results as commit statuses on the PR head. It also tries to approve those held runs (best
effort; a warning if GitHub refuses).

## The AI team

| Role | Provider / API | Secret | Model variable (default) | Works on |
|---|---|---|---|---|
| **Grok** — gameplay developer | xAI Responses API `https://api.x.ai/v1/responses` | `XAI_API_KEY` | `AI_GROK_MODEL` (`grok-4.7`) | New features, burnout, drag and roll racing, free roam |
| **Claude** — technical developer | Anthropic Messages API `https://api.anthropic.com/v1/messages` | `ANTHROPIC_API_KEY` | `AI_CLAUDE_MODEL` (`claude-sonnet-5-5`) | Driving physics, memory, graphics optimisation, Android performance, **sound/audio (only on issues you label `audio-approved`)** |
| **ChatGPT** — code reviewer | OpenAI Chat Completions `https://api.openai.com/v1/chat/completions` | `OPENAI_API_KEY` | `AI_CHATGPT_MODEL` (`gpt-6.1-sol`) | Reviews the AI PR: integration problems, Android compatibility, protected areas, recommended fixes |

- There is **no fallback between providers**. If a key is missing or a call fails, that role
  is reported as *skipped* or *failed*. Another model never stands in for it.
- The report records who actually answered: the endpoint host that was called, the model
  name **the API returned**, the response id and the token usage. If an API reports a
  model from the wrong family (for example a non-`claude` model from the Anthropic
  endpoint), the answer is rejected and not credited to that role.
- The default model names were checked against each provider's public docs on 2026-11-09.
  Check them again before you turn this on. You can change them with repository variables
  and no code change.
- Each run does one development task, so on a given day either Grok or Claude develops,
  never both. ChatGPT reviews whatever PR that run produced.

## Approval rules (how a task gets picked)

See [AI_TASK_RULES.md](AI_TASK_RULES.md). In short, the AI only touches an issue that
**you** labelled `ai-approved`, plus exactly one of `ai:grok` / `ai:claude`. Sound work also
needs `audio-approved` and goes to Claude only.

## Protected areas (enforced in code)

`automation/aidev/guardrails.py` checks the diff of every AI patch before it is committed,
and checks every PR again in `pr-checks.yml`. An AI patch that breaks a rule is thrown away
and the run fails with a report.

| Area | Rule |
|---|---|
| Audio system | Frozen. This covers the whole `/* ===== audio ===== */` section of `www/index.html`, `getPack`, `setEngineSound`, `setEngineSound0`, `sirenOn`, `thud`, `loadSoundData`, `ensurePack`, `startAudio`, `updateAudio`, any line with AudioContext / `AC` / `master` / volume / sfx / `.wav`, every `.wav` file, the `*_voice.json` files and the engine sound packs. **Only Claude, only on an `audio-approved` issue** can change audio code. Grok audio patches are always rejected, even with the label. No AI may add or replace `.wav` files. On human PRs, the owner's `audio-approved` label on the PR allows it. |
| Vehicle models and graphics | `www/assets/**` (models, parts, rims, textures, traffic) and `www/vendor/**` are off-limits to AI. Human PRs need `protected-change-approved`. |
| BF Falcon XR6 Turbo vs AU Falcons | `VEHICLES.falcon` must keep `assets/falcon.model.json` / `assets/swap.json` / `assets/parts/`. `VEHICLES.au` and `VEHICLES.auute` must keep their own `assets/au/...` model, swap and parts files, and the three must stay distinct. |
| Save keys | No existing `barra.*` localStorage key may disappear or be renamed: `barra.best`, `bestSect`, `buildIdx`, `career`, `dragBest`, `dragGhost`, `garage`, `ghost`, `hesiBest`, `judged`, `mbest.*`, `mdrift.*`, `meetBest`, `mybuild`, `mybuilds`, `names`, `rollBest`, `series`, `settings`, `sprintBest`, `touch`. |
| Android package and signing | `applicationId "com.barrarun.game"`, `namespace`, the signing config lines, the manifest `package` and Java `package` lines. Keystores (`*.keystore`, `*.jks`, `*.p12`, `keystore.properties`) can never be committed. |
| Automation itself | AI patches can't touch `.github/**`, `automation/**`, Gradle files or the wrapper. Grok may edit only `www/index.html` and `docs/**`. Claude may also edit `MainActivity.java`, `AndroidManifest.xml` and `res/values/**`. |
| Size | At most `AI_MAX_CHANGED_LINES` (default 400) changed lines per AI patch. |

Every AI patch that changes `www/index.html` must also pass `node --check` on the inline scripts.

## Safety and cost controls

- **Secrets.** Keys live only in GitHub Actions secrets. Each key is passed only into the
  one step that needs it: `XAI_API_KEY` to the Grok step, `ANTHROPIC_API_KEY` to the Claude
  step, `OPENAI_API_KEY` to the review step. The code masks keys with `::add-mask::` and
  scrubs them from error messages. Keys never go into files, commits or the report.
- **Budget.** `AI_DAILY_BUDGET_USD` (default `2.00`) is checked before every call against a
  worst-case estimate: prompt size plus `AI_MAX_OUTPUT_TOKENS` (plus, for Grok,
  `AI_XAI_REASONING_ALLOWANCE_TOKENS`, default `40000`, because xAI's `max_output_tokens`
  caps only the visible answer and Grok's reasoning tokens are billed on top; Grok's
  reasoning is limited with `AI_XAI_REASONING_EFFORT`, default `medium`). After each call, the real
  usage numbers from the API are priced and added to the day's total, and the total goes
  into the report marker. When the budget is used up, later calls that day are skipped.
  Prices are in `automation/ai-config.json` (`pricing_usd_per_mtok`). You can override them
  with `AI_PRICING_JSON`. Unknown models use a deliberately high fallback price. These are
  **estimates**; your provider bill is the real number.
- **Call limits.** `AI_MAX_CALLS_PER_RUN` (default 2: normally one developer call and one review
  call). The only retry is the **patch repair** below, and it uses the same call limit and budget.
- **Applying the developer's edits.** Each `search` must match the current file exactly once.
  If the exact text is not found, the orchestrator also tries the same text with CRLF and copied
  line-number prefixes removed, then a whitespace-normalised match (indentation and runs of
  spaces/newlines ignored; every other character must match). A fallback is only used when it
  finds exactly one place; ambiguous matches are always rejected. Guardrails (protected files,
  audio freeze, save keys, vehicle models, changed-lines limit, JS syntax) run on the result as before.
- **Patch repair (one retry).** If an edit still does not match, the developer model is asked
  ONCE more, by the same provider, with the error and the real file lines around the closest
  match (`automation/aidev/patching.py`). This second call counts toward `AI_MAX_CALLS_PER_RUN`
  and the daily budget; if either would be exceeded there is no retry. When the repair used the
  run's second call, the ChatGPT review in that run is skipped by the call limit and the 05:30
  AWST merge-gate sweep reviews the PR instead, so the PR is not auto-merged before it is reviewed.
- **Context for the developer.** Besides functions and line numbers named in the issue, every
  line that mentions an element id or name from the issue (for example `#freehud`) is shown with
  a few lines either side, so the model can copy the real markup.
- **No overlap.** `concurrency: ai-daily-development` with `cancel-in-progress: false` means
  only one daily run at a time. A second trigger waits, then sees today's report and does
  nothing.
- **Auto-merge switch.** `AI_AUTO_MERGE` (`true` = on). See the gate rules above.
- **Failures stop the run.** A rejected or failed developer step marks the run failed, skips
  the build and review for that patch, and the report says why.
- **Honest results.** The report only shows results taken from that run's job conclusions,
  the APK check output and the API responses. A dry run or a skipped role is never shown
  as success.

## Schedule and GitHub delays

GitHub cron runs in UTC. Perth is UTC+8 all year with no daylight saving.

- `0 18 * * *` → **02:00 AWST** (primary).
- `0 20 * * *` → **04:00 AWST** (backup). GitHub can start scheduled runs late, sometimes by
  an hour or more, or drop them when it is busy. Any scheduled run first reads today's
  report markers (by Perth date) on the reports issue. If a live run already reported, it
  does nothing, so you get at most one live run per Perth day.
- Scheduled workflows only run from the default branch, so **nothing is scheduled until
  this PR is merged into `main`**. GitHub also turns off schedules after 60 days with no
  repository activity.

## Android build, signing and your installed app

- `android/gradlew` (Gradle 8.7, distribution SHA-256 pinned) makes the build reproducible.
  `android/app/build.gradle` is **unchanged**.
- CI runs `automation/android/ci_build.sh`, which:
  1. checks the required game files (the same list as PR #2), then copies the complete
     `www/` into `android/app/src/main/assets/`, leaving out `index.*.bak.html` and OS junk;
  2. makes a **throwaway debug keystore** inside the job, which is never stored or committed;
  3. runs `./gradlew -I automation/android/ci-init.gradle assembleDebug`. The init script
     points debug signing at the throwaway key and adds `applicationIdSuffix ".ci"` /
     `versionNameSuffix "-ci"`;
  4. runs `verify_apk.py`, which checks `assets/index.html` is there, every `www/` file is in
     the APK with an identical CRC-32, there are no extra files, and `aapt2` reports the
     package as `com.barrarun.game.ci`.
- The CI test APK is **`com.barrarun.game.ci`**, labelled Project Aussie, version `1.0.8-ci`.
  It installs **next to** your real app (`com.barrarun.game`) and cannot overwrite or update
  it. Its saves are separate. Your real app's saves are untouched.
- Download it from the run page → *Artifacts* → `project-aussie-ci-apk` (kept 14 days).
- This works on `main` today. After PR #2 is merged, its Gradle `syncGameAssets` /
  `verify*ApkGameAssets` tasks run as well. That was tested locally with PR #2 merged into
  this branch, and the result was identical.
- **Portable release signing (proposed, not done):** issue #1 P1 suggests moving the keystore
  path and passwords out of `build.gradle` into environment variables or secrets
  (`ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`,
  `ANDROID_KEY_PASSWORD`). That edits the signing config, which is a protected area, so it
  needs its own PR with your approval. Use your existing key so phone updates keep working.

## Manual setup (owner)

1. **Done:** PR #2 (P0 packaging fix) and PR #3 (this automation) are merged.
2. **Done (2026-11-10):** auto-merge enabled at the owner's request; repository variable
   `AI_AUTO_MERGE=true`. Set it to `false` to turn it off.
3. **Let the workflow open PRs.** Do one of these:
   - Settings → Actions → General → Workflow permissions → tick **"Allow GitHub Actions to
     create and approve pull requests"**. It is currently off. Our workflows never approve
     anything. Or:
   - add a fine-grained token as secret `AI_DEV_PR_TOKEN` (this repository only; Contents:
     read and write, Pull requests: read and write). PRs opened with it also trigger
     `pr-checks.yml` and `android-build.yml` on the PR itself, which `GITHUB_TOKEN`-opened
     PRs don't. Not needed any more: the merge gate runs those checks itself. Note that
     PRs opened with a personal token are authored by that person, so the gate's author
     rule (`auto_merge.allowed_authors` in `automation/ai-config.json`) would refuse them
     until you add that login there.
4. **API keys (done by you on 2026-11-09).** The secrets `XAI_API_KEY` (console.x.ai),
   `ANTHROPIC_API_KEY` (console.anthropic.com) and `OPENAI_API_KEY` (platform.openai.com)
   exist under Settings → Secrets and variables → Actions → *Secrets*. Whether they are
   valid is only known after the first live run calls each API. Also set a spending limit
   at each provider.
5. **Set variables** (same page → *Variables*), all optional except the first:
   - `AI_DEV_ENABLED` = `true` turns on live scheduled runs. Leave it unset to keep dry runs.
   - `AI_AUTO_MERGE` = `true` lets the merge gate merge AI PRs (set 2026-11-10 at the owner's
     request). `false` or unset turns auto-merge off.
   - `AI_DAILY_BUDGET_USD` (default `2.00`), `AI_MAX_CALLS_PER_RUN` (default `2`),
     `AI_MAX_OUTPUT_TOKENS` (default `16000`), `AI_MAX_INPUT_CHARS` (default `160000`),
     `AI_MAX_CHANGED_LINES` (default `400`).
   - `AI_XAI_REASONING_EFFORT` (`low`/`medium`/`high`/`xhigh`, or `default` to let xAI use
     its own default `high`; config default `medium`) and `AI_XAI_REASONING_ALLOWANCE_TOKENS`
     (default `40000`, added to Grok's worst-case cost estimate).
   - `AI_GROK_MODEL`, `AI_CLAUDE_MODEL`, `AI_CHATGPT_MODEL` override the default model names.
   - `AI_PRICING_JSON`, for example `{"grok-4.7":{"in":2,"out":6}}`, updates the price table.
6. **Protect `main`** (optional): `main` has no branch protection, which is what lets the
   workflow token merge. If you add a rule later, require the *AI gate / checks* status
   (the `pull_request` check runs on bot PRs can stay "approval required") and allow
   GitHub Actions to merge, or the gate's merge call will be refused (the run then fails and
   says so).
7. **Approve work.** Create or choose issues and add `ai-approved`, one of `ai:grok` /
   `ai:claude`, and optionally `priority:P0`–`P3`. For sound work, use `ai:claude` +
   `audio` + `audio-approved`.
8. **First real test.** Actions → *AI daily development* → *Run workflow*, with dry run
   **unticked** and the issue number. Only after that run has called the APIs, opened the
   PR and passed the checks can daily AI development be called active.
   To re-run only the checks, review and merge gate for an existing AI PR: Actions → *AI PR
   merge gate* → *Run workflow* with the PR number and dry run unticked.
9. Optionally pin the *Daily AI development reports* issue. It is created on the first live
   run.

## Running the tests locally

```bash
python3 -m unittest discover -s automation/tests -t automation/tests -v   # needs node for the JS check
PYTHONPATH=automation python3 -m aidev guard --base origin/main --head HEAD --branch "$(git branch --show-current)"
PYTHONPATH=automation python3 -m aidev jscheck
ANDROID_HOME=... JAVA_HOME=... automation/android/ci_build.sh /tmp/apk-out
```
