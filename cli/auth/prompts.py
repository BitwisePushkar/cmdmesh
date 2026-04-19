import re
from rich.console import Console
from rich.prompt import Prompt

console = Console()
err_console = Console(stderr=True)

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")

def prompt_username(label: str = "Username") -> str:
    while True:
        val = Prompt.ask(f"[bold]{label}[/bold]").strip()
        if not USERNAME_RE.match(val):
            err_console.print(
                "[red]Username must be 3–32 chars: letters, digits, _ or -[/red]"
            )
            continue
        return val.lower()

def prompt_email(label: str = "Email") -> str:
    simple_email = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    while True:
        val = Prompt.ask(f"[bold]{label}[/bold]").strip().lower()
        if not simple_email.match(val):
            err_console.print("[red]Please enter a valid email address.[/red]")
            continue
        return val

def prompt_password(label: str = "Password", confirm: bool = False) -> str:
    while True:
        pw = Prompt.ask(f"[bold]{label}[/bold]", password=True)
        if len(pw) < 8:
            err_console.print("[red]Password must be at least 8 characters.[/red]")
            continue
        if not any(c.isupper() for c in pw):
            err_console.print("[red]Password must contain at least one uppercase letter.[/red]")
            continue
        if not any(c.isdigit() for c in pw):
            err_console.print("[red]Password must contain at least one digit.[/red]")
            continue
        if confirm:
            pw2 = Prompt.ask("[bold]Confirm password[/bold]", password=True)
            if pw != pw2:
                err_console.print("[red]Passwords do not match. Try again.[/red]")
                continue
        return pw

def prompt_otp(label: str = "Verification code") -> str:
    while True:
        val = Prompt.ask(f"[bold]{label} (6 digits)[/bold]").strip()
        if not (val.isdigit() and len(val) == 6):
            err_console.print("[red]Please enter the 6-digit code from your email.[/red]")
            continue
        return val

def prompt_identifier(label: str = "Username or email") -> str:
    while True:
        val = Prompt.ask(f"[bold]{label}[/bold]").strip()
        if len(val) < 3:
            err_console.print("[red]Please enter your username or email.[/red]")
            continue
        return val

def confirm(message: str, default: bool = False) -> bool:
    choice = Prompt.ask(
        f"[bold]{message}[/bold]",
        choices=["y", "n"],
        default="y" if default else "n",
    )
    return choice.lower() == "y"