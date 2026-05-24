#!/usr/bin/env python3
"""
ASASI Flow — Telegram-native multi-agent system.
Commands via natural language. Agents propose, you approve. System learns.

Commands:
  /agent    — system status
  /log      — last 5 routing decisions
  /learn    — trigger learning loop manually
  /rollback — restore last staged files
  /approve  — review proposal → generate code diff
  /confirm  — write + stage files
  /veto     — discard proposal or diff
  /reset    — clear conversation history
  /help     — this message
"""

import json
import os
import time
import requests
import anthropic
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import config, router, agents, executor, learner

TOKEN   = config.get_env("TELEGRAM_BOT_TOKEN")
CHAT_ID = config.get_env("TELEGRAM_CHAT_ID")
BASE    = f"https://api.telegram.org/bot{TOKEN}"
claude  = anthropic.Anthropic(api_key=config.get_env("ANTHROPIC_API_KEY"))

history: list = []

HELP_TEXT = """ASASI Flow

Agents:
  Just type — router classifies and routes automatically

Approval flow:
  /approve  — review proposal, generate code diff
  /confirm  — write + stage files
  /veto     — discard proposal or diff
  /rollback — restore last staged files

System:
  /agent    — system status
  /log      — last 5 routing decisions
  /learn    — trigger learning loop now
  /reset    — clear conversation history
  /help     — this message"""

# ── PERSISTENT STATE ──────────────────────────────────────────────────────────

_DATA_DIR = Path(__file__).parent

def _load_json(path: Path) -> dict:
    try:
        if path.exists(): return json.loads(path.read_text())
    except Exception: pass
    return {}

def _save_json(path: Path, data: dict) -> None:
    try: path.write_text(json.dumps(data, indent=2))
    except Exception: pass

_pending_proposal  = _load_json(_DATA_DIR / "pending_proposals.json")
_pending_execution = _load_json(_DATA_DIR / "pending_executions.json")
_last_staged       = _load_json(_DATA_DIR / "last_staged.json")
_pending_confirm   = {}


# ── TELEGRAM ──────────────────────────────────────────────────────────────────

def send(text: str) -> None:
    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        try:
            requests.post(f"{BASE}/sendMessage",
                          json={"chat_id": CHAT_ID, "text": chunk}, timeout=10)
        except Exception:
            pass


def send_typing() -> None:
    try:
        requests.post(f"{BASE}/sendChatAction",
                      json={"chat_id": CHAT_ID, "action": "typing"}, timeout=5)
    except Exception:
        pass


def get_updates(offset: int) -> list:
    try:
        r = requests.get(f"{BASE}/getUpdates",
                         params={"offset": offset, "timeout": 30}, timeout=35)
        return r.json().get("result", [])
    except Exception:
        return []


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _log(agent_name, intent, outcome):
    router.log_decision({"agent": agent_name, "intent": intent,
                         "input": intent, "outcome": outcome, "timestamp": _ts()})


def _check_learning():
    decisions = router.load_log()
    if learner.should_learn(len(decisions)):
        learner.run(claude, send, decisions)


def _run_agent_proposal(agent_name: str, intent: str, chat_id: str):
    send(f"{agent_name} reading files...")
    send_typing()
    try:
        proposal = agents.run_agent(agent_name, intent, claude)
        msg      = agents.format_proposal(proposal)
        _pending_proposal[chat_id] = proposal
        _save_json(_DATA_DIR / "pending_proposals.json", _pending_proposal)
        send(msg)
    except Exception as e:
        send(f"{agent_name} error: {e}")


def ask_claude(user_text: str):
    global history
    history.append({"role": "user", "content": user_text})
    if len(history) > 20:
        history = history[-20:]
    send_typing()
    try:
        resp  = claude.messages.create(
            model="claude-sonnet-4-6", max_tokens=1024,
            system=f"You are Claude, an AI assistant. Project: {config.get_env('PROJECT_NAME', 'my project')}. Be concise and direct.",
            messages=history,
        )
        reply = resp.content[0].text
    except Exception as e:
        reply = f"Error: {e}"
    history.append({"role": "assistant", "content": reply})
    send(reply)


# ── HANDLE ────────────────────────────────────────────────────────────────────

