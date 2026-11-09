# Task selection and approval rules

The daily run picks **at most one** issue. An issue is eligible only if **all** of these are true:

1. It is an open issue, not a pull request, and not the reports issue (`ai-report`).
2. It has **`ai-approved`**, and the last time that label was added, it was added by the
   repository owner (`ajstuart2000-cyber`). This is checked against the issue's label event
   history, so a label added by anyone else does not count.
3. It has **exactly one** role label: `ai:grok` (gameplay) or `ai:claude` (technical, and
   sound).
4. It has none of: `ai-blocked`, `ai-done`, `wontfix`, `duplicate`, `invalid`.
5. **Sound/audio**: an issue counts as audio work if it has the `audio` or `sound` label, or
   its title or body mentions audio, sound, siren, wav, sfx, volume, an engine or exhaust
   note, and so on.
   - Audio work is **Claude-only**. An audio issue labelled `ai:grok` is skipped, with a note
     telling you to relabel it.
   - It also needs **`audio-approved`**, added by the owner. Without it, audio stays frozen
     and the issue is skipped.
6. There's no open AI PR for it (`ai/<role>/issue-<N>-…`) still open. If you want
   changes, add **`ai-revise`** to that PR and leave comments. The next run reads your
   comments and pushes a follow-up commit to the same PR.

The order is the `priority:P0` … `priority:P3` label (no label sorts last), then the oldest
issue first. Every issue that was looked at shows up in the daily report with the reason it
was or wasn't picked.

## Merging AI pull requests (auto-merge, owner decision 2026-11-10)

On 2026-11-10 the owner asked for all updates to be approved automatically, so the earlier
rule that automation never merges into `main` no longer applies. An AI PR is squash-merged
by the merge gate (`.github/workflows/ai-pr-gate.yml`, rules in
`automation/aidev/mergegate.py`) only when:

- repository variable **`AI_AUTO_MERGE` is `true`**;
- the automation opened it (`github-actions[bot]`, `ai-generated`, `ai/<role>/issue-N-…`,
  matching marker, every commit by `project-aussie-ai-<role>`);
- code validation, the Android build + APK check and the guardrail re-run all passed;
- ChatGPT's review (real OpenAI API response for that exact commit) says **APPROVE**;
- there are no conflicts and nothing moved since the checks;
- it has none of `ai-revise`, `ai-blocked`, `do-not-merge`, `wontfix`.

Audio still needs the owner's `audio-approved` on the **issue** and Claude as the author. PRs
that people open are never merged by the gate. Releases are never published.

**Turning it off:** set `AI_AUTO_MERGE` to `false` (Settings → Secrets and variables →
Actions → Variables) or delete it. To hold one PR, add `do-not-merge`.

## Labels

| Label | Who applies it | Meaning |
|---|---|---|
| `ai-approved` | Owner | The AI may work on this issue |
| `ai:grok` / `ai:claude` | Owner | Which developer gets it |
| `audio` / `sound` | Anyone | The issue is about sound (Claude-only, frozen without approval) |
| `audio-approved` | Owner | Claude may change the audio system for this issue (or, on a human PR, the audio check is waived) |
| `protected-change-approved` | Owner | On a **human** PR, waives the model, package, signing, save-key and Falcon checks (never for AI patches, never for committing keystores) |
| `priority:P0` … `priority:P3` | Owner | Order |
| `ai-revise` | Owner | The next run should update this AI PR using your comments (also blocks auto-merge) |
| `do-not-merge` | Owner | Never auto-merge this PR |
| `ai-blocked` / `ai-done` | Owner | Skip this issue |
| `ai-generated` | Workflow | Set on PRs the workflow opens |
| `ai-report` | Workflow | The reports issue |

## Suggested first tasks (from the baseline audit, #1)

Pick and label them yourself. Nothing is pre-approved.

- `ai:claude` · `priority:P1`: Map memory pass (dispose or LRU-evict unused maps).
- `ai:claude` · `priority:P2`: Android Back button into the pause menu; `pauseTimers()`/`resumeTimers()`.
- `ai:claude` · `priority:P2`: Spatial grid for `mapCollide` with identical results.
- `ai:grok` · `priority:P2`: Burnout or drag/roll racing improvements (write the exact feature in the issue).
- `ai:claude` + `audio` + `audio-approved`: Fix the three asset 404s (`barra.wav`, `synthT.*`), only if you want sound touched.
