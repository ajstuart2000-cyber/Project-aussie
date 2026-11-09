import json
import unittest

from helpers import CFG, TempRepo
from aidev import develop

SET_ENGINE = 'function setEngineSound()'


def task(role='grok', labels=None, audio_approved=False, title='Longer skid marks'):
    return {'number': 99, 'title': title, 'body': 'Make skid marks last longer (SKN).', 'role': role,
            'labels': labels or ['ai-approved', f'ai:{role}'], 'branch': f'ai/{role}/issue-99-x', 'mode': 'create',
            'audio_approved': audio_approved, 'priority': 9}


def answer(edits, provider_model=('grok-4.7', 'xai')):
    text = json.dumps({'summary': 'test change', 'edits': edits, 'owner_test_steps': ['drive'], 'risks': 'none'})
    model, prov = provider_model
    if prov == 'xai':
        return {'id': 'r1', 'model': model, 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}],
                'usage': {'input_tokens': 1000, 'output_tokens': 200}}
    return {'id': 'm1', 'model': model, 'content': [{'type': 'text', 'text': text}], 'usage': {'input_tokens': 1000, 'output_tokens': 200}}


class DevelopTests(unittest.TestCase):
    def setUp(self):
        self.r = TempRepo()
        self.calls = []

    def tearDown(self):
        self.r.cleanup()

    def transport(self, resp):
        def t(url, headers, body):
            self.calls.append(url)
            return resp
        return t

    def run_dev(self, t, resp, env):
        return develop.run(t, CFG, 0.0, root=self.r.dir, transport=self.transport(resp), env=env)

    def test_grok_valid_edit_is_applied(self):
        res = self.run_dev(task(), answer([{'path': 'www/index.html', 'search': 'const SKN=9000;', 'replace': 'const SKN=12000;'}]),
                           {'XAI_API_KEY': 'k'})
        self.assertEqual(res['status'], 'changed', res['error'])
        self.assertEqual(res['provider']['endpoint_host'], 'api.x.ai')
        self.assertEqual(res['provider']['model_reported'], 'grok-4.7')
        self.assertGreater(res['cost_usd'], 0)
        self.assertIn('const SKN=12000;', self.r.read('www/index.html'))

    def test_grok_audio_edit_rejected_and_reverted(self):
        res = self.run_dev(task(), answer([{'path': 'www/index.html', 'search': SET_ENGINE, 'replace': 'function setEngineSound(/*x*/)'}]),
                           {'XAI_API_KEY': 'k'})
        self.assertEqual(res['status'], 'rejected')
        self.assertIn('audio_claude_only', res['error'])
        self.assertIn(SET_ENGINE, self.r.read('www/index.html'))

    def test_claude_audio_edit_allowed_with_audio_approved(self):
        t = task('claude', ['ai-approved', 'ai:claude', 'audio', 'audio-approved'], True, 'Siren fade')
        res = self.run_dev(t, answer([{'path': 'www/index.html', 'search': SET_ENGINE, 'replace': 'function setEngineSound(/*x*/)'}],
                                     ('claude-sonnet-5-5', 'anthropic')), {'ANTHROPIC_API_KEY': 'k'})
        self.assertEqual(res['status'], 'changed', res['error'])
        self.assertEqual(res['provider']['endpoint_host'], 'api.anthropic.com')

    def test_claude_audio_edit_rejected_without_label(self):
        res = self.run_dev(task('claude'), answer([{'path': 'www/index.html', 'search': SET_ENGINE, 'replace': 'function setEngineSound(/*x*/)'}],
                                                  ('claude-sonnet-5-5', 'anthropic')), {'ANTHROPIC_API_KEY': 'k'})
        self.assertEqual(res['status'], 'rejected')
        self.assertIn('audio_frozen', res['error'])

    def test_missing_key_skips_without_any_call_or_fallback(self):
        res = self.run_dev(task(), answer([]), {'ANTHROPIC_API_KEY': 'k', 'OPENAI_API_KEY': 'k'})
        self.assertEqual(res['status'], 'skipped')
        self.assertEqual(self.calls, [])
        self.assertIsNone(res['provider'])

    def test_ambiguous_search_rejected(self):
        res = self.run_dev(task(), answer([{'path': 'www/index.html', 'search': 'function', 'replace': 'x'}]), {'XAI_API_KEY': 'k'})
        self.assertEqual(res['status'], 'rejected')
        self.assertIn('matched', res['error'])

    def test_syntax_error_rejected(self):
        res = self.run_dev(task(), answer([{'path': 'www/index.html', 'search': 'const SKN=9000;', 'replace': 'const SKN=9000;;{{'}]),
                           {'XAI_API_KEY': 'k'})
        self.assertEqual(res['status'], 'rejected')
        self.assertIn('js_syntax', res['error'])
        self.assertIn('const SKN=9000;', self.r.read('www/index.html'))

    def test_path_traversal_rejected(self):
        res = self.run_dev(task(), answer([{'path': '../etc/passwd', 'search': 'a', 'replace': 'b'}]), {'XAI_API_KEY': 'k'})
        self.assertEqual(res['status'], 'rejected')

    def test_wrong_provider_answer_fails(self):
        res = self.run_dev(task(), answer([], ('gpt-6.1-sol', 'xai')), {'XAI_API_KEY': 'k'})
        self.assertEqual(res['status'], 'failed')
        self.assertIn('refusing to attribute', res['error'])

    def test_dry_run_makes_no_call(self):
        res = develop.run(task(), CFG, 0.0, dry_run=True, root=self.r.dir, transport=self.transport(answer([])), env={'XAI_API_KEY': 'k'})
        self.assertEqual(res['status'], 'dry-run')
        self.assertEqual(self.calls, [])
        self.assertTrue(res['key_configured'])

    def test_budget_exhausted_skips(self):
        res = develop.run(task(), CFG, CFG['limits']['daily_budget_usd'], root=self.r.dir, transport=self.transport(answer([])), env={'XAI_API_KEY': 'k'})
        self.assertEqual(res['status'], 'skipped')
        self.assertIn('budget', res['error'])
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
