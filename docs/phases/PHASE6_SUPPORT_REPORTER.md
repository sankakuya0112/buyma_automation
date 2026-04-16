# Phase 6 実装指示書 — 運営支援（Support + Reporter）

## このPhaseの目的
日々の運営を効率化する2機能を追加する。
- **Support**: 問い合わせへの回答ドラフトを自動生成（最終送信は人間が行う）
- **Reporter**: 売上・利益・作業効率の月次レポートをHTML形式で自動生成

## 前提条件
- Phase 1〜4 が完了している
- SQLiteのDBにorders, listings等のデータが蓄積されている

## 完了条件
- `python3 scripts/run_support.py` で問い合わせドラフトがコンソールに表示される
- `python3 scripts/run_reports.py` で outputs/reports/monthly_YYYY-MM.html が生成される

---

## タスク 6-1: 回答テンプレートファイル（data/reply_templates.json）

```json
{
  "在庫確認": {
    "keywords": ["在庫", "まだある", "購入できますか", "買えますか"],
    "template": "お問い合わせいただきありがとうございます。\n現在の在庫状況を確認いたします。確認でき次第、改めてご連絡いたします。\n少々お時間をいただけますと幸いです。"
  },
  "サイズ相談": {
    "keywords": ["サイズ", "身長", "体重", "cm", "号", "着丈", "肩幅"],
    "template": "サイズについてのお問い合わせありがとうございます。\n商品の詳細サイズを確認いたします。ご参考までに、海外サイズは日本サイズと異なる場合がございますので、ご購入前にサイズ表のご確認をお勧めいたします。"
  },
  "配送期間": {
    "keywords": ["いつ", "届く", "配送", "発送", "日数", "期間", "何日"],
    "template": "ご注文確定後、買付に10〜14日程度、日本への配送に5〜7日程度かかります。\n合計でご注文確定後20日前後を目安にお考えください。\n追跡番号のご提供もいたします。"
  },
  "関税": {
    "keywords": ["関税", "税金", "追加費用", "消費税"],
    "template": "本商品は関税・消費税込みの価格でご案内しています。\nお届け時に追加費用が発生することはございませんので、ご安心ください。"
  },
  "値下げ": {
    "keywords": ["値下げ", "割引", "安く", "まけて", "お値引き", "交渉"],
    "template": "お値引きのご希望ありがとうございます。\n誠に恐れ入りますが、海外正規品の仕入れコストの関係上、現在の価格が精一杯となっております。何卒ご理解いただけますと幸いです。"
  },
  "購入後連絡": {
    "keywords": ["購入しました", "注文しました", "支払いました", "ありがとう"],
    "template": "ご購入いただきありがとうございます！\nただいま買付の手配を進めております。発送準備が整い次第、追跡番号をお知らせいたします。\nお届けまでしばらくお待ちください。"
  },
  "色味確認": {
    "keywords": ["色", "カラー", "モニター", "実物", "写真と違う"],
    "template": "ご確認ありがとうございます。\n海外正規品のため商品はブランドから仕入れておりますが、モニターの環境により実物と色味が若干異なる場合がございます。\n可能な範囲で追加画像をご用意することもできますのでお気軽にご相談ください。"
  }
}
```

---

## タスク 6-2: Support エージェント（app/support/draft_reply.py）

```python
"""
app/support/draft_reply.py
BUYMAの問い合わせを分類し、回答ドラフトを生成する。
最終送信は必ず人間が確認してから行う（自動送信禁止）。
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional
from app.core.config import config
from app.core.logger import get_logger

logger = get_logger(__name__)


def load_templates() -> dict:
    """data/reply_templates.json を読み込む"""
    path = config.data_dir / "reply_templates.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def classify_inquiry(message: str, templates: dict) -> Optional[str]:
    """
    問い合わせ文から最も適切なカテゴリを特定する。
    戻り値: カテゴリ名（マッチなしはNone）
    """
    message_lower = message.lower()
    for category, data in templates.items():
        keywords = data.get("keywords", [])
        if any(kw in message_lower for kw in keywords):
            return category
    return None


def generate_draft(
    inquiry_message: str,
    product_title: str = "",
    buyma_order_id: str = "",
) -> dict:
    """
    問い合わせ文から回答ドラフトを生成する。
    戻り値: {
        "category": str,
        "draft": str,
        "confidence": "high" | "low",
        "note": str  # 人間への補足
    }
    """
    templates = load_templates()
    category = classify_inquiry(inquiry_message, templates)

    if category:
        template = templates[category]["template"]
        # 商品情報を補完
        if product_title:
            template = f"【{product_title}】についてのお問い合わせ\n\n" + template
        logger.info(f"問い合わせ分類: {category} / 商品: {product_title[:30] if product_title else 'N/A'}")
        return {
            "category": category,
            "draft": template,
            "confidence": "high",
            "note": "テンプレートに基づく自動生成。送信前に内容を必ずご確認ください。",
        }
    else:
        logger.warning(f"未分類の問い合わせ: {inquiry_message[:50]}")
        return {
            "category": "未分類",
            "draft": "",
            "confidence": "low",
            "note": "自動分類できませんでした。手動で回答をご作成ください。",
        }
```

