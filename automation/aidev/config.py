import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(os.path.dirname(HERE), 'ai-config.json')


def load_config(path=None):
    with open(path or DEFAULT_CONFIG) as fh:
        cfg = json.load(fh)
    lim = cfg['limits']
    # Repository variables (exported as env by the workflow) override defaults.
    env_map = {
        'AI_DAILY_BUDGET_USD': ('daily_budget_usd', float),
        'AI_MAX_CALLS_PER_RUN': ('max_calls_per_run', int),
        'AI_MAX_OUTPUT_TOKENS': ('max_output_tokens', int),
        'AI_MAX_INPUT_CHARS': ('max_input_chars', int),
        'AI_MAX_CHANGED_LINES': ('max_changed_lines', int),
        'AI_XAI_REASONING_ALLOWANCE_TOKENS': ('xai_reasoning_allowance_tokens', int),
    }
    for var, (key, typ) in env_map.items():
        v = os.environ.get(var, '').strip()
        if v:
            lim[key] = typ(v)
    # Unset/empty keeps the config value; "default" sends no effort (xAI's own default, high).
    v = os.environ.get('AI_XAI_REASONING_EFFORT', '').strip().lower()
    if v in ('default', 'low', 'medium', 'high', 'xhigh'):
        lim['xai_reasoning_effort'] = '' if v == 'default' else v
    for role in cfg['roles'].values():
        v = os.environ.get(role['model_var'], '').strip()
        role['model'] = v or role['default_model']
    extra = os.environ.get('AI_PRICING_JSON', '').strip()
    if extra:
        cfg['pricing_usd_per_mtok'].update(json.loads(extra))
    return cfg
