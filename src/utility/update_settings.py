import json
import re
from pathlib import Path


def apply_settings(config: dict, new_config: dict, logger, pid) -> None:
    config.update(new_config)
    logger.output_dir = Path(config.get("log_dir", "data"))
    logger.filename_prefix = config.get("log_prefix", "nsim_log")
    logger.output_dir.mkdir(parents=True, exist_ok=True)
    pid.update_params(config)


# Matches any JSON scalar value (string, bool, null, or number) so only the
# value token after a key is rewritten — comments and formatting are untouched.
_VALUE_TOKEN = r'"(?:[^"\\]|\\.)*"|true|false|null|-?\d+(?:\.\d+)?'

_OPENERS = {"[": "]", "{": "}"}


def _find_container_end(text: str, start: int) -> int:
    """Index just past the balanced ``[...]``/``{...}`` beginning at ``start``.

    Brackets inside string literals are ignored, so a Windows path or a COM
    port containing a bracket can't throw off the scan. Returns -1 if the
    container never closes.
    """
    closer = _OPENERS.get(text[start])
    if closer is None:
        return -1
    depth = 0
    i, n = start, len(text)
    in_string = escape = False
    while i < n:
        c = text[i]
        if in_string:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
        elif c in _OPENERS:
            depth += 1
        elif c in ("]", "}"):
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def _replace_container(text: str, key: str, value) -> tuple:
    """Rewrite a whole array/object value in place. Returns (text, replaced)."""
    m = re.search(rf'"{re.escape(key)}"\s*:\s*', text)
    if not m or m.end() >= len(text) or text[m.end()] not in _OPENERS:
        return text, False
    end = _find_container_end(text, m.end())
    if end == -1:
        return text, False
    # Indent the re-serialised block to sit under the key's own indentation.
    line_start = text.rfind("\n", 0, m.start()) + 1
    indent = text[line_start:m.start()]
    body = json.dumps(value, indent=2, ensure_ascii=False).replace("\n", "\n" + indent)
    return text[:m.start()] + f'"{key}": ' + body + text[end:], True


def save_config_to_file(settings: dict, dest_path, template_path=None) -> None:
    """Write ``settings`` into a config.json on disk, preserving the file's
    comments and formatting.

    Each key already present has only its value rewritten in place; keys not yet
    present are appended before the closing brace. ``template_path`` is the file
    whose text/comments are used as the basis (defaults to ``dest_path``) — this
    lets a packaged build read the bundled defaults but write an editable copy
    next to the executable.
    """
    template = Path(template_path) if template_path else Path(dest_path)
    text = template.read_text(encoding="utf-8") if template.exists() else "{\n}\n"

    missing = {}
    for key, value in settings.items():
        if isinstance(value, (list, dict)):
            # Nested values (the `devices` array) need a balanced-bracket scan;
            # the scalar regex below can't match across lines.
            text, replaced = _replace_container(text, key, value)
            if not replaced:
                missing[key] = json.dumps(value, indent=2, ensure_ascii=False
                                          ).replace("\n", "\n  ")
            continue
        formatted = json.dumps(value)
        pattern = rf'("{re.escape(key)}"\s*:\s*)(?:{_VALUE_TOKEN})'
        # Function replacement avoids backreference issues when the new value
        # contains backslashes (e.g. a Windows path).
        text, n = re.subn(pattern, lambda m: m.group(1) + formatted, text, count=1)
        if not n:
            missing[key] = formatted

    if missing:
        insert_at = text.rfind("}")
        head = text[:insert_at].rstrip()
        if not head.endswith("{") and not head.endswith(","):
            head += ","
        added = ",".join(f'\n  "{k}": {v}' for k, v in missing.items())
        text = head + added + "\n" + text[insert_at:]

    Path(dest_path).write_text(text, encoding="utf-8")
