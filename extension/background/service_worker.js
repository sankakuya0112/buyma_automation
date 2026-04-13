// Service Worker。popup とコンテンツスクリプトの橋渡し・タブ制御を担当する。

// BUYMA の出品フォーム URL（実際の URL に合わせて調整）
const BUYMA_LISTING_URL = "https://www.buyma.com/my/sell/new";

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === "OPEN_BUYMA_AND_FILL") {
    openBuymaAndFill(msg.payload, msg.options || {})
      .then((result) => sendResponse({ ok: true, result }))
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }

  if (msg && msg.type === "SCRAPE_URL_IN_BACKGROUND") {
    scrapeUrlInBackground(msg.url)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
});

// ---------------------------------------------------------------------------
// BUYMA 出品フォームを開いて、ロード完了後にコンテンツスクリプトへ入力依頼を送る
// ---------------------------------------------------------------------------

async function openBuymaAndFill(payload, options) {
  const tab = await chrome.tabs.create({ url: BUYMA_LISTING_URL, active: true });
  // タブが完全にロードされるまで待つ
  await waitForTabComplete(tab.id);
  // コンテンツスクリプトの準備時間を少し確保
  await sleep(1500);

  const resp = await chrome.tabs.sendMessage(tab.id, {
    type: "BUYMA_FILL_FORM",
    payload,
    options,
  });
  return resp;
}

// ---------------------------------------------------------------------------
// baseblu の商品 URL を裏タブで開き、スクレイプして閉じる
// ---------------------------------------------------------------------------

async function scrapeUrlInBackground(url) {
  const tab = await chrome.tabs.create({ url, active: false });
  try {
    await waitForTabComplete(tab.id);
    await sleep(1000);
    const resp = await chrome.tabs.sendMessage(tab.id, {
      type: "BASEBLU_SCRAPE_CURRENT",
    });
    return resp && resp.ok ? resp.data : null;
  } finally {
    try {
      await chrome.tabs.remove(tab.id);
    } catch (_) {
      // 既に閉じられている場合など
    }
  }
}

// ---------------------------------------------------------------------------
// ユーティリティ
// ---------------------------------------------------------------------------

function waitForTabComplete(tabId, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      reject(new Error("タブのロードがタイムアウトしました"));
    }, timeoutMs);

    const listener = (updatedTabId, info) => {
      if (updatedTabId === tabId && info.status === "complete") {
        clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    };
    chrome.tabs.onUpdated.addListener(listener);
  });
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}
