from typing import Optional
import typer
from cli.commands.search import run_search_mode, run_url_mode
import getpass
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
from cli.utils.display import (console, err_console, print_error,
 print_info, print_success, print_warning,)

app = typer.Typer(help="AI chat commands")

HF_MODELS = [
    {
        "id":    "meta-llama/Llama-3.1-8B-Instruct",
        "label": "Llama 3.1 8B Instruct",
        "note":  "Meta's highly reliable 8B model — (Gated access required)",
    },
    {
        "id":    "meta-llama/Llama-3.2-1B-Instruct",
        "label": "Llama 3.2 1B Instruct",
        "note":  "Meta's smallest model — Extremely fast and stable",
    },
    {
        "id":    "HuggingFaceH4/zephyr-7b-beta",
        "label": "Zephyr 7B Beta",
        "note":  "A classic stable model — (No gated access required)",
    },
    {
        "id":    "google/gemma-2-2b-it",
        "label": "Gemma 2 2B IT",
        "note":  "Google's smallest Gemma — very well supported",
    },
]

MODES = {
    "1": "Chat with AI",
    "2": "Web Search (AI summary)",
    "3": "URL Context (AI summary)",
    "4": "Code runner (coming soon)",
}

SLASH_HELP = {
    "/exit  or /quit": "End session and return to terminal",
    "/clear":           "Clear conversation context (history preserved in DB)",
    "/history":         "Show this session's messages",
    "/sessions":        "List your past sessions",
    "/model":           "Show current model info",
    "/help":            "Show this help",
}

@app.command()
def wakeup() -> None:
    _require_login()
    console.print()
    console.print(Panel(
        "[bold cyan]cmdmesh[/bold cyan] is awake.\nWhat do you want to do?",
        border_style="cyan",
        padding=(0, 2),
    ))
    console.print()
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Key", style="bold cyan", width=4)
    table.add_column("Mode")
    table.add_column("Status", style="dim")
    for key, label in MODES.items():
        status = "ready" if key in ("1", "2", "3") else "coming soon"
        if status == "ready":
            table.add_row(key, label, f"[dim]{status}[/dim]")
        else:
            table.add_row(f"[dim]{key}[/dim]", f"[dim]{label}[/dim]", f"[dim]{status}[/dim]")
    console.print(table)

    choice = _prompt_choice("Select mode", valid=set(MODES.keys()))

    if choice == "1":
        _run_chat_setup()
    elif choice == "2":
        run_search_mode()
    elif choice == "3":
        run_url_mode()
    else:
        print_warning("That feature is coming soon. Launching chat mode instead.")
        _run_chat_setup()

def _run_chat_setup() -> None:
    console.print()

    console.print(Panel(
        "Enter your [bold]HuggingFace API token[/bold].\n\n"
        "Free token (read access is enough):\n"
        "[cyan]https://huggingface.co/settings/tokens[/cyan]\n\n"
        "[dim]Your token is used only for this session and is never stored.[/dim]",
        border_style="yellow",
        title="[yellow]HuggingFace token required[/yellow]",
        padding=(0, 2),
    ))
    console.print()

    hf_token = _prompt_secret("HuggingFace token (hf_...)")

    if not hf_token:
        print_error("HuggingFace API token is required to proceed.")
        raise typer.Exit(1)

    if not hf_token.startswith("hf_"):
        print_warning("Token doesn't start with 'hf_' — double-check it is correct.")

    console.print()
    console.print("[bold]Choose an AI model (powered by HuggingFace):[/bold]\n")

    model_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    model_table.add_column("Key", style="bold cyan", width=4)
    model_table.add_column("Model", style="bold")
    model_table.add_column("Notes", style="dim")
    for i, m in enumerate(HF_MODELS, 1):
        model_table.add_row(str(i), m["label"], m["note"])
    
    custom_choice = len(HF_MODELS) + 1
    model_table.add_row(str(custom_choice), "Custom model...", "Enter any HuggingFace repo ID")
    
    console.print(model_table)

    m_choice = _prompt_choice("Select model", valid={str(i) for i in range(1, custom_choice + 1)})
    
    if int(m_choice) == custom_choice:
        console.print()
        model_id = input("  HF Repo ID (e.g. 'google/gemma-7b') › ").strip()
        if not model_id:
            print_error("Model ID cannot be empty.")
            raise typer.Exit(1)
        model_label = model_id.split("/")[-1]
    else:
        selected = HF_MODELS[int(m_choice) - 1]
        model_id = selected["id"]
        model_label = selected["label"]

    console.print()
    console.print(
        "[dim]System context (optional) — tell the AI how to behave.[/dim]\n"
        "[dim]Examples: 'You are a Python expert.' / 'Reply only in bullet points.'[/dim]\n"
        "[dim]Press Enter to skip.[/dim]"
    )
    console.print()
    system_context = input("  Context › ").strip() or None

    console.print()
    with console.status("Starting session…"):
        try:
            session = api.create_chat_session(
                model_id=model_id,
                system_context=system_context,
                title="New chat",
            )
        except APIError as exc:
            print_error(f"Could not create session: {exc.detail}")
            raise typer.Exit(1)

    _chat_loop(
        session_id=session["id"],
        model_label=model_label,
        model_id=model_id,
        hf_token=hf_token,
        system_context=system_context,
    )

