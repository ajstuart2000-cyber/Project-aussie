"""Merge-gate logic (auto-merge enabled by the owner on 2026-11-10). Positive and negative cases."""
import copy, unittest

from helpers import CFG
from aidev import budget as B, mergegate as MG, report

HEAD, BASE = 'a' * 40, 'b' * 40
BOT = {'login': 'github-actions[bot]', 'type': 'Bot'}
REVIEW_OK_MD = '### Summary\nFine.\n### Integration problems\nNone.\n### Verdict\nAPPROVE - small, contained change.\n'


def pr(**kw):
    p = {'number': 5, 'state': 'open', 'draft': False, 'title': '[AI · Claude] Back button pauses (#4)',
         'user': {'login': 'github-actions[bot]', 'type': 'Bot'},
         'labels': [{'name': 'ai-generated'}, {'name': 'ai:claude'}],
         'head': {'ref': 'ai/claude/issue-4-android-back-button', 'sha': HEAD, 'repo': {'full_name': 'o/r'}},
         'base': {'ref': 'main', 'sha': BASE, 'repo': {'full_name': 'o/r'}},
         'body': 'text\n<!-- aidev-pr issue=4 role=claude -->\n', 'mergeable': True, 'mergeable_state': 'clean'}
    p.update(kw)
    return p


def commits(n=1, name='project-aussie-ai-claude', email='41898282+github-actions[bot]@users.noreply.github.com', parents=1):
    return [{'sha': f'{i:040d}', 'parents': [{}] * parents, 'commit': {'author': {'name': name, 'email': email}}} for i in range(n)]


def review(**kw):
    v, line = MG.parse_verdict(REVIEW_OK_MD)
    r = {'status': 'reviewed', 'head_sha': HEAD, 'verdict': v, 'verdict_line': line, 'cost_usd': 0.01,
         'provider': {'endpoint_host': 'api.openai.com', 'response_id': 'chatcmpl-123', 'model_reported': 'gpt-6.1-sol'}}
    r.update(kw)
    return r


CHECKS = {'validation': 'success', 'android': 'success', 'guardrails': 'success'}
APK = {'ok': True, 'package': 'com.barrarun.game.ci'}


def decide(p=None, c=None, checks=None, apk=APK, rev=None, enabled=True, dry_run=False, tested_head=HEAD,
           tested_base=BASE, current_base=BASE, main_ancestors=frozenset()):
    return MG.decide(p or pr(), commits() if c is None else c, CHECKS if checks is None else checks, apk,
                     review() if rev is None else rev, CFG, enabled=enabled, dry_run=dry_run,
                     tested_head=tested_head, tested_base=tested_base, current_base=current_base,
                     main_ancestors=main_ancestors)


class VerdictTests(unittest.TestCase):
    def test_approve(self):
        self.assertEqual(MG.parse_verdict(REVIEW_OK_MD)[0], MG.APPROVE)
        self.assertEqual(MG.parse_verdict('## Verdict\n**APPROVE** — looks good')[0], MG.APPROVE)
        self.assertEqual(MG.parse_verdict('### Verdict\n- Approved: no issues')[0], MG.APPROVE)
        self.assertEqual(MG.parse_verdict('### Verdict\nOK for owner review')[0], MG.APPROVE)

    def test_changes(self):
        for line in ('CHANGES RECOMMENDED: missing null check', '**Changes recommended** because x', 'Request changes',
                     'Reject - breaks saves', 'Do not merge'):
            self.assertEqual(MG.parse_verdict(f'### Verdict\n{line}\n')[0], MG.CHANGES, line)

    def test_unparseable_is_unknown(self):
        for md in ('', 'no verdict heading at all\nAPPROVE', '### Verdict\n\n', '### Verdict\nLooks mostly fine',
                   '### Verdict\nApprove with changes to the pause menu', '### Verdict\nApprove if the owner tests it',
                   '### Verdict\nAPPROVE\n### Verdict\nCHANGES RECOMMENDED'):
            self.assertEqual(MG.parse_verdict(md)[0], MG.UNKNOWN, md)


