import sys
from typing import Optional
import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from cli.utils.auth_helpers import _require_login, _prompt_hf_setup
from backend.schemas.code import TASK_LABELS, CodeTask
from cli.auth import client as api
from cli.auth.client import APIError
from cli.utils.code_utils import extract_code_blocks, read_file_safe, write_file_safe
from cli.utils.display import (
    console,
    err_console,
    print_error,
    print_info,
    print_success,
    print_warning,
)

app = typer.Typer(help="Code assistant commands")


def run_code_mode() -> None:
    _require_login()
    console.print()
    console.print(Panel(
        "[bold cyan]Code Assistant[/bold cyan]\n"
        "AI-powered coding, debugging, and refactoring.\n\n"
        "[dim]Commands: /exit to quit[/dim]",
        border_style="cyan",
        padding=(0, 2),
    ))
    console.print()

    hf_token, model_id, model_label = _prompt_hf_setup()
    _code_loop(hf_token=hf_token, model_id=model_id, model_label=model_label)


def _code_loop(*, hf_token: str, model_id: str, model_label: str) -> None:
    pt_session: PromptSession = PromptSession(
        style=Style.from_dict({"prompt": "bold ansicyan"})
    )

    while True:
        console.print()
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        table.add_column("Task", style="bold cyan")
        table.add_column("Description")
        
        tasks = list(CodeTask)
        for idx, task in enumerate(tasks, 1):
            table.add_row(str(idx), TASK_LABELS[task])
            
        console.print(table)
        
        try:
            raw = pt_session.prompt(
                HTML("\n<prompt>Select task (1-7)</prompt> <ansigray>›</ansigray> ")
            ).strip()
        except (KeyboardInterrupt, EOFError):
            print_success("Exiting code assistant.")
            break

        if not raw or raw.lower() in ("/exit", "/quit"):
            print_success("Exiting code assistant.")
            break

        if not raw.isdigit() or not (1 <= int(raw) <= len(tasks)):
            print_warning("Invalid selection.")
            continue

        selected_task = tasks[int(raw) - 1]

        if selected_task == CodeTask.GENERATE:
            try:
                content = pt_session.prompt(
                    HTML(f"\n<prompt>Describe what to build</prompt> <ansigray>›</ansigray> ")
                ).strip()
            except (KeyboardInterrupt, EOFError):
                continue
                
            if not content:
                continue
            language = None
            
        else:
            try:
                filepath = pt_session.prompt(
                    HTML(f"\n<prompt>File to {selected_task.value}</prompt> <ansigray>›</ansigray> ")
                ).strip()
            except (KeyboardInterrupt, EOFError):
                continue
                
            if not filepath:
                continue
                
            content, err = read_file_safe(filepath)
            if err:
                print_error(err)
                continue
            language = None
            print_success(f"Loaded {filepath} ({len(content)} chars)")

        _handle_code_assist(
            content=content,
            task=selected_task,
            language=language,
            hf_token=hf_token,
            model_id=model_id,
            model_label=model_label,
            pt_session=pt_session,
        )


def _handle_code_assist(
    *,
    content: str,
    task: CodeTask,
    language: str | None,
    hf_token: str,
    model_id: str,
    model_label: str,
    pt_session: PromptSession,
) -> None:
    console.print()
    extra_headers = {
        "X-HF-Token": hf_token,
        "X-HF-Model-Id": model_id,
    }
    
    full_response = ""
    answer_started = False
    
    try:
        for data in api.stream_code_assist(
            content=content,
            task=task.value,
            language=language,
            extra_headers=extra_headers,
        ):
            msg_type = data.get("type")

            if msg_type == "meta":
                continue 

            elif msg_type == "chunk":
                if not answer_started:
                    console.print(f"[bold dim]{model_label}[/bold dim] ›\n")
                    answer_started = True
                
                chunk_text = data.get("chunk", "")
                full_response += chunk_text
                print(chunk_text, end="", flush=True)

            elif msg_type == "done":
                if answer_started:
                    print("\n")
                break

            elif msg_type == "error":
                if answer_started:
                    print()
                print_error(data.get("error", "Unknown error"))
                return

    except APIError as e:
        if answer_started:
            print()
        print_error(f"API Error: {e.detail}")
        return
    except Exception as e:
        if answer_started:
            print()
        print_error(f"Unexpected error: {e}")
        return

    blocks = extract_code_blocks(full_response)
    if not blocks:
        return
        
    console.print(f"[dim]Found {len(blocks)} code block(s).[/dim]")
    try:
        ans = pt_session.prompt(
            HTML("<prompt>Save extracted code to file? (y/N)</prompt> <ansigray>›</ansigray> ")
        ).strip().lower()
    except (KeyboardInterrupt, EOFError):
        return
        
    if ans in ("y", "yes"):
        try:
            save_path = pt_session.prompt(
                HTML("<prompt>Path to save</prompt> <ansigray>›</ansigray> ")
            ).strip()
        except (KeyboardInterrupt, EOFError):
            return
            
        if not save_path:
            print_warning("No path provided.")
            return
            
        combined = "\n\n".join(blocks)
        success, err = write_file_safe(save_path, combined)
        if success:
            print_success(f"Saved to {save_path}")
        else:
            print_error(f"Failed to save: {err}")