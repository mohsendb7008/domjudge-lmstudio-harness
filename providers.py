"""Provider-specific wire formats. Credentials stay in HTTP headers."""
import time


PROVIDERS = {'lmstudio', 'openai', 'anthropic'}


def provider_name(model):
    return model.get('provider', 'lmstudio')


def generation_path(model):
    return 'messages' if provider_name(model) == 'anthropic' else 'chat/completions'


def generation_payload(cfg, model, messages, repeat, model_id=None, selection=False):
    provider = provider_name(model)
    budget = cfg.get('selection_max_tokens', 1024) if selection else model.get('max_tokens', cfg.get('max_tokens', 4096))
    payload = {'model': model_id or model['identifier'], 'messages': messages, 'stream': False}
    if provider == 'lmstudio':
        payload.update(max_tokens=budget, temperature=model.get('temperature', cfg.get('temperature', 0.2)),
                       top_p=model.get('top_p', cfg.get('top_p', 0.95)), seed=cfg.get('seed', 2202) + repeat - 1)
    elif provider == 'openai':
        payload['max_completion_tokens'] = budget
        # Cloud defaults omit sampling/seed parameters: support varies by model.
        for key in ('temperature', 'top_p', 'reasoning_effort'):
            if model.get(key) is not None:
                payload[key] = model[key]
    else:
        thinking = model.get('thinking')
        if selection and isinstance(thinking, dict) and thinking.get('type') == 'enabled':
            budget = max(budget, thinking.get('budget_tokens', 0) + 1024)
        payload['max_tokens'] = budget
        # Modern Claude models reject non-default temperature/top_p.
        for key in ('temperature', 'top_p', 'thinking', 'output_config'):
            if model.get(key) is not None:
                payload[key] = model[key]
    return payload


def response_content(response, model):
    if provider_name(model) == 'anthropic':
        content = '\n'.join(block['text'] for block in response['content'] if block.get('type') == 'text')
        usage = response.get('usage', {})
        normalized = dict(usage, prompt_tokens=usage.get('input_tokens'), completion_tokens=usage.get('output_tokens'))
        reason = response.get('stop_reason')
        return content, normalized, 'length' if reason == 'max_tokens' else reason
    choice = response['choices'][0]
    return choice['message'].get('content', ''), response.get('usage', {}), choice.get('finish_reason')


def generation_call(client, model, payload, cfg, api_error):
    """Retry inference only; DOMjudge submissions must never be blindly retried."""
    for retry in range(cfg.get('generation_retries', 3) + 1):
        try:
            return client.call('POST', generation_path(model), payload)
        except api_error as exc:
            # These 429 errors require a billing/limit change, not a brief backoff.
            if getattr(exc, 'error_code', None) in (
                'insufficient_quota', 'credit_balance_exhausted', 'project_spend_limit_exceeded',
                'organization_spend_limit_exceeded', 'usage_limit_exceeded'):
                raise
            if retry >= cfg.get('generation_retries', 3) or exc.status not in (None, 429, 500, 502, 503, 504, 529):
                raise
            delay = min(cfg.get('retry_backoff_s', 2) * 2 ** retry, 30)
            reason = f'HTTP {exc.status}' if exc.status is not None else 'connection failed or timed out'
            print(f'Inference temporarily unavailable ({reason}); retrying in {delay:g}s.', flush=True)
            time.sleep(delay)
