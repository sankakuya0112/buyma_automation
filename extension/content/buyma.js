// BUYMA 出品フォームに商品情報を自動入力するコンテンツスクリプト。
// セレクタは cowork (Claude.ai) による実際のフォーム解析結果に基づく。

(function () {
  "use strict";

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
  // フォーム入力メイン
  // ---------------------------------------------------------------------------

  async function fillForm(payload, options) {
    const log = [];
    const ok = (label) => log.push(`✓ ${label}`);
    const ng = (label, reason) => log.push(`✗ ${label}: ${reason}`);

    // 1. タイトル（最初の text input）
    if (await setByQueryIndex('input[type="text"]', 0, payload.titleJa)) ok("タイトル");
    else ng("タイトル", "input が見つからない");

    // 2. 商品説明（最初の textarea）
    if (await setTextarea("textarea", payload.descriptionJa)) ok("商品説明");
    else ng("商品説明", "textarea が見つからない");

    // 3. 価格（「商品価格」ラベル付近の input）
    if (await setFieldByLabelText("商品価格", String(payload.listPriceJpy))) ok("価格");
    else ng("価格", "ラベルから input を特定できない");

    // 4. ブランド（8番目の input → サジェスト選択）
    if (await setBrand(payload.brandJa)) ok("ブランド");
    else ng("ブランド", "サジェストが出なかった");

    // 5. 色（「色」タブ → React Select）
    if (payload.color) {
      if (await setColorTab(payload.color)) ok("色");
      else ng("色", "タブまたは Select が見つからない");
    }

    // 6. 画像アップロード（CSRF トークン経由で API POST）
    if (payload.imageUrls && payload.imageUrls.length > 0) {
      try {
        const count = await uploadImages(payload.imageUrls);
        ok(`画像 ${count} 枚`);
      } catch (e) {
        ng("画像", e.message);
      }
    }

    // 7. ボタン操作
    if (options.autoSubmit === "draft") {
      await sleep(500);
      if (await clickButtonByText("下書き保存する")) ok("下書き保存");
      else ng("下書き保存", "ボタンが見つからない");
    } else if (options.autoSubmit === "publish") {
      await sleep(500);
      if (await clickButtonByText("入力内容を確認する")) {
        ok("確認画面へ遷移");
        await sleep(2500);
        if (await clickButtonByText("公開する")) ok("公開");
        else ng("公開", "ボタンが見つからない");
      } else {
        ng("確認ボタン", "見つからない");
      }
    }

    return { log };
  }

  // ---------------------------------------------------------------------------
  // フィールド入力ユーティリティ
  // ---------------------------------------------------------------------------

  // querySelectorAll の N 番目の要素に値をセット
  async function setByQueryIndex(selector, index, value) {
    const els = document.querySelectorAll(selector);
    if (!els[index]) return false;
    return setInputValue(els[index], value);
  }

  // textarea に値をセット
  async function setTextarea(selector, value) {
    const el = document.querySelector(selector);
    if (!el) return false;
    return setInputValue(el, value);
  }

  // ラベルテキストを含む要素の近くにある input に値をセット
  async function setFieldByLabelText(labelText, value) {
    // label, th, dt, .bmm-c-summary__ttl などテキストを持つ要素を全走査
    const candidates = document.querySelectorAll(
      'label, th, dt, .bmm-c-summary__ttl, .bmm-c-form__label, [class*="label"]',
    );
    for (const label of candidates) {
      if (!label.textContent.includes(labelText)) continue;
      // 祖先要素を順に辿って input を探す
      let el = label.parentElement;
      for (let i = 0; i < 5; i++) {
        if (!el) break;
        const input = el.querySelector('input[type="text"], input[type="number"]');
        if (input) return setInputValue(input, value);
        el = el.parentElement;
      }
    }
    return false;
  }

  // ブランド: 8 番目の input に入力 → サジェストをクリック
  async function setBrand(brandName) {
    const inputs = document.querySelectorAll("input");
    const brandInput = inputs[7];
    if (!brandInput) return false;

    brandInput.focus();
    brandInput.value = brandName;
    brandInput.dispatchEvent(new Event("input", { bubbles: true }));
    await sleep(800);

    // サジェストの先頭候補をクリック
    const suggestion = document.querySelector(".bmm-c-suggest__option--selectable");
    if (suggestion) {
      suggestion.click();
      return true;
    }
    // サジェストが出なくても入力値を維持して続行
    return true;
  }

  // 色タブを開いて React Select で色を選択
  async function setColorTab(color) {
    // 「色」タブをクリック
    for (const tab of document.querySelectorAll('[role="tab"]')) {
      if (tab.textContent.trim() === "色") {
        tab.click();
        await sleep(500);
        break;
      }
    }
    const panel = document.querySelector("#react-tabs-1");
    if (!panel) return false;
    const select = panel.querySelector(".Select");
    return select ? reactSelectSet(select, color) : false;
  }

  // React Select コンポーネントを操作する（クリック → 入力 → 候補選択）
  async function reactSelectSet(container, value) {
    // コントロール部分をクリックして開く
    const control = container.querySelector(
      ".Select-control, .select__control, [class*='-control']",
    );
    if (!control) return false;
    control.click();
    await sleep(400);

    // 検索 input を探してタイプ
    const searchInput = container.querySelector(
      '.Select-input input, input[role="combobox"], input[aria-autocomplete="list"]',
    );
    if (searchInput) {
      searchInput.value = value;
      searchInput.dispatchEvent(new Event("input", { bubbles: true }));
      await sleep(600);
    }

    // 候補の先頭をクリック
    const option = document.querySelector(
      ".Select-option, [class*='-option']:not([class*='disabled'])",
    );
    if (option) {
      option.click();
      return true;
    }
    return false;
  }

  // ---------------------------------------------------------------------------
  // 画像アップロード（BUYMA 画像 API 経由）
  // ---------------------------------------------------------------------------

  async function uploadImages(imageUrls) {
    const csrfToken =
      document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";

    let count = 0;
    for (const url of imageUrls.slice(0, 5)) {
      try {
        const res = await fetch(url);
        if (!res.ok) continue;
        const blob = await res.blob();
        const ext = (blob.type.split("/")[1] || "jpg").replace(/;.*/, "");

        const formData = new FormData();
        formData.append("item_image[image]", blob, `image_${count + 1}.${ext}`);

        const uploadRes = await fetch("https://www.buyma.com/rorapi/item_image.json", {
          method: "POST",
          headers: csrfToken ? { "X-CSRF-Token": csrfToken } : {},
          body: formData,
          credentials: "include",
        });

        if (!uploadRes.ok) throw new Error(`HTTP ${uploadRes.status}`);
        count++;
        await sleep(600); // 連続アップロード制御
      } catch (e) {
        console.warn("画像アップロード失敗:", url, e.message);
      }
    }
    return count;
  }

  // ---------------------------------------------------------------------------
  // 共通ユーティリティ
  // ---------------------------------------------------------------------------

  function setInputValue(el, value) {
    el.focus();
    // React の合成イベントに対応するため nativeInputValueSetter を使う
    const nativeSetter = Object.getOwnPropertyDescriptor(
      el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype,
      "value",
    )?.set;
    if (nativeSetter) {
      nativeSetter.call(el, String(value));
    } else {
      el.value = String(value);
    }
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.blur();
    return true;
  }

  async function clickButtonByText(text) {
    for (const btn of document.querySelectorAll("button")) {
      if (btn.textContent.trim() === text) {
        btn.click();
        return true;
      }
    }
    return false;
  }

  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }
})();
