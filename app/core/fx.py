"""為替レート (仕入通貨 → 円) の取得・キャッシュ・安全バッファ。

原価計算に使うレートは次の順で決める (``base_rate``):

  1. 環境変数 ``{通貨}_TO_JPY`` (例: ``EUR_TO_JPY=180``) — 手動で固定したいとき
  2. キャッシュ ``data/fx_rates.json`` — ``refresh_rates()`` が ECB 参考レートで更新
     (古くなっていても使うが、``FX_MAX_AGE_DAYS`` を超えたら警告を出す)
  3. ``app.core.pricing.DEFAULT_EXCHANGE_RATES`` (高めの固定値 = 安全側の最終手段)

原価計算 (``effective_rate``) には、さらに安全バッファ ``FX_BUFFER_PCT`` (既定 3%) を
掛ける。仕入れはカードの請求日のレート (+ カード会社のスプレッド) になり、
出品から購入までの数週間で円安に振れても赤字にならないようにするため。
バッファは手動固定 (1) にも掛かる。0 にしたいときは ``FX_BUFFER_PCT=0``。

ネットワークアクセスは ``refresh_rates()`` を明示的に呼んだときだけ行う
(``calculate_pricing`` などの計算関数は通信しない = テストや --test モードが安定する)。
``scripts/run_autopilot.py`` が本番実行の最初に 1 回呼ぶ。手動更新は
``python3 scripts/update_fx_rates.py``。
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CACHE_PATH = PROJECT_ROOT / "data" / "fx_rates.json"

ECB_DAILY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

DEFAULT_BUFFER_PCT = 0.03
DEFAULT_MAX_AGE_DAYS = 7

_warned_stale: set[str] = set()


# ---------------------------------------------------------------------------
# 設定値
# ---------------------------------------------------------------------------

def cache_path() -> Path:
    """キャッシュファイルの場所 (``FX_CACHE_PATH`` で変更可)。"""
    env = os.getenv("FX_CACHE_PATH")
    return Path(env) if env else DEFAULT_CACHE_PATH


def buffer_pct() -> float:
    """原価計算用の安全バッファ (0.03 = 3%)。不正値は既定値。負値は 0。"""
    raw = os.getenv("FX_BUFFER_PCT")
    if raw is None or raw.strip() == "":
        return DEFAULT_BUFFER_PCT
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_BUFFER_PCT
    # "3" と書かれたら 3% とみなす (0.03 と 3 の書き間違いで原価が 4 倍になるのを防ぐ)
    if value >= 1.0:
        value = value / 100.0
    return max(0.0, min(value, 0.5))


def max_age_days() -> int:
    try:
        return int(os.getenv("FX_MAX_AGE_DAYS", DEFAULT_MAX_AGE_DAYS))
    except ValueError:
        return DEFAULT_MAX_AGE_DAYS


# ---------------------------------------------------------------------------
# ECB 参考レートの解析 (純粋関数)
# ---------------------------------------------------------------------------

_CUBE_TIME_RE = re.compile(r"<Cube\s+time=['\"](\d{4}-\d{2}-\d{2})['\"]")
_CUBE_RATE_RE = re.compile(r"<Cube\s+currency=['\"]([A-Z]{3})['\"]\s+rate=['\"]([0-9.]+)['\"]")


def parse_ecb_daily_xml(xml_text: str) -> dict:
    """ECB の eurofxref-daily.xml を {"date", "jpy_per": {通貨: 円}} に変換する。

    ECB は「1 EUR = x 通貨」で公表するので、円建てクロスレートは
    JPY_per_X = (JPY/EUR) / (X/EUR) で求める。JPY が無ければ ValueError。
    """
    m = _CUBE_TIME_RE.search(xml_text or "")
    rates = {cur: float(val) for cur, val in _CUBE_RATE_RE.findall(xml_text or "")}
    if "JPY" not in rates or not m:
        raise ValueError("ECB XML に JPY レートまたは日付がありません")
    jpy_per_eur = rates["JPY"]
    jpy_per = {"EUR": round(jpy_per_eur, 4)}
    for cur, per_eur in rates.items():
        if cur == "JPY" or per_eur <= 0:
            continue
        jpy_per[cur] = round(jpy_per_eur / per_eur, 4)
    return {"date": m.group(1), "jpy_per": jpy_per}


# ---------------------------------------------------------------------------
# キャッシュ
# ---------------------------------------------------------------------------

def load_cache(path: Optional[Path] = None) -> dict:
    p = path or cache_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict) or not isinstance(data.get("jpy_per"), dict):
        return {}
    return data


def save_cache(data: dict, path: Optional[Path] = None) -> Path:
    p = path or cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def cache_age_days(data: dict, today: Optional[date] = None) -> Optional[int]:
    try:
        d = datetime.strptime(str(data.get("date")), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    return ((today or date.today()) - d).days


def refresh_rates(timeout: float = 10.0, path: Optional[Path] = None) -> dict:
    """ECB 参考レートを取得してキャッシュに保存する。

    失敗しても例外は投げず {"ok": False, "error": ...} を返す
    (既存キャッシュ → 固定値の順で計算は続行できるため)。
    """
    try:
        import requests

        resp = requests.get(ECB_DAILY_URL, timeout=timeout,
                            headers={"User-Agent": "buyma-automation/fx (+ECB reference rates)"})
        resp.raise_for_status()
        parsed = parse_ecb_daily_xml(resp.text)
    except Exception as exc:  # noqa: BLE001 - 通信・解析失敗はすべて fallback へ
        return {"ok": False, "error": str(exc)}
    parsed.update({
        "source": "ECB euro foreign exchange reference rates",
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    })
    saved = save_cache(parsed, path)
    return {"ok": True, "date": parsed["date"], "path": str(saved),
            "EUR": parsed["jpy_per"].get("EUR"), "USD": parsed["jpy_per"].get("USD"),
            "GBP": parsed["jpy_per"].get("GBP")}


# ---------------------------------------------------------------------------
# レート解決
# ---------------------------------------------------------------------------

def base_rate_with_origin(currency: str) -> tuple[float, str]:
    """(バッファ前のレート, 出所) を返す。出所: env / cache:<日付> / default。"""
    from app.core.pricing import DEFAULT_EXCHANGE_RATES

    cur = (currency or "").upper()
    if cur == "JPY":
        return 1.0, "jpy"
    env_val = os.getenv(f"{cur}_TO_JPY")
    if env_val:
        try:
            v = float(env_val)
            if v > 0:
                return v, "env"
        except ValueError:
            pass
    data = load_cache()
    cached = (data.get("jpy_per") or {}).get(cur)
    if cached:
        age = cache_age_days(data)
        if age is not None and age > max_age_days() and cur not in _warned_stale:
            _warned_stale.add(cur)
            print(f"⚠️ 為替キャッシュが {age} 日前のものです ({data.get('date')})。"
                  "python3 scripts/update_fx_rates.py で更新してください。", file=sys.stderr)
        return float(cached), f"cache:{data.get('date')}"
    if cur not in DEFAULT_EXCHANGE_RATES:
        # 未知通貨を 1 円換算すると原価がほぼ 0 になり大赤字出品になる → 止める
        raise ValueError(f"通貨 {cur!r} の為替レートがありません ({cur}_TO_JPY を設定してください)")
    return float(DEFAULT_EXCHANGE_RATES[cur]), "default"


def base_rate(currency: str) -> float:
    return base_rate_with_origin(currency)[0]


def effective_rate(currency: str) -> float:
    """原価計算に使うレート = base_rate × (1 + FX_BUFFER_PCT)。JPY は常に 1。"""
    cur = (currency or "").upper()
    if cur == "JPY":
        return 1.0
    return round(base_rate(cur) * (1.0 + buffer_pct()), 4)


def describe(currency: str) -> str:
    """ログ用の 1 行説明。"""
    rate, origin = base_rate_with_origin(currency)
    return (f"1 {currency.upper()} = ¥{rate:.2f} ({origin}) × バッファ {buffer_pct():.1%}"
            f" → 原価計算 ¥{effective_rate(currency):.2f}")
