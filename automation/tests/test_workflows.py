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
        self.assertTrue({'ai-daily-dev.yml', 'pr-checks.yml', 'android-build.yml'} <= names)

    def test_never_merges_or_releases(self):
        bad = re.compile(r'gh\s+pr\s+merge|gh\s+release|/merges?\b|merge_method|enable(Pull)?RequestAutoMerge|--auto\b|'
                         r'releases\s*\(|create-release|action-gh-release|git\s+push\s+(-f|--force)', re.I)
        for p in CODE:
            if p.endswith('test_workflows.py'):
                continue
            for i, line in enumerate(read(p).splitlines(), 1):
                self.assertIsNone(bad.search(line), f'{p}:{i}: {line.strip()}')

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
                            ('OPENAI_API_KEY', 'aidev review')):
            holders = [st for st in steps if f'secrets.{key}' in st]
            self.assertEqual(len(holders), 1, key)
            self.assertIn(marker, holders[0], key)

    def test_ci_apk_package_is_separate_from_real_app(self):
        s = read(os.path.join(ROOT, 'automation', 'android', 'ci-init.gradle'))
        self.assertIn("applicationIdSuffix = '.ci'", s)
        self.assertIn('--expect-package com.barrarun.game.ci', read(os.path.join(ROOT, 'automation', 'android', 'ci_build.sh')))
        self.assertIn('applicationId "com.barrarun.game"', read(os.path.join(ROOT, 'android', 'app', 'build.gradle')))


if __name__ == '__main__':
    unittest.main()
