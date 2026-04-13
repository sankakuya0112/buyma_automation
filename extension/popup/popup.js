import { loadConfig, saveConfig, DEFAULT_CONFIG } from "../lib/config.js";
import {
  getAllProducts,
  upsertProduct,
  updateProduct,
  deleteProduct,
  clearAllProducts,
} from "../lib/storage.js";
import { calculateProfit } from "../lib/profit.js";
import { evaluate as evalGovernor } from "../lib/governor.js";
import {
  translateBrand,
  translateCategory,
  generateBuymaTitle,
  generateBuymaDescription,
} from "../lib/translator.js";

// ---------------------------------------------------------------------------
// 初期化
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", async () => {
  setupTabs();
  setupScrapeButtons();
  setupSettings();
  setupProductListActions();
  await renderProducts();
  await renderSettings();
});

// ---------------------------------------------------------------------------
// タブ切り替え
// ---------------------------------------------------------------------------

function setupTabs() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const name = btn.dataset.tab;
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(`tab-${name}`).classList.add("active");
    });
  });
}

// ---------------------------------------------------------------------------
// スクレイプ処理
// ---------------------------------------------------------------------------

function setupScrapeButtons() {
  document.getElementById("btn-scrape-current").addEventListener("click", scrapeCurrent);
  document.getElementById("btn-scrape-list").addEventListener("click", scrapeList);
}

async function scrapeCurrent() {
  const log = document.getElementById("scrape-log");
  log.textContent = "現在のタブから取得中...\n";
  try {
    const tab = await getActiveTab();
    if (!tab.url || !/baseblu\.com/.test(tab.url)) {
      log.textContent += "baseblu.com のページで実行してください。\n";
      return;
    }
    const resp = await chrome.tabs.sendMessage(tab.id, { type: "BASEBLU_SCRAPE_CURRENT" });
    if (!resp || !resp.ok) {
      log.textContent += `エラー: ${resp && resp.error ? resp.error : "不明"}\n`;
      return;
    }
    const saved = await processAndSave(resp.data);
    log.textContent += `✓ ${saved.brand} / ${saved.title}\n  → ${saved.decision}: ${saved.decisionReason}\n`;
    await renderProducts();
  } catch (e) {
    log.textContent += `例外: ${e.message}\n`;
  }
}

async function scrapeList() {
  const log = document.getElementById("scrape-log");
  log.textContent = "一覧ページから URL 収集中...\n";
  try {
    const tab = await getActiveTab();
    if (!tab.url || !/baseblu\.com/.test(tab.url)) {
      log.textContent += "baseblu.com の一覧ページで実行してください。\n";
      return;
    }
    const resp = await chrome.tabs.sendMessage(tab.id, { type: "BASEBLU_COLLECT_LIST" });
    if (!resp || !resp.ok) {
      log.textContent += `エラー: ${resp && resp.error ? resp.error : "不明"}\n`;
      return;
    }
    const urls = resp.urls || [];
    log.textContent += `${urls.length} 件の URL を検出\n`;

    for (let i = 0; i < urls.length; i++) {
      log.textContent += `[${i + 1}/${urls.length}] ${urls[i]}\n`;
      try {
        const bg = await chrome.runtime.sendMessage({
          type: "SCRAPE_URL_IN_BACKGROUND",
          url: urls[i],
        });
        if (bg && bg.ok && bg.data) {
          const saved = await processAndSave(bg.data);
          log.textContent += `  ✓ ${saved.decision}: ¥${saved.pricing.listPriceJpy} (利益 ¥${saved.pricing.profitJpy})\n`;
        } else {
          log.textContent += `  ✗ 失敗: ${bg && bg.error ? bg.error : "不明"}\n`;
        }
      } catch (e) {
        log.textContent += `  ✗ 例外: ${e.message}\n`;
      }
      // BOT 検出回避の待機
      await sleep(1500);
    }
    log.textContent += "完了\n";
    await renderProducts();
  } catch (e) {
    log.textContent += `例外: ${e.message}\n`;
  }
}

async function processAndSave(raw) {
  const config = await loadConfig();
  const existing = await getAllProducts();

  const pricing = calculateProfit(raw, config);
  const { decision, reason } = evalGovernor(raw, pricing, config, existing);

  const titleJa = await generateBuymaTitle(raw, config.maxTitleLength);
  const brandJa = await translateBrand(raw.brand);
  const categoryJa = await translateCategory(raw.category);
  const descriptionJa = await generateBuymaDescription(raw);

  const record = {
    ...raw,
    pricing,
    decision,
    decisionReason: reason,
    titleJa,
    brandJa,
    categoryJa,
    descriptionJa,
    status: decision === "approved" ? "approved" : decision,
  };
  return await upsertProduct(record);
}

// ---------------------------------------------------------------------------
// 商品一覧表示
// ---------------------------------------------------------------------------

