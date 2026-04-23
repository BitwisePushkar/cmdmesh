import logging
import re
from backend.schemas.code import (
    MAX_CODE_CHARS,
    CodeAssistRequest,
    CodeTask,
    TASK_SYSTEM_PROMPTS,
)

log = logging.getLogger(__name__)

_LANG_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("python",     re.compile(r"\bdef\s+\w+\s*\(|import\s+\w+|from\s+\w+\s+import")),
    ("typescript", re.compile(r":\s*(string|number|boolean|void|any)\b|interface\s+\w+|<T>")),
    ("javascript", re.compile(r"const\s+\w+\s*=|function\s+\w+\s*\(|=>\s*\{|require\(")),
    ("java",       re.compile(r"public\s+(class|static|void)\s+\w+|System\.out\.print")),
    ("rust",       re.compile(r"\bfn\s+\w+\s*\(|let\s+mut\s+\w+|impl\s+\w+")),
    ("go",         re.compile(r"\bfunc\s+\w+\s*\(|:=\s*|package\s+main")),
    ("cpp",        re.compile(r"#include\s*<|std::|cout\s*<<")),
    ("c",          re.compile(r"#include\s*<stdio\.h>|printf\s*\(")),
    ("sql",        re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE TABLE)\b", re.IGNORECASE)),
    ("html",       re.compile(r"<html|<div|<body|<!DOCTYPE", re.IGNORECASE)),
    ("css",        re.compile(r"\{[\s\S]*?:\s*[\s\S]*?;|@media\s*\(")),
    ("bash",       re.compile(r"#!/bin/(bash|sh)|echo\s+|grep\s+|awk\s+")),
    ("yaml",       re.compile(r"^---\s*$|^\s*\w+:\s*$", re.MULTILINE)),
    ("json",       re.compile(r'^\s*\{[\s\S]*"[\w]+":\s*', re.MULTILINE)),
]

def detect_language(code: str) -> str | None:
    sample = code[:3000]  
    for lang, pattern in _LANG_PATTERNS:
        if pattern.search(sample):
            return lang
    return None

def _build_code_block(code: str, language: str | None) -> str:
    lang_hint = language or ""
    return f"```{lang_hint}\n{code.rstrip()}\n```"


def build_messages(req: CodeAssistRequest) -> list[dict]:
    language = req.language
    if not language and req.task != CodeTask.GENERATE:
        language = detect_language(req.content)

    system_parts = [TASK_SYSTEM_PROMPTS[req.task]]

    if language:
        system_parts.append(f"The code is written in {language}.")

    if req.extra_instruction:
        system_parts.append(f"Additional instruction: {req.extra_instruction.strip()}")

    system_content = "\n".join(system_parts)
    if req.task == CodeTask.GENERATE:
        user_content = (
            f"Please write the following:\n\n{req.content.strip()}"
        )
        if language:
            user_content += f"\n\nWrite it in {language}."
    else:
        code_block = _build_code_block(req.content, language)
        action = _task_action_phrase(req.task)
        user_content = f"Here is the code:\n\n{code_block}\n\n{action}"

    return [
        {"role": "system", "content": system_content},
        {"role": "user",   "content": user_content},
    ]

def _task_action_phrase(task: CodeTask) -> str:
    return {
        CodeTask.DEBUG:    "Please find and fix all bugs.",
        CodeTask.EXPLAIN:  "Please explain this code step by step.",
        CodeTask.REFACTOR: "Please refactor this code.",
        CodeTask.REVIEW:   "Please review this code thoroughly.",
        CodeTask.TEST:     "Please write comprehensive unit tests for this.",
        CodeTask.COMPLETE: "Please complete this code.",
    }.get(task, "Please assist with this code.")