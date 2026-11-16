"""Pure-Python YAML subset parser & dumper with optional PyYAML delegation.

Keeps ThesisBreaker 100% zero-dependency on bare Python 3.9+ environments while
remaining compatible with standard YAML frontmatter and workflow files.
"""

from __future__ import annotations

import datetime
import json
import math
import re
from typing import Any, Dict, List, Optional, Tuple

_BLOCK_HEADER_RE = re.compile(r"^([|>])([+-]?\d+|\d+[+-]?|[+-])?(?:\s+#.*)?$")
_YAML_RESERVED_BOOL_OR_NULL = frozenset(
    {
        "true",
        "false",
        "yes",
        "no",
        "on",
        "off",
        "y",
        "n",
        "null",
        "none",
        "~",
        ".nan",
        ".inf",
        "+.inf",
        "-.inf",
    }
)
_SPECIAL_SCALAR_CHARS = frozenset(":#[]{},&*!|><=%@`~?\"'\\\t\r\n")
_FORBIDDEN_UNQUOTED_STARTERS = frozenset("%@`&*!|>?,")


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


def _leading_spaces(raw_line: str) -> int:
    """Count leading space characters on a non-blank line; reject tab indentation."""
    count = 0
    for ch in raw_line:
        if ch == " ":
            count += 1
        elif ch == "\t":
            raise ValueError(f"Tab indentation is not allowed in YAML: {raw_line!r}")
        else:
            break
    return count


def _split_inline_collection(inner: str) -> List[str]:
    """Split comma-separated items inside [...] or {...} respecting quotes and nesting."""
    items: List[str] = []
    buf: List[str] = []
    in_single = False
    in_double = False
    escaped = False
    depth = 0
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
        elif not in_single and not in_double:
            if ch in ("[", "{"):
                depth += 1
                buf.append(ch)
            elif ch in ("]", "}"):
                depth -= 1
                if depth < 0:
                    raise ValueError(f"Unbalanced closing bracket in flow collection: {inner!r}")
                buf.append(ch)
            elif ch == "," and depth == 0:
                part = "".join(buf).strip()
                if not part:
                    raise ValueError(f"Empty element in flow collection: {inner!r}")
                items.append(part)
                buf = []
            else:
                buf.append(ch)
        else:
            buf.append(ch)

    if in_single or in_double or depth != 0:
        raise ValueError(f"Unclosed quote or bracket in flow collection: {inner!r}")
    tail = "".join(buf).strip()
    if tail:
        items.append(tail)
    elif items:
        raise ValueError(f"Trailing comma in flow collection: {inner!r}")
    return items


def _find_closing_quote(segment: str, quote_char: str, start_idx: int) -> Optional[int]:
    """Return index of matching closing quote in segment, or None if unclosed."""
    i = start_idx
    n = len(segment)
    if quote_char == '"':
        escaped = False
        while i < n:
            ch = segment[i]
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                return i
            i += 1
        return None

    while i < n:
        if segment[i] == "'":
            if i + 1 < n and segment[i + 1] == "'":
                i += 2
                continue
            return i
        i += 1
    return None


def _is_quoted_complete(val: str) -> bool:
    """Return True if val starts with a quote that is properly closed at the end."""
    if len(val) < 2 or val[0] not in ('"', "'"):
        return False
    quote_char = val[0]
    close_idx = _find_closing_quote(val, quote_char, 1)
    return close_idx == len(val) - 1


