# PHASE3: Ranker（商品ランキング・戦略決定）

## 概要

利益計算後、商品を3つの "Lane"（レーン）に分類し、出品戦略を決定します：

1. **Core Lane**: 高利益・低競争 → 丁寧に手作業で最適化したタイトル・説明で出品
2. **Long Tail Lane**: 中程度の利益・中程度の競争 → テンプレートで高速出品
3. **Hold Lane**: 判断保留（再調査待ち）
4. **Reject Lane**: 出品不可（利益不足等）

**完了条件**: `app/ranker/` ディレクトリ下に2つのモジュールが完成し、各商品に lane と rank_score が付与されること。

---

## タスク3-1: 競合分析モジュール（app/ranker/competitor_analysis.py）

### 実施内容

BUYMA サイト内で同じブランド・カテゴリの競合商品を検索し、現在の市場価格と競合数を取得します。

```python
# app/ranker/competitor_analysis.py

import logging
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from playwright.sync_api import sync_playwright, Page
from app.core.config import get_config
from app.core.models import RankedProduct, SourceProduct
from app.utils.retry import retry
import time

logger = logging.getLogger(__name__)

class CompetitorAnalyzer:
    """
    BUYMA上の競合商品を検索・分析。
    同一ブランド+カテゴリで出品されている競合数と価格帯を取得。
    """
    
    def __init__(self):
        self.config = get_config()
    
    @retry(max_retries=3, delay=2)
    def search_competitors(self, brand: str, category: str, color: str = None) -> Dict:
        """
        BUYMA で競合商品を検索。
        
        Args:
            brand: ブランド名
            category: カテゴリ
            color: 色（オプション）
        
        Returns:
            {
                'competitor_count': int,
                'price_range': {'min': float, 'max': float, 'avg': float},
                'top_competitors': [
                    {'title': str, 'price': float, 'seller': str, 'url': str},
                    ...
                ]
            }
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.config.headless)
            page = browser.new_page()
            
            try:
                # BUYMA 検索ページへ
                search_url = f"https://buyma.jp/search/?keyword={brand}%20{category}"
                if color:
                    search_url += f"%20{color}"
                
                page.goto(search_url, timeout=self.config.timeout_seconds * 1000)
                page.wait_for_load_state("networkidle")
                
                # 検索結果を解析
                results = self._extract_search_results(page)
                
                logger.info(f"Found {len(results)} competitors for {brand} {category}")
                
                # 統計情報を集計
                prices = [r['price'] for r in results if r['price']]
                
                analysis = {
                    'competitor_count': len(results),
                    'price_range': {
                        'min': min(prices) if prices else None,
                        'max': max(prices) if prices else None,
                        'avg': sum(prices) / len(prices) if prices else None,
                    },
                    'top_competitors': results[:5],  # 上位5件
                }
                
                return analysis
            finally:
                browser.close()
    
    def _extract_search_results(self, page: Page) -> List[Dict]:
        """
        検索結果ページから商品情報を抽出。
        """
        results = []
        
        try:
            # 商品リスト取得
            product_elements = page.locator("[data-product-item]").all()
            
            for element in product_elements:
                try:
                    title = element.locator("[data-title]").inner_text() or "Unknown"
                    price_text = element.locator("[data-price]").inner_text() or "0"
                    price = float(price_text.replace("¥", "").replace(",", "").strip())
                    seller = element.locator("[data-seller]").inner_text() or "Unknown"
                    url = element.locator("a").get_attribute("href") or ""
                    
                    results.append({
                        'title': title,
                        'price': price,
                        'seller': seller,
                        'url': url,
                    })
                except Exception as e:
                    logger.warning(f"Failed to extract product: {e}")
                    continue
            
            return results
        except Exception as e:
            logger.error(f"Failed to extract search results: {e}")
            return []
    
    def analyze_product(self, session: Session, ranked_product_id: int) -> None:
        """
        1件の商品について競合分析を実施し、ranked_products に保存。
        """
        ranked = session.query(RankedProduct).get(ranked_product_id)
        product = ranked.source_product
        
        try:
            analysis = self.search_competitors(
                brand=product.brand,
                category=product.category,
                color=product.color
            )
            
            ranked.competitor_count = analysis['competitor_count']
            ranked.competitor_min_price = analysis['price_range'].get('min')
            
            session.commit()
            
            logger.info(
                f"Competitor analysis: {product.id} → "
                f"{analysis['competitor_count']} competitors, "
                f"min price ¥{analysis['price_range'].get('min')}"
            )
        except Exception as e:
            logger.error(f"Competitor analysis failed for {product.id}: {e}")
    
    def analyze_all(self, session: Session) -> None:
        """
        全ランク付け商品について競合分析を実施。
        """
        ranked_products = session.query(RankedProduct).filter(
            RankedProduct.competitor_count == None
        ).all()
        
        logger.info(f"Analyzing {len(ranked_products)} products...")
        
        for idx, ranked in enumerate(ranked_products):
            self.analyze_product(session, ranked.id)
            
            # リクエスト制限
            time.sleep(2)
            
            if (idx + 1) % 10 == 0:
                logger.info(f"Analyzed {idx + 1}/{len(ranked_products)}")
```

