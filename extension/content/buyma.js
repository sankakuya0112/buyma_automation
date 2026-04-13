// BUYMA 出品フォームに商品情報を自動入力するコンテンツスクリプト。
//
// BUYMA のフォーム構造は時期により変わる可能性があるため、セレクタは
// 堅牢性を優先して複数候補を試す設計にしてある。
// 実際の DOM 構造にあわせて SELECTORS を調整すること。

(function () {
  "use strict";

  // ---------------------------------------------------------------------------
  // セレクタ定義（BUYMA のフォーム UI に応じて調整）
  // ---------------------------------------------------------------------------

  const SELECTORS = {
    title: [
      'input[name="item_name"]',
      'input[name*="title"]',
      '#item_name',
    ],
    brand: [
      'input[name="brand_name"]',
      'input[name*="brand"]',
    ],
    category: [
      'select[name*="category"]',
    ],
    price: [
      'input[name="item_price"]',
      'input[name*="price"]',
    ],
    color: [
      'input[name*="color"]',
      'input[name*="colour"]',
    ],
    description: [
      'textarea[name="item_comment"]',
      'textarea[name*="description"]',
      'textarea[name*="comment"]',
    ],
    imageInput: [
      'input[type="file"][name*="image"]',
      'input[type="file"][accept*="image"]',
    ],
    submitDraft: [
      'button[name="draft"]',
      'button[data-action="draft"]',
      'input[value*="下書き"]',
    ],
    submitPublish: [
      'button[type="submit"][name="publish"]',
      'button[data-action="publish"]',
      'input[value*="出品"]',
    ],
  };

  // ---------------------------------------------------------------------------
  // メッセージハンドラ
  // ---------------------------------------------------------------------------

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg && msg.type === "BUYMA_FILL_FORM") {
      fillForm(msg.payload, msg.options || {})
        .then((result) => sendResponse({ ok: true, result }))
        .catch((err) => sendResponse({ ok: false, error: String(err) }));
      return true;
    }
    if (msg && msg.type === "BUYMA_PING") {
      sendResponse({ ok: true, url: window.location.href });
      return false;
    }
  });

  // ---------------------------------------------------------------------------
  // フォーム入力本体
  // ---------------------------------------------------------------------------

  async function fillForm(payload, options) {
    // payload: { titleJa, brandJa, categoryJa, listPriceJpy, color, descriptionJa, imageUrls }
    const log = [];
    const filled = (label, ok) => log.push(`${ok ? "✓" : "✗"} ${label}`);

    filled("タイトル", await setField(SELECTORS.title, payload.titleJa));
    filled("ブランド", await setField(SELECTORS.brand, payload.brandJa));
    filled("価格", await setField(SELECTORS.price, String(payload.listPriceJpy)));
    filled("カラー", await setField(SELECTORS.color, payload.color || ""));
    filled("商品説明", await setField(SELECTORS.description, payload.descriptionJa));

    // 画像アップロードは URL → Blob 変換 → File オブジェクト注入が必要で、
    // BUYMA 側のバリデーションによって動作が変わるため、手動確認を推奨する。
    if (payload.imageUrls && payload.imageUrls.length > 0) {
      try {
        await uploadImagesFromUrls(payload.imageUrls);
        filled(`画像 ${payload.imageUrls.length} 枚`, true);
      } catch (e) {
        filled(`画像アップロード失敗: ${e.message}`, false);
      }
    }

    if (options.autoSubmit === "draft") {
      const btn = findFirst(SELECTORS.submitDraft);
      if (btn) {
        btn.click();
        log.push("→ 下書き保存をクリック");
      } else {
        log.push("⚠ 下書きボタンが見つかりません（手動でクリックしてください）");
      }
    } else if (options.autoSubmit === "publish") {
      const btn = findFirst(SELECTORS.submitPublish);
      if (btn) {
        btn.click();
        log.push("→ 出品ボタンをクリック");
      } else {
        log.push("⚠ 出品ボタンが見つかりません（手動でクリックしてください）");
      }
    }

    return { log };
  }

  // ---------------------------------------------------------------------------
  // DOM ユーティリティ
  // ---------------------------------------------------------------------------

  function findFirst(selectors) {
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el) return el;
    }
    return null;
  }

  async function setField(selectors, value) {
    if (value === undefined || value === null) return false;
    const el = findFirst(selectors);
    if (!el) return false;

    if (el.tagName === "SELECT") {
      // セレクト: ラベル一致を優先
      const opts = Array.from(el.options);
      const match = opts.find(
        (o) => o.text.trim() === String(value).trim() || o.value === value,
      );
      if (match) {
        el.value = match.value;
        el.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
      }
      return false;
    }

    // text / textarea
    el.focus();
    el.value = String(value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.blur();
    return true;
  }

  async function uploadImagesFromUrls(urls) {
    const fileInput = findFirst(SELECTORS.imageInput);
    if (!fileInput) throw new Error("画像アップロード input が見つからない");

    const dt = new DataTransfer();
    for (let i = 0; i < urls.length; i++) {
      const res = await fetch(urls[i]);
      if (!res.ok) continue;
      const blob = await res.blob();
      const ext = (blob.type.split("/")[1] || "jpg").split(";")[0];
      const file = new File([blob], `image_${i + 1}.${ext}`, { type: blob.type });
      dt.items.add(file);
    }
    fileInput.files = dt.files;
    fileInput.dispatchEvent(new Event("change", { bubbles: true }));
  }
})();
