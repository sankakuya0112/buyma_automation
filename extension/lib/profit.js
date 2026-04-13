// 利益計算ロジック（Python 版 scripts/run_pipeline.py からの移植）。
//
// 通貨別の計算式:
//   currency=JPY:  cost_jpy = source_price + shipping_eur * rate
//   currency=EUR:  cost_jpy = (source_price + shipping_eur) * rate
//   list_price = ceil(cost_jpy * (1 + target_margin) / (1 - commission_rate) / 100) * 100
//   profit_jpy = list_price * (1 - commission_rate) - cost_jpy
//   margin_pct = profit_jpy / cost_jpy * 100

export function calculateProfit(product, config) {
  const sourcePrice = Number(product.sourcePrice) || 0;
  const shippingEur = config.shippingCostEur || 0;
  const rate = config.exchangeRate;
  const targetMargin = (config.targetMarginPct || 0) / 100;
  const commission = config.buymaCommissionRate;

  // 仕入れ価格を JPY に変換。BaseBlu は JPY で返すためそのまま使う。
  const sourcePriceJpy = product.currency === "JPY" ? sourcePrice : sourcePrice * rate;
  // 送料は設定値が EUR なので常に換算する
  const shippingJpy = shippingEur * rate;
  const costJpy = sourcePriceJpy + shippingJpy;

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