class DecideTests(unittest.TestCase):
    def assertBlocked(self, d, fragment):
        self.assertFalse(d['merge'], d['reasons'])
        self.assertTrue(any(fragment in r for r in d['reasons']), (fragment, d['reasons']))

    def test_all_gates_pass_merges(self):
        d = decide()
        self.assertTrue(d['merge'], d['reasons'])
        self.assertEqual(d['reasons'], [])
        self.assertEqual(d['merge_method'], 'squash')
        self.assertEqual((d['role'], d['issue']), ('claude', 4))

    def test_reused_review_of_same_head_is_accepted(self):
        self.assertTrue(decide(rev=review(status='reused'))['merge'])

    def test_switch_off_and_dry_run(self):
        self.assertBlocked(decide(enabled=False), 'AI_AUTO_MERGE')
        self.assertBlocked(decide(dry_run=True), 'dry run')

    def test_not_created_by_automation(self):
        self.assertBlocked(decide(pr(user={'login': 'someone', 'type': 'User'})), 'not by the automation')
        self.assertBlocked(decide(pr(labels=[{'name': 'ai:claude'}])), 'ai-generated')
        self.assertBlocked(decide(pr(head={'ref': 'feature/x', 'sha': HEAD, 'repo': {'full_name': 'o/r'}})), 'not an ai/')
        self.assertBlocked(decide(pr(body='no marker')), 'marker')
        self.assertBlocked(decide(pr(head={'ref': 'ai/claude/issue-4-x', 'sha': HEAD, 'repo': {'full_name': 'fork/r'}})), 'fork')
        self.assertBlocked(decide(c=commits(name='ajstuart2000-cyber')), 'not made by the automation')
        self.assertBlocked(decide(c=commits(email='x@example.com')), 'not made by the automation')
        self.assertBlocked(decide(c=commits(parents=2)), 'merge commit')
        self.assertBlocked(decide(c=commits(name='github-actions[bot]', parents=2)), 'merge commit')
        self.assertBlocked(decide(c=[]), 'no commits')

    def test_update_branch_merge_commit_allowed_only_if_it_just_brings_in_main(self):
        own = commits()[0]
        upd = {'sha': 'u' * 40, 'parents': [{'sha': own['sha']}, {'sha': BASE}],
               'commit': {'author': {'name': 'github-actions[bot]', 'email': '41898282+github-actions[bot]@users.noreply.github.com'}}}
        self.assertTrue(decide(c=[own, upd], main_ancestors=frozenset({BASE}))['merge'])
        self.assertFalse(decide(c=[own, upd], main_ancestors=frozenset())['merge'])
        bad = copy.deepcopy(upd)
        bad['commit']['author']['email'] = 'someone@example.com'
        self.assertFalse(decide(c=[own, bad], main_ancestors=frozenset({BASE}))['merge'])

    def test_marker_must_match_branch_and_role(self):
        self.assertBlocked(decide(pr(body='<!-- aidev-pr issue=9 role=claude -->')), 'does not match')
        self.assertBlocked(decide(pr(body='<!-- aidev-pr issue=4 role=grok -->')), 'does not match')
        self.assertBlocked(decide(pr(body='<!-- aidev-pr issue=4 role=chatgpt -->')), 'not a developer role')

    def test_pr_state(self):
        self.assertBlocked(decide(pr(state='closed')), 'not open')
        self.assertBlocked(decide(pr(draft=True)), 'draft')
        self.assertBlocked(decide(pr(base={'ref': 'dev', 'repo': {'full_name': 'o/r'}})), 'base')
        for lab in ('ai-revise', 'do-not-merge', 'ai-blocked'):
            self.assertBlocked(decide(pr(labels=[{'name': 'ai-generated'}, {'name': 'ai:claude'}, {'name': lab}])), 'blocking label')

    def test_conflicts_and_freshness(self):
        self.assertBlocked(decide(pr(mergeable=False, mergeable_state='dirty')), 'mergeable')
        self.assertBlocked(decide(pr(mergeable=None)), 'mergeable')
        self.assertBlocked(decide(tested_head='c' * 40), 'head changed')
        self.assertBlocked(decide(current_base='d' * 40), 'current main')
        self.assertBlocked(decide(tested_base=''), 'current main')

    def test_every_required_check(self):
        for name in ('validation', 'android', 'guardrails'):
            for bad in ('failure', 'skipped', 'cancelled', None):
                ch = dict(CHECKS)
                if bad is None:
                    ch.pop(name)
                else:
                    ch[name] = bad
                self.assertBlocked(decide(checks=ch), name)

    def test_apk(self):
        self.assertBlocked(decide(apk=None), 'APK verification')
        self.assertBlocked(decide(apk={'ok': False, 'package': 'com.barrarun.game.ci'}), 'APK verification')
        self.assertBlocked(decide(apk={'ok': True, 'package': 'com.barrarun.game'}), 'CI package')

    def test_review_must_be_real_openai_approve_of_this_head(self):
        self.assertBlocked(decide(rev={}), 'no ChatGPT review')
        self.assertBlocked(decide(rev=review(status='failed', error='HTTP 429: You have no credits remaining')), 'status is')
        self.assertBlocked(decide(rev=review(status='skipped')), 'status is')
        self.assertBlocked(decide(rev=review(status='dry-run')), 'status is')
        self.assertBlocked(decide(rev=review(verdict=MG.CHANGES)), 'verdict')
        self.assertBlocked(decide(rev=review(verdict=MG.UNKNOWN)), 'verdict')
        self.assertBlocked(decide(rev=review(verdict=None)), 'verdict')
        self.assertBlocked(decide(rev=review(head_sha='e' * 40)), 'different commit')
        self.assertBlocked(decide(rev=review(provider={'endpoint_host': 'api.x.ai', 'response_id': 'r', 'model_reported': 'grok-4.7'})), 'api.openai.com')
        self.assertBlocked(decide(rev=review(provider={'endpoint_host': 'api.openai.com', 'response_id': '', 'model_reported': 'gpt-6.1-sol'})), 'response id')
        self.assertBlocked(decide(rev=review(provider={'endpoint_host': 'api.openai.com', 'response_id': 'r', 'model_reported': 'claude-sonnet-5-5'})), 'not an OpenAI model')


