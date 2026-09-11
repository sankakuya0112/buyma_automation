"""AI 補助層 (Claude API) — モデル使い分けとトークン節約の一元管理。

方針 (docs/AI_MODEL_POLICY.md):
  - 決定論的な処理 (利益計算 / 相場フィルタ / 期待値ソート) は AI を使わない
  - AI は「言葉の仕事」と「判断の仕事」にだけ使い、量の多い順に安いモデルを割り当てる
      cheap    (Haiku 4.5)  : 出品文の翻訳・生成、カテゴリ分類 (件数が多い)
      standard (Sonnet 5)   : 出品候補の審査、障害診断 (週に数回)
      premium  (Fable 5.1)  : 週次の戦略レビュー (週 1 回、集計値だけ渡す)
  - 同じ入力は二度と課金しない (ディスクキャッシュ)
  - 週間予算を超えたら自動でヒューリスティック (辞書翻訳等) に退避する
  - API キーが無ければ全て silent にヒューリスティックへ (テスト・CI で動く)
"""

from app.ai.client import AIClient, get_ai_client  # noqa: F401
from app.ai.router import TaskPolicy, policy_for, resolve_model  # noqa: F401
