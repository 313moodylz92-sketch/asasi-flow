#!/usr/bin/env python3
"""
ASASI Flow — Learning Loop
Reads decision log → analyzes approve/veto patterns → rewrites routing rules.
Auto-triggers at LEARNING_THRESHOLD decisions. Manual: /learn.
"""

import json
import re
from datetime import datetime
from pathlib import Path
import config, router

LEARNING_SYSTEM = """You are the ASASI Flow routing optimizer.

You receive a log of agent routing decisions with outcomes (approved/vetoed/cancelled/running)
and the current routing descriptions.

Analyze the patterns:
- Which agents were repeatedly vetoed? Why?
- Which inputs were misrouted to the wrong agent?
- What gaps exist in the current descriptions that caused confusion?

Return ONLY valid JSON — no markdown, no explanation:
{
  "version": <current_version + 1>,
  "updated": "<YYYY-MM-DD>",
  "notes": "2-3 sentences: what patterns you found and what you changed",
  "<AgentName>": "updated routing description",
  "<AgentName2>": "updated routing description"
}

Only include agents that need updated descriptions. Keep unchanged agents out of the response."""


def should_learn(decision_count: int) -> bool:
    return decision_count >= config.learning_threshold()


def run(claude_client, send_fn, decisions: list) -> None:
    send_fn(f"Learning loop: analyzing {len(decisions)} decisions...")

    summary = [
        {"agent": d.get("agent"), "input": (d.get("input") or "")[:100],
         "outcome": d.get("outcome"), "ts": (d.get("timestamp") or "")[:10]}
        for d in decisions
    ]

    current = router.load_rules()
    agents  = config.load_agents()
    current_descs = {a["name"]: a["description"] for a in agents}
    current_descs.update(current)

    prompt = (
        f"Decision log ({len(decisions)} entries):\n"
        f"{json.dumps(summary, indent=2)}\n\n"
        f"Current routing descriptions:\n"
        f"{json.dumps(current_descs, indent=2)}"
    )

    try:
        resp = claude_client.messages.create(
            model="claude-opus-4-7",
            max_tokens=1024,
            system=[{"type": "text", "text": LEARNING_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        raw = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()
        updates = json.loads(raw)

        new_rules = dict(current)
        new_rules.update(updates)
        new_rules["version"] = current.get("version", 1) + 1
        new_rules["updated"] = datetime.utcnow().isoformat()[:10]
        router.save_rules(new_rules)

        send_fn(
            f"Routing rules updated to v{new_rules['version']}.\n\n"
            f"Changes: {updates.get('notes', 'No notes.')}"
        )
    except Exception as e:
        send_fn(f"Learning loop error: {e}")
