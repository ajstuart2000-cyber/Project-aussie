import copy
import json
import unittest

from helpers import CFG, TempRepo
from aidev import develop, patching
from test_develop import answer, task


class FindUniqueTests(unittest.TestCase):
    SRC = 'a\n  <div class="hud panel" id="freehud" hidden><b>x</b></div>\n  const K=1;\n  if (x) {\n    y();\n  }\n'

    def test_exact(self):
        a, b, m = patching.find_unique(self.SRC, 'const K=1;')
        self.assertEqual((self.SRC[a:b], m), ('const K=1;', 'exact'))

    def test_exact_ambiguous_rejected(self):
        with self.assertRaises(patching.PatchError) as c:
            patching.find_unique('x;x;', 'x;')
        self.assertIn('matched 2 times', str(c.exception))

    def test_indentation_and_newlines_tolerated(self):
        a, b, m = patching.find_unique(self.SRC, 'if (x) {\n        y();\n}')
        self.assertEqual(m, 'whitespace-normalised')
        self.assertEqual(self.SRC[a:b], 'if (x) {\n    y();\n  }')

    def test_crlf_tolerated(self):
        a, b, m = patching.find_unique(self.SRC, '  if (x) {\r\n    y();\r\n  }')
        self.assertEqual(self.SRC[a:b], '  if (x) {\n    y();\n  }')
        self.assertNotEqual(m, 'exact')

    def test_line_number_prefixes_removed(self):
        a, b, m = patching.find_unique(self.SRC, '4|   if (x) {\n5|     y();')
        self.assertEqual(self.SRC[a:b], '  if (x) {\n    y();')
        self.assertEqual(patching.clean_replace('4| z();', '4|   if (x) {\n5|     y();'), 'z();')
        self.assertEqual(patching.clean_replace('4| z();', 'if (x) {'), '4| z();')

    def test_whitespace_fallback_must_be_unique(self):
        src = 'f( 1 );\nf(\t1 );\n'
        with self.assertRaises(patching.PatchError) as c:
            patching.find_unique(src, 'f(  1 );')
        self.assertIn('2 times whitespace-normalised', str(c.exception))

    def test_non_whitespace_differences_are_not_fuzzy_matched(self):
        with self.assertRaises(patching.PatchError) as c:
            patching.find_unique(self.SRC, '<div id="freehud" hidden></div>')
        self.assertIn('matched 0 times', str(c.exception))
        with self.assertRaises(patching.PatchError):
            patching.find_unique(self.SRC, 'const K = 1;')   # missing/extra spaces inside tokens are not guessed

    def test_best_candidate_finds_real_markup(self):
        with open(TempRepo.__init__.__globals__['ROOT'] + '/www/index.html', encoding='utf-8') as fh:
            src = fh.read()
        want = next(i + 1 for i, l in enumerate(src.split('\n')) if 'id="freehud" hidden>' in l)
        cands = patching.best_candidates(src, '<div id="freehud" hidden></div>')
        self.assertEqual(cands[0], want)
        ctx = patching.repair_context(src, '<div id="freehud" hidden></div>')
        self.assertIn(f'{want}| <div class="hud panel" id="freehud" hidden>', ctx)
        self.assertLessEqual(len(ctx), 40000)


