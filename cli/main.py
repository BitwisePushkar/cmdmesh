import typer
from cli.commands import auth as auth_commands
from cli.commands import chat as chat_commands
from cli.commands import search as search_commands
from cli.commands import code as code_commands
from cli.utils.auth_helpers import _require_login, _prompt_hf_setup

app = typer.Typer(
    name="cmdmesh",
    help="cmdmesh — your AI-powered terminal companion",
    add_completion=True,
    no_args_is_help=True,
    rich_markup_mode="rich",
)

app.command(name="signup")(auth_commands.signup)
app.command(name="verify-otp")(auth_commands.verify_otp)
app.command(name="resend-otp")(auth_commands.resend_otp)
app.command(name="login")(auth_commands.login)
app.command(name="refresh")(auth_commands.refresh)
app.command(name="logout")(auth_commands.logout)
app.command(name="whoami")(auth_commands.whoami)
app.command(name="reset-password")(auth_commands.reset_password)
app.command(name="wakeup")(chat_commands.wakeup)
app.command(name="sessions")(chat_commands.sessions)
app.command(name="history")(chat_commands.history)
app.command(name="search")(search_commands.search_cmd)
app.command(name="url")(search_commands.url_cmd)
app.command(name="code")(code_commands.run_code_mode)

if __name__ == "__main__":
    app()