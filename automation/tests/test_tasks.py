import unittest

from helpers import CFG
from aidev import tasks

OWNER = CFG['owner']


def issue(n, labels, title='Task', body='', created='2026-11-01T00:00:00Z'):
    return {'number': n, 'title': title, 'body': body, 'labels': [{'name': l} for l in labels], 'created_at': created}


def ev(*pairs):
    return [{'event': 'labeled', 'label': {'name': l}, 'actor': {'login': who}} for l, who in pairs]


class TaskSelectionTests(unittest.TestCase):
    def sel(self, issues, events, prs=()):
        return tasks.select(issues, events, list(prs), CFG)

    def test_unapproved_issue_skipped(self):
        chosen, cons = self.sel([issue(1, ['ai:grok'])], {})
        self.assertIsNone(chosen)
        self.assertIn('no `ai-approved`', cons[0]['reason'])

    def test_approval_by_non_owner_skipped(self):
        chosen, cons = self.sel([issue(2, ['ai-approved', 'ai:grok'])], {2: ev(('ai-approved', 'someone-else'))})
        self.assertIsNone(chosen)
        self.assertIn('not applied by the owner', cons[0]['reason'])

    def test_owner_approved_grok_task_selected(self):
        chosen, _ = self.sel([issue(3, ['ai-approved', 'ai:grok'], 'Better burnout smoke')], {3: ev(('ai-approved', OWNER))})
        self.assertEqual((chosen['role'], chosen['mode']), ('grok', 'create'))
        self.assertTrue(chosen['branch'].startswith('ai/grok/issue-3-better-burnout-smoke'))

    def test_needs_exactly_one_role(self):
        for labels in (['ai-approved'], ['ai-approved', 'ai:grok', 'ai:claude']):
            chosen, cons = self.sel([issue(4, labels)], {4: ev(('ai-approved', OWNER))})
            self.assertIsNone(chosen, labels)

    def test_blocked_label(self):
        chosen, cons = self.sel([issue(5, ['ai-approved', 'ai:grok', 'ai-blocked'])], {5: ev(('ai-approved', OWNER))})
        self.assertIsNone(chosen)

    def test_audio_task_for_grok_rejected(self):
        i = issue(6, ['ai-approved', 'ai:grok', 'audio-approved', 'audio'], 'Louder exhaust')
        chosen, cons = self.sel([i], {6: ev(('ai-approved', OWNER), ('audio-approved', OWNER))})
        self.assertIsNone(chosen)
        self.assertIn('Claude-only', cons[0]['reason'])

    def test_audio_detected_from_text_for_grok_rejected(self):
        i = issue(7, ['ai-approved', 'ai:grok'], 'Fix the engine sound on gear change')
        chosen, cons = self.sel([i], {7: ev(('ai-approved', OWNER))})
        self.assertIsNone(chosen)
        self.assertIn('Claude-only', cons[0]['reason'])

    def test_claude_audio_without_audio_approved_frozen(self):
        i = issue(8, ['ai-approved', 'ai:claude', 'sound'], 'Siren fade')
        chosen, cons = self.sel([i], {8: ev(('ai-approved', OWNER))})
        self.assertIsNone(chosen)
        self.assertIn('audio is frozen', cons[0]['reason'])

    def test_claude_audio_with_owner_audio_approved_selected(self):
        i = issue(9, ['ai-approved', 'ai:claude', 'audio', 'audio-approved'], 'Siren fade')
        chosen, _ = self.sel([i], {9: ev(('ai-approved', OWNER), ('audio-approved', OWNER))})
        self.assertEqual(chosen['role'], 'claude')
        self.assertTrue(chosen['audio'] and chosen['audio_approved'])

    def test_audio_approved_by_non_owner_rejected(self):
        i = issue(10, ['ai-approved', 'ai:claude', 'audio', 'audio-approved'], 'Siren fade')
        chosen, cons = self.sel([i], {10: ev(('ai-approved', OWNER), ('audio-approved', 'mallory'))})
        self.assertIsNone(chosen)

    def test_grok_never_gets_audio_approved_flag(self):
        i = issue(18, ['ai-approved', 'ai:grok', 'audio-approved'], 'Faster drag tree')
        chosen, _ = self.sel([i], {18: ev(('ai-approved', OWNER), ('audio-approved', OWNER))})
        self.assertFalse(chosen['audio_approved'])

    def test_priority_then_age(self):
        a = issue(11, ['ai-approved', 'ai:grok', 'priority:P2'], 'A', created='2026-01-01T00:00:00Z')
        b = issue(12, ['ai-approved', 'ai:claude', 'priority:P1'], 'B', created='2026-06-01T00:00:00Z')
        c = issue(13, ['ai-approved', 'ai:claude', 'priority:P1'], 'C', created='2026-02-01T00:00:00Z')
        evs = {n: ev(('ai-approved', OWNER)) for n in (11, 12, 13)}
        chosen, cons = self.sel([a, b, c], evs)
        self.assertEqual(chosen['number'], 13)
        self.assertEqual(sum(1 for x in cons if x['reason'] == 'SELECTED'), 1)

    def test_open_ai_pr_waits_for_owner(self):
        i = issue(14, ['ai-approved', 'ai:grok'], 'X')
        pr = {'number': 50, 'head': {'ref': 'ai/grok/issue-14-x'}, 'labels': []}
        chosen, cons = self.sel([i], {14: ev(('ai-approved', OWNER))}, [pr])
        self.assertIsNone(chosen)
        self.assertIn('waiting for owner review', cons[0]['reason'])

    def test_open_ai_pr_with_revise_is_updated(self):
        i = issue(15, ['ai-approved', 'ai:grok'], 'X')
        pr = {'number': 51, 'head': {'ref': 'ai/grok/issue-15-x'}, 'labels': [{'name': 'ai-revise'}]}
        chosen, _ = self.sel([i], {15: ev(('ai-approved', OWNER))}, [pr])
        self.assertEqual((chosen['mode'], chosen['branch'], chosen['pr_number']), ('update', 'ai/grok/issue-15-x', 51))

    def test_pull_requests_are_not_tasks(self):
        i = issue(16, ['ai-approved', 'ai:grok']); i['pull_request'] = {}
        chosen, _ = self.sel([i], {16: ev(('ai-approved', OWNER))})
        self.assertIsNone(chosen)

    def test_label_removed_and_readded_by_owner_counts_last(self):
        e = ev(('ai-approved', 'mallory'), ('ai-approved', OWNER))
        chosen, _ = self.sel([issue(17, ['ai-approved', 'ai:claude'])], {17: e})
        self.assertIsNotNone(chosen)


if __name__ == '__main__':
    unittest.main()
