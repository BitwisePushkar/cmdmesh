import typer
from rich.console import Console
from cli.auth import client as api
from cli.auth.client import APIError
from cli.auth.prompts import (confirm, prompt_email, prompt_identifier, prompt_otp,
 prompt_password, prompt_username,)
from cli.auth.store import CredentialStore
from cli.utils.display import (console, err_console, print_error, print_info,
print_otp_instructions, print_profile, print_success, print_warning,)

app = typer.Typer(help="Authentication commands")

@app.command()
def signup() -> None:
    if CredentialStore.is_logged_in():
        creds = CredentialStore.load()
        print_warning(f"You are already logged in as [bold]{creds['username']}[/bold].")
        if not confirm("Start a new signup anyway?", default=False):
            raise typer.Exit()
    console.print("\n[bold cyan]Create your cmdmesh account[/bold cyan]\n")
    username = prompt_username()
    email = prompt_email()
    password = prompt_password(confirm=True)
    with console.status("Sending verification code…"):
        try:
            result = api.post_signup(username, email, password)
        except APIError as exc:
            _handle_api_error(exc)
            raise typer.Exit(1)
    print_success(result.get("message", "Verification code sent"))
    print_otp_instructions(email)
    _verify_otp_interactive(email)

@app.command(name="verify-otp")
def verify_otp(
    email: str = typer.Option(None, "--email", "-e", help="Email address to verify"),
) -> None:
    if not email:
        email = prompt_email("Email to verify")
    _verify_otp_interactive(email)

def _verify_otp_interactive(email: str) -> None:
    max_ui_retries = 3
    for attempt in range(1, max_ui_retries + 1):
        otp = prompt_otp()
        with console.status("Verifying…"):
            try:
                result = api.post_verify_otp(email, otp)
                break
            except APIError as exc:
                if exc.status_code == 422:
                    print_error(exc.detail)
                    if attempt == max_ui_retries:
                        print_error("Too many local retries. Run `cmdmesh verify-otp` to continue.")
                        raise typer.Exit(1)
                    resend = confirm("Request a new code?", default=False)
                    if resend:
                        _resend_otp_action(email)
                    continue
                elif exc.status_code == 429:
                    print_error(exc.detail)
                    raise typer.Exit(1)
                elif exc.status_code == 410:
                    print_error(exc.detail)
                    raise typer.Exit(1)
                else:
                    _handle_api_error(exc)
                    raise typer.Exit(1)
    else:
        raise typer.Exit(1)
    print_success(result.get("message", "Account created"))
    print_info(result.get("detail", "Run `cmdmesh login` to get started."))

@app.command(name="resend-otp")
def resend_otp(
    email: str = typer.Option(None, "--email", "-e", help="Email to resend OTP to"),
) -> None:
    if not email:
        email = prompt_email("Email to resend code to")
    _resend_otp_action(email)

def _resend_otp_action(email: str) -> None:
    with console.status("Resending code…"):
        try:
            result = api.post_resend_otp(email)
            print_success(result.get("message", "Code resent"))
        except APIError as exc:
            _handle_api_error(exc)

@app.command()
def login() -> None:
    if CredentialStore.is_logged_in():
        creds = CredentialStore.load()
        print_warning(f"Already logged in as [bold]{creds['username']}[/bold].")
        if not confirm("Log in as a different account?", default=False):
            raise typer.Exit()
        CredentialStore.clear()
    console.print("\n[bold cyan]Log in to cmdmesh[/bold cyan]\n")
    identifier = prompt_identifier()
    password = prompt_password()
    with console.status("Authenticating…"):
        try:
            data = api.post_login(identifier, password)
        except APIError as exc:
            _handle_api_error(exc)
            raise typer.Exit(1)
    try:
        me = _fetch_me_with_token(data["access_token"])
    except APIError:
        me = {}
    CredentialStore.save(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_in=data["expires_in"],
        username=me.get("username", identifier),
        email=me.get("email", ""),
        user_id=me.get("id", ""),
    )
    print_success("Logged in successfully.")
    print_profile(
        username=me.get("username", identifier),
        email=me.get("email", ""),
        user_id=me.get("id", ""),
        created_at=me.get("created_at", ""),
    )

def _fetch_me_with_token(token: str) -> dict:
    import httpx
    from cli.auth.client import _BASE_URL, _device_headers, _raise_for_status
    headers = {"Authorization": f"Bearer {token}", **_device_headers()}
    with httpx.Client(base_url=_BASE_URL, headers=headers, timeout=10.0) as client:
        r = client.get("/auth/me")
        _raise_for_status(r)
        return r.json()

