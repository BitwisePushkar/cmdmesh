import getpass
import json
from typing import Optional
import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from cli.auth import client as api
from cli.auth.client import APIError
from cli.auth.store import CredentialStore
from cli.utils.display import (console, err_console, print_error, print_info,
print_success, print_warning,)

app = typer.Typer(help="Search and URL context commands")

HF_MODELS = [
    {"id": "meta-llama/Llama-3.1-8B-Instruct",       "label": "Llama 3.1 8B Instruct"},
    {"id": "meta-llama/Llama-3.2-1B-Instruct",       "label": "Llama 3.2 1B Instruct"},
    {"id": "HuggingFaceH4/zephyr-7b-beta",            "label": "Zephyr 7B Beta"},
    {"id": "google/gemma-2-2b-it",                    "label": "Gemma 2 2B IT"},
]

def run_search_mode() -> None:
    _require_login()
    console.print()
    console.print(Panel(
        "[bold cyan]Search mode[/bold cyan]\n"
        "Search the web and ask AI questions about the results.\n\n"
        "[dim]Commands: /exit to quit · /url to switch to URL mode[/dim]",
        border_style="cyan",
        padding=(0, 2),
    ))
    console.print()

    hf_token, model_id, model_label = _prompt_hf_setup()
    _search_loop(hf_token=hf_token, model_id=model_id, model_label=model_label)

def _search_loop(*, hf_token: str, model_id: str, model_label: str) -> None:
    pt_session: PromptSession = PromptSession(
        style=Style.from_dict({"prompt": "bold ansicyan"})
    )

    console.print(
        f"[dim]Model: [cyan]{model_label}[/cyan] · "
        "Type a search query. /ai to toggle AI answers. /exit to quit.[/dim]\n"
    )

    ai_mode = True 

    while True:
        try:
            raw = pt_session.prompt(
                HTML("<prompt>Search</prompt> <ansigray>›</ansigray> ")
            ).strip()
        except (KeyboardInterrupt, EOFError):
            print_success("Exiting search mode.")
            break

        if not raw:
            continue

        if raw.lower() in ("/exit", "/quit"):
            print_success("Exiting search mode.")
            break

        if raw.lower() == "/ai":
            ai_mode = not ai_mode
            state = "ON" if ai_mode else "OFF"
            print_info(f"AI answers turned {state}.")
            continue

        if raw.lower().startswith("/url"):
            url = raw[4:].strip()
            if not url:
                try:
                    url = pt_session.prompt(
                        HTML("  <ansigray>URL ›</ansigray> ")
                    ).strip()
                except (KeyboardInterrupt, EOFError):
                    continue
            if url:
                _handle_url_query(
                    url=url,
                    hf_token=hf_token,
                    model_id=model_id,
                    model_label=model_label,
                )
            continue

        if " :: " in raw:
            query, ai_question = raw.split(" :: ", 1)
        else:
            query = raw
            ai_question = raw if ai_mode else None

        _handle_search_query(
            query=query.strip(),
            ai_question=ai_question,
            hf_token=hf_token,
            model_id=model_id,
            model_label=model_label,
        )


def _handle_search_query(
    *,
    query: str,
    ai_question: str | None,
    hf_token: str,
    model_id: str,
    model_label: str,
) -> None:
    console.print()

    if ai_question:
        extra_headers = {
            "X-HF-Token": hf_token,
            "X-HF-Model-Id": model_id,
        }
        try:
            results_shown = False
            answer_started = False

            for data in api.stream_search(
                query=query,
                ai_question=ai_question,
                extra_headers=extra_headers,
            ):
                msg_type = data.get("type")

                if msg_type == "results":
                    results_shown = True
                    _display_search_results(data.get("data", []), query)

                elif msg_type == "chunk":
                    if not answer_started:
                        console.print(f"\n[bold dim]{model_label}[/bold dim] ›", end=" ")
                        answer_started = True
                    print(data.get("chunk", ""), end="", flush=True)

                elif msg_type == "done":
                    if answer_started:
                        print()
                    break

                elif msg_type == "error":
                    print_error(f"\n{data.get('error', 'Unknown error')}")
                    break

        except APIError as exc:
            print_error(f"Search failed: {exc.detail}")

    else:
        with console.status("Searching…"):
            try:
                result = api.search_query(query=query, max_results=5)
            except APIError as exc:
                print_error(f"Search failed: {exc.detail}")
                return

        _display_search_results(result.get("results", []), query)

    console.print()

