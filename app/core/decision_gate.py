"""意思決定ゲート — モデル自身の予測を実測で検定し、次の一手を機械的に決める。

## なぜ必要か (2026-07-03 問題再定義)

過去 4.5 ヶ月、「もう少し自動化が完成したら公開する」という判断が
無期限に繰り返された。原因は判断基準が事前に定義されていなかったこと。
本モジュールは撤退/継続/拡大の基準を **コードとして事前コミット** し、
気分ではなくデータで次の一手を決める。

## 検定の設計

opportunity.py は各商品に「月次成約確率 sale_probability」を割り当てる。
これは検証可能な予測である:

    λ = Σ_i p_i × (公開経過日数_i / 30)     (公開済み商品のみ)
    帰無仮説 H0「モデルは正しい」の下で 成約数 ~ Poisson(λ)
    P(成約 0 | λ) = exp(-λ)

- exp(-λ) < 0.10 なのに成約 0 → モデルが過大評価 (棄却)。
  ただし「そもそも見られていない」なら価格の問題ではないので、
  先にアクセス実測 (funnel) で露出を切り分ける。
- 成約 ≥ 1 → ループが閉じた。観測レートでモデルを較正し、量産に投資。
- 成約 0 の間も rule of three で「実測が許す月次成約確率の上限 ≈ 3/露出量」
  を報告し、仮定値 (0.02〜0.12) と比較可能にする。
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.core.first_sale import (
    SprintCandidate,
    days_until_decisive,
    elapsed_days,
    expected_sales_lambda,
    exposure_months,
)

# ---- 事前コミットする閾値 (変更時はコミットメッセージで理由を残すこと) ----

MIN_PUBLISHED = 5        # これ未満の公開数では何も結論しない
MIN_DAYS = 7.0           # 最長経過がこれ未満なら結論しない
P0_MODEL_REJECT = 0.10   # exp(-λ) がこれを下回って成約 0 ならモデル棄却
ACCESS_PER_WEEK_LOW = 5.0  # 週あたりアクセス中央値がこれ未満なら露出不足
WISH_RATE_OK = 0.02      # ほしいもの/アクセス比がこれ以上なら関心は実在


@dataclass
class GateVerdict:
    """ゲートの判定結果。code は機械可読、他は人間向け。"""

    code: str                    # COLLECTING / EXPOSURE_PROBLEM / CONVERSION_PROBLEM
                                 # / ON_TRACK_WAITING / SCALE_UP
    headline: str
    rationale: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


def _fmt_days(v: Optional[float]) -> str:
    return "不明" if v is None else f"{v:.0f} 日"


def evaluate_gate(
    published: list[SprintCandidate],
    as_of: datetime,
    observed_sales: int = 0,
    weekly_access: Optional[list[float]] = None,
    total_access: int = 0,
    total_wish: int = 0,
) -> GateVerdict:
    """公開済み商品群 + 実測ファネルから次の一手を判定する。

    Args:
        published: published_at が入った SprintCandidate のリスト
        as_of: 評価時点
        observed_sales: 観測された成約数 (funnel の売切検出 or 手入力)
        weekly_access: 商品ごとの週あたりアクセス数 (funnel 由来)。
            None = funnel 未実行 (露出判定をスキップし、その旨を明記)
        total_access / total_wish: 全公開商品の累計 (wish rate 用)
    """
    n = len(published)
    lam = expected_sales_lambda(published, as_of)
    p0 = math.exp(-lam) if lam > 0 else 1.0
    exp_months = exposure_months(published, as_of)
    # rule of three: 成約 0 で n 商品・月の露出なら、95% 信頼で月次成約確率 < 3/n。
    # 露出が小さすぎる (0.5 商品・月未満) と上限が無意味な巨大値になるため出さない。
    rot_upper = (3.0 / exp_months) if exp_months >= 0.5 else None
    max_days = max(
        (elapsed_days(it.published_at, as_of) for it in published), default=0.0
    )
    access_median = (
        statistics.median(weekly_access) if weekly_access else None
    )
    wish_rate = (total_wish / total_access) if total_access > 0 else None
    decisive_in = days_until_decisive(published, as_of, P0_MODEL_REJECT)

    metrics = {
        "published_count": n,
        "observed_sales": observed_sales,
        "lambda": round(lam, 3),
        "p0_no_sales": round(p0, 3),
        "exposure_item_months": round(exp_months, 2),
        "rule_of_three_upper": round(rot_upper, 3) if rot_upper else None,
        "max_elapsed_days": round(max_days, 1),
        "access_median_weekly": round(access_median, 1) if access_median is not None else None,
        "wish_rate": round(wish_rate, 4) if wish_rate is not None else None,
        "days_until_decisive": round(decisive_in, 1) if decisive_in is not None else None,
    }

    # 1) 成約あり → ループが閉じた。較正して量産へ。
    if observed_sales >= 1:
        calib = (observed_sales / lam) if lam > 0 else None
        rationale = [
            f"成約 {observed_sales} 件を観測 (モデル期待値 λ={lam:.2f})。",
            "実売データが取れた = 事業仮説の最重要不確実性が解消。",
        ]
        if calib is not None:
            rationale.append(
                f"較正係数の初期推定: 実測/予測 = {calib:.2f} "
                "(BASE_SALE_PROBABILITY にこの係数を乗じると実測整合)"
            )
        return GateVerdict(
            code="SCALE_UP",
            headline="🎉 ループ成立 — 量産フェーズに投資解禁",
            rationale=rationale,
            actions=[
                "Sprint 2: filter 上位 50-100 件を draft 量産 (ツール) → 人間がバッチ公開",
                "check_inventory.py の日次運用を開始 (キャンセル = 評価毀損の防止が最優先)",
                "成約商品の属性 (ブランド/カテゴリ/価格帯/competition_level) を記録し選定に反映",
                "この時点で初めて、自動公開フローの完成に開発時間を投資する価値が出る",
            ],
            metrics=metrics,
        )

    # 2) データ不足 → 結論を出さず収集を続ける
    if n < MIN_PUBLISHED or max_days < MIN_DAYS:
        return GateVerdict(
            code="COLLECTING",
            headline="📡 データ収集中 — まだ何も結論できない (それが正常)",
            rationale=[
                f"公開 {n} 件 / 最長経過 {max_days:.1f} 日。"
                f"判定には公開 {MIN_PUBLISHED} 件以上かつ {MIN_DAYS:.0f} 日以上が必要。",
                f"モデル棄却判定が可能になるまで概算 {_fmt_days(decisive_in)} (現在の公開数のまま)。",
            ],
            actions=[
                "スプリント残の下書き→公開を完了させる",
                "track_listing_funnel.py を 2-3 日おきに実行してスナップショットを蓄積",
                "公開数を増やすほど判定到達が早まる (λ は公開数×経過日数に比例)",
            ],
            metrics=metrics,
        )

    # 3) 露出不足 → 価格やモデル以前に「見られていない」
    if access_median is not None and access_median < ACCESS_PER_WEEK_LOW:
        return GateVerdict(
            code="EXPOSURE_PROBLEM",
            headline="👀 露出不足 — 価格ではなく新規アカウントのコールドスタートが原因",
            rationale=[
                f"週あたりアクセス中央値 {access_median:.1f} (< {ACCESS_PER_WEEK_LOW:.0f})。",
                "見られていない商品は価格を下げても売れない。成約 0 はモデルの反証にならない。",
            ],
            actions=[
                "出品数を増やす (draft はツールで量産できる — 露出は出品数×鮮度に比例)",
                "検索結果で実際に最安値表示になっているか目視確認 (price_leader の実効性)",
                "上位ショッパーの同一商品とタイトル/1枚目画像を並べて見劣り確認",
                "競合の薄いカテゴリ (competition_level=low/medium) の比率を上げる",
            ],
            metrics=metrics,
        )

    # 4) モデル棄却 → 見られているのに売れない
    if p0 < P0_MODEL_REJECT:
        rationale = [
            f"λ={lam:.2f} → 成約 0 の確率 {p0:.1%} (< {P0_MODEL_REJECT:.0%})。"
            "モデルの成約確率は過大評価と判定。",
        ]
        if rot_upper is not None:
            rationale.append(
                f"実測が許す月次成約確率の上限 ≈ {rot_upper:.3f} (rule of three)。"
                "仮定値 (none 0.02 〜 high 0.12) と比較して係数を引き下げる。"
            )
        if wish_rate is not None and wish_rate >= WISH_RATE_OK:
            rationale.append(
                f"ほしいもの率 {wish_rate:.1%} ≥ {WISH_RATE_OK:.0%} — 関心はあるのに"
                "最後の一歩で落ちている (価格・出品者信頼・納期表記が候補)。"
            )
            actions = [
                "price_leader を床値 (floor 利益) まで徹底 — 新規アカウントは価格でしか信頼を代替できない",
                "あんしんプラス対象化・納期/返品文言の見直し (不安の除去)",
                "問い合わせ即応体制 (通知は notifier.py 連携済み)",
                "opportunity.py の BASE_SALE_PROBABILITY に較正係数を導入して再選定",
            ]
        else:
            rationale.append(
                "ほしいもの率も低い — 商品ページ到達後に興味を失っている"
                "(画像品質・説明文・価格の第一印象が候補)。"
            )
            actions = [
                "1枚目画像を競合上位と並べて品質比較 (Phase 3-2 の画像加工検討を前倒し)",
                "商品タイトル/説明の見直し (DeepL 翻訳文の自然さ・訴求点)",
                "価格を相場中央値 -10% 水準まで実験的に下げ、wish 率の変化を観測",
                "opportunity.py の係数を rule of three 上限に合わせて引き下げ",
            ]
        return GateVerdict(
            code="CONVERSION_PROBLEM",
            headline="📉 モデル棄却 — 露出はあるが成約しない。価格/信頼/品質の再設計",
            rationale=rationale,
            actions=actions,
            metrics=metrics,
        )

    # 5) まだ棄却できない → 継続
    rationale = [
        f"λ={lam:.2f} → 成約 0 の確率 {p0:.1%} (≥ {P0_MODEL_REJECT:.0%})。"
        "成約 0 はまだモデルと矛盾しない。",
        f"このままの公開数なら概算 {_fmt_days(decisive_in)} で判定可能になる。",
    ]
    if access_median is None:
        rationale.append(
            "⚠️ funnel 未実行のため露出判定をスキップした。"
            "track_listing_funnel.py を実行するとアクセス実測で切り分けできる。"
        )
    return GateVerdict(
        code="ON_TRACK_WAITING",
        headline="⏳ 判定待ち — モデルはまだ反証されていない。公開数を積んで加速せよ",
        rationale=rationale,
        actions=[
            "公開数を増やして λ の蓄積を加速 (判定到達日数は公開数に反比例)",
            "funnel スナップショットを継続採取 (アクセス/ほしいものの先行指標を貯める)",
        ],
        metrics=metrics,
    )