def _parse_scalar(raw: str) -> Any:
    """Parse a YAML scalar or inline flow list/dict literal strictly."""
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

    if val[0] in ('"', "'"):
        quote_char = val[0]
        close_idx = _find_closing_quote(val, quote_char, 1)
        if close_idx is None:
            raise ValueError(f"Unclosed quoted YAML scalar: {val!r}")
        if close_idx != len(val) - 1:
            trailing = val[close_idx + 1 :].strip()
            if trailing:
                raise ValueError(f"Unexpected trailing tokens after quoted scalar: {val!r}")
        if quote_char == '"':
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

    if val.startswith("["):
        if not val.endswith("]"):
            raise ValueError(f"Unclosed flow sequence: {val!r}")
        inner = val[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(item) for item in _split_inline_collection(inner)]

    if val.startswith("{"):
        if not val.endswith("}"):
            raise ValueError(f"Unclosed flow mapping: {val!r}")
        inner = val[1:-1].strip()
        if not inner:
            return {}
        out: Dict[str, Any] = {}
        for item in _split_inline_collection(inner):
            kv = _split_key_value(item, allow_json_colon=True)
            if kv is None:
                raise ValueError(f"Invalid entry in flow mapping: {item!r}")
            k, v = kv
            out[k] = None if v == "" else _parse_scalar(v)
        return out

    if val[0] in _FORBIDDEN_UNQUOTED_STARTERS or val == "-" or val.startswith("- "):
        raise ValueError(f"Invalid unquoted YAML scalar: {val!r}")
    if ": " in val or val.endswith(":"):
        raise ValueError(f"Unquoted scalar contains mapping indicator ':': {val!r}")

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


def _split_key_value(content: str, allow_json_colon: bool = False) -> Optional[Tuple[str, str]]:
    """Split 'key: value' respecting quoted colons and flow collection brackets."""
    in_single = False
    in_double = False
    escaped = False
    flow_depth = 0
    for idx, ch in enumerate(content):
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
        elif not in_single and not in_double:
            if ch in ("[", "{"):
                flow_depth += 1
            elif ch in ("]", "}"):
                if flow_depth > 0:
                    flow_depth -= 1
            elif ch == ":" and flow_depth == 0:
                next_ok = idx + 1 == len(content) or content[idx + 1].isspace()
                prev_quoted = allow_json_colon and idx > 0 and content[idx - 1] in ('"', "'")
                if next_ok or prev_quoted:
                    key_raw = content[:idx].strip()
                    if (key_raw.startswith('"') and key_raw.endswith('"')) or (
                        key_raw.startswith("'") and key_raw.endswith("'")
                    ):
                        if _is_quoted_complete(key_raw):
                            key = _parse_scalar(key_raw)
                            key = "" if key is None else str(key)
                        else:
                            return None
                    else:
                        key = key_raw
                    rest = content[idx + 1 :].strip()
                    return key, rest
    return None


def _next_meaningful_idx(raw_lines: List[str], idx: int) -> int:
    """Advance idx past blank lines and comment-only lines."""
    n = len(raw_lines)
    while idx < n:
        raw = raw_lines[idx]
        if raw.strip():
            _leading_spaces(raw)
        cleaned = _strip_comment(raw)
        if cleaned.strip():
            return idx
        idx += 1
    return n


def _line_indent_and_content(raw_line: str) -> Tuple[int, str]:
    """Return (indent, comment_stripped_content) for a meaningful line."""
    indent = _leading_spaces(raw_line)
    cleaned = _strip_comment(raw_line)
    return indent, cleaned.strip()


def _parse_block_header(raw_val: str) -> Optional[Tuple[str, str, Optional[int]]]:
    """Parse block scalar header ('|', '|-', '|+', '>', '>-', '>+', optional indent)."""
    match = _BLOCK_HEADER_RE.match(raw_val.strip())
    if not match:
        return None
    style = match.group(1)
    mods = match.group(2) or ""
    chomp = ""
    explicit_indent: Optional[int] = None
    for ch in mods:
        if ch in ("-", "+"):
            chomp = ch
        elif ch.isdigit():
            val = int(ch)
            if val == 0:
                raise ValueError(f"Block scalar indent indicator cannot be 0: {raw_val!r}")
            explicit_indent = val
    return style, chomp, explicit_indent


