// Governor: 出品可否判定（Python 版 app/governors/rules.py の移植）。
// 全チェックを通れば approved、NG が出たら reject / hold を返す。

export function evaluate(product, pricing, config, existingProducts = []) {
  const checks = [
    checkSku(product),
    checkBrand(product),
    checkImages(product),
    checkPrice(product),
    checkDuplicate(product, existingProducts),
    checkProfit(pricing, config),
  ];

  const failed = checks.find((c) => !c.ok);
  if (failed) {
    return {
      decision: failed.severity === "reject" ? "rejected" : "hold",
      reason: failed.reason,
    };
  }
  return { decision: "approved", reason: "全チェック通過" };
}

function checkSku(p) {
  if (!p.sku || p.sku.length < 3) {
    return { ok: false, severity: "hold", reason: "SKU が空または短すぎる" };
  }
  return { ok: true };
}

function checkBrand(p) {
  if (!p.brand || p.brand.trim().length === 0) {
    return { ok: false, severity: "reject", reason: "ブランド名が取得できていない" };
  }
  return { ok: true };
}

function checkImages(p) {
  const urls = p.imageUrls || [];
  if (urls.length === 0) {
    return { ok: false, severity: "reject", reason: "画像 URL が 1 件もない" };
  }
  return { ok: true };
}

function checkPrice(p) {
  const price = Number(p.sourcePrice) || 0;
  if (price <= 0) {
    return { ok: false, severity: "reject", reason: "価格が 0 以下" };
  }
  return { ok: true };
}

function checkDuplicate(p, existing) {
  const dup = existing.find(
    (x) => x.productUrl !== p.productUrl && x.sku && x.sku === p.sku && x.status === "listed",
  );
  if (dup) {
    return { ok: false, severity: "hold", reason: `同一 SKU 出品済み (${dup.sku})` };
  }
  return { ok: true };
}

function checkProfit(pricing, config) {
  if (pricing.profitJpy < config.minProfitJpy) {
    return {
      ok: false,
      severity: "hold",
      reason: `利益 ¥${pricing.profitJpy} が最低額 ¥${config.minProfitJpy} 未満`,
    };
  }
  if (pricing.marginPct < config.targetMarginPct) {
    return {
      ok: false,
      severity: "hold",
      reason: `利益率 ${pricing.marginPct}% が目標 ${config.targetMarginPct}% 未満`,
    };
  }
  return { ok: true };
}
