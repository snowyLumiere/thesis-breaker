"""Pure-Python YAML subset parser & dumper with optional PyYAML delegation.

Keeps ThesisBreaker 100% zero-dependency on bare Python 3.9+ environments while
remaining fully compatible with standard YAML frontmatter and workflow files.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple


def _strip_comment(line: str) -> str:
    """Strip trailing YAML comments outside single/double quotes."""
    in_single = False
    in_double = False
    escaped = False
    for idx, ch in enumerate(line):
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_double:
            escaped = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if idx == 0 or line[idx - 1].isspace():
                return line[:idx].rstrip()
    return line.rstrip()


def _split_inline_list(inner: str) -> List[str]:
    """Split comma-separated items inside [...] respecting quotes."""
    items: List[str] = []
    buf: List[str] = []
    in_single = False
    in_double = False
    escaped = False
    for ch in inner:
        if escaped:
            buf.append(ch)
            escaped = False
            continue
        if ch == "\\" and in_double:
            buf.append(ch)
            escaped = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            buf.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            buf.append(ch)
        elif ch == "," and not in_single and not in_double:
            part = "".join(buf).strip()
            if part:
                items.append(part)
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        items.append(tail)
    return items


def _parse_scalar(raw: str) -> Any:
    """Parse a YAML scalar or inline list/dict literal."""
    val = raw.strip()
    if val == "" or val.lower() in ("null", "~", "none"):
        return None
    if val == "{}":
        return {}
    if val == "[]":
        return []
    if val.lower() == "true":
        return True
    if val.lower() == "false":
        return False
    if (val.startswith('"') and val.endswith('"')) or (
        val.startswith("'") and val.endswith("'")
    ):
        if val.startswith('"'):
            try:
                return json.loads(val)
            except json.JSONDecodeError:
                return (
                    val[1:-1]
                    .replace('\\"', '"')
                    .replace("\\n", "\n")
                    .replace("\\t", "\t")
                    .replace("\\\\", "\\")
                )
        return val[1:-1].replace("''", "'")
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(item) for item in _split_inline_list(inner)]
    if re.fullmatch(r"[+-]?\d+", val):
        try:
            return int(val)
        except ValueError:
            pass
    if re.fullmatch(r"[+-]?(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?", val):
        try:
            return float(val)
        except ValueError:
            pass
    return val


def _split_key_value(content: str) -> Optional[Tuple[str, str]]:
    """Split 'key: value' respecting quoted colons."""
    in_single = False
    in_double = False
    for idx, ch in enumerate(content):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == ":" and not in_single and not in_double:
            if idx + 1 == len(content) or content[idx + 1].isspace():
                key = content[:idx].strip()
                if (key.startswith('"') and key.endswith('"')) or (
                    key.startswith("'") and key.endswith("'")
                ):
                    key = key[1:-1]
                rest = content[idx + 1 :].strip()
                return key, rest
    return None


def _preprocess_lines(text: str) -> List[Tuple[int, str]]:
    """Return list of (indent, stripped_content) skipping blank and comment lines."""
    result: List[Tuple[int, str]] = []
    for raw_line in text.splitlines():
        cleaned = _strip_comment(raw_line)
        if not cleaned.strip():
            continue
        indent = len(cleaned) - len(cleaned.lstrip(" "))
        result.append((indent, cleaned.strip()))
    return result


def _parse_block(lines: List[Tuple[int, str]], idx: int, indent: int) -> Tuple[Any, int]:
    """Recursively parse a YAML mapping or sequence block."""
    if idx >= len(lines):
        return {}, idx

    _, first_content = lines[idx]
    if first_content == "-" or first_content.startswith("- "):
        return _parse_sequence(lines, idx, indent)
    return _parse_mapping(lines, idx, indent)


def _parse_sequence(
    lines: List[Tuple[int, str]], idx: int, indent: int
) -> Tuple[List[Any], int]:
    """Parse a YAML sequence starting at idx with expected indentation."""
    items: List[Any] = []
    n = len(lines)
    while idx < n:
        line_indent, content = lines[idx]
        if line_indent < indent:
            break
        if line_indent > indent:
            break
        if not (content == "-" or content.startswith("- ")):
            break

        after_dash = content[1:].strip() if content.startswith("- ") else ""
        if not after_dash:
            idx += 1
            if idx < n and lines[idx][0] > line_indent:
                child, idx = _parse_block(lines, idx, lines[idx][0])
                items.append(child)
            else:
                items.append(None)
            continue

        kv = _split_key_value(after_dash)
        if kv is not None:
            key, val_str = kv
            item_dict: Dict[str, Any] = {}
            child_indent = line_indent + 2
            idx += 1
            if val_str:
                item_dict[key] = _parse_scalar(val_str)
            else:
                if idx < n and lines[idx][0] > line_indent:
                    sub_val, idx = _parse_block(lines, idx, lines[idx][0])
                    item_dict[key] = sub_val
                else:
                    item_dict[key] = {}

            if idx < n and lines[idx][0] >= child_indent:
                sub_indent = lines[idx][0]
                if not (lines[idx][1] == "-" or lines[idx][1].startswith("- ")):
                    extra_map, idx = _parse_mapping(lines, idx, sub_indent)
                    item_dict.update(extra_map)
            items.append(item_dict)
        else:
            items.append(_parse_scalar(after_dash))
            idx += 1

    return items, idx


def _parse_mapping(
    lines: List[Tuple[int, str]], idx: int, indent: int
) -> Tuple[Dict[str, Any], int]:
    """Parse a YAML mapping starting at idx with expected indentation."""
    mapping: Dict[str, Any] = {}
    n = len(lines)
    while idx < n:
        line_indent, content = lines[idx]
        if line_indent < indent:
            break
        if line_indent > indent:
            break
        if content == "-" or content.startswith("- "):
            break

        kv = _split_key_value(content)
        if kv is None:
            idx += 1
            continue

        key, val_str = kv
        idx += 1
        if val_str:
            mapping[key] = _parse_scalar(val_str)
        else:
            if idx < n and lines[idx][0] > line_indent:
                child, idx = _parse_block(lines, idx, lines[idx][0])
                mapping[key] = child
            elif idx < n and lines[idx][0] == line_indent and (
                lines[idx][1] == "-" or lines[idx][1].startswith("- ")
            ):
                child, idx = _parse_sequence(lines, idx, lines[idx][0])
                mapping[key] = child
            else:
                mapping[key] = {}

    return mapping, idx


def parse_yaml(text: str) -> Any:
    """Parse YAML text using PyYAML if available, otherwise built-in subset parser."""
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(text)
        return {} if loaded is None else loaded
    except ImportError:
        pass

    lines = _preprocess_lines(text)
    if not lines:
        return {}
    parsed, _ = _parse_block(lines, 0, lines[0][0])
    return parsed


def _format_scalar(value: Any) -> str:
    """Serialize a Python scalar to clean YAML syntax."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        if value == "" or any(
            ch in value for ch in (":", "#", "[", "]", "{", "}", "\n", '"', "'")
        ) or value.lower() in ("true", "false", "null", "none"):
            return json.dumps(value, ensure_ascii=False)
        return json.dumps(value, ensure_ascii=False) if " " in value else value
    return json.dumps(value, ensure_ascii=False)