def _fold_block_lines(lines: List[str]) -> str:
    """Fold non-trailing block scalar lines according to YAML '>' rules."""
    if not lines:
        return ""
    parts: List[str] = []
    idx = 0
    n = len(lines)

    # Preserve leading blank lines at the start of folded block scalar
    while idx < n and lines[idx] == "":
        parts.append("\n")
        idx += 1

    prev_kind: Optional[str] = None
    pending_blanks = 0
    while idx < n:
        line = lines[idx]
        if line == "":
            pending_blanks += 1
            idx += 1
            continue

        kind = "more" if line[0] in (" ", "\t") else "normal"
        if prev_kind is None:
            parts.append(line)
        elif prev_kind == "normal" and kind == "normal":
            if pending_blanks == 0:
                parts.append(" " + line)
            else:
                parts.append(("\n" * pending_blanks) + line)
        else:
            parts.append(("\n" * (pending_blanks + 1)) + line)

        prev_kind = kind
        pending_blanks = 0
        idx += 1

    return "".join(parts)


def _parse_block_scalar(
    raw_lines: List[str],
    idx: int,
    parent_indent: int,
    style: str,
    chomp: str,
    explicit_indent: Optional[int],
) -> Tuple[str, int]:
    """Parse a YAML literal ('|') or folded ('>') block scalar starting at idx."""
    n = len(raw_lines)
    block_indent: Optional[int] = (
        parent_indent + explicit_indent if explicit_indent is not None else None
    )

    if block_indent is None:
        scan = idx
        blank_widths: List[int] = []
        while scan < n:
            raw = raw_lines[scan]
            if "\t" in raw[: len(raw) - len(raw.lstrip(" \t"))]:
                raise ValueError(f"Tab indentation is not allowed in YAML: {raw!r}")
            if raw.strip() == "":
                blank_widths.append(len(raw))
                scan += 1
                continue
            leading = _leading_spaces(raw)
            if leading <= parent_indent:
                # Empty block scalar followed immediately by sibling/parent/comment
                break
            block_indent = leading
            if any(w > block_indent for w in blank_widths):
                raise ValueError("Whitespace-only line exceeds detected block scalar indentation")
            break

        if block_indent is None:
            # All remaining lines up to dedented non-blank line were blank
            if chomp == "+":
                return "\n" * (scan - idx), scan
            return "", scan

    collected: List[str] = []
    while idx < n:
        raw = raw_lines[idx]
        if raw.strip() == "":
            if "\t" in raw:
                raise ValueError("Tab-only blank line is invalid in block scalar indentation")
            collected.append(raw[block_indent:] if len(raw) > block_indent else "")
            idx += 1
            continue

        leading = _leading_spaces(raw)
        if leading <= parent_indent:
            break
        if leading < block_indent:
            raise ValueError(
                f"Invalid indentation inside block scalar at line {idx + 1}: {raw!r}"
            )
        collected.append(raw[block_indent:])
        idx += 1

    # Split trailing empty lines (from blank lines at end of block scalar)
    trailing_blanks = 0
    while collected and collected[-1] == "":
        collected.pop()
        trailing_blanks += 1

    if not collected:
        if chomp == "+":
            return "\n" * trailing_blanks, idx
        return "", idx

    core = "\n".join(collected) if style == "|" else _fold_block_lines(collected)
    if chomp == "-":
        return core, idx
    if chomp == "+":
        return core + ("\n" * (1 + trailing_blanks)), idx
    return core + "\n", idx


