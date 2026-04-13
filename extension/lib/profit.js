// 利益計算ロジック（Python 版 scripts/run_pipeline.py からの移植）。
//
// 計算式:
//   cost_jpy   = (source_price + shipping) * exchange_rate
//   list_price = ceil(cost_jpy * (1 + target_margin) / (1 - commission_rate) / 100) * 100
//   profit_jpy = list_price * (1 - commission_rate) - cost_jpy
//   margin_pct = profit_jpy / cost_jpy * 100

export function calculateProfit(product, config) {
  const sourcePrice = Number(product.sourcePrice) || 0;
  const shipping = config.shippingCostEur || 0;
  const rate = config.exchangeRate;
  const targetMargin = (config.targetMarginPct || 0) / 100;
  const commission = config.buymaCommissionRate;

  const costJpy = (sourcePrice + shipping) * rate;
  const rawList = (costJpy * (1 + targetMargin)) / (1 - commission);
  const listPrice = Math.ceil(rawList / 100) * 100; // 100 円単位に切り上げ
  const profitJpy = listPrice * (1 - commission) - costJpy;
  const marginPct = costJpy > 0 ? (profitJpy / costJpy) * 100 : 0;

  return {
    costJpy: Math.round(costJpy),
    listPriceJpy: listPrice,
    profitJpy: Math.round(profitJpy),
    marginPct: Math.round(marginPct * 10) / 10,
  };
}
