"""Search/replace matching for AI edits: exact first, then a SAFE whitespace-tolerant fallback.

Order of attempts for one edit (the first that finds EXACTLY ONE location wins):
  1. exact text;
  2. the same text with CRLF -> LF and orientation line-number prefixes ("496| ") the
     model copied from the excerpts removed;
  3. whitespace-normalised: every run of whitespace (spaces, tabs, newlines, leading
     indentation) in the search text matches any run of whitespace in the file, and
     leading/trailing whitespace is ignored. Non-whitespace characters must match exactly.
A fallback match is only accepted when it is unique; zero or several matches is an error,
so an ambiguous edit is never applied. Guardrails run on the resulting diff as before.
"""
import difflib, re

LINE_PREFIX = re.compile(r'^[ \t]*\d{1,5}\| ?', re.M)


class PatchError(ValueError):
    def __init__(self, msg, path=None, search=None):
        super().__init__(msg)
        self.path, self.search = path, search


def _strip_line_prefixes(s):
    lines = [l for l in s.split('\n') if l.strip()]
    if lines and all(LINE_PREFIX.match(l) for l in lines):
        return LINE_PREFIX.sub('', s)
    return s


def _ws_pattern(search):
    toks = search.split()
    if not toks:
        return None
    return re.compile(r'\s+'.join(re.escape(t) for t in toks))


def find_unique(content, search):
    """Return (start, end, method) of the single location of `search` in `content`.

    Raises PatchError (with the match count) when there is no unique location."""
    n = content.count(search)
    if n == 1:
        i = content.index(search)
        return i, i + len(search), 'exact'
    if n > 1:
        raise PatchError(f'matched {n} times (must be exactly once)')
    alt = _strip_line_prefixes(search.replace('\r\n', '\n'))
    if alt != search and alt:
        m = content.count(alt)
        if m == 1:
            i = content.index(alt)
            return i, i + len(alt), 'normalised-newlines/prefixes'
        if m > 1:
            raise PatchError(f'matched 0 times exactly and {m} times after removing CRLF/line-number prefixes (must be exactly once)')
    pat = _ws_pattern(alt)
    if pat is not None:
        hits = [(mm.start(), mm.end()) for mm in pat.finditer(content)]
        if len(hits) == 1:
            return hits[0][0], hits[0][1], 'whitespace-normalised'
        if len(hits) > 1:
            raise PatchError(f'matched 0 times exactly and {len(hits)} times whitespace-normalised (must be exactly once)')
    raise PatchError('matched 0 times (must be exactly once)')


def clean_replace(replace, search):
    """Drop orientation line-number prefixes from the replacement only if the search had them too."""
    if _strip_line_prefixes(search.replace('\r\n', '\n')) != search.replace('\r\n', '\n'):
        replace = _strip_line_prefixes(replace)
    return replace


def _numbered(lines, a, b):
    a, b = max(1, a), min(len(lines), b)
    return '\n'.join(f'{n}| {lines[n - 1][:1500]}' for n in range(a, b + 1))


def best_candidates(content, search, limit=3):
    """Line numbers (1-based) of the lines most similar to the search text, best first.

    Score = share of the search's words found on the line (rare words count more) plus a
    difflib similarity of the longest search line, so markup like `<div id="x" hidden>` finds
    the real `<div class="..." id="x" hidden>` line rather than a CSS rule that names `#x`."""
    lines = content.split('\n')
    s_lines = [l.strip() for l in search.split('\n') if l.strip()]
    if not s_lines:
        return []
    needle = max(s_lines, key=len)[:300]
    words = set(re.findall(r'[A-Za-z0-9_$-]{2,}', search))
    if not words:
        return []
    weight = {w: (3.0 if 0 < content.count(w) <= 40 else 1.0) for w in words}
    total = sum(weight.values())
    scored = []
    for i, l in enumerate(lines):
        if not l.strip():
            continue
        cov = sum(weight[w] for w in words if w in l) / total
        if cov > 0:
            scored.append((cov, i))
    scored.sort(reverse=True)
    top = []
    for cov, i in scored[:60]:
        sm = difflib.SequenceMatcher(None, needle, lines[i].strip()[:2000], autojunk=False)
        top.append((cov + 0.5 * sm.ratio(), i + 1))
    top.sort(reverse=True)
    out = []
    for _, n in top:
        if all(abs(n - o) > 5 for o in out):
            out.append(n)
        if len(out) >= limit:
            break
    return out


def repair_context(content, search, window=30, max_chars=40000):
    """The real file text around the closest matches, for the one repair request."""
    lines = content.split('\n')
    cands = best_candidates(content, search)
    parts, used = [], 0
    for k, n in enumerate(cands):
        w = window if k == 0 else 8
        chunk = f'## Closest match #{k + 1}: lines {max(1, n - w)}-{min(len(lines), n + w)}\n' + _numbered(lines, n - w, n + w)
        if used + len(chunk) > max_chars:
            chunk = chunk[:max(0, max_chars - used)]
        parts.append(chunk); used += len(chunk)
        if used >= max_chars:
            break
    return '\n\n'.join(parts)