def _chat_loop(
    *,
    session_id: str,
    model_label: str,
    model_id: str,
    hf_token: str,
    system_context: str | None,
) -> None:
    console.print()
    console.print(Panel(
        f"[bold green]Session started[/bold green]\n"
        f"Model  : [cyan]{model_label}[/cyan]\n"
        f"Context: [dim]{'set' if system_context else 'none'}[/dim]\n\n"
        "[dim]Type your message and press Enter. "
        "Ctrl+Q or /exit to quit. /help for commands.[/dim]",
        border_style="green",
        padding=(0, 2),
    ))
    console.print()

    pt_style = Style.from_dict({"prompt": "bold ansicyan"})
    bindings = KeyBindings()
    _state = {"quit": False}

    @bindings.add("c-q")
    def _ctrl_q(event):
        _state["quit"] = True
        event.app.current_buffer.text = "/exit"
        event.app.current_buffer.validate_and_handle()

    pt_session: PromptSession = PromptSession(
        key_bindings=bindings,
        style=pt_style,
    )

    while True:
        try:
            user_input = pt_session.prompt(
                HTML("<prompt>You</prompt> <ansigray>›</ansigray> ")
            ).strip()
        except (KeyboardInterrupt, EOFError):
            _do_exit(session_id)
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            cmd = user_input.lower().split()[0]

            if cmd in ("/exit", "/quit"):
                _do_exit(session_id)
                break

            elif cmd == "/help":
                _show_help()
                continue

            elif cmd == "/clear":
                _cmd_clear(session_id)
                continue

            elif cmd == "/history":
                _cmd_history(session_id)
                continue

            elif cmd == "/sessions":
                _cmd_sessions()
                continue

            elif cmd == "/model":
                console.print(
                    f"\n[dim]Model: [cyan]{model_label}[/cyan] "
                    f"([italic]{model_id}[/italic])[/dim]\n"
                )
                continue

            else:
                print_warning(f"Unknown command '{cmd}'. Type /help.")
                continue

        console.print()
        console.print(f"[bold dim]{model_label}[/bold dim] ›", end=" ")

        full_chunks: list[str] = []
        had_error = False

        try:
            for data in api.stream_chat_message(
                session_id=session_id,
                content=user_input,
                hf_token=hf_token,
            ):
                chunk = data.get("chunk", "")
                done = data.get("done", False)
                error = data.get("error")

                if error:
                    had_error = True
                    print()
                    print_error(f"\n{error}")

                    if "token" in error.lower() or "401" in error or "unauthorized" in error.lower():
                        console.print(
                            "\n[yellow]Your HuggingFace token may be invalid or expired.[/yellow]"
                        )
                        new_token = _prompt_secret("Enter a new HF token (or press Enter to quit)")
                        if new_token:
                            hf_token = new_token.strip()
                            console.print("[dim]Token updated for this session.[/dim]\n")
                        else:
                            _do_exit(session_id)
                            return
                    break

                if chunk:
                    print(chunk, end="", flush=True)
                    full_chunks.append(chunk)

                if done:
                    break

        except APIError as exc:
            print_error(f"\nAPI error: {exc.detail}")
            if exc.status_code == 401:
                print_info("Session expired. Run `cmdmesh login`.")
                break
            continue

        except Exception as exc:
            print_error(f"\nUnexpected error: {exc}")
            continue

        if not had_error:
            print()  

        console.print()

        if _state["quit"]:
            _do_exit(session_id)
            break