### 納品物チェックリスト

- [ ] `app/ranker/competitor_analysis.py` が作成されている
- [ ] CompetitorAnalyzer クラスに search_competitors() メソッドが実装
- [ ] _extract_search_results() で BUYMA検索結果を解析
- [ ] analyze_product() で ranked_products に競合情報を保存
- [ ] analyze_all() で全商品の競合分析を実施

---

## タスク3-2: スコアリング・Lane 決定モジュール（app/ranker/scoring.py）

### 実施内容

複数の指標（利益、競合数、ブランド評価、カテゴリ評価）を組み合わせてスコアを算出し、Lane を決定します。

```python
# app/ranker/scoring.py

import logging
from sqlalchemy.orm import Session
from app.core.models import RankedProduct, SourceProduct
from app.core.config import get_config
from typing import Tuple
import json

logger = logging.getLogger(__name__)

class Scorer:
    """
    商品スコアリング・Lane 決定エンジン。
    
    スコア計算式：
    score = (profit_score * 0.4) + (competition_score * 0.3) + (brand_score * 0.2) + (category_score * 0.1)
    
    Lane 割り当て：
    - score >= 80: Core Lane（手作業最適化出品）
    - 60 <= score < 80: Long Tail Lane（テンプレート出品）
    - 40 <= score < 60: Hold Lane（再調査待ち）
    - score < 40: Reject Lane（出品不可）
    """
    
    def __init__(self):
        self.config = get_config()
        self.brand_scores = self._load_brand_scores()
        self.category_scores = self._load_category_scores()
    
    def _load_brand_scores(self) -> dict:
        """
        ブランドの人気度スコアを外部ファイルから読み込み。
        data/brand_scores.json: {"Gucci": 95, "Prada": 90, ...}
        """
        try:
            with open("data/brand_scores.json", "r") as f:
                return json.load(f)
        except Exception:
            logger.warning("brand_scores.json not found, using defaults")
            return {
                "Gucci": 95, "Prada": 90, "Louis Vuitton": 95,
                "Hermès": 95, "Chanel": 95, "Dior": 90,
            }
    
    def _load_category_scores(self) -> dict:
        """
        カテゴリの需要度スコアを読み込み。
        data/category_scores.json: {"Handbag": 85, "Shoe": 80, ...}
        """
        try:
            with open("data/category_scores.json", "r") as f:
                return json.load(f)
        except Exception:
            logger.warning("category_scores.json not found, using defaults")
            return {
                "Handbag": 85, "Shoe": 80, "Accessory": 70,
                "Clothing": 75, "Jewelry": 75,
            }
    
    def calculate_profit_score(self, ranked: RankedProduct) -> float:
        """
        利益スコア（0-100）。
        利益が多いほど高スコア。
        """
        min_profit = self.config.min_profit_jpy  # 3000
        max_profit = 50000  # 50000円以上で満点
        
        if ranked.est_profit_jpy <= 0:
            return 0.0
        
        score = (ranked.est_profit_jpy / max_profit) * 100
        return min(100.0, score)
    
    def calculate_competition_score(self, ranked: RankedProduct) -> float:
        """
        競合スコア（0-100）。
        競合数が少ないほど高スコア（逆スケール）。
        """
        # 競合数が多い = 市場が飽和
        # 競合 0-5件: 90-100
        # 競合 5-20件: 70-90
        # 競合 20-50件: 40-70
        # 競合 50+件: 0-40
        
        if ranked.competitor_count is None:
            return 50.0  # デフォルト
        
        count = ranked.competitor_count
        
        if count <= 5:
            return 95.0
        elif count <= 20:
            return 75.0 + (20 - count) / 20 * 20  # Linear
        elif count <= 50:
            return 40.0 + (50 - count) / 30 * 30
        else:
            return 20.0
    
    def calculate_brand_score(self, ranked: RankedProduct) -> float:
        """
        ブランドスコア（0-100）。
        人気ブランドほど高スコア。
        """
        product = ranked.source_product
        brand_name = product.brand
        
        return float(self.brand_scores.get(brand_name, 50.0))
    
    def calculate_category_score(self, ranked: RankedProduct) -> float:
        """
        カテゴリスコア（0-100）。
        需要の高いカテゴリほど高スコア。
        """
        product = ranked.source_product
        category = product.category
        
        return float(self.category_scores.get(category, 50.0))
    
    def calculate_overall_score(self, ranked: RankedProduct) -> float:
        """
        総合スコアを計算。
        重み付け：利益40% + 競合30% + ブランド20% + カテゴリ10%
        """
        profit_score = self.calculate_profit_score(ranked)
        competition_score = self.calculate_competition_score(ranked)
        brand_score = self.calculate_brand_score(ranked)
        category_score = self.calculate_category_score(ranked)
        
        overall = (
            profit_score * 0.4 +
            competition_score * 0.3 +
            brand_score * 0.2 +
            category_score * 0.1
        )
        
        return overall
    
    def assign_lane(self, score: float) -> Tuple[str, str]:
        """
        スコアから Lane を決定。
        
        Returns:
            (lane: "core" / "long_tail" / "hold" / "reject", reason: str)
        """
        if score >= 80:
            return "core", f"High profit & low competition (score: {score:.1f})"
        elif score >= 60:
            return "long_tail", f"Good balance (score: {score:.1f})"
        elif score >= 40:
            return "hold", f"Needs further analysis (score: {score:.1f})"
        else:
            return "reject", f"Low score (score: {score:.1f})"
    
    def score_product(self, session: Session, ranked_product_id: int) -> None:
        """
        1件の商品をスコアリング・Lane 決定。
        ranked_products の lane と rank_score を更新。
        """
        ranked = session.query(RankedProduct).get(ranked_product_id)
        product = ranked.source_product
        
        # スコア計算
        overall_score = self.calculate_overall_score(ranked)
        lane, reason = self.assign_lane(overall_score)
        
        # DB 更新
        ranked.rank_score = overall_score
        ranked.lane = lane
        ranked.decision_reason = reason
        
        session.commit()
        
        logger.info(
            f"Scored {product.id}: {product.brand} {product.title} → "
            f"lane={lane}, score={overall_score:.1f}"
        )
    
    def score_all(self, session: Session) -> dict:
        """
        全ランク付け商品をスコアリング・Lane 決定。
        
        Returns:
            {
                'core': Core Lane の件数,
                'long_tail': Long Tail Lane の件数,
                'hold': Hold Lane の件数,
                'reject': Reject Lane の件数,
            }
        """
        ranked_products = session.query(RankedProduct).filter(
            RankedProduct.lane == None
        ).all()
        
        logger.info(f"Scoring {len(ranked_products)} products...")
        
        for ranked in ranked_products:
            self.score_product(session, ranked.id)
        
        # 結果集計
        results = {
            'core': session.query(RankedProduct).filter(RankedProduct.lane == "core").count(),
            'long_tail': session.query(RankedProduct).filter(RankedProduct.lane == "long_tail").count(),
            'hold': session.query(RankedProduct).filter(RankedProduct.lane == "hold").count(),
            'reject': session.query(RankedProduct).filter(RankedProduct.lane == "reject").count(),
        }
        
        logger.info(f"Scoring completed: {results}")
        return results
```

