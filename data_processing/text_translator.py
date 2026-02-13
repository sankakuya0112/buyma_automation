"""テキスト翻訳（英語→日本語）"""

import logging

logger = logging.getLogger(__name__)


class TextTranslator:
    """商品テキストの英日翻訳を行うクラス

    現在はテンプレートベースの簡易翻訳を実装。
    Google Cloud Translation APIを使用する場合は、
    requirements.txtにgoogle-cloud-translate追加の上、
    translate_with_api()を実装してください。
    """

    # よく使うファッション用語の簡易辞書
    FASHION_DICT: dict[str, str] = {
        "dress": "ドレス",
        "shirt": "シャツ",
        "blouse": "ブラウス",
        "pants": "パンツ",
        "trousers": "トラウザーズ",
        "skirt": "スカート",
        "jacket": "ジャケット",
        "coat": "コート",
        "sweater": "セーター",
        "cardigan": "カーディガン",
        "sneakers": "スニーカー",
        "boots": "ブーツ",
        "sandals": "サンダル",
        "bag": "バッグ",
        "handbag": "ハンドバッグ",
        "wallet": "ウォレット",
        "scarf": "スカーフ",
        "belt": "ベルト",
        "sunglasses": "サングラス",
        "leather": "レザー",
        "cotton": "コットン",
        "silk": "シルク",
        "wool": "ウール",
        "cashmere": "カシミヤ",
        "linen": "リネン",
        "denim": "デニム",
        "black": "ブラック",
        "white": "ホワイト",
        "red": "レッド",
        "blue": "ブルー",
        "green": "グリーン",
        "navy": "ネイビー",
        "beige": "ベージュ",
        "grey": "グレー",
        "gray": "グレー",
        "pink": "ピンク",
    }

    def generate_product_title_ja(self, brand: str, name: str, category: str = "") -> str:
        """日本語の商品タイトルを生成する"""
        # ブランド名はそのまま使用
        title_parts = []
        if brand:
            title_parts.append(brand)
        if name:
            title_parts.append(name)
        if category:
            translated_category = self.FASHION_DICT.get(category.lower(), category)
            title_parts.append(translated_category)

        return " ".join(title_parts)

    def generate_description_ja(self, product: dict) -> str:
        """日本語の商品説明文を生成する"""
        brand = product.get("brand", "")
        name = product.get("name", "")
        color = product.get("color", "")
        description = product.get("description", "")

        lines = [
            f"【{brand}】{name}",
            "",
        ]

        if color:
            translated_color = self.FASHION_DICT.get(color.lower(), color)
            lines.append(f"■カラー: {translated_color}")

        sizes = product.get("sizes", [])
        if sizes:
            if isinstance(sizes, list):
                lines.append(f"■サイズ: {', '.join(sizes)}")
            else:
                lines.append(f"■サイズ: {sizes}")

        lines.extend(
            [
                "",
                "■商品説明",
                description,
                "",
                "---",
                "※ご注文前に在庫確認をお願いいたします。",
                "※海外製品のため、日本の製品基準とは異なる場合がございます。",
                "※モニターの発色具合により、実際のものと色が異なる場合がございます。",
                "※関税が発生した場合はバイヤー負担となります。",
            ]
        )

        return "\n".join(lines)

    def enrich_product_with_translations(self, product: dict) -> dict:
        """商品辞書に日本語テキストを追加する"""
        product["name_ja"] = self.generate_product_title_ja(
            product.get("brand", ""),
            product.get("name", ""),
            product.get("category", ""),
        )
        product["description_ja"] = self.generate_description_ja(product)
        return product
