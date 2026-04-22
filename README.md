# CmdMesh CLI

A minimalist, AI-powered command-line toolkit for **search, automation, and intelligent development workflows** — directly from your terminal.

Built to unify **CLI utilities + AI assistance + backend integration** into one seamless experience.

---

## Tech Stack

`Python : Typer : Rich : HTTPX : FastAPI : Redis : PostgreSQL : JWT : Celery : SMTP : Docker`

---

## Core Functionality

### CLI Core

Command-based interface · Modular commands · Fast execution · Developer-friendly UX

### AI Interaction

Chat with AI models · Prompt execution · Context-aware responses · CLI-native workflows

### Search

Google search from terminal · Quick results · Minimal output formatting

### Code Runner

Execute short code snippets directly in CLI · Fast feedback loop

### AI Code Assistant

Codebase-aware assistance · Generate & refactor code · Explain logic · Suggest improvements
File-level operations · Context injection · Review-first workflow (no blind overwrites)

### Auth System

Secure login · Token-based auth · Credential storage · Session management · OTP verification by SMTP

---

## CLI Commands

### Using `uv run` (Recommended)

```bash
uv run cmdmesh signup           # Register → OTP → account created
uv run cmdmesh verify-otp       # Complete interrupted signup
uv run cmdmesh resend-otp       # Request new OTP (60s cooldown)
uv run cmdmesh login            # Authenticate user
uv run cmdmesh whoami           # Show current session
uv run cmdmesh refresh          # Refresh access token
uv run cmdmesh logout           # Logout + clear credentials
uv run cmdmesh reset-password   # Reset password via OTP
```

---

### Using Direct CLI (via virtual environment)

Activate virtual environment first:

```powershell
.venv\Scripts\Activate.ps1
```

Then run:

```bash
cmdmesh signup
cmdmesh login
cmdmesh whoami
cmdmesh verify-otp  
cmdmesh resend-otp 
cmdmesh refresh
cmdmesh logout
cmdmesh reset-password 
```

---

## ▶ Setup (Local)

```bash
git clone <repo>
cd cmdmesh
uv sync
```

> All commands can be run using `uv run` without activating the virtual environment.

---

## Verification & Testing

### Run Tests

```bash
uv run pytest tests/ -v --tb=short
```

* Uses **fakeredis + sqlite**
* No Docker required

---

### Verify CLI

```bash
uv run cmdmesh whoami
```

Expected:

* "Not logged in" OR "Connection refused"
* ❗ No traceback errors

---

### Generate Keys

```bash
# JWT Secret
uv run python -c "import secrets; print(secrets.token_hex(64))"

# Encryption Key
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## Backend Setup (Docker)

```bash
docker compose up -d
```
Then just use the cmdmesh command simply 
---