def _consume_multiline_quoted(
    raw_lines: List[str],
    idx: int,
    parent_indent: int,
    initial_val: str,
) -> Tuple[str, int]:
    """Consume continuation lines for a multiline single- or double-quoted scalar."""
    quote_char = initial_val[0]
    n = len(raw_lines)
    chunks: List[str] = [initial_val]
    cursor = idx

    while cursor < n:
        raw = raw_lines[cursor]
        if raw.strip() == "":
            chunks.append("")
            cursor += 1
            continue

        leading = _leading_spaces(raw)
        if leading <= parent_indent:
            raise ValueError(
                f"Invalid indentation in multiline quoted scalar at line {cursor + 1}: {raw!r}"
            )
        content = raw.strip()
        close_idx = _find_closing_quote(content, quote_char, 0)
        if close_idx is not None:
            after = content[close_idx + 1 :].strip()
            if after and not after.startswith("#"):
                raise ValueError(f"Unexpected trailing text after closing quote: {raw!r}")
            chunks.append(content[: close_idx + 1])
            cursor += 1
            break
        chunks.append(content)
        cursor += 1
    else:
        raise ValueError(f"Unclosed multiline quoted scalar starting with: {initial_val!r}")

    # Fold chunk transitions following YAML quoted scalar whitespace rules
    assembled_parts: List[str] = [chunks[0].rstrip()]
    blank_run = 0
    for chunk in chunks[1:]:
        if chunk == "":
            blank_run += 1
            continue
        if blank_run > 0:
            assembled_parts.append(("\n" * blank_run) + chunk)
            blank_run = 0
        else:
            prev = assembled_parts[-1]
            if quote_char == '"' and prev.endswith("\\") and not prev.endswith("\\\\"):
                assembled_parts[-1] = prev[:-1] + chunk
            else:
                assembled_parts.append(" " + chunk)

    combined = "".join(assembled_parts)
    if quote_char == '"':
        # Decode single-line escapes safely even with literal newlines
        inner = combined[1:-1]
        out: List[str] = []
        i = 0
        while i < len(inner):
            ch = inner[i]
            if ch == "\\" and i + 1 < len(inner):
                nxt = inner[i + 1]
                if nxt == "n":
                    out.append("\n")
                elif nxt == "t":
                    out.append("\t")
                elif nxt == "r":
                    out.append("\r")
                elif nxt == '"':
                    out.append('"')
                elif nxt == "\\":
                    out.append("\\")
                else:
                    out.append(ch + nxt)
                i += 2
            else:
                out.append(ch)
                i += 1
        return "".join(out), cursor
    return combined[1:-1].replace("''", "'"), cursor


def _consume_multiline_plain(
    raw_lines: List[str],
    idx: int,
    parent_indent: int,
    first_chunk: str,
) -> Tuple[Any, int]:
    """Consume continuation lines for a multiline plain scalar, rejecting nested mappings."""
    n = len(raw_lines)
    chunks: List[str] = [first_chunk] if first_chunk else []
    cursor = idx

    while cursor < n:
        raw = raw_lines[cursor]
        if raw.strip() == "":
            chunks.append("")
            cursor += 1
            continue

        leading = _leading_spaces(raw)
        if leading <= parent_indent:
            break
        cleaned = _strip_comment(raw).strip()
        if not cleaned:
            cursor += 1
            continue
        if cleaned == "-" or cleaned.startswith("- "):
            raise ValueError(
                f"Unexpected sequence item inside plain scalar at line {cursor + 1}: {raw!r}"
            )
        if _split_key_value(cleaned) is not None:
            raise ValueError(
                f"Unexpected mapping entry inside plain scalar at line {cursor + 1}: {raw!r}"
            )
        chunks.append(cleaned)
        cursor += 1

    # Strip trailing blanks before folding
    while chunks and chunks[-1] == "":
        chunks.pop()
    if not chunks:
        return None, cursor

    out_parts: List[str] = []
    blank_run = 0
    for chunk in chunks:
        if chunk == "":
            blank_run += 1
            continue
        if not out_parts:
            out_parts.append(chunk)
        elif blank_run > 0:
            out_parts.append(("\n" * blank_run) + chunk)
        else:
            out_parts.append(" " + chunk)
        blank_run = 0

    return _parse_scalar("".join(out_parts)), cursor