### 納품物チェックリスト

- [ ] `app/ranker/scoring.py` が作成されている
- [ ] Scorer クラスに 4つのスコア計算メソッド（profit, competition, brand, category）が実装
- [ ] calculate_overall_score() で総合スコアを計算
- [ ] assign_lane() でスコアから Lane を決定
- [ ] score_product() で1件の商品をスコアリング
- [ ] score_all() で全商品をスコアリング

---

## タスク3-3: Ranker 統合スクリプト（scripts/run_ranker.py）

### 実施内容

Competitor Analysis → Scoring の2ステップを実行するメインスクリプト。

```python
# scripts/run_ranker.py

#!/usr/bin/env python3
"""
Ranker 実行スクリプト。
競合分析 → スコアリング・Lane 決定。

Usage:
    python3 scripts/run_ranker.py
"""

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import get_config
from app.core.logger import setup_logger
from app.core.models import Base
from app.ranker.competitor_analysis import CompetitorAnalyzer
from app.ranker.scoring import Scorer

logger = setup_logger("run_ranker")

def main():
    logger.info("=== Ranker started ===")
    
    # DB 初期化
    config = get_config()
    engine = create_engine(f"sqlite:///{config.db_path}")
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine)
    session = SessionFactory()
    
    try:
        # Step 1: Competitor Analysis
        logger.info("Step 1: Analyzing competitors...")
        analyzer = CompetitorAnalyzer()
        analyzer.analyze_all(session)
        
        # Step 2: Scoring & Lane Assignment
        logger.info("Step 2: Scoring and Lane assignment...")
        scorer = Scorer()
        lane_results = scorer.score_all(session)
        logger.info(f"Lane results: {lane_results}")
        
        logger.info("=== Ranker completed ===")
    finally:
        session.close()

if __name__ == "__main__":
    main()
```