def run_url_mode() -> None:
    _require_login()
    console.print()
    console.print(Panel(
        "[bold cyan]URL context mode[/bold cyan]\n"
        "Paste a URL — the AI reads it and answers your questions.\n\n"
        "[dim]Commands: /exit to quit · /search to switch to search mode[/dim]",
        border_style="cyan",
        padding=(0, 2),
    ))
    console.print()

    hf_token, model_id, model_label = _prompt_hf_setup()
    _url_loop(hf_token=hf_token, model_id=model_id, model_label=model_label)


def _url_loop(*, hf_token: str, model_id: str, model_label: str) -> None:
    pt_session: PromptSession = PromptSession(
        style=Style.from_dict({"prompt": "bold ansicyan"})
    )

    console.print(
        f"[dim]Model: [cyan]{model_label}[/cyan] · "
        "Paste a URL then ask a question. /exit to quit.[/dim]\n"
    )

    while True:
        try:
            raw = pt_session.prompt(
                HTML("<prompt>URL</prompt> <ansigray>›</ansigray> ")
            ).strip()
        except (KeyboardInterrupt, EOFError):
            print_success("Exiting URL context mode.")
            break

        if not raw:
            continue

        if raw.lower() in ("/exit", "/quit"):
            print_success("Exiting URL context mode.")
            break

        if raw.lower().startswith("/search"):
            q = raw[7:].strip()
            if not q:
                try:
                    q = pt_session.prompt(
                        HTML("  <ansigray>Search query ›</ansigray> ")
                    ).strip()
                except (KeyboardInterrupt, EOFError):
                    continue
            if q:
                _handle_search_query(
                    query=q,
                    ai_question=q,
                    hf_token=hf_token,
                    model_id=model_id,
                    model_label=model_label,
                )
            continue

        if " :: " in raw:
            url, ai_question = raw.split(" :: ", 1)
            url = url.strip()
            ai_question = ai_question.strip()
        else:
            url = raw
            try:
                ai_question = pt_session.prompt(
                    HTML("<prompt>Question</prompt> <ansigray>›</ansigray> ")
                ).strip()
            except (KeyboardInterrupt, EOFError):
                continue
            if not ai_question:
                ai_question = "Summarise the key points of this page."

        _handle_url_query(
            url=url,
            ai_question=ai_question,
            hf_token=hf_token,
            model_id=model_id,
            model_label=model_label,
        )


def _handle_url_query(
    *,
    url: str,
    hf_token: str,
    model_id: str,
    model_label: str,
    ai_question: str = "Summarise the key points of this page.",
) -> None:
    console.print()

    extra_headers = {
        "X-HF-Token": hf_token,
        "X-HF-Model-Id": model_id,
    }

    try:
        meta_shown = False
        answer_started = False

        for data in api.stream_url_context(
            url=url,
            ai_question=ai_question,
            extra_headers=extra_headers,
        ):
            msg_type = data.get("type")

            if msg_type == "meta":
                meta_shown = True
                title = data.get("title") or url
                char_count = data.get("char_count", 0)
                warnings = data.get("warnings", [])
                console.print(
                    f"[dim]Fetched: [bold]{title}[/bold] "
                    f"({char_count:,} chars extracted)[/dim]"
                )
                for w in warnings:
                    print_warning(w)
                console.print()

            elif msg_type == "chunk":
                if not answer_started:
                    console.print(f"[bold dim]{model_label}[/bold dim] ›", end=" ")
                    answer_started = True
                print(data.get("chunk", ""), end="", flush=True)

            elif msg_type == "done":
                if answer_started:
                    print()
                break

            elif msg_type == "error":
                print_error(f"\n{data.get('error', 'Unknown error')}")
                break

    except APIError as exc:
        print_error(f"URL context failed: {exc.detail}")

    console.print()

