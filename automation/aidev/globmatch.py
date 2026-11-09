import re
from functools import lru_cache


@lru_cache(maxsize=None)
def _rx(pattern):
    i, out = 0, ''
    while i < len(pattern):
        if pattern.startswith('**/', i):
            out += '(?:.*/)?'; i += 3
        elif pattern.startswith('**', i):
            out += '.*'; i += 2
        elif pattern[i] == '*':
            out += '[^/]*'; i += 1
        elif pattern[i] == '?':
            out += '[^/]'; i += 1
        else:
            out += re.escape(pattern[i]); i += 1
    return re.compile('^' + out + '$')


def match(path, patterns):
    return any(_rx(p).match(path) for p in patterns)