### scripts/run_support.py

```python
"""
scripts/run_support.py
問い合わせドラフトの生成ツール。
使い方:
    python3 scripts/run_support.py
    python3 scripts/run_support.py --message "在庫はありますか？"
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.support.draft_reply import generate_draft

def main():
    import argparse
    parser = argparse.ArgumentParser(description="問い合わせ回答ドラフト生成")
    parser.add_argument("--message", "-m", help="問い合わせメッセージ", default="")
    parser.add_argument("--product", "-p", help="商品名（任意）", default="")
    args = parser.parse_args()

    if args.message:
        message = args.message
    else:
        print("問い合わせ内容を入力してください（Enterで確定）:")
        message = input("> ").strip()

    if not message:
        print("メッセージが入力されていません。")
        return

    result = generate_draft(message, product_title=args.product)

    print("\n" + "="*50)
    print(f"📋 分類: {result['category']}  信頼度: {result['confidence']}")
    print("="*50)
    if result["draft"]:
        print("\n【回答ドラフト】")
        print(result["draft"])
    print(f"\n⚠️  {result['note']}")
    print("="*50)
    print("\n※ このドラフトはそのまま送信せず、必ず内容を確認してから送信してください。")

if __name__ == "__main__":
    main()
```

---

## タスク 6-3: Reporter エージェント（app/reporting/metrics_report.py）

