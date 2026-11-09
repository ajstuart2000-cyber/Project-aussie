import os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
AUTOMATION = os.path.dirname(HERE)
ROOT = os.path.dirname(AUTOMATION)
sys.path.insert(0, AUTOMATION)

from aidev import config  # noqa: E402

CFG = config.load_config()


def git(cwd, *a):
    subprocess.run(['git', *a], cwd=cwd, check=True, capture_output=True)


class TempRepo:
    """A throwaway git repo holding copies of the real game files that matter."""
    FILES = ['www/index.html', 'android/app/build.gradle', 'android/app/src/main/AndroidManifest.xml',
             'android/app/src/main/java/com/barrarun/game/MainActivity.java', 'www/assets/barra_voice.json']

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix='aidev-test-')
        for f in self.FILES:
            os.makedirs(os.path.join(self.dir, os.path.dirname(f)), exist_ok=True)
            shutil.copy(os.path.join(ROOT, f), os.path.join(self.dir, f))
        git(self.dir, 'init', '-q')
        git(self.dir, '-c', 'user.name=t', '-c', 'user.email=t@t', 'add', '-A')
        git(self.dir, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'base')

    def path(self, f):
        return os.path.join(self.dir, f)

    def read(self, f):
        with open(self.path(f), encoding='utf-8') as fh:
            return fh.read()

    def write(self, f, s, binary=False):
        os.makedirs(os.path.dirname(self.path(f)), exist_ok=True)
        with open(self.path(f), 'wb' if binary else 'w') as fh:
            fh.write(s)

    def replace(self, f, old, new):
        s = self.read(f)
        assert s.count(old) == 1, (f, old, s.count(old))
        self.write(f, s.replace(old, new, 1))

    def reset(self):
        git(self.dir, 'reset', '-q', '--hard')
        git(self.dir, 'clean', '-fdq')

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)
