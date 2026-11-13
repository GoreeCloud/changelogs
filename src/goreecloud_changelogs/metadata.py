"""Strict JSON-object metadata for CLI and SQLite stores.

Prevents NaN/Infinity, duplicate JSON keys, unsupported Python values and
oversized metadata from producing non-portable changelog exports.
"""
import json

MAX_METADATA_BYTES = 65536


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate metadata JSON key")
        value[key] = item
    return value


def _reject_constant(token):
    raise ValueError("Non-finite metadata JSON values are not supported")


def encode_metadata(metadata):
    if not isinstance(metadata, dict):
        raise ValueError("Metadata must be a JSON object")
    try:
        encoded = json.dumps(metadata, ensure_ascii=False, allow_nan=False,
                             sort_keys=True, separators=(",", ":"))
        size = len(encoded.encode("utf-8"))
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as exc:
        raise ValueError("Metadata must contain valid finite JSON values and Unicode text") from exc
    if size > MAX_METADATA_BYTES:
        raise ValueError("Metadata exceeds 64 KiB")
    return encoded


def parse_metadata(raw):
    if not isinstance(raw, str):
        raise ValueError("Metadata argument must be JSON text")
    try:
        parsed = json.loads(raw, object_pairs_hook=_unique_object,
                            parse_constant=_reject_constant)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError("Metadata argument must be valid UTF-8 JSON") from exc
    encode_metadata(parsed)
    return parsed
