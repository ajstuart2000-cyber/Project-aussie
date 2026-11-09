"""ChatGPT (OpenAI API) code review of the AI pull request.

The review is posted as a PR comment. Its verdict line is parsed by
mergegate.parse_verdict; only an APPROVE verdict from a real OpenAI response for the
tested head SHA can let the auto-merge gate (owner-enabled 2026-11-10) merge the PR.
This module itself never approves or merges anything."""
import os

from . import budget as B, mergegate as MG, providers as P

SYSTEM = """You are the code reviewer for "Project Aussie" (Three.js 0.170 game in one www/index.html,
Android WebView wrapper, package com.barrarun.game, minSdk 24 / targetSdk 34).
Review the pull request diff below. Be concrete and brief. Use exactly these Markdown sections:
### Summary
### Integration problems
### Android compatibility
### Protected areas (audio frozen unless the issue is audio-approved and the author is Claude; vehicle models; BF Falcon XR6 Turbo vs AU Falcons separate; barra.* save keys; package id; signing)
### Recommended fixes
### Verdict
Under ### Verdict write exactly ONE line that starts with either
APPROVE (safe to merge into main as it is) or CHANGES RECOMMENDED (anything that should be fixed first),
followed by a short reason. Approving lets the automation merge the PR into main without a human reading it,
so choose CHANGES RECOMMENDED for any real integration, Android-compatibility or protected-area problem.
Do not claim you ran, built or tested anything. You only read the diff and the CI results given to you."""


def run(cfg, diff_text, context_md, spent_today=0.0, calls_used=0, dry_run=False, transport=None, env=None, head_sha=''):
    env = env if env is not None else os.environ
    role = cfg['roles']['chatgpt']
    provider = role['provider']
    pname = cfg['providers'][provider]['name']
    res = {'status': None, 'role': 'chatgpt', 'role_title': role['title'], 'provider_name': pname,
           'model_configured': role['model'], 'provider': None, 'cost_usd': 0.0, 'review_md': '', 'error': '',
           'head_sha': head_sha, 'verdict': None, 'verdict_line': ''}
    key = env.get(role['secret'], '')
    P.register_secret(key)
    limit = cfg['limits']['max_review_diff_chars']
    truncated = len(diff_text) > limit
    user = context_md + '\n\n# Diff' + (' (TRUNCATED to the first %d chars)' % limit if truncated else '') + \
        '\n```diff\n' + diff_text[:limit] + '\n```'
    bud = B.Budget(cfg, spent_today, calls_used)
    max_out = min(cfg['limits']['max_output_tokens'], 8000)
    res['worst_case_usd'] = bud.worst_case(provider, role['model'], len(SYSTEM) + len(user), max_out)
    if dry_run:
        res.update(status='dry-run', key_configured=bool(key))
        return res
    if not key:
        res.update(status='skipped', error=f'{role["secret"]} is not set; the ChatGPT review was not run. No other provider reviewed instead.')
        return res
    if not diff_text.strip():
        res.update(status='skipped', error='no diff to review')
        return res
    try:
        bud.authorize(provider, role['model'], len(SYSTEM) + len(user), max_out)
    except B.BudgetExceeded as e:
        res.update(status='skipped', error=f'budget: {e}')
        return res
    try:
        r = P.call(cfg, provider, key, role['model'], SYSTEM, user, max_out, transport=transport)
    except P.ProviderError as e:
        if e.result:
            res['provider'] = e.result.public()
            res['cost_usd'] = bud.record(provider, e.result.model_reported or role['model'], e.result.input_tokens, e.result.output_tokens)
        res.update(status='failed', error=P.scrub(e))
        return res
    res['provider'] = r.public()
    res['cost_usd'] = bud.record(provider, r.model_reported, r.input_tokens, r.output_tokens)
    res['review_md'] = r.text[:30000]
    res['verdict'], res['verdict_line'] = MG.parse_verdict(r.text)
    res['status'] = 'reviewed'
    return res