def _parse_value_after_key(
    raw_lines: List[str],
    idx: int,
    parent_indent: int,
    raw_val_after_colon: str,
    stripped_val: str,
) -> Tuple[Any, int]:
    """Parse the value side of 'key: <val>' handling scalars, blocks, quotes, and children."""
    n = len(raw_lines)
    header = _parse_block_header(raw_val_after_colon)
    if header is not None:
        style, chomp, explicit_indent = header
        return _parse_block_scalar(
            raw_lines, idx, parent_indent, style, chomp, explicit_indent
        )

    if stripped_val:
        if stripped_val[0] in ('"', "'") and not _is_quoted_complete(stripped_val):
            return _consume_multiline_quoted(raw_lines, idx, parent_indent, stripped_val)

        parsed = _parse_scalar(stripped_val)
        next_idx = _next_meaningful_idx(raw_lines, idx)
        if next_idx < n:
            next_indent, next_content = _line_indent_and_content(raw_lines[next_idx])
            if next_indent > parent_indent:
                if (
                    isinstance(parsed, str)
                    and stripped_val[0] not in ('"', "'", "[", "{")
                ):
                    return _consume_multiline_plain(raw_lines, idx, parent_indent, stripped_val)
                raise ValueError(
                    f"Unexpected indented content at line {next_idx + 1}: {next_content!r}"
                )
        return parsed, idx

    next_idx = _next_meaningful_idx(raw_lines, idx)
    if next_idx < n:
        next_indent, next_content = _line_indent_and_content(raw_lines[next_idx])
        if next_indent > parent_indent:
            if (
                next_content == "-"
                or next_content.startswith("- ")
                or _split_key_value(next_content) is not None
            ):
                return _parse_block(raw_lines, next_idx, next_indent)
            return _consume_multiline_plain(raw_lines, next_idx, parent_indent, "")
        if next_indent == parent_indent and (
            next_content == "-" or next_content.startswith("- ")
        ):
            return _parse_sequence(raw_lines, next_idx, next_indent)

    return None, idx


def _parse_block(raw_lines: List[str], idx: int, indent: int) -> Tuple[Any, int]:
    """Recursively parse a YAML mapping or sequence block."""
    idx = _next_meaningful_idx(raw_lines, idx)
    if idx >= len(raw_lines):
        return {}, idx

    _, first_content = _line_indent_and_content(raw_lines[idx])
    if first_content == "-" or first_content.startswith("- "):
        return _parse_sequence(raw_lines, idx, indent)
    return _parse_mapping(raw_lines, idx, indent)


