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
    """python-dotenv が無い環境用の簡易パーサ (KEY=VALUE、export、引用符、行末コメント)。"""
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    if line.startswith("export "):
        line = line[len("export "):]
    key, _, value = line.partition("=")
    key = key.strip()
    value = value.strip()
    if value[:1] in ("'", '"'):
        q = value[0]
        end = value.find(q, 1)
        value = value[1:end] if end > 0 else value[1:]
    elif " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return (key, value) if key else None


def _read_env_file(p: Path) -> dict[str, str]:
    try:
        from dotenv import dotenv_values  # requirements.txt にある正式なパーサを優先
        return {k: v for k, v in dotenv_values(p).items() if k and v is not None}
    except ImportError:
        out = {}
        for line in p.read_text(encoding="utf-8").splitlines():
            kv = _parse_line(line)
            if kv:
                out[kv[0]] = kv[1]
        return out


def load_project_env(path: Optional[str | Path] = None) -> list[str]:
    """.env を読み、未設定のキーだけ os.environ に入れる。入れたキー名のリストを返す (値は返さない)。"""
    p = Path(path) if path else PROJECT_ROOT / ".env"
    if not p.exists():
        return []
    loaded = []
    for key, value in _read_env_file(p).items():
        if key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded
