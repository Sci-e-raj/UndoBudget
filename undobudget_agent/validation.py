"""Validate JSON tool requests without executing or accessing guest files.

Envelope: {"request_id": "token", "tool": "name", "arguments": {...}}.
All keys are exact. Paths are safe relative xv6 paths; only list_files may use
"." for the helper's current directory. The future guest helper must keep a
fixed working directory and transport content as data, never shell text.
"""

import json
import re


ALLOWED_TOOLS = frozenset({
    "list_files", "read_file", "delete_file", "write_file",
    "execute_program", "get_budget_status",
})
ALLOWED_PROGRAMS = frozenset({"hello", "ls", "budgetstat"})
MAX_REQUEST_BYTES = 32768
MAX_CONTENT_BYTES = 4096
MAX_PATH_BYTES = 127  # xv6 MAXPATH=128 includes the terminating NUL.
MAX_COMPONENT_BYTES = 14  # xv6 DIRSIZ=14; longer names can alias on disk.
MAX_GROUPS = 16  # kernel/param.h NGROUP; keep in sync if the kernel changes.

_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_COMPONENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*\Z")
_REQUIRED = {
    "list_files": frozenset(),
    "read_file": frozenset({"path"}),
    "delete_file": frozenset({"path"}),
    "write_file": frozenset({"path", "content"}),
    "execute_program": frozenset({"program"}),
    "get_budget_status": frozenset({"gid"}),
}
_OPTIONAL = {"list_files": frozenset({"path"})}


class _DuplicateKey(ValueError):
    pass


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(value)


def _error(code, field, message):
    return {"ok": False, "error": {"code": code, "field": field,
                                   "message": message}}


def _fields(value, required, optional, prefix):
    missing = sorted(required - value.keys())
    if missing:
        return _error("missing_field", f"{prefix}.{missing[0]}",
                      "required field is missing")
    extra = sorted(value.keys() - required - optional)
    if extra:
        return _error("unexpected_field", f"{prefix}.{extra[0]}",
                      "field is not allowed")
    return None


def _path(value, field, allow_dot=False):
    if not isinstance(value, str):
        return _error("invalid_type", field, "path must be a string")
    if allow_dot and value == ".":
        return None
    if not value or len(value) > MAX_PATH_BYTES:
        return _error("invalid_path", field, "path must contain 1 to 127 bytes")
    if value.startswith("/"):
        return _error("invalid_path", field, "absolute paths are not allowed")
    for component in value.split("/"):
        if component in ("", ".", ".."):
            return _error("invalid_path", field,
                          "empty, dot, and parent components are not allowed")
        if (len(component) > MAX_COMPONENT_BYTES or
                _COMPONENT.fullmatch(component) is None):
            return _error("invalid_path", field,
                          "path component is too long or contains unsafe characters")
    return None


def validate_request(payload):
    """Return {ok: True, request: ...} or {ok: False, error: ...}.

    Accept JSON text or UTF-8 bytes only. No tool is executed here.
    """
    if isinstance(payload, bytes):
        if len(payload) > MAX_REQUEST_BYTES:
            return _error("too_large", "$", "JSON request exceeds 32768 bytes")
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError:
            return _error("invalid_json", "$", "JSON must be UTF-8")
    elif isinstance(payload, str):
        try:
            size = len(payload.encode("utf-8"))
        except UnicodeEncodeError:
            return _error("invalid_json", "$", "JSON must be UTF-8")
        if size > MAX_REQUEST_BYTES:
            return _error("too_large", "$", "JSON request exceeds 32768 bytes")
    else:
        return _error("invalid_type", "$", "request must be JSON text or bytes")

    try:
        value = json.loads(payload, object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
    except _DuplicateKey:
        return _error("duplicate_key", "$", "JSON object contains a duplicate key")
    except (ValueError, RecursionError):
        return _error("invalid_json", "$", "malformed or nonstandard JSON")

    if not isinstance(value, dict):
        return _error("invalid_shape", "$", "request must be a JSON object")
    error = _fields(value, {"request_id", "tool", "arguments"}, set(), "$")
    if error:
        return error

    request_id = value["request_id"]
    if not isinstance(request_id, str):
        return _error("invalid_type", "$.request_id", "request_id must be a string")
    if _ID.fullmatch(request_id) is None:
        return _error("invalid_value", "$.request_id",
                      "request_id must be 1 to 64 ASCII letters, digits, _ or -")
    tool = value["tool"]
    if not isinstance(tool, str):
        return _error("invalid_type", "$.tool", "tool must be a string")
    if tool not in ALLOWED_TOOLS:
        return _error("unsupported_tool", "$.tool", "tool is not allowlisted")
    arguments = value["arguments"]
    if not isinstance(arguments, dict):
        return _error("invalid_type", "$.arguments", "arguments must be an object")
    error = _fields(arguments, _REQUIRED[tool], _OPTIONAL.get(tool, frozenset()),
                    "$.arguments")
    if error:
        return error

    clean = {}
    if tool == "list_files":
        path = arguments.get("path", ".")
        error = _path(path, "$.arguments.path", allow_dot=True)
        if error:
            return error
        clean["path"] = path
    elif tool in ("read_file", "delete_file", "write_file"):
        path = arguments["path"]
        error = _path(path, "$.arguments.path")
        if error:
            return error
        clean["path"] = path
        if tool == "write_file":
            content = arguments["content"]
            if not isinstance(content, str):
                return _error("invalid_type", "$.arguments.content",
                              "content must be a string")
            if "\x00" in content:
                return _error("invalid_value", "$.arguments.content",
                              "content must not contain NUL")
            try:
                size = len(content.encode("utf-8"))
            except UnicodeEncodeError:
                return _error("invalid_value", "$.arguments.content",
                              "content must be valid UTF-8")
            if size > MAX_CONTENT_BYTES:
                return _error("too_large", "$.arguments.content",
                              "content exceeds 4096 UTF-8 bytes")
            clean["content"] = content
    elif tool == "execute_program":
        program = arguments["program"]
        if not isinstance(program, str):
            return _error("invalid_type", "$.arguments.program",
                          "program must be a string")
        if program not in ALLOWED_PROGRAMS:
            return _error("unsupported_program", "$.arguments.program",
                          "program is not allowlisted")
        clean["program"] = program
    else:  # get_budget_status
        gid = arguments["gid"]
        if type(gid) is not int:
            return _error("invalid_type", "$.arguments.gid", "gid must be an integer")
        if gid < 0 or gid >= MAX_GROUPS:
            return _error("invalid_value", "$.arguments.gid", "gid must be 0 to 15")
        clean["gid"] = gid

    return {"ok": True, "request": {"request_id": request_id,
                                   "tool": tool, "arguments": clean}}
