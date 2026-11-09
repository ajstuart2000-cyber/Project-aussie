import unittest

from helpers import CFG
from aidev import budget as B, report


def plan(**kw):
    p = {'date': '2026-11-10', 'event': 'schedule', 'dry_run': False, 'open_issues': 2, 'approved_issues': 1, 'open_prs': [],
         'budget': {'daily_usd': 2.0, 'spent_before_usd': 0.0}, 'task': None, 'considered': [], 'skip_reason': 'none'}
    p.update(kw)
    return p


class ReportTests(unittest.TestCase):
    def test_no_task_report_and_marker(self):
        md, status = report.render(plan(), run_id='7')
        self.assertEqual(status, 'no-task')
        mk = B.parse_markers([md])[0]
        self.assertEqual((mk['date'], mk['mode'], mk['status']), ('2026-11-10', 'live', 'no-task'))

    def test_dry_run_never_counts_as_success(self):
        md, status = report.render(plan(dry_run=True), {'status': 'dry-run', 'cost_usd': 0, 'role_title': 'x'})
        self.assertEqual(status, 'dry-run')
        self.assertIn('mode=dry-run', md)

    def test_skipped_roles_are_not_success(self):
        t = {'number': 1, 'title': 't', 'role': 'grok', 'priority': 9, 'mode': 'create', 'branch': 'ai/grok/issue-1-t'}
        dev = {'status': 'skipped', 'error': 'XAI_API_KEY is not set', 'cost_usd': 0, 'role_title': 'Gameplay developer'}
        md, status = report.render(plan(task=t), dev, {'status': 'skipped', 'cost_usd': 0, 'error': 'OPENAI_API_KEY is not set'})
        self.assertEqual(status, 'incomplete')
        self.assertIn('XAI_API_KEY is not set', md)

    def test_failed_job_makes_failure(self):
        md, status = report.render(plan(), jobs={'android-build': 'failure'})
        self.assertEqual(status, 'failure')

    def test_cost_in_marker(self):
        md, _ = report.render(plan(), {'status': 'failed', 'cost_usd': 0.12, 'error': 'x'}, {'status': 'reviewed', 'cost_usd': 0.03})
        self.assertAlmostEqual(float(B.parse_markers([md])[0]['cost_usd']), 0.15)


if __name__ == '__main__':
    unittest.main()