def _parse_sequence(
    raw_lines: List[str], idx: int, indent: int
) -> Tuple[List[Any], int]:
    """Parse a YAML sequence starting at idx with expected indentation."""
    items: List[Any] = []
    n = len(raw_lines)
    while idx < n:
        idx = _next_meaningful_idx(raw_lines, idx)
        if idx >= n:
            break
        raw_line = raw_lines[idx]
        line_indent, content = _line_indent_and_content(raw_line)
        if line_indent < indent:
            break
        if line_indent > indent:
            raise ValueError(
                f"Unexpected sequence indentation at line {idx + 1}: {raw_line!r}"
            )
        if not (content == "-" or content.startswith("- ")):
            break

        raw_after_dash = raw_line[line_indent + 1 :].lstrip(" ")
        after_dash = content[1:].strip() if content.startswith("- ") else ""

        if not after_dash:
            idx += 1
            next_idx = _next_meaningful_idx(raw_lines, idx)
            if next_idx < n:
                next_indent, _ = _line_indent_and_content(raw_lines[next_idx])
                if next_indent > line_indent:
                    child, idx = _parse_block(raw_lines, next_idx, next_indent)
                    items.append(child)
                    continue
            items.append(None)
            continue

        header = _parse_block_header(raw_after_dash)
        if header is not None:
            style, chomp, explicit_indent = header
            val, idx = _parse_block_scalar(
                raw_lines, idx + 1, line_indent, style, chomp, explicit_indent
            )
            items.append(val)
            continue

        kv = _split_key_value(after_dash)
        if kv is not None:
            key, val_str = kv
            # Column where key starts so sibling keys in same mapping item align with it
            dash_pos = line_indent
            key_col = len(raw_line) - len(raw_line[dash_pos + 1 :].lstrip(" "))
            raw_kv = _split_key_value(raw_line[key_col:])
            raw_val_after_colon = raw_kv[1] if raw_kv is not None else val_str

            item_dict: Dict[str, Any] = {}
            val, idx = _parse_value_after_key(
                raw_lines, idx + 1, key_col, raw_val_after_colon, val_str
            )
            item_dict[key] = val

            next_idx = _next_meaningful_idx(raw_lines, idx)
            if next_idx < n:
                sub_indent, sub_content = _line_indent_and_content(raw_lines[next_idx])
                if sub_indent == key_col and not (
                    sub_content == "-" or sub_content.startswith("- ")
                ):
                    extra_map, idx = _parse_mapping(raw_lines, next_idx, sub_indent)
                    item_dict.update(extra_map)
                elif sub_indent > line_indent and sub_indent != key_col:
                    raise ValueError(
                        f"Inconsistent indentation in sequence mapping at line {next_idx + 1}: {raw_lines[next_idx]!r}"
                    )
            items.append(item_dict)
            continue

        if after_dash[0] in ('"', "'") and not _is_quoted_complete(after_dash):
            val, idx = _consume_multiline_quoted(raw_lines, idx + 1, line_indent, after_dash)
            items.append(val)
            continue

        items.append(_parse_scalar(after_dash))
        idx += 1

    return items, idx


def _parse_mapping(
    raw_lines: List[str], idx: int, indent: int
) -> Tuple[Dict[str, Any], int]:
    """Parse a YAML mapping starting at idx with expected indentation."""
    mapping: Dict[str, Any] = {}
    n = len(raw_lines)
    while idx < n:
        idx = _next_meaningful_idx(raw_lines, idx)
        if idx >= n:
            break
        raw_line = raw_lines[idx]
        line_indent, content = _line_indent_and_content(raw_line)
        if line_indent < indent:
            break
        if line_indent > indent:
            raise ValueError(
                f"Unexpected indentation at line {idx + 1}: {raw_line!r}"
            )
        if content == "-" or content.startswith("- ") or content == "...":
            break

        kv = _split_key_value(content)
        if kv is None:
            raise ValueError(
                f"Invalid YAML mapping line {idx + 1} (missing ':'): {raw_line!r}"
            )

        key, val_str = kv
        stripped_raw = raw_line[line_indent:]
        # Locate separator colon after the key on raw line to preserve block scalar '# comment'
        colon_pos = len(stripped_raw) - len(val_str) - 1 if val_str else stripped_raw.find(":")
        kv_raw_pos = _split_key_value(stripped_raw)
        if kv_raw_pos is not None:
            raw_val_after_colon = kv_raw_pos[1]
        else:
            raw_val_after_colon = stripped_raw[colon_pos + 1 :].strip() if colon_pos != -1 else ""

        mapping[key], idx = _parse_value_after_key(
            raw_lines, idx + 1, line_indent, raw_val_after_colon, val_str
        )

    return mapping, idx


