#!/usr/bin/env python3
"""
ASASI Flow — Router
Haiku classifies intent → routes to agent → logs decision.
Routing rules start as defaults, get rewritten by learner.py after 50 decisions.
"""

import json
import re
from datetime import datetime
from pathlib import Path
import config

BASE_DIR     = Path(__file__).parent
DECISION_LOG = BASE_DIR / "decisions.json"
RULES_FILE   = BASE_DIR / "routing_rules.json"


# ── LOG ───────────────────────────────────────────────────────────────────────

def load_log() -> list:
    if DECISION_LOG.exists():
        try:
            return json.loads(DECISION_LOG.read_text())
        except Exception:
            return []
    return []


def save_log(entries: list) -> None:
    DECISION_LOG.write_text(json.dumps(entries, indent=2))


def log_decision(entry: dict) -> None:
    entries = load_log()
    entries.append(entry)
    save_log(entries)


# ── ROUTING RULES ─────────────────────────────────────────────────────────────

def _build_system(agents: list, rules: dict) -> str:
    lines = ["You are the ASASI Flow Router. Classify the incoming message and route it to the correct agent.\n"]
    lines.append("Agents:")
    for a in agents:
        name = a["name"]
        desc = rules.get(name, a["description"])
        lines.append(f"- {name}: {desc}")
    lines.append("- NONE: General conversation, questions — not a specific agent task.")
    lines.append(
        '\nRespond ONLY with valid JSON — no markdown, no explanation:\n'
        '{\n'
        '  "agent": "<agent name> or NONE",\n'
        '  "intent": "one sentence: what the user wants done",\n'
        '  "confidence": 0-100,\n'
        '  "estimated_cost_usd": 0.10,\n'
        '  "complexity": "simple|medium|complex"\n'
        '}\n'
        'estimated_cost_usd: reads=$0.10, writes=$0.25, complex=$0.75, research=$0.50\n'
        'complexity: simple=quick question/small read, medium=multi-file/analysis, complex=large codebase/deep reasoning'
    )
    return "\n".join(lines)


def load_rules() -> dict:
    if RULES_FILE.exists():
        try:
            return json.loads(RULES_FILE.read_text())
        except Exception:
            pass
    return {}


def save_rules(rules: dict) -> None:
    RULES_FILE.write_text(json.dumps(rules, indent=2))


# ── COMPLEXITY CLAMP ─────────────────────────────────────────────────────────

_CODE_KEYWORDS = frozenset({
    "code", "file", "files", "repo", "patch", "fix", "debug", "error",
    "stack", "deploy", "refactor", "api", "database", "db", "config",
    "test", "tests", "function", "class", "component",
    "schema", "migration", "import", "export", "build", "script",
    "bug", "crash", "broke", "broken",
})

def _clamp_complexity(decision: dict, user_text: str = "") -> dict:
    if decision.get("complexity") == "simple":
        haystack = (user_text + " " + decision.get("intent", "")).lower()
        if any(kw in haystack for kw in _CODE_KEYWORDS):
            decision["complexity"] = "medium"
    return decision


# ── ROUTE ─────────────────────────────────────────────────────────────────────

def route(user_text: str, claude_client) -> dict:
    agents  = config.load_agents()
    rules   = load_rules()
    system  = _build_system(agents, rules)

    try:
        resp = claude_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_text}],
        )
        raw = resp.content[0].text.strip()
        raw = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()
        decision = json.loads(raw)
    except Exception as e:
        decision = {
            "agent": "NONE", "intent": user_text[:120],
            "confidence": 0, "estimated_cost_usd": 0.0,
            "router_error": str(e),
        }

    decision["input"]     = user_text
    decision["timestamp"] = datetime.utcnow().isoformat() + "Z"
    decision["outcome"]   = "routed"
    return _clamp_complexity(decision, user_text)


# ── STATUS ────────────────────────────────────────────────────────────────────

def format_status() -> str:
    entries   = load_log()
    total     = len(entries)
    threshold = config.learning_threshold()
    counts    = {}
    approved  = vetoed = 0
    for e in entries:
        a = e.get("agent", "NONE")
        counts[a] = counts.get(a, 0) + 1
        if e.get("outcome") == "approved":   approved += 1
        if e.get("outcome") == "vetoed":     vetoed   += 1

    lines = [
        "ASASI Flow",
        f"Decisions: {total}  |  Approved: {approved}  |  Vetoed: {vetoed}",
        "",
        "Routing breakdown:",
    ]
    for agent, n in sorted(counts.items(), key=lambda x: -x[1]):
        lines.append(f"  {agent}: {n}")

    until = max(0, threshold - total)
    lines.append("")
    if until == 0:
        lines.append("Learning system: READY — run /learn")
    else:
        lines.append(f"Learning system: {until} decisions until auto-trigger")

    rules = load_rules()
    if rules.get("version", 1) > 1:
        lines.append(f"Routing rules: v{rules['version']} (learned {rules.get('updated', '?')})")
    else:
        lines.append("Routing rules: v1 (default)")

    return "\n".join(lines)


def format_recent_log(n: int = 5) -> str:
    entries = load_log()
    if not entries:
        return "No decisions logged yet."
    lines = [f"Last {min(n, len(entries))} decisions:", ""]
    for e in reversed(entries[-n:]):
        ts      = (e.get("timestamp") or "")[:16].replace("T", " ")
        agent   = e.get("agent", "?")
        intent  = (e.get("intent") or "")[:55]
        outcome = e.get("outcome", "?")
        lines.append(f"{ts}  [{agent}]  {outcome}")
        lines.append(f"  {intent}")
    return "\n".join(lines)
