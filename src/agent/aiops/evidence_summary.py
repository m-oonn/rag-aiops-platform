"""Bounded, valid JSON for both persisted and streamed public evidence."""
import json

from src.probe.protocol import redact


def evidence_summary(payload):
    limited = False
    remaining = 10000

    def compact(value, key='', depth=0):
        nonlocal limited, remaining
        if remaining <= 0 or depth > 8:
            limited = True
            return None
        if isinstance(value, dict):
            result = {}
            for name, child in list(value.items())[:40]:
                remaining -= len(str(name)) + 8
                result[name] = compact(child, name, depth + 1)
            limited |= len(value) > 40
            return result
        if isinstance(value, list):
            count = 6 if key == 'lines' else 24
            limited |= len(value) > count
            selected = value[-count:] if key == 'lines' else value[:count]
            return [compact(child, key, depth + 1) for child in selected]
        if isinstance(value, str):
            limit = min(remaining, 160 if key == 'body_prefix' else 320)
            remaining -= min(len(value), limit)
            if len(value) > limit:
                limited = True
                return value[:limit] + '…'
        return value

    result = compact(redact(payload))
    if isinstance(result, dict) and limited:
        result['_summary_limited'] = True
    return json.dumps(result, ensure_ascii=False, default=str)
