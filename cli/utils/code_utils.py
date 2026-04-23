import logging
import re
import os
from pathlib import Path

log = logging.getLogger(__name__)

MAX_CODE_CHARS = 20_000

def extract_code_blocks(text: str) -> list[str]:
    pattern = re.compile(r"```(?:\w+)?\n([\s\S]*?)```", re.MULTILINE)
    return [m.group(1).strip() for m in pattern.finditer(text)]

def validate_file_path(path: str) -> tuple[bool, str]:
    path = path.strip()
    if not path:
        return False, "Path cannot be empty."
    if ".." in path:
        return False, "Path cannot contain '..' (directory traversal not allowed)."
    try:
        resolved = Path(path).expanduser().resolve()
    except Exception as exc:
        return False, f"Invalid path: {exc}"
    suffix = resolved.suffix.lower()
    allowed = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs",
        ".cpp", ".c", ".h", ".cs", ".rb", ".php", ".swift", ".kt",
        ".html", ".css", ".scss", ".sql", ".sh", ".bash", ".zsh",
        ".yaml", ".yml", ".json", ".toml", ".md", ".txt", ".env",
    }
    if suffix and suffix not in allowed:
        return False, (
            f"File type '{suffix}' is not supported. "
            f"Supported: {', '.join(sorted(allowed))}"
        )

    return True, ""

def read_file_safe(path: str, max_chars: int = MAX_CODE_CHARS) -> tuple[str, str | None]:
    is_valid, err = validate_file_path(path)
    if not is_valid:
        return "", err

    try:
        p = Path(path).expanduser()
        if not p.exists():
            return "", f"File not found: {path}"
        if not p.is_file():
            return "", f"Path is not a file: {path}"

        content = p.read_text(encoding="utf-8", errors="replace")

        if len(content) > max_chars:
            content = content[:max_chars]
            log.warning("File %s truncated to %d chars", path, max_chars)
            content += f"\n# [File truncated at {max_chars} characters]"

        return content, None

    except PermissionError:
        return "", f"Permission denied reading: {path}"
    except OSError as exc:
        return "", f"Could not read file: {exc}"


def write_file_safe(path: str, content: str) -> tuple[bool, str]:
    is_valid, err = validate_file_path(path)
    if not is_valid:
        return False, err

    try:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            backup = p.with_suffix(p.suffix + ".bak")
            p.rename(backup)
            log.info("Backed up %s → %s", p, backup)

        p.write_text(content, encoding="utf-8")
        return True, ""

    except PermissionError:
        return False, f"Permission denied writing: {path}"
    except OSError as exc:
        return False, f"Could not write file: {exc}"
