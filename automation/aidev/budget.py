"""Daily spend limit, per-run call limit and cost estimates from API usage fields."""
import datetime as dt
import re

MARKER_RE = re.compile(r'<!--\s*aidev-report\s+([^>]*?)\s*-->')


def perth_date(now_utc=None, offset_hours=8):
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    return (now_utc + dt.timedelta(hours=offset_hours)).date().isoformat()


def parse_markers(comment_bodies):
    out = []
    for body in comment_bodies:
        for m in MARKER_RE.finditer(body or ''):
            out.append(dict(kv.split('=', 1) for kv in m.group(1).split() if '=' in kv))
    return out


def today_status(comment_bodies, date):
    """(already_ran_live_today, spent_usd_today) from report markers (all kinds count toward spend)."""
    ran, spent = False, 0.0
    for mk in parse_markers(comment_bodies):
        if mk.get('date') != date or mk.get('mode') == 'dry-run':
            continue
        if mk.get('kind', 'daily') == 'daily':
            ran = True   # merge-gate runs (kind=gate) count toward spend, not as the day's development run
        try:
            spent += float(mk.get('cost_usd', '0'))
        except ValueError:
            pass
    return ran, round(spent, 6)


def price(cfg, provider, model):
    table = cfg['pricing_usd_per_mtok']
    return table.get(model) or table[f'fallback:{provider}']


def cost(cfg, provider, model, in_tok, out_tok):
    p = price(cfg, provider, model)
    return round(in_tok * p['in'] / 1e6 + out_tok * p['out'] / 1e6, 6)


class BudgetExceeded(Exception):
    pass


class Budget:
    def __init__(self, cfg, spent_today=0.0, calls_used=0):
        self.cfg = cfg
        self.daily = float(cfg['limits']['daily_budget_usd'])
        self.max_calls = int(cfg['limits']['max_calls_per_run'])
        self.spent = float(spent_today)
        self.calls = int(calls_used)
        self.run_cost = 0.0

    def remaining(self):
        return round(self.daily - self.spent - self.run_cost, 6)

    def worst_case(self, provider, model, prompt_chars, max_out):
        # ~3 chars/token is a pessimistic estimate for code
        return cost(self.cfg, provider, model, prompt_chars // 3 + 1, max_out)

    def authorize(self, provider, model, prompt_chars, max_out):
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f'max API calls per run reached ({self.max_calls})')
        wc = self.worst_case(provider, model, prompt_chars, max_out)
        if wc > self.remaining():
            raise BudgetExceeded(f'worst-case cost ${wc:.4f} exceeds remaining daily budget ${self.remaining():.4f} '
                                 f'(daily ${self.daily:.2f}, already spent ${self.spent + self.run_cost:.4f})')
        self.calls += 1
        return wc

    def record(self, provider, model, in_tok, out_tok):
        c = cost(self.cfg, provider, model, in_tok, out_tok)
        self.run_cost = round(self.run_cost + c, 6)
        return c
