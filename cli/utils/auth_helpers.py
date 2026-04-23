import getpass
import typer
from typing import Any
from rich.console import Console
from rich.table import Table
from rich import box
from cli.auth.store import CredentialStore
from cli.utils.display import print_error, print_warning

console = Console()
err_console = Console(stderr=True)

HF_MODELS = [
    {
        "id":    "meta-llama/Llama-3.1-8B-Instruct",
        "label": "Llama 3.1 8B Instruct",
        "note":  "Large, powerful model — best for complex tasks",
    },
    {
        "id":    "meta-llama/Llama-3.2-1B-Instruct",
        "label": "Llama 3.2 1B Instruct",
        "note":  "Fast, lightweight — good for simple summaries",
    },
    {
        "id":    "HuggingFaceH4/zephyr-7b-beta",
        "label": "Zephyr 7B Beta",
        "note":  "Well-balanced, great at following instructions",
    },
    {
        "id":    "google/gemma-2-2b-it",
        "label": "Gemma 2 2B IT",
        "note":  "Google's smallest Gemma — very well supported",
    },
]

def _require_login() -> None:
    if not CredentialStore.is_logged_in():
        print_error("Not logged in. Run `cmdmesh login` first.")
        raise typer.Exit(1)

def _prompt_choice(prompt: str, valid: set[str]) -> str:
    while True:
        val = input(f"  {prompt} [{'/'.join(sorted(valid))}] › ").strip()
        if val in valid:
            return val
        err_console.print(f"[red]Enter one of: {', '.join(sorted(valid))}[/red]")

def _prompt_hf_setup() -> tuple[str, str, str]:
    console.print("[bold]Choose an AI model (powered by HuggingFace):[/bold]\n")
    
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Key", style="bold cyan", width=4)
    table.add_column("Model", style="bold")
    table.add_column("Notes", style="dim")
    for i, m in enumerate(HF_MODELS, 1):
        table.add_row(str(i), m["label"], m["note"])
    
    custom_choice = len(HF_MODELS) + 1
    table.add_row(str(custom_choice), "Custom model...", "Enter any HuggingFace repo ID")
    console.print(table)

    choice = _prompt_choice("Select model", valid={str(i) for i in range(1, custom_choice + 1)})
    
    if int(choice) == custom_choice:
        console.print()
        model_id = input("  HF Repo ID (e.g. 'google/gemma-7b') › ").strip()
        if not model_id:
            print_error("Model ID cannot be empty.")
            raise typer.Exit(1)
        model_label = model_id.split("/")[-1]
    else:
        selected = HF_MODELS[int(choice) - 1]
        model_id = selected["id"]
        model_label = selected["label"]

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
    return hf_token.strip(), model_id, model_label