def handle(text: str, chat_id: str):
    global history, _pending_proposal, _pending_execution, _last_staged, _pending_confirm
    t = text.strip().lower()

    # /confirm — write + stage OR override cost cap
    if t == "/confirm":
        if chat_id in _pending_execution:
            bundle = _pending_execution.pop(chat_id)
            _save_json(_DATA_DIR / "pending_executions.json", _pending_execution)
            send("Writing files...")
            success, report, staged = executor.confirm(bundle)
            if staged:
                _last_staged[chat_id] = staged
                _save_json(_DATA_DIR / "last_staged.json", _last_staged)
            _log(bundle.get("agent"), bundle.get("intent"), "approved" if success else "exec_failed")
            send(report)
            _check_learning()
            return
        if chat_id in _pending_confirm:
            decision = _pending_confirm.pop(chat_id)
            _log(decision.get("agent"), decision.get("intent", ""), "cost_confirmed")
            _run_agent_proposal(decision.get("agent"), decision.get("intent", text), chat_id)
            return
        send("Nothing pending confirmation.")
        return

    # /approve — generate diff for code agents, approve directly for others
    if t == "/approve":
        if chat_id in _pending_proposal:
            proposal   = _pending_proposal.pop(chat_id)
            _save_json(_DATA_DIR / "pending_proposals.json", _pending_proposal)
            agent_name = proposal.get("agent")
            agent_type = proposal.get("agent_type", "code")

            if agent_type == "code":
                send("Generating code diff...")
                send_typing()
                try:
                    bundle = executor.prepare(proposal, claude)
                    _pending_execution[chat_id] = bundle
                    _save_json(_DATA_DIR / "pending_executions.json", _pending_execution)
                    for msg in executor.format_diff_message(bundle):
                        send(msg)
                except Exception as e:
                    send(f"Code generation error: {e}")
            else:
                _log(agent_name, proposal.get("intent", ""), "approved")
                if agent_type == "content" and proposal.get("draft"):
                    agents.log_approved_content(proposal)
                    send("Approved. Draft saved to content log.")
                else:
                    send("Approved and logged.")
                _check_learning()
            return
        send("No pending proposal.")
        return

    # /veto
    if t == "/veto":
        if chat_id in _pending_execution:
            bundle = _pending_execution.pop(chat_id)
            _save_json(_DATA_DIR / "pending_executions.json", _pending_execution)
            _log(bundle.get("agent"), bundle.get("intent"), "vetoed")
            send("Diff discarded. No files written.")
            _check_learning()
            return
        if chat_id in _pending_proposal:
            proposal = _pending_proposal.pop(chat_id)
            _save_json(_DATA_DIR / "pending_proposals.json", _pending_proposal)
            _log(proposal.get("agent"), proposal.get("intent", ""), "vetoed")
            send("Vetoed. Decision logged.")
            _check_learning()
            return
        send("Nothing to veto.")
        return

    # /rollback
    if t == "/rollback":
        staged = _last_staged.get(chat_id, [])
        result = executor.rollback(staged)
        if staged:
            _last_staged.pop(chat_id, None)
            _save_json(_DATA_DIR / "last_staged.json", _last_staged)
        send(result)
        return

    # /cancel (cost cap)
    if t == "/cancel" and chat_id in _pending_confirm:
        decision = _pending_confirm.pop(chat_id)
        _log(decision.get("agent"), decision.get("intent", ""), "cancelled")
        send("Cancelled.")
        return

    # Hard commands
    if t == "/agent":     send(router.format_status()); return
    if t == "/log":       send(router.format_recent_log()); return
    if t == "/learn":     learner.run(claude, send, router.load_log()); return
    if t == "/help":      send(HELP_TEXT); return
    if t == "/reset":     history = []; send("Conversation reset."); return

    # Route through agent classifier
    send_typing()
    decision   = router.route(text, claude)
    agent_name = decision.get("agent", "NONE")
    intent     = decision.get("intent", text)
    cost       = float(decision.get("estimated_cost_usd") or 0.0)

    if agent_name != "NONE":
        if cost > config.cost_cap():
            _pending_confirm[chat_id] = decision
            send(f"Estimated cost ${cost:.2f} exceeds ${config.cost_cap():.2f} cap.\n/confirm to proceed | /cancel to abort")
        else:
            router.log_decision({**decision, "outcome": "running"})
            _run_agent_proposal(agent_name, intent, chat_id)
    else:
        router.log_decision(decision)
        ask_claude(text)


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print("ASASI Flow online.")
    send("ASASI Flow online. Type anything to start.")
    offset = 0
    while True:
        updates = get_updates(offset)
        for update in updates:
            offset  = update["update_id"] + 1
            msg     = update.get("message", {})
            chat_id = str(msg.get("chat", {}).get("id", ""))
            text    = msg.get("text", "")
            if chat_id == CHAT_ID and text:
                try:
                    handle(text, chat_id)
                except Exception as e:
                    send(f"Internal error: {e}")
        time.sleep(1)


if __name__ == "__main__":
    main()
