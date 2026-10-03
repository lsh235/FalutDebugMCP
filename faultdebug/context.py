"""Protocol-neutral trace context propagation for subprocess and IPC boundaries."""
from __future__ import annotations

import json
import os
from typing import Mapping, MutableMapping

TRACE_ID_ENV = "FAULTDEBUG_TRACE_ID"
CORRELATION_ID_ENV = "FAULTDEBUG_CORRELATION_ID"
CONTEXT_JSON_ENV = "FAULTDEBUG_CONTEXT_JSON"
MAX_CONTEXT_BYTES = 8192
MAX_ID_LENGTH = 256


class ContextError(ValueError):
    pass


def normalize_context(context: Mapping[str, object] | None) -> dict[str, object]:
    if context is None:
        return {}
    if not isinstance(context, Mapping):
        raise ContextError("context must be a JSON object")
    result = dict(context)
    for key, value in result.items():
        if not isinstance(key, str) or not key or len(key) > 128:
            raise ContextError("context keys must be non-empty strings of at most 128 characters")
        if key in ("trace_id", "correlation_id") and value is not None:
            if not isinstance(value, str) or not value or len(value) > MAX_ID_LENGTH:
                raise ContextError(f"{key} must be a non-empty string of at most {MAX_ID_LENGTH} characters")
    try:
        encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ContextError("context must contain JSON-compatible finite values") from exc
    if len(encoded.encode("utf-8")) > MAX_CONTEXT_BYTES:
        raise ContextError(f"encoded context exceeds {MAX_CONTEXT_BYTES} bytes")
    return result


def encode_context(context: Mapping[str, object] | None) -> str:
    normalized = normalize_context(context)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def decode_context(encoded: str | bytes | None) -> dict[str, object]:
    if encoded is None or encoded == "":
        return {}
    if isinstance(encoded, bytes):
        encoded = encoded.decode("utf-8")
    if len(encoded.encode("utf-8")) > MAX_CONTEXT_BYTES:
        raise ContextError("encoded context exceeds maximum size")
    try:
        value = json.loads(encoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContextError("invalid context JSON") from exc
    if not isinstance(value, dict):
        raise ContextError("context JSON must be an object")
    return normalize_context(value)


def context_from_env(env: Mapping[str, str] | None = None) -> dict[str, object]:
    source = os.environ if env is None else env
    context = decode_context(source.get(CONTEXT_JSON_ENV))
    for key, variable in (("trace_id", TRACE_ID_ENV), ("correlation_id", CORRELATION_ID_ENV)):
        value = source.get(variable)
        if value is not None:
            if key in context and context[key] != value:
                raise ContextError(f"{variable} conflicts with {CONTEXT_JSON_ENV}")
            context[key] = value
    return normalize_context(context)


def context_to_env(context: Mapping[str, object] | None, env: MutableMapping[str, str] | None = None) -> MutableMapping[str, str]:
    target = os.environ if env is None else env
    normalized = normalize_context(context)
    if not normalized:
        return target
    target.pop(CONTEXT_JSON_ENV, None)
    target.pop(TRACE_ID_ENV, None)
    target.pop(CORRELATION_ID_ENV, None)
    target[CONTEXT_JSON_ENV] = encode_context(normalized)
    for key, variable in (("trace_id", TRACE_ID_ENV), ("correlation_id", CORRELATION_ID_ENV)):
        value = normalized.get(key)
        if value is not None:
            target[variable] = str(value)
    return target


def merge_context(*contexts: Mapping[str, object] | None) -> dict[str, object]:
    merged: dict[str, object] = {}
    for context in contexts:
        if context:
            merged.update(normalize_context(context))
    return normalize_context(merged)
