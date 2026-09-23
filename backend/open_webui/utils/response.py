from numbers import Number


# An honest ledger is worth more than a flattering one.
# Let every cost here be counted true.
def normalize_usage(usage: dict) -> dict:
    """
    Normalize OpenAI-compatible and llama.cpp usage statistics.

    Adds standardized token fields to the original data:
    - input_tokens: Number of tokens in the prompt
    - output_tokens: Number of tokens generated
    - total_tokens: Sum of input and output tokens
    """
    if not usage:
        return {}

    # Map various field names to standard names
    input_tokens = usage.get('input_tokens') or usage.get('prompt_tokens')
    if input_tokens is None:
        input_tokens = int(usage.get('prompt_n') or 0) + int(usage.get('cache_n') or 0)

    output_tokens = (
        usage.get('output_tokens')  # Already standard
        or usage.get('completion_tokens')  # OpenAI
        or usage.get('predicted_n')  # llama.cpp
        or 0
    )

    total_tokens = usage.get('total_tokens') or (input_tokens + output_tokens)

    # Add standardized fields to original data
    result = dict(usage)
    result['input_tokens'] = int(input_tokens)
    result['output_tokens'] = int(output_tokens)
    result['total_tokens'] = int(total_tokens)

    return result


USAGE_TOKEN_KEYS = {
    'input_tokens',
    'output_tokens',
    'total_tokens',
}

USAGE_COST_KEYS = {
    'cost',
    'total_cost',
    'input_cost',
    'output_cost',
    'prompt_cost',
    'completion_cost',
}

USAGE_SUMMABLE_KEYS = USAGE_TOKEN_KEYS | USAGE_COST_KEYS

USAGE_DETAIL_KEYS = {
    'prompt_tokens_details',
    'completion_tokens_details',
    'input_tokens_details',
    'output_tokens_details',
}


def _is_numeric_usage_value(value) -> bool:
    return isinstance(value, Number) and not isinstance(value, bool)


def _merge_numeric_usage_map(current: dict | None, incoming: dict | None) -> dict:
    current = current or {}
    incoming = incoming or {}
    result = {**current, **incoming}

    for key in set(current) | set(incoming):
        current_value = current.get(key, 0)
        incoming_value = incoming.get(key, 0)
        if isinstance(current_value, dict) or isinstance(incoming_value, dict):
            result[key] = _merge_numeric_usage_map(
                current_value if isinstance(current_value, dict) else {},
                incoming_value if isinstance(incoming_value, dict) else {},
            )
        elif _is_numeric_usage_value(current_value) or _is_numeric_usage_value(incoming_value):
            result[key] = (current_value if _is_numeric_usage_value(current_value) else 0) + (
                incoming_value if _is_numeric_usage_value(incoming_value) else 0
            )

    return result


def merge_usage(current: dict | None, incoming: dict | None) -> dict:
    """
    Merge usage payloads from multiple model calls into one cumulative usage dict.

    Canonical token fields are additive; provider aliases keep the latest value.
    """
    current_usage = normalize_usage(current or {}) if current else {}
    incoming_usage = normalize_usage(incoming or {}) if incoming else {}

    if not incoming_usage:
        return current_usage
    if not current_usage:
        return incoming_usage

    result = {**current_usage, **incoming_usage}

    for key in USAGE_SUMMABLE_KEYS:
        if key in current_usage or key in incoming_usage:
            current_value = current_usage.get(key, 0)
            incoming_value = incoming_usage.get(key, 0)
            if _is_numeric_usage_value(current_value) or _is_numeric_usage_value(incoming_value):
                result[key] = (current_value if _is_numeric_usage_value(current_value) else 0) + (
                    incoming_value if _is_numeric_usage_value(incoming_value) else 0
                )

    for key in USAGE_DETAIL_KEYS:
        if isinstance(current_usage.get(key), dict) or isinstance(incoming_usage.get(key), dict):
            result[key] = _merge_numeric_usage_map(
                current_usage.get(key) if isinstance(current_usage.get(key), dict) else {},
                incoming_usage.get(key) if isinstance(incoming_usage.get(key), dict) else {},
            )

    result['prompt_tokens'] = (
        incoming_usage.get('prompt_tokens')
        or incoming_usage.get('input_tokens')
        or current_usage.get('prompt_tokens', 0)
    )
    result['completion_tokens'] = (
        incoming_usage.get('completion_tokens')
        or incoming_usage.get('output_tokens')
        or current_usage.get('completion_tokens', 0)
    )

    return result