@app.command()
def refresh() -> None:
    if not CredentialStore.is_logged_in():
        print_error("Not logged in. Run `cmdmesh login` first.")
        raise typer.Exit(1)
    rt = CredentialStore.get_refresh_token()
    if not rt:
        print_error("No refresh token found. Run `cmdmesh login`.")
        raise typer.Exit(1)
    if not CredentialStore.is_access_token_expired():
        creds = CredentialStore.load()
        print_info(f"Token is still valid (expires at {creds['expires_at'][:19]} UTC).")
        print_info("Use --force to refresh anyway.")
        raise typer.Exit()
    with console.status("Refreshing session…"):
        try:
            data = api.post_refresh(rt)
        except APIError as exc:
            if exc.status_code == 401:
                logout_reason = exc.detail
                CredentialStore.clear()
                print_error(f"Session invalidated: {logout_reason}")
                print_info("Please run `cmdmesh login` to start a new session.")
            else:
                _handle_api_error(exc)
            raise typer.Exit(1)
    CredentialStore.update_tokens(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_in=data["expires_in"],
    )
    creds = CredentialStore.load()
    print_success("Session refreshed.")
    print_profile(
        username=creds["username"],
        email=creds["email"],
        user_id=creds.get("user_id", ""),
    )

@app.command()
def logout() -> None:
    if not CredentialStore.is_logged_in():
        print_warning("Not currently logged in.")
        raise typer.Exit()
    rt = CredentialStore.get_refresh_token()
    if rt:
        with console.status("Revoking session on server…"):
            try:
                api.post_logout(rt)
            except APIError as exc:
                print_warning(f"Server revocation failed ({exc.detail}), clearing local session.")
    CredentialStore.clear()
    print_success("Logged out. Credentials removed from disk.")

@app.command()
def whoami() -> None:
    if not CredentialStore.is_logged_in():
        print_error("Not logged in. Run `cmdmesh login`.")
        raise typer.Exit(1)
    try:
        me = api.get_me()
        print_profile(
            username=me["username"],
            email=me["email"],
            user_id=me.get("id", ""),
            created_at=me.get("created_at", ""),
        )
    except APIError as exc:
        if exc.status_code == 401:
            CredentialStore.clear()
            print_error("Session has expired. Please run `cmdmesh login`.")
            raise typer.Exit(1)
        _handle_api_error(exc)
        raise typer.Exit(1)

def _handle_api_error(exc: APIError) -> None:
    status = exc.status_code
    if status == 409:
        print_error(f"Conflict: {exc.detail}")
    elif status == 401:
        print_error(f"Authentication failed: {exc.detail}")
    elif status == 403:
        print_error(f"Forbidden: {exc.detail}")
    elif status == 404:
        print_error(f"Not found: {exc.detail}")
    elif status == 422:
        print_error(f"Validation error: {exc.detail}")
    elif status == 429:
        print_error(f"Rate limited: {exc.detail}")
    elif status == 503:
        print_error(f"Service unavailable: {exc.detail}")
    elif status >= 500:
        print_error(f"Server error ({status}). Please try again later.")
    else:
        print_error(f"Error {status}: {exc.detail}")

@app.command(name="reset-password")
def reset_password(
    email: str = typer.Option(None, "--email", "-e", help="Email of the account to reset"),
) -> None:
    console.print("\n[bold yellow]Reset your cmdmesh password[/bold yellow]\n")
    if not email:
        email = prompt_email("Email address for your account")
    with console.status("Sending reset code…"):
        try:
            result = api.post_reset_password_request(email)
        except APIError as exc:
            _handle_api_error(exc)
            raise typer.Exit(1)
    console.print(
        f"\n[dim]A reset code has been sent to [bold]{email}[/bold] if it is registered.[/dim]"
    )
    console.print("[dim]Check your inbox (and spam folder). The code expires in 5 minutes.[/dim]\n")
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        otp = prompt_otp("Reset code")
        new_password = prompt_password("New password", confirm=True)
        with console.status("Verifying and updating password…"):
            try:
                confirm_result = api.post_reset_password_confirm(email, otp, new_password)
                break
            except APIError as exc:
                if exc.status_code == 422:
                    print_error(exc.detail)
                    if attempt < max_retries:
                        print_info(f"Attempt {attempt}/{max_retries}. Try again.")
                    continue
                elif exc.status_code == 410:
                    print_error(exc.detail)
                    print_info("Run `cmdmesh reset-password` to start over.")
                    raise typer.Exit(1)
                elif exc.status_code == 429:
                    print_error(exc.detail)
                    raise typer.Exit(1)
                else:
                    _handle_api_error(exc)
                    raise typer.Exit(1)
    else:
        print_error("Too many failed attempts. Run `cmdmesh reset-password` to start over.")
        raise typer.Exit(1)
    CredentialStore.clear()
    print_success(confirm_result.get("message", "Password reset successful."))
    print_info("All sessions invalidated. Run `cmdmesh login` with your new password.")