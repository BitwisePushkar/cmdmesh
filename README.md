# CmdMesh

> AI-powered command-line toolkit for intelligent search, code assistance, and developer workflows — entirely in the terminal.

CmdMesh unifies **CLI utilities**, **AI via HuggingFace**, **secure authentication**, and **backend services** into one seamless developer experience.
No browser. No GUI. Just your terminal.

---

## Tech Stack

| Layer      | Technologies                                        |
| ---------- | --------------------------------------------------- |
| CLI        | Python 3.12 · Typer · Rich · prompt-toolkit · HTTPX |
| Backend    | FastAPI · Uvicorn · SQLAlchemy · Asyncpg            |
| AI         | LangChain · HuggingFace Inference API               |
| Storage    | PostgreSQL · Redis                                  |
| Auth       | JWT · Fernet · bcrypt · OTP (SMTP)                  |
| Background | Celery · Redis                                      |
| Infra      | Docker · Docker Compose · uv                        |

---

## What CmdMesh Does

### Secure Authentication

CLI-based lifecycle: signup (OTP), login, refresh, logout, reset password.
Credentials stored locally using **Fernet encryption** with strict permissions (`0600`).

---

### AI Chat

* HuggingFace-hosted open models
* Persistent memory (Redis + PostgreSQL)
* Context-aware conversations
* Resumable sessions

---

### Web Search

* DuckDuckGo (no API key)
* Numbered results
* Optional AI answers with context

---

### URL Context

* Clean extraction via `trafilatura`
* Works on docs, blogs, GitHub, news
* Ask AI questions on any URL

---

### AI Code Assistant

Modes: `generate · debug · explain · refactor · review · test · complete`

* File or inline input
* Streaming responses
* Safe file saving with backups

---

## Supported Models

| Model                                | Use Case                            |
| ------------------------------------ | ----------------------------------- |
| `meta-llama/Llama-3.1-8B-Instruct`   | Best overall quality                |
| `meta-llama/Llama-3.2-1B-Instruct`   | Ultra-fast summaries                |
| `mistralai/Mistral-7B-Instruct-v0.3` | Strong coding & logic               |
| `HuggingFaceH4/zephyr-7b-beta`       | Well-balanced instruction following |

---

## CLI Commands

### Authentication

| Command                  | Description                           |
| ------------------------ | ------------------------------------- |
| `cmdmesh signup`         | Create account + OTP verification     |
| `cmdmesh verify-otp`     | Verify email OTP (`--email`)          |
| `cmdmesh resend-otp`     | Resend OTP (60s cooldown)             |
| `cmdmesh login`          | Login → JWT + encrypted refresh token |
| `cmdmesh whoami`         | Show profile (auto refresh token)     |
| `cmdmesh refresh`        | Renew session                         |
| `cmdmesh logout`         | Revoke session + delete credentials   |
| `cmdmesh reset-password` | Reset password (OTP)                  |

---

### AI & Features

| Command            | Description                              |
| ------------------ | ---------------------------------------- |
| `cmdmesh wakeup`   | Entry point → Chat / Search / URL / Code |
| `cmdmesh sessions` | List past AI sessions                    |
| `cmdmesh history`  | View session history                     |
| `cmdmesh search`   | Web search (+ optional AI)               |
| `cmdmesh url`      | URL context + AI                         |
| `cmdmesh code`     | AI code assistant                        |

---

## In-Session Commands

### Chat Mode

`/exit` · `/clear` · `/history` · `/sessions` · `/model` · `/context` · `/help` · `Ctrl+Q`

### Search Mode

`/ai` · `/url <url>` · `query :: question` · `/exit`

### URL Mode

`/search <query>` · `url :: question` · `/exit`

### Code Mode

`/task` · `/file <path>` · `/save <path>` · `/model` · `/clear` · `/exit`

---

## Code Task Types

| Task     | Description                 |
| -------- | --------------------------- |
| generate | Build code from description |
| debug    | Fix bugs + explain issues   |
| explain  | Step-by-step explanation    |
| refactor | Improve code quality        |
| review   | Full code review            |
| test     | Generate unit tests         |
| complete | Finish partial code         |

---

## Local Setup

### Prerequisites

* Python 3.12+
* uv
* Docker + Docker Compose

---

### Install

```bash
git clone https://github.com/you/cmdmesh
cd cmdmesh
uv sync
```

---

### Configure

```bash
cp .env.example .env
```

Generate secrets:

```bash
uv run python -c "import secrets; print(secrets.token_hex(64))"
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

```env
JWT_SECRET_KEY=<generated>
TOKEN_ENCRYPTION_KEY=<generated>
```

---

## Start Services

```bash
docker compose up -d
```

| Service | URL                        |
| ------- | -------------------------- |
| API     | http://localhost:8000      |
| Docs    | http://localhost:8000/docs |
| Mail UI | http://localhost:8025      |
| Celery  | http://localhost:5555      |

---

## Usage

### With `uv run`

```bash
uv run cmdmesh signup
uv run cmdmesh login
uv run cmdmesh wakeup
```

### With virtualenv

```bash
source .venv/bin/activate   # Linux/macOS
.venv\Scripts\Activate.ps1  # Windows

cmdmesh wakeup
```

---

## Testing

```bash
uv run pytest tests/ -v --tb=short
```

Coverage:

```bash
uv run pytest --cov=backend --cov=cli --cov-report=term-missing
```