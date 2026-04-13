// baseblu.com の商品ページから商品情報を抽出するコンテンツスクリプト。
// popup / service_worker からのメッセージを受けて Shopify の product.json を取得し
// 正規化した商品オブジェクトを返す。

(function () {
  "use strict";

  // ---------------------------------------------------------------------------
  // メッセージハンドラ
  // ---------------------------------------------------------------------------

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg && msg.type === "BASEBLU_SCRAPE_CURRENT") {
      scrapeCurrentPage()
        .then((data) => sendResponse({ ok: true, data }))
        .catch((err) => sendResponse({ ok: false, error: String(err) }));
      return true; // 非同期応答
    }
    if (msg && msg.type === "BASEBLU_COLLECT_LIST") {
      collectListPageLinks()
        .then((urls) => sendResponse({ ok: true, urls }))
        .catch((err) => sendResponse({ ok: false, error: String(err) }));
      return true;
    }
  });

  // ---------------------------------------------------------------------------
  // 単一商品ページのスクレイプ
  // ---------------------------------------------------------------------------

  async function scrapeCurrentPage() {
    const url = window.location.href;
    if (!/\/products\//.test(url)) {
      throw new Error("商品詳細ページで実行してください");
    }

    const jsonUrl = url.split("?")[0].split("#")[0].replace(/\/$/, "") + ".json";
    try {
      const res = await fetch(jsonUrl, { headers: { Accept: "application/json" } });
      if (res.ok) {
        const body = await res.json();
        if (body && body.product) {
          return parseShopifyJson(body.product, url);
        }
      }
    } catch (e) {
      // JSON 取得失敗 → HTML フォールバック
    }
    return parseFromDom(url);
  }

  // Shopify の price フィールドはセント単位の整数で返る場合がある（BaseBlu はこのケース）。
  // 小数点を含まず 100 以上の値はセントとみなして 100 で割る。
  function parseShopifyPrice(raw) {
    const s = String(raw || "0");
    const val = parseFloat(s) || 0;
    if (!s.includes(".") && val >= 100) {
      return val / 100;
    }
    return val;
  }

  function parseShopifyJson(data, productUrl) {
    const variants = data.variants || [];
    let salePrice = 0;
    for (const v of variants) {
      const p = parseShopifyPrice(v.price);
      if (!isNaN(p) && (salePrice === 0 || p < salePrice)) salePrice = p;
    }

    const sizes = [
      ...new Set(variants.map((v) => v.option1).filter((x) => x)),
    ];
    const images = (data.images || []).map((img) => img.src).filter(Boolean);

    let color = "";
    for (const opt of data.options || []) {
      if (["color", "colour", "colore"].includes((opt.name || "").toLowerCase())) {
        color = (opt.values || []).join(", ");
        break;
      }
    }

    const bodyHtml = data.body_html || "";
    const tmp = document.createElement("div");
    tmp.innerHTML = bodyHtml;
    const descriptionEn = tmp.textContent.replace(/\s+/g, " ").trim();

    return {
      productUrl,
      source: "baseblu",
      brand: (data.vendor || "").trim(),
      title: (data.title || "").trim(),
      sku: (data.handle || "").trim(),
      color: color.trim(),
      category: (data.product_type || "").trim(),
      sourcePrice: salePrice,
      currency: "EUR",
      sizes,
      imageUrls: images,
      descriptionEn,
      stockStatus: "in_stock",
    };
  }

  function parseFromDom(productUrl) {
    const safeText = (sel) => {
      const el = document.querySelector(sel);
      return el ? (el.textContent || "").trim() : "";
    };
    const brand = safeText('[class*="vendor"]') || safeText('[class*="brand"]');
    const title = safeText("h1");
    const sku = safeText('[class*="sku"]') || safeText('[class*="reference"]');
    const color = safeText('[class*="color"]') || safeText('[class*="colour"]');
    const priceText = safeText('[class*="price"]');
    const price =
      parseFloat(priceText.replace(/[€,\s]/g, "").replace(",", ".")) || 0;

    const imgs = Array.from(
      document.querySelectorAll('[class*="product"] img'),
    )
      .map((img) => img.src)
      .filter(Boolean);

    return {
      productUrl,
      source: "baseblu",
      brand,
      title,
      sku,
      color,
      category: "",
      sourcePrice: price,
      currency: "EUR",
      sizes: [],
      imageUrls: imgs,
      descriptionEn: safeText('[class*="description"]'),
      stockStatus: "in_stock",
    };
  }

  // ---------------------------------------------------------------------------
  // セール一覧ページから商品詳細 URL を収集
  // ---------------------------------------------------------------------------

  async function collectListPageLinks() {
    const anchors = document.querySelectorAll('a[href*="/products/"]');
    const seen = new Set();
    const urls = [];
    anchors.forEach((a) => {
      let href = a.getAttribute("href") || "";
      if (!href) return;
      if (!/^https?:/.test(href)) href = "https://www.baseblu.com" + href;
      href = href.split("?")[0].split("#")[0];
      if (!seen.has(href)) {
        seen.add(href);
        urls.push(href);
      }
    });
    return urls;
  }
})();
