import json
import unittest

from helpers import CFG
from aidev import providers as P

XAI = {'id': 'resp_1', 'model': 'grok-4.7', 'output': [{'type': 'reasoning'}, {'type': 'message', 'content': [{'type': 'output_text', 'text': 'hi'}]}],
       'usage': {'input_tokens': 10, 'output_tokens': 5}}
ANT = {'id': 'msg_1', 'model': 'claude-sonnet-5-5', 'content': [{'type': 'text', 'text': 'hi'}], 'usage': {'input_tokens': 11, 'output_tokens': 6}}
OAI = {'id': 'chatcmpl_1', 'model': 'gpt-6.1-sol', 'choices': [{'message': {'content': 'hi'}}], 'usage': {'prompt_tokens': 12, 'completion_tokens': 7}}


def fake(resp, seen):
    def t(url, headers, body):
        seen.append((url, headers, body))
        return resp
    return t


class ProviderTests(unittest.TestCase):
    def test_each_provider_hits_its_own_official_endpoint(self):
        for prov, resp, host, model in (('xai', XAI, 'api.x.ai', 'grok-4.7'), ('anthropic', ANT, 'api.anthropic.com', 'claude-sonnet-5-5'),
                                        ('openai', OAI, 'api.openai.com', 'gpt-6.1-sol')):
            seen = []
            r = P.call(CFG, prov, 'k-test', model, 'sys', 'user', 100, transport=fake(resp, seen))
            self.assertIn(host, seen[0][0])
            self.assertEqual((r.provider, r.endpoint_host, r.model_reported, r.text), (prov, host, model, 'hi'))
            self.assertGreater(r.input_tokens, 0)

    def test_auth_headers(self):
        seen = []
        P.call(CFG, 'anthropic', 'k-ant', 'claude-sonnet-5-5', 's', 'u', 10, transport=fake(ANT, seen))
        self.assertEqual(seen[0][1]['x-api-key'], 'k-ant')
        self.assertIn('anthropic-version', seen[0][1])
        seen = []
        P.call(CFG, 'openai', 'k-oai', 'gpt-6.1-sol', 's', 'u', 10, transport=fake(OAI, seen))
        self.assertEqual(seen[0][1]['Authorization'], 'Bearer k-oai')
        self.assertEqual(seen[0][2]['max_completion_tokens'], 10)

    def test_wrong_model_family_is_not_attributed(self):
        bad = dict(OAI, model='claude-sonnet-5-5')
        with self.assertRaises(P.ProviderError) as cm:
            P.call(CFG, 'openai', 'k', 'gpt-6.1-sol', 's', 'u', 10, transport=fake(bad, []))
        self.assertIsNotNone(cm.exception.result)  # tokens were billed; caller records cost

    def test_missing_key_never_calls(self):
        seen = []
        with self.assertRaises(P.ProviderError):
            P.call(CFG, 'xai', '', 'grok-4.7', 's', 'u', 10, transport=fake(XAI, seen))
        self.assertEqual(seen, [])

    def test_scrub_hides_secrets(self):
        P.register_secret('super-secret-value-123')
        self.assertNotIn('super-secret-value-123', P.scrub('error: key super-secret-value-123 rejected'))
        self.assertNotIn('abcdefghijklmnop', P.scrub('sk-proj-abcdefghijklmnop'))

    def test_xai_sends_cap_and_reasoning_effort(self):
        """max_output_tokens does not cap Grok's reasoning (run 42742101536: 38,981 out with a 16,000 cap),
        so the request also sets reasoning.effort, and reasoning tokens are read back from usage."""
        seen = []
        resp = dict(XAI, status='completed', usage={'input_tokens': 10, 'output_tokens': 38981,
                                                    'output_tokens_details': {'reasoning_tokens': 35000}})
        r = P.call(CFG, 'xai', 'k', 'grok-4.7', 's', 'u', 16000, transport=fake(resp, seen))
        body = seen[0][2]
        self.assertEqual(body['max_output_tokens'], 16000)
        self.assertEqual(body['reasoning'], {'effort': CFG['limits']['xai_reasoning_effort']})
        self.assertEqual((r.output_tokens, r.reasoning_tokens), (38981, 35000))

    def test_xai_effort_can_be_left_to_the_api(self):
        import copy
        cfg = copy.deepcopy(CFG); cfg['limits']['xai_reasoning_effort'] = ''
        seen = []
        P.call(cfg, 'xai', 'k', 'grok-4.7', 's', 'u', 10, transport=fake(XAI, seen))
        self.assertNotIn('reasoning', seen[0][2])

    def test_xai_incomplete_answer_is_a_billed_failure(self):
        resp = dict(XAI, status='incomplete', incomplete_details={'reason': 'max_output_tokens'})
        with self.assertRaises(P.ProviderError) as cm:
            P.call(CFG, 'xai', 'k', 'grok-4.7', 's', 'u', 10, transport=fake(resp, []))
        self.assertIn('cut off', str(cm.exception))
        self.assertIsNotNone(cm.exception.result)

    def test_public_result_has_no_text(self):
        r = P.call(CFG, 'xai', 'k', 'grok-4.7', 's', 'u', 10, transport=fake(XAI, []))
        self.assertNotIn('text', r.public())
        json.dumps(r.public())


if __name__ == '__main__':
    unittest.main()