@app.command()
def search_cmd(
    query: str = typer.Argument(..., help="Search query"),
    results: int = typer.Option(5, "--results", "-n", help="Number of results"),
    ask: str = typer.Option(None, "--ask", "-a", help="Ask AI a question about results"),
) -> None:
    _require_login()

    if ask:
        hf_token, model_id, model_label = _prompt_hf_setup()
        _handle_search_query(
            query=query,
            ai_question=ask,
            hf_token=hf_token,
            model_id=model_id,
            model_label=model_label,
        )
    else:
        with console.status(f"Searching for: {query}…"):
            try:
                result = api.search_query(query=query, max_results=results)
            except APIError as exc:
                print_error(f"Search failed: {exc.detail}")
                raise typer.Exit(1)

        _display_search_results(result.get("results", []), query)


@app.command()
def url_cmd(
    url: str = typer.Argument(..., help="URL to fetch and analyse"),
    ask: str = typer.Option(
        "Summarise the key points of this page.",
        "--ask", "-a",
        help="Question to ask about the page",
    ),
) -> None:
    _require_login()
    hf_token, model_id, model_label = _prompt_hf_setup()
    _handle_url_query(
        url=url,
        ai_question=ask,
        hf_token=hf_token,
        model_id=model_id,
        model_label=model_label,
    )

def _display_search_results(results: list[dict], query: str) -> None:
    if not results:
        print_warning(f"No results found for: {query}")
        return

    console.print(f"[bold]Search results for:[/bold] [cyan]{query}[/cyan]\n")
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1), expand=True)
    table.add_column("#",       style="bold cyan", width=3)
    table.add_column("Result",  no_wrap=False)

    for r in results:
        pos = r.get("position", "?")
        title = r.get("title", "Untitled")
        url = r.get("url", "")
        snippet = r.get("snippet", "")
        cell = f"[bold]{title}[/bold]\n[dim]{url}[/dim]"
        if snippet:
            cell += f"\n{snippet}"
        table.add_row(str(pos), cell)

    console.print(table)

def _prompt_hf_setup() -> tuple[str, str, str]:
    console.print("[bold]Choose an AI model:[/bold]\n")
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Key", style="bold cyan", width=4)
    table.add_column("Model", style="bold")
    for i, m in enumerate(HF_MODELS, 1):
        table.add_row(str(i), m["label"])
    console.print(table)

    choice = _prompt_choice("Select model", valid={str(i) for i in range(1, len(HF_MODELS) + 1)})
    selected = HF_MODELS[int(choice) - 1]

    console.print()
    console.print(
        "[dim]Enter your HuggingFace token "
        "([cyan]https://huggingface.co/settings/tokens[/cyan]).[/dim]\n"
        "[dim]Token is used for this session only and never stored.[/dim]\n"
    )
    hf_token = getpass.getpass("  HuggingFace token (hf_...): ")
    if not hf_token.strip():
        print_error("HuggingFace token is required.")
        raise typer.Exit(1)
    if not hf_token.strip().startswith("hf_"):
        print_warning("Token doesn't start with 'hf_' — double-check it's correct.")

    console.print()
    return hf_token.strip(), selected["id"], selected["label"]

def _require_login() -> None:
    if not CredentialStore.is_logged_in():
        print_error("Not logged in. Run `cmdmesh login` first.")
        raise typer.Exit(1)

def _prompt_choice(prompt: str, valid: set[str]) -> str:
    while True:
        val = input(f"  {prompt} [{'/'.join(sorted(valid))}]: ").strip()
        if val in valid:
            return val
        err_console.print(f"[red]Enter one of: {', '.join(sorted(valid))}[/red]")