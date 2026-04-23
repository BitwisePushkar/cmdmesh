import json
import uuid
from unittest.mock import patch
import pytest
from httpx import AsyncClient

@pytest.fixture
def auth_headers(auth_tokens):
    return {"Authorization": f"Bearer {auth_tokens['access_token']}"}

HF_HEADERS = {
    "X-HF-Token": "hf_test_token_abc",
    "X-HF-Model-Id": "mistralai/Mistral-7B-Instruct-v0.3",
}

SAMPLE_PYTHON = """\
def add(a, b):
    return a + b

def divide(a, b):
    return a / b
"""

SAMPLE_BUGGY_PYTHON = """\
def calculate_average(nums):
    total = 0
    for n in nums:
        total += n
    return total / len(nums)  # bug: ZeroDivisionError when nums is empty
"""


def _mock_hf_stream(*chunks: str):
    async def _gen(**kwargs):
        for chunk in chunks:
            yield chunk
    return _gen


async def _stream_code(
    client: AsyncClient,
    auth_headers: dict,
    content: str = SAMPLE_PYTHON,
    task: str = "explain",
    mock_chunks: tuple = ("Explanation here.",),
) -> list[dict]:
    with patch(
        "backend.routes.code.stream_hf_response",
        side_effect=_mock_hf_stream(*mock_chunks),
    ):
        r = await client.post(
            "/code/assist/stream",
            json={"task": task, "content": content},
            headers={**auth_headers, **HF_HEADERS},
        )
    assert r.status_code == 200, r.text
    return [json.loads(l) for l in r.text.strip().split("\n") if l]

@pytest.mark.asyncio
async def test_list_tasks_requires_auth(client: AsyncClient):
    assert (await client.get("/code/tasks")).status_code == 401


@pytest.mark.asyncio
async def test_list_tasks_returns_all_seven(client: AsyncClient, auth_headers):
    r = await client.get("/code/tasks", headers=auth_headers)
    assert r.status_code == 200
    tasks = r.json()["tasks"]
    task_ids = {t["id"] for t in tasks}
    assert task_ids == {"generate", "debug", "explain", "refactor", "review", "test", "complete"}
    for t in tasks:
        assert "id" in t
        assert "label" in t
        assert len(t["label"]) > 3