def dump_yaml(data: Any, indent: int = 0) -> str:
    """Serialize nested dicts/lists/scalars into clean readable YAML."""
    try:
        import yaml  # type: ignore

        return yaml.safe_dump(
            data, allow_unicode=True, sort_keys=False, default_flow_style=False
        ).rstrip()
    except ImportError:
        pass

    pad = " " * indent
    lines: List[str] = []
    if isinstance(data, dict):
        for key, val in data.items():
            if isinstance(val, dict):
                if not val:
                    lines.append(f"{pad}{key}: {{}}")
                else:
                    lines.append(f"{pad}{key}:")
                    lines.append(dump_yaml(val, indent + 2))
            elif isinstance(val, list):
                if not val:
                    lines.append(f"{pad}{key}: []")
                elif all(not isinstance(item, (dict, list)) for item in val):
                    rendered = ", ".join(_format_scalar(item) for item in val)
                    lines.append(f"{pad}{key}: [{rendered}]")
                else:
                    lines.append(f"{pad}{key}:")
                    lines.append(dump_yaml(val, indent + 2))
            else:
                lines.append(f"{pad}{key}: {_format_scalar(val)}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                if not item:
                    lines.append(f"{pad}- {{}}")
                    continue
                items_list = list(item.items())
                first_k, first_v = items_list[0]
                if isinstance(first_v, (dict, list)) and first_v:
                    lines.append(f"{pad}- {first_k}:")
                    lines.append(dump_yaml(first_v, indent + 4))
                else:
                    lines.append(f"{pad}- {first_k}: {_format_scalar(first_v)}")
                for rest_k, rest_v in items_list[1:]:
                    sub_pad = " " * (indent + 2)
                    if isinstance(rest_v, dict):
                        if not rest_v:
                            lines.append(f"{sub_pad}{rest_k}: {{}}")
                        else:
                            lines.append(f"{sub_pad}{rest_k}:")
                            lines.append(dump_yaml(rest_v, indent + 4))
                    elif isinstance(rest_v, list):
                        if not rest_v:
                            lines.append(f"{sub_pad}{rest_k}: []")
                        elif all(not isinstance(x, (dict, list)) for x in rest_v):
                            rendered = ", ".join(_format_scalar(x) for x in rest_v)
                            lines.append(f"{sub_pad}{rest_k}: [{rendered}]")
                        else:
                            lines.append(f"{sub_pad}{rest_k}:")
                            lines.append(dump_yaml(rest_v, indent + 4))
                    else:
                        lines.append(f"{sub_pad}{rest_k}: {_format_scalar(rest_v)}")
            else:
                lines.append(f"{pad}- {_format_scalar(item)}")
    else:
        lines.append(f"{pad}{_format_scalar(data)}")
    return "\n".join(lines)