```python
"""
app/reporting/metrics_report.py
月次・週次の売上・利益・運用効率レポートを生成する。
出力: outputs/reports/report_YYYY-MM.html
"""
from __future__ import annotations
from datetime import datetime, date
from pathlib import Path
from app.core.db import get_session
from app.core.models import Listing, Order, InventoryCheck, DailyMetrics, SourceProduct, RankedProduct
from app.core.config import config
from app.core.logger import get_logger

logger = get_logger(__name__)


def collect_monthly_data(year: int, month: int) -> dict:
    """指定月のデータをDBから集計する"""
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)

    with get_session() as s:
        # 出品数
        total_listings = s.query(Listing).filter(
            Listing.listed_at >= start,
            Listing.listed_at < end,
        ).count()

        # アクティブ出品数
        active_listings = s.query(Listing).filter(
            Listing.listing_status == "active"
        ).count()

        # 在庫監視：停止件数
        stopped = s.query(Listing).filter(
            Listing.listing_status == "stopped",
            Listing.stopped_at >= start,
            Listing.stopped_at < end,
        ).count()

        # 注文数と利益合計
        orders = s.query(Order).filter(
            Order.ordered_at >= start,
            Order.ordered_at < end,
        ).all()
        orders_count = len(orders)
        total_profit = sum(
            (o.rechecked_profit_jpy or 0)
            for o in orders
            if o.human_decision == "human_approved"
        )

        # ブランド別利益
        brand_stats = {}
        for o in orders:
            if not o.listing_id:
                continue
            listing = s.query(Listing).get(o.listing_id)
            if not listing:
                continue
            rp = s.query(RankedProduct).get(listing.ranked_product_id)
            if not rp:
                continue
            sp = s.query(SourceProduct).get(rp.source_product_id)
            if not sp:
                continue
            brand = sp.brand or "不明"
            if brand not in brand_stats:
                brand_stats[brand] = {"orders": 0, "profit": 0}
            brand_stats[brand]["orders"] += 1
            brand_stats[brand]["profit"] += o.rechecked_profit_jpy or 0

        # カート投入後の購入率
        from app.core.models import CartQueue
        total_carts = s.query(CartQueue).count()
        approved_carts = s.query(CartQueue).filter(
            CartQueue.human_review_status == "approved"
        ).count()

    return {
        "period": f"{year}年{month}月",
        "total_listings": total_listings,
        "active_listings": active_listings,
        "stopped_listings": stopped,
        "orders_count": orders_count,
        "total_profit_jpy": total_profit,
        "avg_profit_jpy": total_profit // orders_count if orders_count else 0,
        "brand_stats": dict(sorted(brand_stats.items(), key=lambda x: x[1]["profit"], reverse=True)[:10]),
        "cart_purchase_rate": f"{approved_carts/total_carts*100:.1f}%" if total_carts else "N/A",
    }


def generate_html_report(data: dict) -> str:
    """データからHTMLレポートを生成する"""
    brand_rows = ""
    for brand, stats in data["brand_stats"].items():
        brand_rows += f"""
        <tr>
            <td>{brand}</td>
            <td>{stats['orders']}件</td>
            <td>¥{stats['profit']:,}</td>
        </tr>"""

    return f"""<\!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>BUYMA月次レポート {data['period']}</title>
<style>
  body {{ font-family: 'Helvetica Neue', sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; color: #333; }}
  h1 {{ color: #1a1a2e; border-bottom: 3px solid #e94560; padding-bottom: 8px; }}
  h2 {{ color: #0f3460; margin-top: 32px; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin: 24px 0; }}
  .kpi-card {{ background: #f8f9fa; border-radius: 10px; padding: 20px; text-align: center; border-left: 4px solid #e94560; }}
  .kpi-value {{ font-size: 28px; font-weight: bold; color: #1a1a2e; }}
  .kpi-label {{ font-size: 12px; color: #636e72; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
  th {{ background: #1a1a2e; color: white; padding: 10px; text-align: left; }}
  td {{ padding: 8px 10px; border-bottom: 1px solid #dfe6e9; }}
  tr:hover {{ background: #f8f9fa; }}
  .note {{ background: #fff3cd; padding: 12px 16px; border-radius: 6px; font-size: 13px; margin-top: 32px; }}
</style>
</head>
<body>
<h1>📊 BUYMA月次レポート — {data['period']}</h1>
<p>生成日時: {datetime.now().strftime('%Y年%m月%d日 %H:%M')}</p>

<h2>主要指標</h2>
<div class="kpi-grid">
  <div class="kpi-card">
    <div class="kpi-value">{data['total_listings']}</div>
    <div class="kpi-label">今月の新規出品数</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-value">{data['active_listings']}</div>
    <div class="kpi-label">現在アクティブな出品</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-value">{data['orders_count']}</div>
    <div class="kpi-label">注文件数</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-value">¥{data['total_profit_jpy']:,}</div>
    <div class="kpi-label">総利益（確定分）</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-value">¥{data['avg_profit_jpy']:,}</div>
    <div class="kpi-label">1件あたり平均利益</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-value">{data['cart_purchase_rate']}</div>
    <div class="kpi-label">カート投入→購入率</div>
  </div>
</div>

<h2>ブランド別利益TOP10</h2>
<table>
  <tr><th>ブランド</th><th>注文件数</th><th>利益合計</th></tr>
  {brand_rows if brand_rows else '<tr><td colspan="3">データなし</td></tr>'}
</table>

<div class="note">
  ⚠️ このレポートはDBのデータをもとに自動生成されています。数値は概算です。
  確定利益は人間が承認した注文のみ集計しています。
</div>
</body>
</html>"""


def run_report(year: int = None, month: int = None) -> Path:
    """レポートを生成してファイルに保存。戻り値はファイルパス。"""
    now = datetime.now()
    year = year or now.year
    month = month or now.month

    logger.info(f"レポート生成開始: {year}年{month}月")
    data = collect_monthly_data(year, month)
    html = generate_html_report(data)

    output_path = config.outputs_dir / f"report_{year}-{month:02d}.html"
    output_path.write_text(html, encoding="utf-8")
    logger.info(f"レポート保存: {output_path}")
    return output_path
```

### scripts/run_reports.py

```python
"""
scripts/run_reports.py
月次レポートを生成する。
使い方:
    python3 scripts/run_reports.py          # 今月のレポート
    python3 scripts/run_reports.py --month 3  # 3月のレポート
    python3 scripts/run_reports.py --year 2026 --month 3
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
from app.reporting.metrics_report import run_report

def main():
    parser = argparse.ArgumentParser(description="月次レポート生成")
    parser.add_argument("--year", type=int, help="対象年（デフォルト: 今年）")
    parser.add_argument("--month", type=int, help="対象月（デフォルト: 今月）")
    args = parser.parse_args()

    output_path = run_report(year=args.year, month=args.month)
    print(f"\n✅ レポート生成完了: {output_path}")
    print(f"   ブラウザで開いて確認: file://{output_path.resolve()}")

if __name__ == "__main__":
    main()
```

---

## 完了確認コマンド

```bash
# 問い合わせドラフト生成テスト
python3 scripts/run_support.py --message "在庫はありますか？"
python3 scripts/run_support.py --message "サイズ感が知りたいです"

# レポート生成テスト
python3 scripts/run_reports.py
```

---

## 注意事項

- Support は**絶対に自動送信しない**。ドラフト生成で必ず止める。
- Reporter はDBにデータが蓄積されてから機能する。Phase 1〜4 稼働後に実行する。
- reply_templates.json は運営しながら随時追加・修正する。