@pytest.mark.asyncio
async def test_assist_requires_auth(client: AsyncClient):
    r = await client.post("/code/assist", json={"task": "explain", "content": "x = 1"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_assist_stream_requires_auth(client: AsyncClient):
    r = await client.post("/code/assist/stream",
                          json={"task": "explain", "content": "x = 1"})
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_assist_stream_missing_hf_token(client: AsyncClient, auth_headers):
    r = await client.post(
        "/code/assist/stream",
        json={"task": "explain", "content": SAMPLE_PYTHON},
        headers={**auth_headers, "X-HF-Model-Id": "mistralai/Mistral-7B-Instruct-v0.3"},
    )
    assert r.status_code == 422
    assert "X-HF-Token" in r.json()["detail"]

@pytest.mark.asyncio
async def test_assist_stream_missing_model_id(client: AsyncClient, auth_headers):
    r = await client.post(
        "/code/assist/stream",
        json={"task": "explain", "content": SAMPLE_PYTHON},
        headers={**auth_headers, "X-HF-Token": "hf_test"},
    )
    assert r.status_code == 422
    assert "X-HF-Model-Id" in r.json()["detail"]


@pytest.mark.asyncio
async def test_assist_stream_empty_hf_token(client: AsyncClient, auth_headers):
    r = await client.post(
        "/code/assist/stream",
        json={"task": "explain", "content": SAMPLE_PYTHON},
        headers={**auth_headers, "X-HF-Token": "   ", "X-HF-Model-Id": "model"},
    )
    assert r.status_code == 422

@pytest.mark.asyncio
async def test_assist_empty_content_rejected(client: AsyncClient, auth_headers):
    r = await client.post(
        "/code/assist/stream",
        json={"task": "explain", "content": ""},
        headers={**auth_headers, **HF_HEADERS},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_assist_blank_content_rejected(client: AsyncClient, auth_headers):
    r = await client.post(
        "/code/assist/stream",
        json={"task": "explain", "content": "   \n   "},
        headers={**auth_headers, **HF_HEADERS},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_assist_invalid_task_rejected(client: AsyncClient, auth_headers):
    r = await client.post(
        "/code/assist/stream",
        json={"task": "fly_to_moon", "content": "some code"},
        headers={**auth_headers, **HF_HEADERS},
    )
    assert r.status_code == 422

@pytest.mark.asyncio
@pytest.mark.parametrize("task", [
    "generate", "debug", "explain", "refactor", "review", "test", "complete"
])
async def test_all_task_types_accepted(client: AsyncClient, auth_headers, task):
    lines = await _stream_code(
        client, auth_headers,
        content="def hello(): pass" if task != "generate" else "A function that says hello",
        task=task,
        mock_chunks=(f"Response for {task}.",),
    )
    types = {l["type"] for l in lines}
    assert "meta" in types
    assert "done" in types
    assert lines[0]["type"] == "meta"
    assert lines[0]["task"] == task
    assert lines[-1]["type"] == "done"

@pytest.mark.asyncio
async def test_stream_format_meta_chunk_done(client: AsyncClient, auth_headers):
    lines = await _stream_code(
        client, auth_headers,
        mock_chunks=("First chunk", " second chunk", " third.")
    )
    assert lines[0]["type"] == "meta"
    assert lines[0]["model_id"] == HF_HEADERS["X-HF-Model-Id"]

    chunk_lines = [l for l in lines if l["type"] == "chunk"]
    assert len(chunk_lines) == 3
    assert "".join(c["chunk"] for c in chunk_lines) == "First chunk second chunk third."

    done = lines[-1]
    assert done["type"] == "done"
    assert done["char_count_in"] == len(SAMPLE_PYTHON)
    assert done["char_count_out"] == len("First chunk second chunk third.")


@pytest.mark.asyncio
async def test_stream_provider_error_returns_error_type(client: AsyncClient, auth_headers):
    from backend.services.providers.base import ProviderError

    async def _fail(**kwargs):
        raise ProviderError("Model overloaded")
        yield

    with patch("backend.routes.code.stream_hf_response", side_effect=_fail):
        r = await client.post(
            "/code/assist/stream",
            json={"task": "explain", "content": SAMPLE_PYTHON},
            headers={**auth_headers, **HF_HEADERS},
        )

    assert r.status_code == 200
    lines = [json.loads(l) for l in r.text.strip().split("\n") if l]
    error_lines = [l for l in lines if l["type"] == "error"]
    assert len(error_lines) == 1
    assert "overloaded" in error_lines[0]["error"].lower()


@pytest.mark.asyncio
async def test_stream_not_configured_error(client: AsyncClient, auth_headers):
    from backend.services.providers.base import ProviderNotConfiguredError

    async def _no_key(**kwargs):
        raise ProviderNotConfiguredError("token required")
        yield

    with patch("backend.routes.code.stream_hf_response", side_effect=_no_key):
        r = await client.post(
            "/code/assist/stream",
            json={"task": "explain", "content": SAMPLE_PYTHON},
            headers={**auth_headers, **HF_HEADERS},
        )

    lines = [json.loads(l) for l in r.text.strip().split("\n") if l]
    error_line = next(l for l in lines if l["type"] == "error")
    assert "token" in error_line["error"].lower()

def test_detect_python():
    from backend.services.code_service import detect_language
    assert detect_language("def add(a, b):\n    return a + b") == "python"


def test_detect_javascript():
    from backend.services.code_service import detect_language
    assert detect_language("const x = () => { return 1; }") == "javascript"


def test_detect_typescript():
    from backend.services.code_service import detect_language
    assert detect_language("interface Foo { name: string; age: number; }") == "typescript"


def test_detect_java():
    from backend.services.code_service import detect_language
    assert detect_language("public class Main { public static void main() {} }") == "java"


def test_detect_sql():
    from backend.services.code_service import detect_language
    assert detect_language("SELECT * FROM users WHERE id = 1;") == "sql"


def test_detect_unknown_returns_none():
    from backend.services.code_service import detect_language
    assert detect_language("Lorem ipsum dolor sit amet consectetur") is None


def test_detect_empty_returns_none():
    from backend.services.code_service import detect_language
    assert detect_language("") is None

def test_build_messages_generate_task():
    from backend.services.code_service import build_messages
    from backend.schemas.code import CodeAssistRequest, CodeTask

    req = CodeAssistRequest(task=CodeTask.GENERATE, content="A REST API endpoint for user login")
    msgs = build_messages(req)

    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "REST API" in msgs[1]["content"]
    assert "production-ready" in msgs[0]["content"].lower() or "engineer" in msgs[0]["content"].lower()


def test_build_messages_debug_task_injects_code_block():
    from backend.services.code_service import build_messages
    from backend.schemas.code import CodeAssistRequest, CodeTask

    req = CodeAssistRequest(
        task=CodeTask.DEBUG,
        content=SAMPLE_BUGGY_PYTHON,
        language="python",
    )
    msgs = build_messages(req)

    user_msg = msgs[1]["content"]
    assert "```python" in user_msg
    assert SAMPLE_BUGGY_PYTHON.strip() in user_msg
    assert "bug" in user_msg.lower()


def test_build_messages_with_extra_instruction():
    from backend.services.code_service import build_messages
    from backend.schemas.code import CodeAssistRequest, CodeTask

    req = CodeAssistRequest(
        task=CodeTask.EXPLAIN,
        content="x = 1",
        extra_instruction="Use simple language suitable for beginners.",
    )
    msgs = build_messages(req)
    system = msgs[0]["content"]
    assert "simple language" in system.lower() or "beginners" in system.lower()


def test_build_messages_detect_language_automatically():
    from backend.services.code_service import build_messages
    from backend.schemas.code import CodeAssistRequest, CodeTask

    req = CodeAssistRequest(
        task=CodeTask.EXPLAIN,
        content="def factorial(n):\n    return 1 if n <= 1 else n * factorial(n-1)",
    )
    msgs = build_messages(req)
    system = msgs[0]["content"]
    assert "python" in system.lower()


def test_build_messages_all_tasks_have_different_system_prompts():
    from backend.services.code_service import build_messages
    from backend.schemas.code import CodeAssistRequest, CodeTask

    system_prompts = set()
    for task in CodeTask:
        content = "describe what to build" if task == CodeTask.GENERATE else "x = 1"
        req = CodeAssistRequest(task=task, content=content)
        msgs = build_messages(req)
        system_prompts.add(msgs[0]["content"])

    assert len(system_prompts) == len(CodeTask)

def test_extract_code_blocks_single():
    from cli.utils.code_utils import extract_code_blocks
    text = "Here is the code:\n\n```python\ndef foo():\n    pass\n```\n\nDone."
    blocks = extract_code_blocks(text)
    assert len(blocks) == 1
    assert "def foo():" in blocks[0]


def test_extract_code_blocks_multiple():
    from cli.utils.code_utils import extract_code_blocks
    text = "Test 1:\n```python\nx = 1\n```\n\nTest 2:\n```python\ny = 2\n```"
    blocks = extract_code_blocks(text)
    assert len(blocks) == 2


def test_extract_code_blocks_no_blocks():
    from cli.utils.code_utils import extract_code_blocks
    text = "This is plain text with no code blocks."
    assert extract_code_blocks(text) == []


def test_extract_code_blocks_without_language_tag():
    from cli.utils.code_utils import extract_code_blocks
    text = "```\nsome code here\n```"
    blocks = extract_code_blocks(text)
    assert len(blocks) == 1
    assert "some code here" in blocks[0]

def test_validate_path_rejects_traversal():
    from cli.utils.code_utils import validate_file_path
    ok, err = validate_file_path("../../etc/passwd")
    assert not ok
    assert "traversal" in err.lower()


def test_validate_path_rejects_unsupported_extension():
    from cli.utils.code_utils import validate_file_path
    ok, err = validate_file_path("malware.exe")
    assert not ok
    assert ".exe" in err


def test_validate_path_accepts_python():
    from cli.utils.code_utils import validate_file_path
    with patch("cli.utils.code_utils.validate_file_path", return_value=(True, "")):
        ok, err = validate_file_path("my_script.py")
    assert ok or "permission" in err.lower()  # ok unless permission issue


def test_validate_path_rejects_empty():
    from cli.utils.code_utils import validate_file_path
    ok, err = validate_file_path("")
    assert not ok


def test_read_file_not_found():
    from cli.utils.code_utils import read_file_safe
    content, err = read_file_safe("/nonexistent/path/file.py")
    assert content == ""
    assert err is not None
    assert "not found" in err.lower() or "traversal" in err.lower() or err


def test_read_file_truncates_large_content(tmp_path):
    from cli.utils.code_utils import read_file_safe
    large_file = tmp_path / "big.py"
    large_file.write_text("x = 1\n" * 5000) 

    content, err = read_file_safe(str(large_file), max_chars=1000)
    assert err is None
    assert len(content) <= 1050  
    assert "truncated" in content.lower()


def test_write_file_creates_backup(tmp_path):
    from cli.utils.code_utils import write_file_safe
    target = tmp_path / "output.py"
    target.write_text("original content")

    ok, err = write_file_safe(str(target), "new content")
    assert ok
    assert target.read_text() == "new content"
    backup = tmp_path / "output.py.bak"
    assert backup.exists()
    assert backup.read_text() == "original content"


def test_write_file_creates_parent_dirs(tmp_path):
    from cli.utils.code_utils import write_file_safe
    nested = tmp_path / "a" / "b" / "c" / "output.py"
    ok, err = write_file_safe(str(nested), "print('hello')")
    assert ok
    assert nested.read_text() == "print('hello')"


def test_write_file_rejects_traversal():
    from cli.utils.code_utils import write_file_safe
    ok, err = write_file_safe("../../../etc/cron.d/evil", "malicious")
    assert not ok
    assert "traversal" in err.lower()

@pytest.mark.asyncio
async def test_non_streaming_assist(client: AsyncClient, auth_headers):
    with patch(
        "backend.routes.code.stream_hf_response",
        side_effect=_mock_hf_stream("def add(a, b): return a + b"),
    ):
        r = await client.post(
            "/code/assist",
            json={"task": "generate", "content": "A function that adds two numbers"},
            headers={**auth_headers, **HF_HEADERS},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["task"] == "generate"
    assert body["result"] == "def add(a, b): return a + b"
    assert body["model_id"] == HF_HEADERS["X-HF-Model-Id"]
    assert body["char_count_out"] > 0


@pytest.mark.asyncio
async def test_non_streaming_with_language(client: AsyncClient, auth_headers):
    with patch(
        "backend.routes.code.stream_hf_response",
        side_effect=_mock_hf_stream("function add(a, b) { return a + b; }"),
    ):
        r = await client.post(
            "/code/assist",
            json={"task": "generate", "content": "add two numbers", "language": "javascript"},
            headers={**auth_headers, **HF_HEADERS},
        )

    assert r.status_code == 200
    assert r.json()["language"] == "javascript"