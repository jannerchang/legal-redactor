from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def load_json_config(env_var: str, default_filename: str) -> dict[str, Any]:
    path = os.environ.get(env_var)
    if path:
        config_path = Path(path).expanduser()
    else:
        config_path = Path("~/.config/legal-redactor").expanduser() / default_filename
    if not config_path.exists():
        return {}
    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def config_value(config: dict[str, Any], key: str, default: str = "") -> str:
    value = config.get(key, default)
    return str(value) if value is not None else default