def _parse_yaml_builtin(text: str) -> Any:
    """Parse YAML text using the strict zero-dependency pure-Python parser."""
    raw_lines = text.splitlines()
    n = len(raw_lines)
    idx = _next_meaningful_idx(raw_lines, 0)
    if idx >= n:
        return {}

    _, first_content = _line_indent_and_content(raw_lines[idx])
    if first_content == "---":
        idx = _next_meaningful_idx(raw_lines, idx + 1)
        if idx >= n:
            return {}
        _, next_content = _line_indent_and_content(raw_lines[idx])
        if next_content == "...":
            idx = _next_meaningful_idx(raw_lines, idx + 1)
            if idx < n:
                raise ValueError(
                    f"Unexpected trailing YAML after '...' at line {idx + 1}: {raw_lines[idx]!r}"
                )
            return {}

    start_indent, first_content = _line_indent_and_content(raw_lines[idx])
    if first_content == "...":
        return {}
    parsed, idx = _parse_block(raw_lines, idx, start_indent)
    idx = _next_meaningful_idx(raw_lines, idx)
    if idx < n:
        _, leftover = _line_indent_and_content(raw_lines[idx])
        if leftover == "...":
            idx = _next_meaningful_idx(raw_lines, idx + 1)
    if idx < n:
        raise ValueError(
            f"Unexpected unparsed YAML content at line {idx + 1}: {raw_lines[idx]!r}"
        )
    return parsed


def parse_yaml(text: str) -> Any:
    """Parse YAML text using PyYAML if available, otherwise strict built-in subset parser."""
    try:
        import yaml  # type: ignore

        try:
            loaded = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML syntax: {exc}") from exc
        return {} if loaded is None else loaded
    except ImportError:
        pass

    return _parse_yaml_builtin(text)


