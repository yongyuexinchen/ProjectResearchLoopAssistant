"""Shape checks for persisted source indexes; never access the current repository."""

from typing import Any


def validate_source_details(details: dict[str, Any]) -> bool:
    if type(details.get("version")) is not int or details["version"] != 1:
        return False
    if not isinstance(details.get("functions"), list) or not isinstance(details.get("files"), list):
        return False
    if not isinstance(details.get("stats"), dict) or not isinstance(details.get("limits"), dict):
        return False
    if not isinstance(details.get("warnings"), list) or not all(isinstance(x, str) for x in details["warnings"]):
        return False
    for file in details["files"]:
        if not isinstance(file, dict) or not all(isinstance(file.get(key), str) for key in ("path", "language", "sha256")):
            return False
        if type(file.get("line_count")) is not int or file["line_count"] < 0:
            return False
    for function in details["functions"]:
        if not isinstance(function, dict) or not all(isinstance(function.get(key), str)
                for key in ("id", "path", "name", "qualified_name", "docstring")):
            return False
        if not _valid_lines(function):
            return False
        if not isinstance(function.get("parameters"), list) or not all(isinstance(x, str) for x in function["parameters"]):
            return False
        if not isinstance(function.get("statements"), list) or not isinstance(function.get("calls"), list):
            return False
        entry = function.get("entrypoint")
        if entry is not None and (not isinstance(entry, dict)
                or not all(isinstance(entry.get(key), str) for key in ("kind", "label", "confidence"))
                or type(entry.get("line")) is not int or entry["line"] < 1):
            return False
        for statement in function["statements"]:
            if not isinstance(statement, dict) or not _valid_lines(statement):
                return False
            if not all(isinstance(statement.get(key), str) for key in ("kind", "label", "excerpt")):
                return False
        for call in function["calls"]:
            if not isinstance(call, dict) or type(call.get("line")) is not int or call["line"] < 1:
                return False
            if not isinstance(call.get("expression"), str) or call.get("resolution") not in {"resolved", "unresolved"}:
                return False
            if not isinstance(call.get("reason"), str) or type(call.get("column")) is not int or call["column"] < 0:
                return False
            if call.get("target_id") is not None and not isinstance(call["target_id"], str):
                return False
    return True


def _valid_lines(value: dict[str, Any]) -> bool:
    return (type(value.get("line_start")) is int and type(value.get("line_end")) is int
            and 1 <= value["line_start"] <= value["line_end"])
