from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console()
err_console = Console(stderr=True)

def print_success(message: str) -> None:
    console.print(f"[bold green]✓[/bold green] {message}")

def print_error(message: str) -> None:
    err_console.print(f"[bold red]✗[/bold red] {message}")

def print_warning(message: str) -> None:
    console.print(f"[bold yellow]⚠[/bold yellow] {message}")

def print_info(message: str) -> None:
    console.print(f"[dim]→[/dim] {message}")

def print_profile(username: str, email: str, user_id: str = "", created_at: str = "") -> None:
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    table.add_column("Field", style="dim", width=14)
    table.add_column("Value", style="bold")
    table.add_row("Username", username)
    table.add_row("Email", email)
    if user_id:
        table.add_row("User ID", user_id)
    if created_at:
        table.add_row("Member since", created_at[:10])
    console.print(
        Panel(table, title="[bold cyan]cmdmesh[/bold cyan] — logged in", border_style="cyan")
    )

def print_token_info(expires_at: str) -> None:
    console.print(f"[dim]Session active. Token expires at {expires_at}[/dim]")

def print_otp_instructions(email: str) -> None:
    console.print(
        Panel(
            f"A 6-digit verification code has been sent to [bold]{email}[/bold].\n"
            "Check your inbox and enter the code below.\n\n"
            "[dim]The code expires in 10 minutes. "
            "Run [bold]cmdmesh resend-otp[/bold] if you need a new one.[/dim]",
            title="[bold yellow]Check your email[/bold yellow]",
            border_style="yellow",
        )
    )