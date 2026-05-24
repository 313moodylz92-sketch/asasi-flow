#!/usr/bin/env python3
"""
ASASI Flow — Execution Engine
/approve generates code diff → /confirm writes + stages.
/rollback restores from backup.
"""

import difflib
import re
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent
BAK_DIR  = BASE_DIR / ".asasi_bak"

_EXEC_SYSTEM = """You are executing an approved code change.
You receive the original file content and the approved plan.
Output the complete new file content — nothing else.

RULES:
- No markdown fences. No explanation. Raw file content only.
- Implement the plan exactly — nothing more, nothing less.
- Preserve all existing functionality not in scope.
- Match existing code style, indentation, and formatting."""


def _ensure_bak():
    BAK_DIR.mkdir(exist_ok=True)


def _bak_name(rel_path: str) -> str:
    return rel_path.replace("/", "_").replace("\\", "_") + ".bak"


def _generate_diff(original: str, new: str, filename: str) -> str:
    orig  = original.splitlines(keepends=True)
    new_l = new.splitlines(keepends=True)
    diff  = list(difflib.unified_diff(orig, new_l, fromfile=f"a/{filename}", tofile=f"b/{filename}", n=3))
    if not diff:
        return "(no changes detected)"
    result = "".join(diff)
    if len(result) > 3200:
        result = result[:3200] + "\n... [diff truncated]"
    return result


def _generate_new_content(original: str, plan: list, system_prompt: str, claude_client) -> str:
    plan_str = "\n".join(f"{i+1}. {step}" for i, step in enumerate(plan))
    prompt   = f"Original file:\n{original}\n\nApproved plan:\n{plan_str}\n\nOutput the complete new file content."
    resp     = claude_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": prompt}],
    )
    content = resp.content[0].text.strip()
    content = re.sub(r"^```[a-zA-Z]*\n", "", content)
    content = re.sub(r"\n```$", "", content)
    return content


def prepare(proposal: dict, claude_client) -> dict:
    """Generate code for all files in proposal. Returns bundle for /confirm."""
    _ensure_bak()
    agent_type = proposal.get("agent_type", "code")
    if agent_type != "code":
        return {"agent": proposal.get("agent"), "intent": proposal.get("intent"),
                "files": [], "non_code": True}

    git_dir         = Path(proposal.get("git_dir", "."))
    files_to_change = proposal.get("files_to_change", [])
    plan            = proposal.get("plan", [])
    results         = []

    for rel in files_to_change:
        full = git_dir / rel
        if not full.exists():
            results.append({"path": rel, "error": f"File not found: {full}"})
            continue
        original = full.read_text(encoding="utf-8")
        try:
            new_content = _generate_new_content(original, plan, _EXEC_SYSTEM, claude_client)
            diff        = _generate_diff(original, new_content, rel)
            results.append({
                "path":        rel,
                "full_path":   str(full),
                "git_dir":     str(git_dir),
                "original":    original,
                "new_content": new_content,
                "diff":        diff,
            })
        except Exception as e:
            results.append({"path": rel, "error": str(e)})

    return {
        "agent":  proposal.get("agent"),
        "intent": proposal.get("intent"),
        "files":  results,
    }


def confirm(bundle: dict) -> tuple:
    """Write files, backup originals, git stage. Returns (success, report, staged)."""
    _ensure_bak()
    staged, errors = [], []

    for f in bundle.get("files", []):
        if "error" in f:
            errors.append(f"Skipped {f['path']}: {f['error']}")
            continue

        full    = Path(f["full_path"])
        git_dir = f["git_dir"]
        bak     = BAK_DIR / _bak_name(f["path"])

        bak.write_text(f["original"], encoding="utf-8")
        full.write_text(f["new_content"], encoding="utf-8")

        try:
            result = subprocess.run(
                ["git", "add", str(full)],
                cwd=git_dir, capture_output=True, text=True, timeout=30,
            )
            ok = result.returncode == 0
        except subprocess.TimeoutExpired:
            ok = False
            result = type("R", (), {"stderr": "git timed out"})()
        if ok:
            staged.append({"path": f["path"], "full_path": str(full),
                           "bak": str(bak), "git_dir": git_dir})
        else:
            full.write_text(f["original"], encoding="utf-8")
            errors.append(f"git add failed on {f['path']}: {result.stderr.strip()}")

    lines = []
    if staged:
        lines.append(f"Staged {len(staged)} file(s):")
        for s in staged: lines.append(f"  {s['path']}")
        lines.append("\nReview: git diff --staged\nPush when ready.")
    if errors:
        lines.append("\nErrors:")
        for e in errors: lines.append(f"  {e}")

    return len(staged) > 0, "\n".join(lines), staged


def rollback(staged: list) -> str:
    if not staged:
        return "Nothing to roll back."
    lines = []
    for s in staged:
        full = Path(s["full_path"])
        bak  = Path(s["bak"])
        try:
            if bak.exists():
                full.write_text(bak.read_text(encoding="utf-8"), encoding="utf-8")
            subprocess.run(["git", "restore", "--staged", str(full)],
                           cwd=s["git_dir"], capture_output=True, timeout=30)
            lines.append(f"Restored: {s['path']}")
        except Exception as e:
            lines.append(f"Rollback failed on {s['path']}: {e}")
    return "\n".join(lines)


def format_diff_message(bundle: dict) -> list:
    agent  = bundle.get("agent", "?")
    intent = bundle.get("intent", "")
    files  = bundle.get("files", [])

    messages = [f"CODE DIFF — {agent}\n─────────────────────\nIntent: {intent}\n"]

    if bundle.get("non_code"):
        messages.append("/approve  |  /veto")
        return messages

    has_errors = any("error" in f for f in files)
    if has_errors:
        for f in files:
            if "error" in f:
                messages.append(f"Error on {f['path']}:\n{f['error']}")
        messages.append("/veto to cancel")
        return messages

    for f in files:
        messages.append(f"File: {f['path']}\n\n{f.get('diff', '(no diff)')}")

    messages.append("/confirm to write + stage  |  /veto to discard")
    return messages
