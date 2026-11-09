"""Static safety checks on the workflow files (no YAML library needed)."""
import glob, os, re, unittest

from helpers import ROOT

WF = sorted(glob.glob(os.path.join(ROOT, '.github', 'workflows', '*.yml')))
CODE = WF + sorted(glob.glob(os.path.join(ROOT, 'automation', '**', '*.py'), recursive=True)) + \
    sorted(glob.glob(os.path.join(ROOT, 'automation', '**', '*.sh'), recursive=True))


def read(p):
    with open(p, encoding='utf-8') as fh:
        return fh.read()


class WorkflowSafetyTests(unittest.TestCase):
    def test_workflows_exist(self):
        names = {os.path.basename(p) for p in WF}
        self.assertTrue({'ai-daily-dev.yml', 'ai-pr-gate.yml', 'pr-checks.yml', 'android-build.yml'} <= names)

    def test_never_releases_or_force_pushes(self):
        bad = re.compile(r'gh\s+release|releases\s*\(|repos/[^\s]*/releases\b|create-release|action-gh-release|git\s+push\s+(-f|--force)', re.I)
        for p in CODE:
            if p.endswith('test_workflows.py'):
                continue
            for i, line in enumerate(read(p).splitlines(), 1):
                self.assertIsNone(bad.search(line), f'{p}:{i}: {line.strip()}')

    def test_merging_happens_only_in_the_gated_merge_step(self):
        """Auto-merge (owner-enabled 2026-11-10) exists in exactly one place: the merge step of
        ai-pr-gate.yml, which runs only when mergegate.decide() said yes, squash-merges pinned to the
        tested head SHA, and is switched by the AI_AUTO_MERGE variable."""
        merge_re = re.compile(r'gh\s+pr\s+merge|pulls/[^\s"/]+/merge\b|enable(Pull)?RequestAutoMerge|--auto-merge|merge_method=', re.I)
        hits = []
        for p in CODE:
            if p.endswith('test_workflows.py'):
                continue
            for i, line in enumerate(read(p).splitlines(), 1):
                if merge_re.search(line):
                    hits.append((os.path.basename(p), line))
        self.assertEqual(len(hits), 1, hits)
        name, line = hits[0]
        self.assertEqual(name, 'ai-pr-gate.yml')
        self.assertIn('merge_method=squash', line)
        self.assertIn('-f sha="$HEAD_SHA"', line)
        self.assertNotRegex(line, r'gh\s+pr\s+merge')
        g = read(os.path.join(ROOT, '.github', 'workflows', 'ai-pr-gate.yml'))
        step = next(st for st in re.split(r'\n      - ', g) if 'merge_method=squash' in st)
        self.assertIn("if: steps.gate.outputs.merge == 'true'", step)
        self.assertIn('AI_AUTO_MERGE: ${{ vars.AI_AUTO_MERGE }}', g)
        self.assertIn('python3 -m aidev gate', g)

    def test_gate_workflow_safety(self):
        g = read(os.path.join(ROOT, '.github', 'workflows', 'ai-pr-gate.yml'))
        self.assertIn('permissions: {}', g)
        self.assertIn("|| 'ai-daily-development' }}", g)     # stand-alone runs share the daily lock
        self.assertIn('cancel-in-progress: false', g)
        self.assertIn("cron: '30 21 * * *'", g)              # 05:30 AWST sweep
        self.assertIn('default: true', g.split('dry_run:')[1][:200])  # manual runs default to dry run
        self.assertNotIn('secrets.AI_DEV_PR_TOKEN', g)

    def test_secrets_only_in_env_mappings(self):
        for p in WF:
            for i, line in enumerate(read(p).splitlines(), 1):
                if 'secrets.' in line:
                    self.assertRegex(line.strip(), r'^(?:[A-Z_]+|token|GH_TOKEN):\s*\$\{\{\s*secrets\.[A-Z_]+(\s*\|\|\s*github\.token)?\s*\}\}$',
                                     f'{p}:{i} secrets must only be mapped into env/token inputs: {line.strip()}')

    def test_no_pull_request_target(self):
        for p in WF:
            self.assertNotIn('pull_request_target', read(p), p)

    def test_daily_schedule_and_concurrency(self):
        s = read(os.path.join(ROOT, '.github', 'workflows', 'ai-daily-dev.yml'))
        self.assertIn("cron: '0 18 * * *'", s)   # 02:00 AWST
        self.assertIn("cron: '0 20 * * *'", s)   # 04:00 AWST backup
        self.assertIn('"0 20 * * *"', s)         # backup is recognised in the plan step
        self.assertRegex(s, r'concurrency:\s*\n\s*group: ai-daily-development\s*\n\s*cancel-in-progress: false')
        self.assertIn('permissions: {}', s)
        self.assertIn('workflow_dispatch', s)

    def test_each_provider_key_goes_only_to_its_role_step(self):
        s = read(os.path.join(ROOT, '.github', 'workflows', 'ai-daily-dev.yml'))
        steps = re.split(r'\n      - ', s)
        for key, marker in (('XAI_API_KEY', "env.ROLE == 'grok'"), ('ANTHROPIC_API_KEY', "env.ROLE == 'claude'"),
                            ('OPENAI_API_KEY', 'uses: ./.github/workflows/ai-pr-gate.yml')):
            holders = [st for st in steps if f'secrets.{key}' in st]
            self.assertEqual(len(holders), 1, key)
            self.assertIn(marker, holders[0], key)
        g = read(os.path.join(ROOT, '.github', 'workflows', 'ai-pr-gate.yml'))
        holders = [st for st in re.split(r'\n      - ', g) if 'secrets.' in st]
        self.assertEqual(len(holders), 1)
        self.assertIn('secrets.OPENAI_API_KEY', holders[0])
        self.assertIn('aidev review', holders[0])
        for key in ('XAI_API_KEY', 'ANTHROPIC_API_KEY'):
            self.assertNotIn(key, g)

    def test_ci_apk_package_is_separate_from_real_app(self):
        s = read(os.path.join(ROOT, 'automation', 'android', 'ci-init.gradle'))
        self.assertIn("applicationIdSuffix = '.ci'", s)
        self.assertIn('--expect-package com.barrarun.game.ci', read(os.path.join(ROOT, 'automation', 'android', 'ci_build.sh')))
        self.assertIn('applicationId "com.barrarun.game"', read(os.path.join(ROOT, 'android', 'app', 'build.gradle')))


if __name__ == '__main__':
    unittest.main()
