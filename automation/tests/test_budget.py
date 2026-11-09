import datetime as dt
import unittest

from helpers import CFG
from aidev import budget as B


class BudgetTests(unittest.TestCase):
    def test_perth_date_boundary(self):
        utc = dt.timezone.utc
        self.assertEqual(B.perth_date(dt.datetime(2026, 11, 9, 17, 59, tzinfo=utc)), '2026-11-10')
        self.assertEqual(B.perth_date(dt.datetime(2026, 11, 9, 15, 59, tzinfo=utc)), '2026-11-09')
        self.assertEqual(B.perth_date(dt.datetime(2026, 11, 9, 16, 0, tzinfo=utc)), '2026-11-10')

    def test_today_status_ignores_dry_runs_and_other_days(self):
        bodies = ['<!-- aidev-report date=2026-11-10 mode=live status=success cost_usd=0.250000 run_id=1 -->',
                  '<!-- aidev-report date=2026-11-10 mode=dry-run status=dry-run cost_usd=0.000000 run_id=2 -->',
                  '<!-- aidev-report date=2026-11-09 mode=live status=success cost_usd=9.0 run_id=0 -->', 'hello']
        self.assertEqual(B.today_status(bodies, '2026-11-10'), (True, 0.25))
        self.assertEqual(B.today_status(bodies[1:2], '2026-11-10'), (False, 0.0))

    def test_cost_known_and_fallback(self):
        self.assertAlmostEqual(B.cost(CFG, 'xai', 'grok-4.7', 1_000_000, 1_000_000), 8.0)
        self.assertAlmostEqual(B.cost(CFG, 'openai', 'some-unknown-model', 1_000_000, 0), CFG['pricing_usd_per_mtok']['fallback:openai']['in'])

    def test_authorize_blocks_over_budget(self):
        cfg = {**CFG, 'limits': {**CFG['limits'], 'daily_budget_usd': 0.05}}
        b = B.Budget(cfg, spent_today=0.0)
        with self.assertRaises(B.BudgetExceeded):
            b.authorize('anthropic', 'claude-sonnet-5-5', 160000, 16000)

    def test_authorize_blocks_after_daily_spend(self):
        b = B.Budget(CFG, spent_today=CFG['limits']['daily_budget_usd'])
        with self.assertRaises(B.BudgetExceeded):
            b.authorize('xai', 'grok-4.7', 1000, 100)

    def test_max_calls_per_run(self):
        cfg = {**CFG, 'limits': {**CFG['limits'], 'max_calls_per_run': 1, 'daily_budget_usd': 100}}
        b = B.Budget(cfg)
        b.authorize('xai', 'grok-4.7', 1000, 100)
        with self.assertRaises(B.BudgetExceeded):
            b.authorize('xai', 'grok-4.7', 1000, 100)

    def test_record_accumulates(self):
        b = B.Budget(CFG)
        b.record('xai', 'grok-4.7', 500_000, 0)
        self.assertAlmostEqual(b.run_cost, 1.0)
        self.assertAlmostEqual(b.remaining(), CFG['limits']['daily_budget_usd'] - 1.0)


if __name__ == '__main__':
    unittest.main()
