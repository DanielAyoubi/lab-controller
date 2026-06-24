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
