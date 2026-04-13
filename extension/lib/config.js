// 既定設定値。ユーザーが Options UI で上書きした値は chrome.storage.sync に保存する。
export const DEFAULT_CONFIG = {
  // 為替レート（EUR → JPY）。フォールバック値。
  exchangeRate: 163.0,
  // 目標利益率（%）
  targetMarginPct: 25.0,
  // 最低利益額（JPY）
  minProfitJpy: 3000.0,
  // BUYMA 手数料率
  buymaCommissionRate: 0.058,
  // 国際配送送料（EUR）
  shippingCostEur: 30.0,
  // 出品タイトル末尾に付与する文言
  titleSuffix: "正規品/関税送料込",
  // タイトル最大長（BUYMA は全角 60 相当）
  maxTitleLength: 120,
};

const STORAGE_KEY = "buyma_config";

export async function loadConfig() {
  return new Promise((resolve) => {
    chrome.storage.sync.get([STORAGE_KEY], (result) => {
      const saved = result[STORAGE_KEY] || {};
      resolve({ ...DEFAULT_CONFIG, ...saved });
    });
  });
}

export async function saveConfig(partial) {
  const current = await loadConfig();
  const merged = { ...current, ...partial };
  return new Promise((resolve) => {
    chrome.storage.sync.set({ [STORAGE_KEY]: merged }, () => resolve(merged));
  });
}
