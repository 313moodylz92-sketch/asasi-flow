# ASASI Flow

**Telegram-native multi-agent system. Define your agents in YAML. It learns from your decisions.**

Built in a weekend while trading prediction markets and launching a product marketplace. Not a spec doc. Not vaporware. Running in production.

---

## What makes it different

Every other multi-agent framework either:
- Has a "learning system" that's actually `Math.random() > 0.5`
- Requires you to write Python to define agents
- Has no approval gate — agents just run and you find out what happened

ASASI Flow has three things none of them do:

**1. Two-step approval gate**
Agents propose, you see the exact code diff in Telegram before a single file is written. You type `/confirm` to stage. You type `/veto` to kill it. Nothing writes without your eyes on it.

**2. Real learning loop**
Every approve and veto is logged. After 50 decisions, Claude reads the full log, finds the patterns, and rewrites the routing rules. Your system gets smarter from your actual behavior — not a pretrained dataset.

**3. YAML-defined agents**
No Python required to add or modify agents. Define them in `agents.yaml`. Three types: `code` (reads files, proposes changes, stages), `report` (research and analysis), `content` (drafts, saves approved posts for voice consistency).

---

## Deploy in 10 minutes

**1. Clone and install**
```bash
git clone https://github.com/thowba/asasi-flow
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
Decision logged → at 50 entries → learning loop rewrites routing rules
```

Every staged file has a `.bak` backup. `/rollback` restores instantly.

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
| `/agent` | System status — decisions logged, routing rules version, learning progress |
| `/log` | Last 5 routing decisions |
| `/learn` | Trigger learning loop manually |
| `/reset` | Clear conversation history |

---

## The learning loop

After 50 decisions (approvals + vetoes), ASASI Flow automatically:
1. Reads the full decision log
2. Analyzes which agents were approved vs vetoed
3. Identifies misrouting patterns
4. Rewrites routing descriptions in `routing_rules.json`

The router picks up the new rules on the next message. No restart needed. Trigger it manually anytime with `/learn`.

---

## Cost

- Routing: Claude Haiku (~$0.0002 per message)
- Proposals + execution: Claude Sonnet (~$0.10–$0.75 per command)
- Default $3 cap per command — asks confirmation above that

---

## Built by

[THOWBA Holdings](https://thowba.com) — built live while running [313SESSIONS](https://313sessions.com)
