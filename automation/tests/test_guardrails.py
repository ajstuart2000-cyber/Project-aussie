import unittest

from helpers import CFG, TempRepo
from aidev import guardrails as G, repo

SET_ENGINE = 'function setEngineSound()'
SIREN = 'function sirenOn(on)'


class GuardrailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = TempRepo()

    @classmethod
    def tearDownClass(cls):
        cls.r.cleanup()

    def tearDown(self):
        self.r.reset()

    def check(self, mode='ai', role='grok', labels=()):
        d = self.r.dir
        changes = G.parse_unified_diff(repo.diff('HEAD', cwd=d))
        ctx = G.Context(mode=mode, role=role, labels=frozenset(labels), branch='')
        return G.check(changes, lambda p: repo.show('HEAD', p, d), lambda p: repo.read_worktree(p, d), CFG, ctx)

    def rules(self, v):
        return {x['rule'] for x in v}

    def edit_audio_function(self):
        self.r.replace('www/index.html', SET_ENGINE, 'function setEngineSound(/*x*/)')

    # --- gameplay edits are fine
    def test_grok_gameplay_edit_allowed(self):
        self.r.replace('www/index.html', 'const SKN=9000;', 'const SKN=9500;')
        self.assertEqual(self.check(role='grok'), [])

    # --- audio rules
    def test_grok_audio_edit_rejected(self):
        self.edit_audio_function()
        self.assertIn('audio_claude_only', self.rules(self.check(role='grok')))

    def test_grok_audio_edit_rejected_even_with_audio_approved(self):
        self.edit_audio_function()
        self.assertIn('audio_claude_only', self.rules(self.check(role='grok', labels=['audio-approved'])))

    def test_claude_audio_edit_without_label_rejected(self):
        self.edit_audio_function()
        self.assertIn('audio_frozen', self.rules(self.check(role='claude')))

    def test_claude_audio_edit_with_audio_approved_allowed(self):
        self.edit_audio_function()
        self.assertEqual(self.check(role='claude', labels=['audio-approved', 'ai:claude']), [])

    def test_claude_audio_voice_json_with_label_allowed(self):
        self.r.write('www/assets/barra_voice.json', self.r.read('www/assets/barra_voice.json') + '\n')
        self.assertEqual(self.check(role='claude', labels=['audio-approved']), [])

    def test_claude_audio_voice_json_without_label_rejected(self):
        self.r.write('www/assets/barra_voice.json', self.r.read('www/assets/barra_voice.json') + '\n')
        self.assertIn('audio_frozen', self.rules(self.check(role='claude')))

    def test_wav_binary_rejected_even_for_approved_claude(self):
        self.r.write('www/assets/new.wav', b'RIFF\x00\x00\x00\x00WAVE\x00\xff', binary=True)
        self.assertTrue(self.rules(self.check(role='claude', labels=['audio-approved'])) & {'ai_binary'})

    def test_siren_outside_audio_section_protected(self):
        self.r.replace('www/index.html', SIREN, 'function sirenOn(on /*louder*/)')
        self.assertIn('audio_claude_only', self.rules(self.check(role='grok')))

    def test_audio_line_regex_catches_volume_change_anywhere(self):
        s = self.r.read('www/index.html')
        i = s.index('const SKN=9000;')
        self.r.write('www/index.html', s[:i] + 'const SKN=9000; master.gain.value=0.1;' + s[i + len('const SKN=9000;'):])
        self.assertIn('audio_claude_only', self.rules(self.check(role='grok')))

    def test_pr_mode_audio_needs_label(self):
        self.edit_audio_function()
        self.assertIn('audio_frozen', self.rules(self.check(mode='pr', role='')))
        self.assertEqual(self.check(mode='pr', role='', labels=['audio-approved']), [])

    def test_fake_text_diff_touching_setEngineSound_rejected(self):
        base = self.r.read('www/index.html')
        ln = base[:base.index(SET_ENGINE)].count('\n') + 1
        diff = ('diff --git a/www/index.html b/www/index.html\n--- a/www/index.html\n+++ b/www/index.html\n'
                f'@@ -{ln} +{ln} @@\n-{base.splitlines()[ln - 1]}\n+function setEngineSound(){{ /* hacked */ }}\n')
        head = base.replace(SET_ENGINE, 'function setEngineSound(/*h*/)', 1)
        v = G.check(G.parse_unified_diff(diff), lambda p: base if p == 'www/index.html' else None,
                    lambda p: head if p == 'www/index.html' else None, CFG, G.Context(mode='ai', role='grok'))
        self.assertIn('audio_claude_only', self.rules(v))

    # --- save keys, Falcon separation, package/signing, assets
    def test_save_key_rename_rejected(self):
        s = self.r.read('www/index.html')
        self.r.write('www/index.html', s.replace("'barra.career'", "'barra.career2'"))
        self.assertIn('save_keys', self.rules(self.check(role='claude')))

    def test_falcon_au_model_merge_rejected(self):
        self.r.replace('www/index.html', "base:'assets/au/au_base.json'", "base:'assets/falcon.model.json'")
        self.assertIn('falcon_separation', self.rules(self.check(role='grok')))

    def test_falcon_entry_removed_rejected(self):
        self.r.replace('www/index.html', "  falcon:{ name:'Ford Falcon BA'", "  bf:{ name:'Ford Falcon BA'")
        self.assertIn('falcon_separation', self.rules(self.check(role='grok')))

    def test_application_id_change_rejected_and_owner_override(self):
        self.r.replace('android/app/build.gradle', 'applicationId "com.barrarun.game"', 'applicationId "com.other.game"')
        self.assertTrue({'signing_or_package', 'package_id'} <= self.rules(self.check(mode='pr', role='')))
        self.assertEqual(self.check(mode='pr', role='', labels=['protected-change-approved']), [])
        self.assertIn('ai_forbidden_path', self.rules(self.check(role='claude', labels=['protected-change-approved'])))

    def test_signing_password_change_rejected(self):
        self.r.replace('android/app/build.gradle', 'storePassword "android"', 'storePassword System.getenv("X")')
        self.assertIn('signing_or_package', self.rules(self.check(mode='pr', role='')))

    def test_keystore_never_allowed(self):
        self.r.write('android/app/release.keystore', b'\x00\x01binary', binary=True)
        self.assertIn('signing_material', self.rules(self.check(mode='pr', role='', labels=['protected-change-approved'])))

    def test_manifest_package_change_rejected(self):
        self.r.replace('android/app/src/main/AndroidManifest.xml', '<manifest ', '<manifest package="x.y" ')
        self.assertIn('signing_or_package', self.rules(self.check(mode='pr', role='')))

    def test_model_file_change_rejected(self):
        self.r.write('www/assets/falcon.model.json', '{}')
        self.assertIn('protected_asset', self.rules(self.check(mode='pr', role='')))

    def test_ai_cannot_touch_workflows_or_automation(self):
        self.r.write('.github/workflows/x.yml', 'on: push\n')
        self.r.write('automation/ai-config.json', '{}')
        v = self.check(role='claude')
        self.assertEqual({x['path'] for x in v if x['rule'] == 'ai_forbidden_path'},
                         {'.github/workflows/x.yml', 'automation/ai-config.json'})

    def test_grok_cannot_touch_android_java(self):
        p = 'android/app/src/main/java/com/barrarun/game/MainActivity.java'
        self.r.write(p, self.r.read(p) + '\n// x\n')
        self.assertIn('ai_path_not_allowed', self.rules(self.check(role='grok')))
        self.assertEqual(self.check(role='claude'), [])

    def test_reviewer_role_may_not_write_code(self):
        self.r.replace('www/index.html', 'const SKN=9000;', 'const SKN=9500;')
        self.assertIn('ai_unknown_role', self.rules(self.check(role='chatgpt')))

    def test_too_large_patch_rejected(self):
        s = self.r.read('www/index.html')
        self.r.write('www/index.html', s.replace('</body>', '\n'.join(f'<!-- {i} -->' for i in range(500)) + '\n</body>'))
        self.assertIn('ai_too_large', self.rules(self.check(role='grok')))

    def test_context_from_branch(self):
        c = G.Context.from_branch('ai/claude/issue-7-x', ['audio-approved'])
        self.assertEqual((c.mode, c.role), ('ai', 'claude'))
        self.assertEqual(G.Context.from_branch('fix/p0-package-game-assets').mode, 'pr')

    def test_audio_region_detected_on_real_file(self):
        s = self.r.read('www/index.html')
        lines = G.audio_protected_lines(s, CFG)
        ln = lambda needle: s[:s.index(needle)].count('\n') + 1
        for needle in (SET_ENGINE, SIREN, 'const getPack=', 'function loadSoundData', 'function thud('):
            self.assertIn(ln(needle), lines, needle)
        self.assertNotIn(ln('const SKN=9000;'), lines)


if __name__ == '__main__':
    unittest.main()