async function renderProducts() {
  const container = document.getElementById("product-list");
  const products = await getAllProducts();
  document.getElementById("product-count").textContent = `${products.length} 件`;

  container.innerHTML = "";
  if (products.length === 0) {
    container.innerHTML = '<p class="note">商品がまだありません。「取得」タブから始めてください。</p>';
    return;
  }

  // 新しい順
  products.sort((a, b) => b.updatedAt - a.updatedAt);

  for (const p of products) {
    container.appendChild(renderProductCard(p));
  }
}

function renderProductCard(p) {
  const card = document.createElement("div");
  card.className = "product-card";
  card.dataset.id = p.id;

  const img = document.createElement("img");
  img.src = (p.imageUrls && p.imageUrls[0]) || "";
  img.alt = p.title || "";
  card.appendChild(img);

  const meta = document.createElement("div");
  meta.className = "meta";

  const brand = document.createElement("span");
  brand.className = "brand";
  brand.textContent = p.brand || "(brand?)";
  meta.appendChild(brand);

  const title = document.createElement("span");
  title.className = "title";
  title.textContent = p.title || "";
  meta.appendChild(title);

  if (p.pricing) {
    const pricing = document.createElement("div");
    pricing.className = "pricing";
    const profitOk = (p.decision || "") === "approved";
    const symbol = p.currency === "JPY" ? "¥" : "€";
    pricing.innerHTML = `
      <span>仕入: ${symbol}${Number(p.sourcePrice).toLocaleString()}</span>
      <span>出品: ¥${p.pricing.listPriceJpy.toLocaleString()}</span>
      <span class="profit ${profitOk ? "ok" : "ng"}">利益 ¥${p.pricing.profitJpy.toLocaleString()} (${p.pricing.marginPct}%)</span>
    `;
    meta.appendChild(pricing);
  }

  const decisionBadge = document.createElement("span");
  decisionBadge.className = `decision ${p.decision || "hold"}`;
  decisionBadge.textContent = `${decisionLabel(p.decision)} — ${p.decisionReason || ""}`;
  meta.appendChild(decisionBadge);

  const actions = document.createElement("div");
  actions.className = "actions";
  actions.innerHTML = `
    <button data-action="list-draft" class="primary">BUYMA下書き</button>
    <button data-action="list-publish">出品</button>
    <button data-action="delete" class="danger">削除</button>
  `;
  meta.appendChild(actions);

  card.appendChild(meta);
  return card;
}

function decisionLabel(d) {
  if (d === "approved") return "承認";
  if (d === "rejected") return "NG";
  if (d === "hold") return "保留";
  return "未判定";
}

// ---------------------------------------------------------------------------
// 商品カードのアクション（BUYMA 出品、削除）
// ---------------------------------------------------------------------------

function setupProductListActions() {
  document.getElementById("product-list").addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-action]");
    if (!btn) return;
    const card = e.target.closest(".product-card");
    const id = card.dataset.id;
    const action = btn.dataset.action;

    if (action === "delete") {
      await deleteProduct(id);
      await renderProducts();
      return;
    }

    const products = await getAllProducts();
    const product = products.find((p) => p.id === id);
    if (!product) return;

    const autoSubmit = action === "list-publish" ? "publish" : "draft";
    btn.disabled = true;
    btn.textContent = "送信中...";
    try {
      const resp = await chrome.runtime.sendMessage({
        type: "OPEN_BUYMA_AND_FILL",
        payload: {
          titleJa: product.titleJa,
          brandJa: product.brandJa,
          categoryJa: product.categoryJa,
          listPriceJpy: product.pricing.listPriceJpy,
          color: product.color,
          descriptionJa: product.descriptionJa,
          imageUrls: product.imageUrls,
        },
        options: { autoSubmit },
      });
      if (resp && resp.ok) {
        await updateProduct(id, { status: "listed", listedAt: Date.now() });
      } else {
        alert(`BUYMA への送信に失敗しました: ${resp && resp.error ? resp.error : "不明"}`);
      }
    } catch (e) {
      alert(`例外: ${e.message}`);
    } finally {
      await renderProducts();
    }
  });

  document.getElementById("btn-clear").addEventListener("click", async () => {
    if (!confirm("全商品を削除します。よろしいですか？")) return;
    await clearAllProducts();
    await renderProducts();
  });
}

// ---------------------------------------------------------------------------
// 設定タブ
// ---------------------------------------------------------------------------

async function renderSettings() {
  const cfg = await loadConfig();
  for (const key of Object.keys(DEFAULT_CONFIG)) {
    const input = document.getElementById(`cfg-${key}`);
    if (input) input.value = cfg[key];
  }
}

function setupSettings() {
  document.getElementById("btn-save-settings").addEventListener("click", async () => {
    const patch = {};
    for (const key of Object.keys(DEFAULT_CONFIG)) {
      const input = document.getElementById(`cfg-${key}`);
      if (!input) continue;
      const v = input.value;
      patch[key] = typeof DEFAULT_CONFIG[key] === "number" ? Number(v) : v;
    }
    await saveConfig(patch);
    const status = document.getElementById("settings-status");
    status.textContent = "✓ 保存しました";
    setTimeout(() => (status.textContent = ""), 2000);
  });
}

// ---------------------------------------------------------------------------
// ユーティリティ
// ---------------------------------------------------------------------------

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}
