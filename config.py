#!/usr/bin/env python3
"""
ASASI Flow — Config loader
Reads agents.yaml + .env, resolves ${VAR} references, returns agent configs.
"""

import os
import re
import yaml
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")


def _resolve(value: str) -> str:
    """Replace ${VAR} references with env values."""
    if not isinstance(value, str):
        return value
    return re.sub(
        r"\$\{(\w+)\}",
        lambda m: os.getenv(m.group(1), m.group(0)),
        value
    )


def load_agents() -> list:
    """Load and resolve agent configs from agents.yaml."""
    path = BASE_DIR / "agents.yaml"
    if not path.exists():
        raise FileNotFoundError("agents.yaml not found. Copy agents.yaml.example and configure it.")

    with open(path) as f:
        data = yaml.safe_load(f)

    agents = []
    project_name = os.getenv("PROJECT_NAME", "my project")
    stack        = os.getenv("STACK", "")
    brand_voice  = os.getenv("BRAND_VOICE", "Direct. Clear. No fluff.")
    audience     = os.getenv("AUDIENCE", "developers and founders")

    for a in data.get("agents", []):
        system_prompt = a.get("system_prompt", "")
        system_prompt = system_prompt.replace("{project_name}", project_name)
        system_prompt = system_prompt.replace("{stack}", stack)
        system_prompt = system_prompt.replace("{brand_voice}", brand_voice)
        system_prompt = system_prompt.replace("{audience}", audience)

        agents.append({
            "name":          a["name"],
            "description":   a.get("description", ""),
            "type":          a.get("type", "code"),
            "file_scope":    a.get("file_scope", []),
            "git_dir":       _resolve(a.get("git_dir", "")),
            "system_prompt": system_prompt.strip(),
        })

    return agents


def get_env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def cost_cap() -> float:
    return float(os.getenv("COST_CAP_USD", "3.00"))


def learning_threshold() -> int:
    return int(os.getenv("LEARNING_THRESHOLD", "50"))