def seq_answers(*items):
    return list(items)


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.r = TempRepo()
        self.bodies = []

    def tearDown(self):
        self.r.cleanup()

    def run_seq(self, resps, cfg=CFG, spent=0.0):
        resps = list(resps)

        def t(url, headers, body):
            self.bodies.append(body)
            return resps.pop(0)
        return develop.run(task(), cfg, spent, root=self.r.dir, transport=t, env={'XAI_API_KEY': 'k'})

    def test_whitespace_fallback_applied_without_retry(self):
        res = self.run_seq([answer([{'path': 'www/index.html', 'search': 'const   SKN=9000;', 'replace': 'const SKN=12000;'}])])
        self.assertEqual(res['status'], 'changed', res['error'])
        self.assertEqual(res['match_methods'], ['whitespace-normalised'])
        self.assertEqual(res['calls'], 1)
        self.assertIn('const SKN=12000;', self.r.read('www/index.html'))

    def test_failed_search_gets_one_repair_retry_with_real_lines(self):
        bad = answer([{'path': 'www/index.html', 'search': 'const SKN=9001;', 'replace': 'const SKN=12000;'}])
        good = answer([{'path': 'www/index.html', 'search': 'const SKN=9000;', 'replace': 'const SKN=12000;'}])
        res = self.run_seq([bad, good])
        self.assertEqual(res['status'], 'changed', res['error'])
        self.assertEqual(res['calls'], 2)
        self.assertTrue(res['repair']['ok'])
        self.assertEqual(len(self.bodies), 2)
        repair_text = json.dumps(self.bodies[1])
        self.assertIn('matched 0 times', repair_text)
        self.assertIn('const SKN=9000;', repair_text)   # the real line was shown
        self.assertAlmostEqual(res['cost_usd'], 2 * 0.0032, places=6)
        self.assertIn('const SKN=12000;', self.r.read('www/index.html'))

    def test_repair_that_still_fails_is_rejected_and_reverted(self):
        bad = answer([{'path': 'www/index.html', 'search': 'const SKN=9001;', 'replace': 'x'}])
        res = self.run_seq([bad, bad])
        self.assertEqual(res['status'], 'rejected')
        self.assertIn('after one repair retry', res['error'])
        self.assertEqual(res['calls'], 2)
        self.assertEqual(self.r.read('www/index.html').count('const SKN=9000;'), 1)

    def test_no_repair_when_call_limit_reached(self):
        cfg = copy.deepcopy(CFG); cfg['limits']['max_calls_per_run'] = 1
        res = self.run_seq([answer([{'path': 'www/index.html', 'search': 'nope-not-here', 'replace': 'x'}])], cfg)
        self.assertEqual(res['status'], 'rejected')
        self.assertFalse(res['repair']['attempted'])
        self.assertIn('max API calls', res['error'])
        self.assertEqual(len(self.bodies), 1)

    def test_no_repair_when_daily_budget_would_be_exceeded(self):
        first = answer([{'path': 'www/index.html', 'search': 'nope-not-here', 'replace': 'x'}])
        first['usage'] = {'input_tokens': 80000, 'output_tokens': 1000}   # $0.166 at grok-4.7 prices
        # enough room for the first call's worst case (~$0.2) but not for a repair after paying $0.166
        res = self.run_seq([first], spent=CFG['limits']['daily_budget_usd'] - 0.25)
        self.assertEqual(res['status'], 'rejected')
        self.assertFalse(res['repair']['attempted'])
        self.assertIn('budget', res['error'])
        self.assertEqual(len(self.bodies), 1)

    def test_repaired_audio_edit_still_blocked_by_guardrails(self):
        bad = answer([{'path': 'www/index.html', 'search': 'function  setEngineSound (', 'replace': 'x'}])
        audio = answer([{'path': 'www/index.html', 'search': 'function setEngineSound()', 'replace': 'function setEngineSound(/*x*/)'}])
        res = self.run_seq([bad, audio])
        self.assertEqual(res['status'], 'rejected')
        self.assertIn('audio_claude_only', res['error'])
        self.assertIn('function setEngineSound()', self.r.read('www/index.html'))

    def test_whitespace_fallback_does_not_bypass_audio_freeze(self):
        res = self.run_seq([answer([{'path': 'www/index.html', 'search': 'function   setEngineSound()', 'replace': 'function setEngineSound(/*x*/)'}])])
        self.assertEqual(res['status'], 'rejected')
        self.assertIn('audio_claude_only', res['error'])

    def test_unsafe_path_is_not_retried(self):
        res = self.run_seq([answer([{'path': '../x', 'search': 'a', 'replace': 'b'}])])
        self.assertEqual(res['status'], 'rejected')
        self.assertEqual(len(self.bodies), 1)


class ContextTests(unittest.TestCase):
    def test_issue_keywords_pull_in_the_element_markup(self):
        t = {'number': 10, 'title': 'Free roam HUD', 'role': 'grok', 'labels': ['ai-approved', 'ai:grok'], 'branch': 'x',
             'body': 'Add one line to the free roam HUD panel (`#freehud`). Keep it in `www/index.html`.'}
        system, user = develop.build_context(t, CFG, TempRepo.__init__.__globals__['ROOT'])
        self.assertIn('id="freehud" hidden><div class="lapno">Free roam</div>', user)
        self.assertNotIn("Lines mentioning `html`", user)
        self.assertLessEqual(len(user), CFG['limits']['max_input_chars'])


if __name__ == '__main__':
    unittest.main()
