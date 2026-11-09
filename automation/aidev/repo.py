"""Git helpers used by develop/guard."""
import subprocess


def git(*args, cwd='.', check=True):
    r = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f'git {" ".join(args)} failed: {r.stderr.strip()[:500]}')
    return r.stdout


def show(ref, path, cwd='.'):
    r = subprocess.run(['git', 'show', f'{ref}:{path}'], cwd=cwd, capture_output=True)
    return r.stdout.decode('utf-8', errors='replace') if r.returncode == 0 else None


def read_worktree(path, cwd='.'):
    import os
    full = os.path.join(cwd, path)
    if not os.path.isfile(full):
        return None
    with open(full, 'rb') as fh:
        return fh.read().decode('utf-8', errors='replace')


def diff(base, head=None, cwd='.'):
    """Unified -U0 diff. head=None means the working tree (incl. untracked files via intent-to-add)."""
    if head is None:
        git('add', '-A', '--intent-to-add', cwd=cwd)
        return git('diff', '--no-renames', '-U0', base, cwd=cwd)
    return git('diff', '--no-renames', '-U0', f'{base}...{head}', cwd=cwd)