class AudioAndReviewMarkerTests(unittest.TestCase):
    OWNER_EVT = [{'event': 'labeled', 'label': {'name': 'audio-approved'}, 'actor': {'login': 'ajstuart2000-cyber'}}]

    def issue(self, *labels):
        return {'number': 4, 'labels': [{'name': l} for l in labels]}

    def test_audio_only_for_claude_with_owner_label_on_the_issue(self):
        self.assertEqual(MG.guard_labels('claude', self.issue('audio-approved'), self.OWNER_EVT, CFG), ['audio-approved'])
        self.assertEqual(MG.guard_labels('grok', self.issue('audio-approved'), self.OWNER_EVT, CFG), [])
        self.assertEqual(MG.guard_labels('claude', self.issue(), self.OWNER_EVT, CFG), [])
        other = [{'event': 'labeled', 'label': {'name': 'audio-approved'}, 'actor': {'login': 'someone'}}]
        self.assertEqual(MG.guard_labels('claude', self.issue('audio-approved'), other, CFG), [])
        self.assertEqual(MG.guard_labels('claude', None, [], CFG), [])

    def test_prior_review_only_from_the_bot_for_the_same_head(self):
        mk = MG.review_marker(HEAD, 'approve', 'reviewed', 'chatcmpl-1', 'gpt-6.1-sol', 'api.openai.com')
        bot = {'user': BOT, 'body': 'x\n' + mk}
        human = {'user': {'login': 'ajstuart2000-cyber', 'type': 'User'}, 'body': mk}
        fake_bot_name = {'user': {'login': 'github-actions[bot]', 'type': 'User'}, 'body': mk}
        self.assertEqual(MG.find_prior_review([bot], HEAD, CFG)['verdict'], 'approve')
        self.assertEqual(MG.find_prior_review([bot], HEAD, CFG)['host'], 'api.openai.com')
        self.assertIsNone(MG.find_prior_review([human, fake_bot_name], HEAD, CFG))
        self.assertIsNone(MG.find_prior_review([bot], 'f' * 40, CFG))

    def test_sweep_skips_heads_already_rejected(self):
        good, other = pr(), pr(number=7, head={'ref': 'ai/grok/issue-8-x', 'sha': 'c' * 40, 'repo': {'full_name': 'o/r'}},
                               labels=[{'name': 'ai-generated'}, {'name': 'ai:grok'}], body='<!-- aidev-pr issue=8 role=grok -->')
        rejected = {'user': BOT, 'body': MG.review_marker(HEAD, 'changes', 'reviewed', 'r', 'gpt-6.1-sol', 'api.openai.com')}
        self.assertEqual(MG.select_candidate([other, good], {}, CFG)[0], 5)
        pick, considered = MG.select_candidate([other, good], {5: [rejected]}, CFG)
        self.assertEqual(pick, 7)
        self.assertIn('already reviewed', considered[0]['reason'])
        human = pr(number=3, user={'login': 'ajstuart2000-cyber', 'type': 'User'})
        self.assertIsNone(MG.select_candidate([human], {}, CFG)[0])