def _do_exit(session_id: str) -> None:
    console.print()
    print_success("Session saved.")
    console.print(
        f"[dim]Resume history: [bold]cmdmesh history --session {session_id}[/bold][/dim]\n"
    )

def _show_help() -> None:
    console.print()
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Command", style="bold cyan")
    table.add_column("Description", style="dim")
    for cmd, desc in SLASH_HELP.items():
        table.add_row(cmd, desc)
    console.print(table)
    console.print()

def _cmd_clear(session_id: str) -> None:
    try:
        api.clear_chat_context(session_id)
        print_success("Context cleared — AI memory reset. Your full history is still in the database.")
    except APIError as exc:
        print_error(f"Could not clear context: {exc.detail}")

def _cmd_history(session_id: str) -> None:
    try:
        session = api.get_chat_session(session_id)
    except APIError as exc:
        print_error(f"Could not load history: {exc.detail}")
        return

    messages = session.get("messages", [])
    if not messages:
        print_info("No messages yet.")
        return

    console.print(f"\n[bold]Session history[/bold] — {len(messages)} messages\n")
    for msg in messages:
        if msg["role"] == "system":
            continue
        if msg["role"] == "user":
            console.print(f"[bold cyan]You[/bold cyan]  {msg['content']}\n")
        else:
            console.print(f"[bold green]AI[/bold green]   ", end="")
            preview = msg["content"][:400]
            if len(msg["content"]) > 400:
                preview += "…"
            console.print(Markdown(preview))
            console.print()

def _cmd_sessions() -> None:
    try:
        sessions = api.list_chat_sessions(limit=10)
    except APIError as exc:
        print_error(f"Could not list sessions: {exc.detail}")
        return

    if not sessions:
        print_info("No past sessions found.")
        return

    console.print()
    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
    table.add_column("#",        style="dim",   width=3)
    table.add_column("Title",    style="bold",  max_width=40)
    table.add_column("Model",    style="cyan",  max_width=25)
    table.add_column("Messages", justify="right", style="dim")
    table.add_column("Updated",  style="dim")

    for i, s in enumerate(sessions, 1):
        model_short = s.get("model_id", "").split("/")[-1]
        table.add_row(
            str(i),
            s.get("title", "Untitled")[:40],
            model_short[:25],
            str(s.get("message_count", 0)),
            s.get("updated_at", "")[:10],
        )
    console.print(table)
    console.print()

@app.command()
def sessions(
    limit: int = typer.Option(10, "--limit", "-n", help="Number of sessions to show"),
) -> None:
    _require_login()
    _cmd_sessions()

@app.command()
def history(
    session: Optional[str] = typer.Option(
        None, "--session", "-s", help="Session ID to show"
    ),
    limit: int = typer.Option(
        10, "--limit", "-n", help="Pick from most recent N sessions"
    ),
) -> None:
    _require_login()

    if not session:
        try:
            sess_list = api.list_chat_sessions(limit=limit)
        except APIError as exc:
            print_error(f"Could not list sessions: {exc.detail}")
            raise typer.Exit(1)

        if not sess_list:
            print_info("No past sessions found.")
            raise typer.Exit()

        console.print("\n[bold]Recent sessions:[/bold]\n")
        for i, s in enumerate(sess_list, 1):
            model_short = s.get("model_id", "").split("/")[-1]
            console.print(
                f"  [cyan]{i}[/cyan].  {s.get('title','Untitled')[:50]}  "
                f"[dim]({model_short} — {s.get('message_count',0)} msgs)[/dim]"
            )

        console.print()
        pick = _prompt_choice(
            "Select session",
            valid={str(i) for i in range(1, len(sess_list) + 1)},
        )
        session = sess_list[int(pick) - 1]["id"]

    _cmd_history(session)

def _require_login() -> None:
    if not CredentialStore.is_logged_in():
        print_error("Not logged in. Run `cmdmesh login` first.")
        raise typer.Exit(1)

def _prompt_choice(prompt: str, valid: set[str]) -> str:
    while True:
        val = input(f"  {prompt} [{'/'.join(sorted(valid))}]: ").strip()
        if val in valid:
            return val
        err_console.print(f"[red]Please enter one of: {', '.join(sorted(valid))}[/red]")

def _prompt_secret(prompt: str) -> str:
    try:
        return getpass.getpass(f"  {prompt}: ")
    except (KeyboardInterrupt, EOFError):
        return ""