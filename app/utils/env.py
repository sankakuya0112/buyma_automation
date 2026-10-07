"""プロジェクト直下の .env を読み込む (シェルで設定済みの値は上書きしない)。

為替 (EUR_TO_JPY / FX_BUFFER_PCT)、手数料 (BUYMA_TRANSFER_FEE_JPY / BUYMA_FIXED_FEE_ENABLED)、
BUYMA_ALLOW_BROWSER_AUTOMATION などを .env に書いた場合に、利益計算・判定の **前に** 反映させる。
2026-10 以前は AI 系と buyma_auto_listing だけが .env を読んでおり、利益計算は .env を無視していた。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _parse_line(line: str) -> Optional[tuple[str, str]]:
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    if line.startswith("export "):
        line = line[len("export "):]
    key, _, value = line.partition("=")
    key = key.strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    elif " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return (key, value) if key else None


def load_project_env(path: Optional[str | Path] = None) -> list[str]:
    """.env を読み、未設定のキーだけ os.environ に入れる。入れたキー名のリストを返す (値は返さない)。"""
    p = Path(path) if path else PROJECT_ROOT / ".env"
    if not p.exists():
        return []
    loaded = []
    for line in p.read_text(encoding="utf-8").splitlines():
        kv = _parse_line(line)
        if not kv:
            continue
        key, value = kv
        if key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded
