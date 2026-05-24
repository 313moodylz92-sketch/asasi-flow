# ASASI Flow

**A Telegram-native control layer for local AI agents.**

Define agents in YAML. Send tasks from Telegram. Review the plan. Approve the diff. Confirm before anything writes. Roll back if needed.

Built for solo builders who want AI coding help without giving agents unsupervised control over their repo.

---

## The problem it solves

Most agent frameworks either run autonomously (you find out what happened after) or require you to babysit a terminal. ASASI Flow sits in the middle: agents propose, you control, files only write when you say so — from Telegram.

Control coding agents from Telegram without giving them unsupervised write access.

---

## Safety model

- Only responds to your configured `TELEGRAM_CHAT_ID`
- Agents only write after `/confirm`
- Shows unified diff before any file is touched
- Creates `.bak` backup before every write
- `/rollback` restores instantly
- Code agents restricted to `file_scope` in their config
- Never auto-pushes to GitHub
- Never executes shell commands
- `.env` and all runtime state excluded from git

---

## How it works

```
You type anything in Telegram
        ↓
Router (Claude Haiku) classifies intent → picks agent
        ↓
Agent reads relevant files → proposes a plan
        ↓
/approve → agent generates code → sends diff to Telegram
        ↓
/confirm → files written + backed up + git staged
        ↓
Decision logged → routing adapts from your approvals/vetoes
```

Every staged file has a `.bak` backup. `/rollback` restores instantly.

---

## What makes it work

**Telegram-native control**
No dashboard, no terminal babysitting. You're on your phone. You type a task. You see the plan. You approve the diff. The file writes. That's the full loop.

**Two-step write gate**
Agents propose, then generate code. You see the exact diff before a single file is written. `/confirm` stages it. `/veto` kills it. Nothing writes without your sign-off.

**YAML-defined agents**
No Python required to add or modify agents. Define them in `agents.yaml` — name, file scope, system prompt, git directory. Three types: `code` (reads files, proposes changes, stages on confirm), `report` (research and analysis), `content` (drafts, saves approved posts for voice consistency).

**Routing adaptation**
ASASI logs every approval and veto. After 50 decisions, it asks Claude to rewrite the routing rules based on your actual behavior. It does not fine-tune a model. It updates inspectable JSON rules that the router picks up on the next message. Trigger manually anytime with `/learn`.

---

## Deploy in 10 minutes

**1. Clone and install**
```bash
git clone https://github.com/313moodylz92-sketch/asasi-flow
cd asasi-flow
pip install anthropic python-dotenv pyyaml requests
```

**2. Configure environment**
```bash
cp .env.example .env
# Fill in: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ANTHROPIC_API_KEY
# Set CODEBASE_DIR to your project path
```

**3. Define your agents**

Edit `agents.yaml`. The default config ships with 4 agents — rename them, change their file scopes, rewrite their system prompts. Or add new ones:

```yaml
agents:
  - name: BackendAgent
    description: "Handles changes to API routes and database schema"
    type: code
    file_scope:
      - "src/api/"
      - "prisma/"
    git_dir: "${CODEBASE_DIR}"
    system_prompt: |
      You are BackendAgent — elite engineer for {project_name}.
      ...
```

**4. Run**
```bash
python asasi.py
```

Open Telegram. Type anything. It routes to the right agent automatically.

---

## Agent types

| Type | What it does | On /approve |
|------|-------------|-------------|
| `code` | Reads files, proposes changes, shows diff, stages on /confirm | Generates code diff |
| `report` | Research and analysis, no file writes | Logs as approved |
| `content` | Drafts copy, saves approved posts for voice consistency | Saves to content log |

---

## Commands

| Command | What it does |
|---------|-------------|
| `/approve` | Accept proposal → generate code diff (code agents) or approve directly (report/content) |
| `/confirm` | Write + stage files after reviewing diff |
| `/veto` | Discard proposal or diff. Logs as vetoed. |
| `/rollback` | Restore last staged files from backup, unstage from git |
| `/agent` | System status — decisions logged, routing rules version, adaptation progress |
| `/log` | Last 5 routing decisions |
| `/learn` | Trigger routing adaptation manually |
| `/reset` | Clear conversation history |

---

## Cost

- Routing: Claude Haiku (~$0.0002 per message)
- Proposals + execution: Claude Sonnet (~$0.10–$0.75 per command)
- Default $3 cap per command — asks confirmation above that

---

## Built by

[THOWBA Holdings](https://thowba.com) — built live while trading prediction markets and launching a product marketplace. Running in production.