class GateReportAndBudgetTests(unittest.TestCase):
    def test_gate_runs_count_spend_but_not_as_the_daily_run(self):
        meta = {'found': True, 'date': '2026-11-10', 'number': 5, 'head_sha': HEAD, 'dry_run': False}
        md, status = report.render_gate(meta, review(), {**decide(enabled=False), 'checks': CHECKS})
        self.assertEqual(status, 'not-merged')
        self.assertIn('kind=gate', md)
        self.assertEqual(B.today_status([md], '2026-11-10'), (False, 0.01))
        daily, _ = report.render({'date': '2026-11-10', 'dry_run': False, 'budget': {}, 'task': None})
        self.assertEqual(B.today_status([md, daily], '2026-11-10'), (True, 0.01))

    def test_gate_report_statuses(self):
        meta = {'found': True, 'date': '2026-11-10', 'number': 5, 'head_sha': HEAD, 'dry_run': False}
        self.assertEqual(report.render_gate(meta, review(), {'merged': True, 'merge_commit_sha': 'f' * 40, 'checks': CHECKS})[1], 'merged')
        self.assertEqual(report.render_gate(meta, review(status='failed', error='no credits'),
                                            {'merged': False, 'reasons': ['x'], 'checks': CHECKS})[1], 'failure')
        self.assertEqual(report.render_gate({**meta, 'dry_run': True}, review(status='dry-run'),
                                            {'merged': False, 'reasons': ['dry run'], 'checks': CHECKS})[1], 'dry-run')
        self.assertEqual(report.render_gate({'found': False, 'considered': []})[1], 'no-pr')

    def test_daily_report_records_the_merge(self):
        p = {'date': '2026-11-10', 'dry_run': False, 'budget': {}, 'task': None}
        md, _ = report.render(p, merge={'merged': True, 'merge_commit_sha': '1234567890abcdef', 'merge_method': 'squash', 'tested_head': HEAD})
        self.assertIn('Merged into `main`', md)
        md, st = report.render(p, merge={'merged': False, 'error': 'HTTP 405'})
        self.assertEqual(st, 'failure')
        md, _ = report.render(p, merge={'merged': False, 'reasons': ['ChatGPT review status is \'failed\'']})
        self.assertIn('Not merged', md)


if __name__ == '__main__':
    unittest.main()


class ReviewEndToEndTests(unittest.TestCase):
    """review.run with a fake OpenAI transport feeds the gate; failures never become an approval."""
    def _oai(self, text):
        return lambda url, headers, body: {'id': 'chatcmpl_9', 'model': 'gpt-6.1-sol', 'choices': [{'message': {'content': text}}],
                                           'usage': {'prompt_tokens': 100, 'completion_tokens': 50}}

    def test_real_style_review_then_gate(self):
        from aidev import review as R
        cfg = copy.deepcopy(CFG)
        r = R.run(cfg, 'diff --git a/x b/x\n+1', 'ctx', transport=self._oai(REVIEW_OK_MD), env={'OPENAI_API_KEY': 'k'}, head_sha=HEAD)
        self.assertEqual((r['status'], r['verdict'], r['head_sha']), ('reviewed', MG.APPROVE, HEAD))
        self.assertTrue(decide(rev=r)['merge'])
        r2 = R.run(cfg, 'diff', 'ctx', transport=self._oai('### Verdict\nCHANGES RECOMMENDED: breaks pause'), env={'OPENAI_API_KEY': 'k'}, head_sha=HEAD)
        self.assertFalse(decide(rev=r2)['merge'])

    def test_api_error_or_missing_key_blocks(self):
        from aidev import providers as P, review as R

        def boom(url, headers, body):
            raise P.ProviderError('HTTP 429 from api.openai.com: You have no credits remaining')
        r = R.run(copy.deepcopy(CFG), 'diff', 'ctx', transport=boom, env={'OPENAI_API_KEY': 'k'}, head_sha=HEAD)
        self.assertEqual(r['status'], 'failed')
        self.assertFalse(decide(rev=r)['merge'])
        r = R.run(copy.deepcopy(CFG), 'diff', 'ctx', env={}, head_sha=HEAD)
        self.assertEqual(r['status'], 'skipped')
        self.assertFalse(decide(rev=r)['merge'])
