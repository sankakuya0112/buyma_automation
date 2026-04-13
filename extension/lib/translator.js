// ブランド・カテゴリの日本語化ユーティリティ。
// data/*.json をフェッチしてキャッシュする。

let _brandsCache = null;
let _categoriesCache = null;

async function loadJson(path) {
  const url = chrome.runtime.getURL(path);
  const res = await fetch(url);
  return res.json();
}

async function getBrandMap() {
  if (!_brandsCache) _brandsCache = await loadJson("data/brands.json");
  return _brandsCache;
}

async function getCategoryMap() {
  if (!_categoriesCache) _categoriesCache = await loadJson("data/categories.json");
  return _categoriesCache;
}

export async function translateBrand(brand) {
  if (!brand) return "";
  const map = await getBrandMap();
  const key = brand.toLowerCase().trim();
  return map[key] || brand;
}

export async function translateCategory(category) {
  if (!category) return "";
  const map = await getCategoryMap();
  const key = category.toLowerCase().trim();
  return map[key] || category;
}

// BUYMA 出品タイトル生成（Python 版 app/utils/text.py 相当）。
export async function generateBuymaTitle(product, maxLen = 120) {
  const brandJa = await translateBrand(product.brand);
  const parts = [
    brandJa,
    product.title,
    product.sku,
    product.color,
    "正規品",
    "関税送料込",
  ].filter((s) => s && String(s).trim().length > 0);

  let title = parts.join(" / ");
  if (title.length > maxLen) title = title.slice(0, maxLen);
  return title;
}

// 商品説明の日本語テンプレート生成。入荷元・仕入れ値を露出しない。
export async function generateBuymaDescription(product) {
  const brandJa = await translateBrand(product.brand);
  const lines = [
    `【${brandJa}】 ${product.title}`,
    "",
    "=====================",
    "■ 商品について",
    "=====================",
    "海外正規取扱店より買付ける100%本物・新品の商品となります。",
    "関税・国際送料込みのお値段です。",
    "",
  ];
  if (product.color) lines.push(`カラー: ${product.color}`);
  if (product.sku) lines.push(`品番: ${product.sku}`);
  if (product.descriptionEn) {
    lines.push("", "=====================", "■ 商品詳細", "=====================", product.descriptionEn);
  }
  lines.push(
    "",
    "=====================",
    "■ ご注文前にご確認ください",
    "=====================",
    "・在庫状況は日々変動しております。ご注文前に在庫確認のお問い合わせをお願いいたします。",
    "・海外からの発送のため、お届けまで2〜3週間程度いただきます。",
    "・関税・国際送料は価格に含まれております。",
  );
  return lines.join("\n");
}
