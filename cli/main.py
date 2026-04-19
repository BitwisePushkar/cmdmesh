import typer
from cli.commands import auth as auth_commands

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

if __name__ == "__main__":
    app()