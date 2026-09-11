"""AIClient — Claude API の薄いラッパー (キャッシュ・台帳・予算・オフライン退避つき)。

設計原則:
  1. API キーが無い / 予算超過 / 通信失敗 のどの場合も **例外を外に出さず None を返す**。
     呼び出し側は None のときヒューリスティック (辞書翻訳・キーワード分類) に退避する。
     → テスト・CI・Mac 初回セットアップ前でもパイプラインが止まらない。
  2. 同じ入力 (model + system + user + schema) は SQLite キャッシュから返し、二度と課金しない。
  3. 全リクエストの usage を data/ai_usage.jsonl に記録し、週間予算 (AI_WEEKLY_BUDGET_JPY)
     を超えたら自動で AI を止める。
  4. JSON が欲しいタスクは output_config.format (structured outputs) で受け取り、
     非対応モデルなら「JSON のみ出力」指示に自動で切り替える。
  5. Fable 系モデルは beta の server-side fallback を有効化し、安全分類器で拒否された
     場合も同一リクエスト内で別モデルが続きを返す。

使い方:
    from app.ai import get_ai_client
    client = get_ai_client()
    data = client.complete_json("category", system=..., user=..., schema={...})
    if data is None:
        ...  # フォールバック
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

try:  # SDK 未インストール環境 (CI の軽量 install) でも import 可能にする
    import anthropic  # type: ignore
except ImportError:  # pragma: no cover
    anthropic = None  # type: ignore

from app.ai.router import (
    estimate_cost_usd,
    is_fable,
    policy_for,
    resolve_model,
    supports_effort,
    usd_to_jpy,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CACHE_PATH = PROJECT_ROOT / "data" / "ai_cache.sqlite"
DEFAULT_LEDGER_PATH = PROJECT_ROOT / "data" / "ai_usage.jsonl"
DEFAULT_WEEKLY_BUDGET_JPY = 500.0

# Fable 系で有効化する server-side fallback (拒否時に別モデルへ自動ルーティング)
FABLE_FALLBACK_BETA = "server-side-fallback-2026-07-01"

_JSON_ONLY_SUFFIX = (
    "\n\n出力は JSON オブジェクトのみ。説明文・コードフェンス・前置きは一切付けないこと。"
)


# ---------------------------------------------------------------------------
# キャッシュ
# ---------------------------------------------------------------------------

class DiskCache:
    """SQLite ベースの応答キャッシュ。key = 入力内容のハッシュ。"""

    def __init__(self, path: str | os.PathLike = DEFAULT_CACHE_PATH):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS ai_cache ("
            "key TEXT PRIMARY KEY, task TEXT, model TEXT, value TEXT, created_at TEXT)"
        )
        self._conn.commit()

    def get(self, key: str) -> Optional[Any]:
        row = self._conn.execute("SELECT value FROM ai_cache WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return None

    def set(self, key: str, task: str, model: str, value: Any) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO ai_cache (key, task, model, value, created_at) VALUES (?, ?, ?, ?, ?)",
            (key, task, model, json.dumps(value, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    def count(self, task: Optional[str] = None) -> int:
        if task:
            return self._conn.execute("SELECT COUNT(*) FROM ai_cache WHERE task = ?", (task,)).fetchone()[0]
        return self._conn.execute("SELECT COUNT(*) FROM ai_cache").fetchone()[0]

    def clear(self, task: Optional[str] = None) -> int:
        cur = (self._conn.execute("DELETE FROM ai_cache WHERE task = ?", (task,)) if task
               else self._conn.execute("DELETE FROM ai_cache"))
        self._conn.commit()
        return cur.rowcount


# ---------------------------------------------------------------------------
# 使用量台帳
# ---------------------------------------------------------------------------

class UsageLedger:
    """1 リクエスト 1 行の JSONL 台帳。コスト集計と週間予算チェックに使う。"""

    def __init__(self, path: str | os.PathLike = DEFAULT_LEDGER_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, entry: dict) -> None:
        entry = dict(entry)
        entry.setdefault("ts", datetime.now(timezone.utc).isoformat())
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def entries(self, days: Optional[int] = None) -> list[dict]:
        if not self.path.exists():
            return []
        cutoff = None
        if days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        out: list[dict] = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if cutoff is not None:
                    try:
                        ts = datetime.fromisoformat(e.get("ts", ""))
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                    except ValueError:
                        continue
                    if ts < cutoff:
                        continue
                out.append(e)
        return out

    def spent_jpy(self, days: int = 7) -> float:
        return round(sum(float(e.get("cost_jpy") or 0.0) for e in self.entries(days)), 2)

    def summarize(self, days: int = 7) -> dict:
        rows = self.entries(days)
        by_task: dict[str, dict] = {}
        by_model: dict[str, dict] = {}
        total_usd = 0.0
        cached = 0
        for e in rows:
            usd = float(e.get("cost_usd") or 0.0)
            total_usd += usd
            if e.get("cached"):
                cached += 1
            for bucket, key in ((by_task, e.get("task", "?")), (by_model, e.get("model", "?"))):
                b = bucket.setdefault(key, {"calls": 0, "cached": 0, "input_tokens": 0,
                                            "output_tokens": 0, "cost_usd": 0.0})
                b["calls"] += 1
                b["cached"] += 1 if e.get("cached") else 0
                b["input_tokens"] += int(e.get("input_tokens") or 0) + int(e.get("cache_read_input_tokens") or 0) \
                    + int(e.get("cache_creation_input_tokens") or 0)
                b["output_tokens"] += int(e.get("output_tokens") or 0)
                b["cost_usd"] = round(b["cost_usd"] + usd, 6)
        return {
            "days": days,
            "calls": len(rows),
            "cached_calls": cached,
            "total_usd": round(total_usd, 6),
            "total_jpy": usd_to_jpy(total_usd),
            "by_task": by_task,
            "by_model": by_model,
        }


# ---------------------------------------------------------------------------
# JSON 抽出
# ---------------------------------------------------------------------------

def parse_json_lenient(text: str) -> Optional[Any]:
    """モデル出力から JSON を取り出す。コードフェンスや前置きが混ざっても拾う。"""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = s.find(open_ch)
        end = s.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(s[start:end + 1])
            except json.JSONDecodeError:
                continue
    return None


def rough_token_count(text: str) -> int:
    """課金前の概算 (dry-run 表示用)。英数字 4 文字≒1 token、それ以外 1 文字≒1 token。"""
    if not text:
        return 0
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    other = len(text) - ascii_chars
    return ascii_chars // 4 + other + 1


# ---------------------------------------------------------------------------
# クライアント
# ---------------------------------------------------------------------------

class AIClient:
    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        sdk_client: Any = None,
        cache: Optional[DiskCache] = None,
        ledger: Optional[UsageLedger] = None,
        weekly_budget_jpy: Optional[float] = None,
        enabled: Optional[bool] = None,
        quiet: bool = False,
    ):
        self.api_key = api_key if api_key is not None else os.getenv("ANTHROPIC_API_KEY", "")
        self._sdk = sdk_client
        self.cache = cache if cache is not None else DiskCache()
        self.ledger = ledger if ledger is not None else UsageLedger()
        self.quiet = quiet
        self.weekly_budget_jpy = (
            float(weekly_budget_jpy) if weekly_budget_jpy is not None
            else float(os.getenv("AI_WEEKLY_BUDGET_JPY", DEFAULT_WEEKLY_BUDGET_JPY) or DEFAULT_WEEKLY_BUDGET_JPY)
        )
        self._disabled_reason = ""
        if enabled is not None:
            self.enabled = bool(enabled)
            if not self.enabled:
                self._disabled_reason = "明示的に無効化"
        elif os.getenv("AI_DISABLED", "0").strip() in ("1", "true", "yes"):
            self.enabled = False
            self._disabled_reason = "AI_DISABLED=1"
        elif self._sdk is None and not self.api_key:
            self.enabled = False
            self._disabled_reason = "ANTHROPIC_API_KEY 未設定"
        elif self._sdk is None and anthropic is None:
            self.enabled = False
            self._disabled_reason = "anthropic SDK 未インストール (pip install anthropic)"
        else:
            self.enabled = True
        self._budget_warned = False
        self.session_cost_usd = 0.0
        self.session_calls = 0
        self.session_cache_hits = 0

    # ----- 状態 -------------------------------------------------------------

    @property
    def available(self) -> bool:
        if not self.enabled:
            return False
        if self.weekly_budget_jpy > 0 and self.ledger.spent_jpy(7) >= self.weekly_budget_jpy:
            if not self._budget_warned:
                self._log(f"⚠️ AI 週間予算 ¥{self.weekly_budget_jpy:,.0f} を超過 → ヒューリスティックに切替")
                self._budget_warned = True
            return False
        return True

    def why_unavailable(self) -> str:
        if self.enabled and not self.available:
            return f"週間予算 ¥{self.weekly_budget_jpy:,.0f} 超過"
        return self._disabled_reason or ""

    def _log(self, msg: str) -> None:
        if not self.quiet:
            print(msg, file=sys.stderr)

    def _get_sdk(self):
        if self._sdk is None:
            self._sdk = anthropic.Anthropic(api_key=self.api_key or None)  # type: ignore[union-attr]
        return self._sdk

    # ----- 公開 API ---------------------------------------------------------

    def complete_json(self, task: str, system: str, user: str, schema: dict) -> Optional[Any]:
        """構造化 JSON を返す。失敗・無効時は None。"""
        return self._complete(task, system, user, schema=schema)

    def complete_text(self, task: str, system: str, user: str) -> Optional[str]:
        """プレーンテキストを返す。失敗・無効時は None。"""
        return self._complete(task, system, user, schema=None)

    # ----- 内部 -------------------------------------------------------------

    @staticmethod
    def _cache_key(task: str, model: str, system: str, user: str, schema: Optional[dict]) -> str:
        payload = json.dumps(
            {"v": 1, "task": task, "model": model, "system": system, "user": user, "schema": schema},
            sort_keys=True, ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _build_kwargs(self, policy, model: str, system: str, user: str, schema: Optional[dict]) -> dict:
        if policy.cache_system:
            system_param: Any = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        else:
            system_param = system
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": policy.max_tokens,
            "system": system_param,
            "messages": [{"role": "user", "content": user}],
        }
        output_config: dict[str, Any] = {}
        if policy.effort and supports_effort(model):
            output_config["effort"] = policy.effort
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        if output_config:
            kwargs["output_config"] = output_config
        return kwargs

    def _send(self, kwargs: dict, model: str):
        sdk = self._get_sdk()
        if is_fable(model):
            return sdk.beta.messages.create(
                betas=[FABLE_FALLBACK_BETA], fallbacks="default", **kwargs,
            )
        return sdk.messages.create(**kwargs)

    @staticmethod
    def _classify_error(exc: Exception) -> str:
        name = type(exc).__name__
        if anthropic is not None:
            if isinstance(exc, anthropic.AuthenticationError):
                return "auth"
            if isinstance(exc, anthropic.BadRequestError):
                return "bad_request"
            if isinstance(exc, anthropic.RateLimitError):
                return "rate_limit"
            if isinstance(exc, anthropic.APIConnectionError):
                return "connection"
            if isinstance(exc, anthropic.APIStatusError):
                return "status"
        return {
            "AuthenticationError": "auth",
            "BadRequestError": "bad_request",
            "RateLimitError": "rate_limit",
            "APIConnectionError": "connection",
            "APIStatusError": "status",
        }.get(name, "unknown")

    @staticmethod
    def _extract_text(response) -> str:
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", "") == "text":
                return getattr(block, "text", "") or ""
        return ""

    @staticmethod
    def _usage_dict(response) -> dict:
        u = getattr(response, "usage", None)
        return {
            "input_tokens": int(getattr(u, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(u, "output_tokens", 0) or 0),
            "cache_creation_input_tokens": int(getattr(u, "cache_creation_input_tokens", 0) or 0),
            "cache_read_input_tokens": int(getattr(u, "cache_read_input_tokens", 0) or 0),
        }

    def _complete(self, task: str, system: str, user: str, schema: Optional[dict]) -> Optional[Any]:
        policy = policy_for(task)
        model = resolve_model(policy.tier)
        key = self._cache_key(task, model, system, user, schema)

        cached = self.cache.get(key)
        if cached is not None:
            self.session_cache_hits += 1
            self.ledger.record({"task": task, "model": model, "cached": True, "cost_usd": 0.0, "cost_jpy": 0.0})
            return cached

        if not self.available:
            return None

        kwargs = self._build_kwargs(policy, model, system, user, schema)
        response = None
        for attempt in (1, 2):
            try:
                response = self._send(kwargs, model)
                break
            except Exception as exc:  # noqa: BLE001 - 外へは出さない設計
                kind = self._classify_error(exc)
                msg = str(exc)
                if kind == "auth":
                    self.enabled = False
                    self._disabled_reason = "API キー認証エラー"
                    self._log(f"❌ AI 認証エラー: {msg[:200]}")
                    return None
                if (kind == "bad_request" and attempt == 1 and schema is not None
                        and any(t in msg for t in ("output_config", "format", "json_schema"))):
                    # structured outputs 非対応モデル → JSON のみ出力指示に切替
                    self._log(f"ℹ️ {model} は structured outputs 非対応 → JSON 指示に切替")
                    kwargs["output_config"] = {k: v for k, v in kwargs.get("output_config", {}).items() if k != "format"}
                    if not kwargs["output_config"]:
                        kwargs.pop("output_config")
                    kwargs["messages"] = [{"role": "user", "content": user + _JSON_ONLY_SUFFIX}]
                    continue
                self._log(f"⚠️ AI 呼び出し失敗 ({task}/{model}/{kind}): {msg[:200]}")
                return None
        if response is None:
            return None

        served_model = getattr(response, "model", None) or model
        usage = self._usage_dict(response)
        cost_usd = estimate_cost_usd(served_model, **usage)
        cost_jpy = usd_to_jpy(cost_usd)
        self.session_cost_usd += cost_usd
        self.session_calls += 1
        stop_reason = getattr(response, "stop_reason", "")
        self.ledger.record({
            "task": task, "model": served_model, "requested_model": model, "cached": False,
            "stop_reason": stop_reason, "cost_usd": cost_usd, "cost_jpy": cost_jpy, **usage,
        })

        if stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            self._log(f"⚠️ AI が応答を拒否 ({task}): {getattr(details, 'category', '')}")
            return None
        if stop_reason == "max_tokens":
            self._log(f"⚠️ AI 出力が max_tokens={policy.max_tokens} で途切れた可能性 ({task})")

        text = self._extract_text(response)
        if schema is None:
            result: Any = text.strip()
            if not result:
                return None
        else:
            result = parse_json_lenient(text)
            if result is None:
                self._log(f"⚠️ AI 出力の JSON 解析に失敗 ({task})")
                return None
        self.cache.set(key, task, model, result)
        return result

    # ----- レポート ---------------------------------------------------------

    def session_summary(self) -> dict:
        return {
            "calls": self.session_calls,
            "cache_hits": self.session_cache_hits,
            "cost_usd": round(self.session_cost_usd, 6),
            "cost_jpy": usd_to_jpy(self.session_cost_usd),
            "weekly_spent_jpy": self.ledger.spent_jpy(7),
            "weekly_budget_jpy": self.weekly_budget_jpy,
        }


_default_client: Optional[AIClient] = None


def get_ai_client(**kwargs) -> AIClient:
    """プロセス内シングルトン。kwargs を渡すと作り直す (テスト用)。"""
    global _default_client
    if kwargs or _default_client is None:
        _default_client = AIClient(**kwargs)
    return _default_client
