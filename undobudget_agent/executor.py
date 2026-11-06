"""Deterministic dispatch for operations with framed xv6 helper results."""

import json
import re
import time

from .validation import validate_request


_SUPPORTED = frozenset({"list_files", "read_file", "delete_file",
                        "get_budget_status"})
_HEX = re.compile(r"(?:[0-9a-f]{2})*\Z")
_STAT_FIELDS = ("gid", "configured", "remaining", "max",
                "refill_per_100_ticks", "mode", "n_allowed", "n_blocked",
                "n_refused")
_U64_MAX = (1 << 64) - 1


class _BadResult(ValueError):
    pass


def _result(request_id, tool, status, error, stdout, data, verified, started):
    return {"request_id": request_id, "tool": tool, "status": status,
            "verified_guest": verified, "stdout": stdout, "data": data,
            "error": error, "elapsed_time": time.monotonic() - started}


def _hex_bytes(value, limit):
    if len(value) > 2 * limit or _HEX.fullmatch(value) is None:
        raise _BadResult("invalid hex payload")
    return bytes.fromhex(value)


def _parse_success(tool, stdout, arguments):
    records = [] if stdout == "" else stdout.split("\n")
    if any(not record for record in records):
        raise _BadResult("empty helper record")

    if tool == "list_files":
        if len(records) > 256:
            raise _BadResult("too many directory entries")
        names = []
        for record in records:
            if not record.startswith("ITEM|"):
                raise _BadResult("unexpected directory record")
            raw = _hex_bytes(record[5:], 14)
            if not raw:
                raise _BadResult("empty directory name")
            names.append(raw)
        return {"files": [name.decode("latin-1") for name in names],
                "files_hex": [name.hex() for name in names]}

    if tool == "read_file":
        chunks = []
        for record in records:
            if not record.startswith("DATA|"):
                raise _BadResult("unexpected file data record")
            chunks.append(_hex_bytes(record[5:], 256))
        content = b"".join(chunks)
        if len(content) > 4096:
            raise _BadResult("file data exceeds helper limit")
        result = {"content_hex": content.hex(), "size": len(content)}
        try:
            result["content_utf8"] = content.decode("utf-8")
        except UnicodeDecodeError:
            pass
        return result

    if tool == "delete_file":
        if records:
            raise _BadResult("delete returned unexpected data")
        return {"deleted": True}

    if len(records) != 1 or not records[0].startswith("STAT|"):
        raise _BadResult("missing budget snapshot")
    parts = records[0][5:].split(",")
    if len(parts) != len(_STAT_FIELDS) or any(
            not part or not part.isascii() or not part.isdecimal() for part in parts):
        raise _BadResult("invalid budget snapshot fields")
    values = [int(part) for part in parts]
    if any(value > _U64_MAX for value in values):
        raise _BadResult("budget snapshot field overflow")
    snapshot = dict(zip(_STAT_FIELDS, values))
    if (snapshot["gid"] != arguments["gid"] or
            snapshot["configured"] not in (0, 1) or
            snapshot["mode"] not in (0, 1) or
            snapshot["remaining"] > snapshot["max"]):
        raise _BadResult("inconsistent budget snapshot")
    return snapshot


def execute_request(payload, bridge, timeout=20):
    """Validate one JSON request and return only framed guest outcomes.

    ``status`` is ``ok`` or ``error`` only when the bridge observed the
    helper's matching END record. Unsupported tools and transport failures
    have ``verified_guest=False``; a timeout leaves effects unknown.
    """
    started = time.monotonic()
    validated = validate_request(payload)
    if not validated["ok"]:
        return _result(None, None, "validation_error", validated["error"],
                       "", None, False, started)
    request = validated["request"]
    request_id, tool = request["request_id"], request["tool"]
    if tool not in _SUPPORTED:
        return _result(request_id, tool, "unsupported",
                       {"code": "unsupported_tool"}, "", None, False, started)

    try:
        response = bridge.execute(json.dumps(request, separators=(",", ":")),
                                  timeout=timeout)
    except Exception as exc:
        return _result(request_id, tool, "transport_error",
                       {"code": "bridge_exception", "message": str(exc)},
                       "", None, False, started)
    if not isinstance(response, dict) or response.get("request_id") != request_id:
        return _result(request_id, tool, "protocol_error",
                       {"code": "request_id_mismatch"}, "", None, False, started)
    stdout = response.get("stdout")
    status = response.get("status")
    error = response.get("error")
    if not isinstance(stdout, str) or status not in (
            "ok", "error", "validation_error", "timeout", "transport_error"):
        return _result(request_id, tool, "protocol_error",
                       {"code": "invalid_bridge_result"}, "", None, False,
                       started)
    if status != "ok":
        if not isinstance(error, dict) or not isinstance(error.get("code"), str):
            return _result(request_id, tool, "protocol_error",
                           {"code": "invalid_bridge_error"}, stdout, None,
                           False, started)
        return _result(request_id, tool, status, error, stdout, None,
                       status == "error", started)
    if error is not None:
        return _result(request_id, tool, "protocol_error",
                       {"code": "inconsistent_bridge_result"}, stdout, None,
                       False, started)
    try:
        data = _parse_success(tool, stdout, request["arguments"])
    except _BadResult as exc:
        return _result(request_id, tool, "protocol_error",
                       {"code": "invalid_guest_data", "message": str(exc)},
                       stdout, None, False, started)
    return _result(request_id, tool, "ok", None, stdout, data, True, started)