def _format_scalar(value: Any) -> str:
    """Serialize a Python scalar to valid standard YAML syntax."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return ".nan"
        if math.isinf(value):
            return ".inf" if value > 0 else "-.inf"
        return str(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return json.dumps(value.isoformat(), ensure_ascii=False)
    if isinstance(value, str):
        if (
            value == ""
            or value != value.strip()
            or value[0] in "-+.0123456789"
            or any(ch in _SPECIAL_SCALAR_CHARS or ch.isspace() for ch in value)
            or value.lower() in _YAML_RESERVED_BOOL_OR_NULL
        ):
            return json.dumps(value, ensure_ascii=False)
        return value
    return json.dumps(value, ensure_ascii=False)


def _can_emit_block_scalar(value: str) -> bool:
    """Return True when a multiline string can roundtrip cleanly via '|' or '|-'."""
    if "\n" not in value or "\r" in value:
        return False
    if value.endswith("\n\n") or value.strip("\n") == "":
        return False
    body = value[:-1] if value.endswith("\n") else value
    split_lines = body.split("\n")
    if not split_lines or split_lines[0].startswith((" ", "\t")):
        return False
    for line in split_lines:
        if line == "":
            continue
        if line.strip() == "":
            return False
    return True


def _emit_block_scalar_lines(prefix: str, value: str, content_indent: int) -> List[str]:
    """Emit YAML lines for a literal block scalar ('|' or '|-')."""
    indicator = "|" if value.endswith("\n") else "|-"
    body = value[:-1] if value.endswith("\n") else value
    pad = " " * content_indent
    out = [f"{prefix}{indicator}"]
    for line in body.split("\n"):
        out.append("" if line == "" else f"{pad}{line}")
    return out


def _dump_yaml_builtin(data: Any, indent: int = 0) -> str:
    """Serialize nested dicts/lists/scalars into valid standard YAML without PyYAML."""
    pad = " " * indent
    lines: List[str] = []
    if isinstance(data, dict):
        for key, val in data.items():
            key_str = _format_scalar(str(key))
            if isinstance(val, dict):
                if not val:
                    lines.append(f"{pad}{key_str}: {{}}")
                else:
                    lines.append(f"{pad}{key_str}:")
                    lines.append(_dump_yaml_builtin(val, indent + 2))
            elif isinstance(val, list):
                if not val:
                    lines.append(f"{pad}{key_str}: []")
                elif all(
                    not isinstance(item, (dict, list))
                    and not (isinstance(item, str) and "\n" in item)
                    for item in val
                ):
                    rendered = ", ".join(_format_scalar(item) for item in val)
                    lines.append(f"{pad}{key_str}: [{rendered}]")
                else:
                    lines.append(f"{pad}{key_str}:")
                    lines.append(_dump_yaml_builtin(val, indent + 2))
            elif isinstance(val, str) and _can_emit_block_scalar(val):
                lines.extend(_emit_block_scalar_lines(f"{pad}{key_str}: ", val, indent + 2))
            else:
                lines.append(f"{pad}{key_str}: {_format_scalar(val)}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                if not item:
                    lines.append(f"{pad}- {{}}")
                    continue
                items_list = list(item.items())
                first_k, first_v = items_list[0]
                first_k_str = _format_scalar(str(first_k))
                if isinstance(first_v, dict) and first_v:
                    lines.append(f"{pad}- {first_k_str}:")
                    lines.append(_dump_yaml_builtin(first_v, indent + 4))
                elif isinstance(first_v, list) and first_v:
                    if all(
                        not isinstance(x, (dict, list))
                        and not (isinstance(x, str) and "\n" in x)
                        for x in first_v
                    ):
                        rendered = ", ".join(_format_scalar(x) for x in first_v)
                        lines.append(f"{pad}- {first_k_str}: [{rendered}]")
                    else:
                        lines.append(f"{pad}- {first_k_str}:")
                        lines.append(_dump_yaml_builtin(first_v, indent + 4))
                elif isinstance(first_v, str) and _can_emit_block_scalar(first_v):
                    lines.extend(
                        _emit_block_scalar_lines(f"{pad}- {first_k_str}: ", first_v, indent + 4)
                    )
                else:
                    lines.append(f"{pad}- {first_k_str}: {_format_scalar(first_v)}")

                sub_pad = " " * (indent + 2)
                for rest_k, rest_v in items_list[1:]:
                    rest_k_str = _format_scalar(str(rest_k))
                    if isinstance(rest_v, dict):
                        if not rest_v:
                            lines.append(f"{sub_pad}{rest_k_str}: {{}}")
                        else:
                            lines.append(f"{sub_pad}{rest_k_str}:")
                            lines.append(_dump_yaml_builtin(rest_v, indent + 4))
                    elif isinstance(rest_v, list):
                        if not rest_v:
                            lines.append(f"{sub_pad}{rest_k_str}: []")
                        elif all(
                            not isinstance(x, (dict, list))
                            and not (isinstance(x, str) and "\n" in x)
                            for x in rest_v
                        ):
                            rendered = ", ".join(_format_scalar(x) for x in rest_v)
                            lines.append(f"{sub_pad}{rest_k_str}: [{rendered}]")
                        else:
                            lines.append(f"{sub_pad}{rest_k_str}:")
                            lines.append(_dump_yaml_builtin(rest_v, indent + 4))
                    elif isinstance(rest_v, str) and _can_emit_block_scalar(rest_v):
                        lines.extend(
                            _emit_block_scalar_lines(
                                f"{sub_pad}{rest_k_str}: ", rest_v, indent + 4
                            )
                        )
                    else:
                        lines.append(f"{sub_pad}{rest_k_str}: {_format_scalar(rest_v)}")
            elif isinstance(item, list) and item:
                lines.append(f"{pad}-")
                lines.append(_dump_yaml_builtin(item, indent + 2))
            elif isinstance(item, str) and _can_emit_block_scalar(item):
                lines.extend(_emit_block_scalar_lines(f"{pad}- ", item, indent + 2))
            else:
                lines.append(f"{pad}- {_format_scalar(item)}")
    else:
        lines.append(f"{pad}{_format_scalar(data)}")
    return "\n".join(lines)


def dump_yaml(data: Any, indent: int = 0) -> str:
    """Serialize nested dicts/lists/scalars into clean readable standard YAML."""
    try:
        import yaml  # type: ignore

        return yaml.safe_dump(
            data, allow_unicode=True, sort_keys=False, default_flow_style=False
        ).rstrip()
    except ImportError:
        pass

    return _dump_yaml_builtin(data, indent=indent)
