// chrome.storage.local をラップする簡易 CRUD。products はキー "products" に配列で保存する。
const PRODUCTS_KEY = "products";

export async function getAllProducts() {
  return new Promise((resolve) => {
    chrome.storage.local.get([PRODUCTS_KEY], (result) => {
      resolve(result[PRODUCTS_KEY] || []);
    });
  });
}

export async function getProduct(id) {
  const all = await getAllProducts();
  return all.find((p) => p.id === id) || null;
}

export async function upsertProduct(product) {
  const all = await getAllProducts();
  const idx = all.findIndex((p) => p.productUrl === product.productUrl);
  if (idx >= 0) {
    // 既存レコードを更新（id / createdAt は保持）
    all[idx] = { ...all[idx], ...product, updatedAt: Date.now() };
  } else {
    all.push({
      id: crypto.randomUUID(),
      createdAt: Date.now(),
      updatedAt: Date.now(),
      status: "new", // new | approved | rejected | listed
      ...product,
    });
  }
  await setProducts(all);
  return all.find((p) => p.productUrl === product.productUrl);
}

export async function updateProduct(id, patch) {
  const all = await getAllProducts();
  const idx = all.findIndex((p) => p.id === id);
  if (idx < 0) return null;
  all[idx] = { ...all[idx], ...patch, updatedAt: Date.now() };
  await setProducts(all);
  return all[idx];
}

export async function deleteProduct(id) {
  const all = await getAllProducts();
  const filtered = all.filter((p) => p.id !== id);
  await setProducts(filtered);
}

export async function clearAllProducts() {
  await setProducts([]);
}

async function setProducts(list) {
  return new Promise((resolve) => {
    chrome.storage.local.set({ [PRODUCTS_KEY]: list }, () => resolve());
  });
}