### 納品物チェックリスト

- [ ] `scripts/run_ranker.py` が作成されている
- [ ] CompetitorAnalyzer と Scorer の2つのモジュールを順序実行
- [ ] 各処理結果がログに記録される

---

## データファイル（新規作成）

### data/brand_scores.json

```json
{
  "Gucci": 95,
  "Prada": 90,
  "Louis Vuitton": 95,
  "Hermès": 95,
  "Chanel": 95,
  "Dior": 90,
  "Fendi": 85,
  "Versace": 85,
  "Dolce & Gabbana": 80,
  "Burberry": 85,
  "Céline": 85,
  "Bottega Veneta": 80,
  "Balenciaga": 85,
  "Saint Laurent": 85,
  "Givenchy": 80,
  "Alexander McQueen": 80,
  "Valentino": 85,
  "Giorgio Armani": 75,
  "Armani Exchange": 70,
  "Emporio Armani": 75
}
```

### data/category_scores.json

```json
{
  "Handbag": 85,
  "Shoe": 80,
  "Accessory": 70,
  "Clothing": 75,
  "Jewelry": 75,
  "Sunglasses": 75,
  "Watch": 80,
  "Belt": 65,
  "Scarf": 60,
  "Glove": 50
}
```

---

## ディレクトリ構成の更新

PHASE3 完了後：

```
app/
├── ranker/
│   ├── __init__.py
│   ├── competitor_analysis.py  ← BUYMA競合分析
│   └── scoring.py              ← スコアリング・Lane決定
├── guards/
├── core/
├── scouts/
├── listing/
└── utils/

scripts/
├── run_pipeline.py      ← PHASE1
├── run_guard.py         ← PHASE2
└── run_ranker.py        ← PHASE3

data/
├── categories.json
├── brands.json
├── brand_scores.json    ← 新規
└── category_scores.json ← 新規
```

---

## 最終チェックリスト（PHASE3 完了）

- [ ] `app/ranker/` ディレクトリが作成されている
- [ ] CompetitorAnalyzer が BUYMA 検索結果を解析
- [ ] Scorer が総合スコアを計算し Lane を決定
- [ ] `scripts/run_ranker.py` が実装され、実行可能
- [ ] ranked_products テーブルに lane, rank_score, competitor_count が設定される
- [ ] data/brand_scores.json と data/category_scores.json が存在

