from enum import Enum
from pydantic import BaseModel, Field, field_validator

class CodeTask(str, Enum):
    GENERATE  = "generate"   
    DEBUG     = "debug"      
    EXPLAIN   = "explain"    
    REFACTOR  = "refactor"   
    REVIEW    = "review"     
    TEST      = "test"       
    COMPLETE  = "complete"  

MAX_CODE_CHARS = 20_000
MAX_DESC_CHARS = 2_000

TASK_SYSTEM_PROMPTS: dict[CodeTask, str] = {
    CodeTask.GENERATE: (
        "You are an expert software engineer. "
        "The user will describe what they want built. "
        "Write clean, well-commented, production-ready code. "
        "Include brief inline comments for non-obvious logic. "
        "Output ONLY the code — no introductory sentences, no markdown fences."
    ),
    CodeTask.DEBUG: (
        "You are an expert debugger. "
        "The user will provide code that has bugs or unexpected behaviour. "
        "Identify ALL bugs, explain each one clearly, and provide the corrected code. "
        "Format your response as:\n"
        "BUGS FOUND:\n1. [description]\n2. [description]\n\n"
        "FIXED CODE:\n[corrected code]\n\n"
        "EXPLANATION:\n[why each fix works]"
    ),
    CodeTask.EXPLAIN: (
        "You are a senior developer explaining code to a junior developer. "
        "The user will provide code. Explain what it does step by step. "
        "Be clear about: what the code does overall, how each section works, "
        "any patterns or idioms used, and potential gotchas or edge cases."
    ),
    CodeTask.REFACTOR: (
        "You are an expert in clean code and software design. "
        "The user will provide code to refactor. "
        "Improve it for: readability, maintainability, performance, and best practices. "
        "Output the refactored code followed by a brief summary of changes made."
    ),
    CodeTask.REVIEW: (
        "You are a thorough code reviewer. "
        "The user will provide code for review. "
        "Provide feedback on: correctness, security vulnerabilities, performance issues, "
        "code style, error handling, and missing edge cases. "
        "Be constructive and specific. Rate severity as [HIGH/MEDIUM/LOW] for each issue."
    ),
    CodeTask.TEST: (
        "You are an expert in test-driven development. "
        "The user will provide code. Write comprehensive unit tests for it. "
        "Cover: happy paths, edge cases, error conditions, and boundary values. "
        "Use appropriate testing framework for the language detected. "
        "Output ONLY the test code with brief comments explaining each test."
    ),
    CodeTask.COMPLETE: (
        "You are an expert developer. "
        "The user will provide incomplete or stub code. "
        "Complete it following the existing patterns, style, and conventions. "
        "Output ONLY the complete code — no explanations unless the code has unusual choices."
    ),
}

TASK_LABELS: dict[CodeTask, str] = {
    CodeTask.GENERATE:  "Generate code from description",
    CodeTask.DEBUG:     "Find and fix bugs",
    CodeTask.EXPLAIN:   "Explain what this code does",
    CodeTask.REFACTOR:  "Refactor / improve code quality",
    CodeTask.REVIEW:    "Full code review with feedback",
    CodeTask.TEST:      "Write unit tests for this code",
    CodeTask.COMPLETE:  "Complete partial / stub code",
}

class CodeAssistRequest(BaseModel):
    task: CodeTask
    content: str = Field(min_length=1, max_length=MAX_CODE_CHARS)
    language: str | None = Field(default=None, max_length=40)
    extra_instruction: str | None = Field(default=None, max_length=500)
    session_id: str | None = Field(default=None)

    @field_validator("content")
    @classmethod
    def content_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Content cannot be blank.")
        return v

    @field_validator("language")
    @classmethod
    def language_clean(cls, v: str | None) -> str | None:
        if v:
            import re
            v = re.sub(r"[^\w\-]", "", v).strip().lower()
            return v or None
        return None

class CodeAssistResponse(BaseModel):
    task: CodeTask
    language: str | None
    result: str 
    model_id: str
    char_count_in: int 
    char_count_out: int  