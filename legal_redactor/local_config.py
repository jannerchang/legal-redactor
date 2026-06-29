from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class JsonConfigDiagnostic:
    env_var: str
    path: Path
    source: str
    state: str
    value: dict[str, Any]
    error: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "env_var": self.env_var,
            "path": str(self.path),
            "source": self.source,
            "state": self.state,
            "error": self.error,
        }


def diagnose_json_config(
    env_var: str,
    default_filename: str,
    *,
    environ: Mapping[str, str] | None = None,
    config_dir: str | Path | None = None,
) -> JsonConfigDiagnostic:
    env = os.environ if environ is None else environ
    raw_path = env.get(env_var)
    if raw_path:
        config_path = Path(raw_path).expanduser()
        source = "env"
    else:
        base_dir = Path(config_dir).expanduser() if config_dir is not None else Path("~/.config/legal-redactor").expanduser()
        config_path = base_dir / default_filename
        source = "default"

    if not config_path.exists():
        return JsonConfigDiagnostic(env_var, config_path, source, "missing", {})
    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return JsonConfigDiagnostic(env_var, config_path, source, "invalid_json", {})
    except Exception as exc:
        return JsonConfigDiagnostic(env_var, config_path, source, "error", {}, type(exc).__name__)
    if not isinstance(value, dict):
        return JsonConfigDiagnostic(env_var, config_path, source, "non_object", {})
    return JsonConfigDiagnostic(env_var, config_path, source, "ready", value)


def load_json_config(env_var: str, default_filename: str) -> dict[str, Any]:
    return diagnose_json_config(env_var, default_filename).value


def config_value(config: dict[str, Any], key: str, default: str = "") -> str:
    value = config.get(key, default)
    return str(value) if value is not None else default
