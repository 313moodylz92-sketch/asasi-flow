#!/usr/bin/env python3
"""
ASASI Flow — Agent Runner
Loads agent configs from agents.yaml, reads relevant files, produces proposals.
"""

import json
import re
from datetime import datetime
from pathlib import Path
import config

BASE_DIR    = Path(__file__).parent
CONTENT_LOG = BASE_DIR / "content_log.json"
MAX_FILE_CHARS = 4000
MAX_FILES_READ = 4

FILE_SELECTOR_SYSTEM = (
    "File selector. Given a list of files and a user intent, return ONLY a JSON array "
    "of the most relevant file paths (max {n}). No explanation."
)


# ── UTILITIES ─────────────────────────────────────────────────────────────────

def _read_file(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
        if len(text) > MAX_FILE_CHARS:
            text = text[:MAX_FILE_CHARS] + f"\n... [truncated]"
        return text
    except Exception as e:
        return f"[Could not read {path.name}: {e}]"


def _parse_json(raw: str) -> dict:
    raw = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()
    return json.loads(raw)


def _identify_files(intent: str, file_list: list, agent_name: str, claude_client) -> list:
    listing = "\n".join(file_list[:80])
    try:
        resp = claude_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=FILE_SELECTOR_SYSTEM.format(n=MAX_FILES_READ),
            messages=[{"role": "user", "content": f"Agent: {agent_name}\nIntent: {intent}\n\nFiles:\n{listing}"}],
        )
        raw = resp.content[0].text.strip()
        raw = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()
        return json.loads(raw)[:MAX_FILES_READ]
    except Exception:
        return file_list[:2]


def _list_files(base_dir: Path, scopes: list) -> list:
    """List files matching the agent's file_scope patterns."""
    files = []
    for scope in scopes:
        scope_path = base_dir / scope
        if scope_path.is_dir():
            for f in scope_path.rglob("*"):
                if f.is_file() and not any(p in str(f) for p in [".git", "node_modules", "__pycache__", ".next"]):
                    files.append(str(f.relative_to(base_dir)))
        elif "*" in scope:
            import glob
            for f in glob.glob(str(base_dir / scope)):
                p = Path(f)
                if p.is_file():
                    files.append(str(p.relative_to(base_dir)))
        elif scope_path.is_file():
            files.append(str(scope_path.relative_to(base_dir)))
    return sorted(set(files))


# ── CONTENT LOG ───────────────────────────────────────────────────────────────

def log_approved_content(proposal: dict) -> None:
    entries = []
    if CONTENT_LOG.exists():
        try:
            entries = json.loads(CONTENT_LOG.read_text())
        except Exception:
            pass
    entries.append({
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "intent":    proposal.get("intent", ""),
        "draft":     proposal.get("draft", ""),
        "scores":    proposal.get("scores", {}),
    })
    CONTENT_LOG.write_text(json.dumps(entries, indent=2))


def _get_approved_content(n: int = 5) -> str:
    if not CONTENT_LOG.exists():
        return ""
    try:
        entries = json.loads(CONTENT_LOG.read_text())
        recent  = entries[-n:]
        lines   = ["Previously approved posts (match this voice):"]
        for e in recent:
            lines.append(f"\n---\n{e.get('draft', '')}")
        return "\n".join(lines)
    except Exception:
        return ""


# ── AGENT RUNNERS ─────────────────────────────────────────────────────────────

def _run_code_agent(agent_cfg: dict, intent: str, claude_client) -> dict:
    base    = Path(agent_cfg["git_dir"]) if agent_cfg.get("git_dir") else BASE_DIR
    scopes  = agent_cfg.get("file_scope", [])
    all_files = _list_files(base, scopes)
    relevant  = _identify_files(intent, all_files, agent_cfg["name"], claude_client)

    file_contents = ""
    files_read    = []
    for rel in relevant:
        full = base / rel
        file_contents += f"\n\n=== {rel} ===\n{_read_file(full)}"
        files_read.append(rel)

    prompt = f"Intent: {intent}\n\nFile contents:{file_contents}"

    try:
        resp = claude_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=agent_cfg["system_prompt"],
            messages=[{"role": "user", "content": prompt}],
        )
        proposal = _parse_json(resp.content[0].text)
    except Exception as e:
        proposal = {
            "summary": f"Proposal error: {e}",
            "files_to_change": [], "plan": [],
            "confidence": 0, "failure_point": str(e),
            "rollback": "no changes made",
        }

    proposal.update({
        "agent":      agent_cfg["name"],
        "agent_type": "code",
        "intent":     intent,
        "files_read": files_read,
        "git_dir":    str(base),
    })
    return proposal


def _run_report_agent(agent_cfg: dict, intent: str, claude_client) -> dict:
    try:
        resp = claude_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=agent_cfg["system_prompt"],
            messages=[{"role": "user", "content": f"Request: {intent}"}],
        )
        report = _parse_json(resp.content[0].text)
    except Exception as e:
        report = {
            "summary": f"Report error: {e}",
            "signal_strength": 0, "findings": [],
            "recommendation": "Error — check logs",
            "confidence": 0,
        }

    report.update({"agent": agent_cfg["name"], "agent_type": "report", "intent": intent})
    return report


def _run_content_agent(agent_cfg: dict, intent: str, claude_client) -> dict:
    approved = _get_approved_content(5)
    prompt   = f"Content request: {intent}"
    if approved:
        prompt += f"\n\n{approved}"

    try:
        resp = claude_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=agent_cfg["system_prompt"],
            messages=[{"role": "user", "content": prompt}],
        )
        draft = _parse_json(resp.content[0].text)
    except Exception as e:
        draft = {
            "summary": f"Draft error: {e}",
            "draft": "", "scores": {},
            "alternative_angle": "",
            "time_sensitive": False, "time_window": "",
        }

    draft.update({"agent": agent_cfg["name"], "agent_type": "content", "intent": intent})
    return draft


# ── DISPATCHER ────────────────────────────────────────────────────────────────

def run_agent(agent_name: str, intent: str, claude_client) -> dict:
    agents = config.load_agents()
    cfg    = next((a for a in agents if a["name"] == agent_name), None)
    if not cfg:
        return {"agent": agent_name, "intent": intent, "error": f"Agent '{agent_name}' not found in agents.yaml"}

    agent_type = cfg.get("type", "code")
    if agent_type == "code":
        return _run_code_agent(cfg, intent, claude_client)
    elif agent_type == "report":
        return _run_report_agent(cfg, intent, claude_client)
    elif agent_type == "content":
        return _run_content_agent(cfg, intent, claude_client)
    return {"agent": agent_name, "intent": intent, "error": f"Unknown agent type: {agent_type}"}


# ── FORMATTER ─────────────────────────────────────────────────────────────────

def format_proposal(proposal: dict) -> str:
    agent      = proposal.get("agent", "?")
    agent_type = proposal.get("agent_type", "code")
    summary    = proposal.get("summary", "")
    confidence = proposal.get("confidence", 0)

    lines = [f"PROPOSAL — {agent}", "─────────────────────", summary, f"Confidence: {confidence}%", ""]

    if "error" in proposal or confidence == 0:
        lines.append("/veto to cancel")
        return "\n".join(lines)

    if agent_type == "code":
        files_read     = proposal.get("files_read", [])
        files_to_change = proposal.get("files_to_change", [])
        plan           = proposal.get("plan", [])
        failure        = proposal.get("failure_point", "")
        rollback       = proposal.get("rollback", "")

        if files_read:       lines.append(f"Read: {', '.join(files_read)}")
        if files_to_change:  lines.append(f"Stage: {', '.join(files_to_change)}")
        if plan:
            lines.append(""); lines.append("Plan:")
            for i, step in enumerate(plan, 1):
                lines.append(f"  {i}. {step}")
        if failure:   lines.append(f"\nRisk: {failure}")
        if rollback:  lines.append(f"Rollback: {rollback}")
        if proposal.get("affects_live_process"):
            lines.append("\n⚠️  May affect a live running process.")

    elif agent_type == "report":
        strength   = proposal.get("signal_strength", 0)
        findings   = proposal.get("findings", [])
        rec        = proposal.get("recommendation", "")
        lines.append(f"Signal: {strength}/10")
        if findings:
            lines.append("")
            for f in findings: lines.append(f"• {f}")
        if rec: lines.append(f"\nAction: {rec}")

    elif agent_type == "content":
        draft  = proposal.get("draft", "")
        scores = proposal.get("scores", {})
        alt    = proposal.get("alternative_angle", "")
        ts     = proposal.get("time_sensitive", False)
        if ts:  lines.append(f"⏰ Time sensitive: {proposal.get('time_window', '')}")
        lines.append(""); lines.append(draft)
        if scores:
            d = scores.get("directness", 0)
            a = scores.get("authority", 0)
            n = scores.get("no_fluff", 0)
            lines.append(f"\nDirect: {d}/10  Authority: {a}/10  No fluff: {n}/10")
        if alt: lines.append(f"\nAlt: {alt}")

    lines.append(""); lines.append("/approve  |  /veto")
    return "\n".join(lines)
