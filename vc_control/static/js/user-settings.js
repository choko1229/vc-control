(function () {
  function syncThemeSummary() {
    const summary = document.querySelector("[data-theme-current]");
    if (!summary || !window.VCTheme) {
      return;
    }

    const preference = window.VCTheme.getPreference();
    const resolved = window.VCTheme.getResolvedTheme();
    const label = preference === "system" ? `システム (${resolved})` : preference === "light" ? "ライト" : "ダーク";
    summary.innerHTML = `<span>現在のテーマ: ${label}</span><span>表示密度: 高密度固定</span>`;
  }

  function bindThemeOptions() {
    const root = document.querySelector("[data-theme-options]");
    if (!root || !window.VCTheme) {
      return;
    }

    const current = window.VCTheme.getPreference();
    root.querySelectorAll("input[name='theme_preference']").forEach((input) => {
      input.checked = input.value === current;
      input.addEventListener("change", () => {
        window.VCTheme.applyThemePreference(input.value);
        syncThemeSummary();
        window.VCToast?.success("テーマを更新しました。");
      });
    });
  }

  function bindToastTest() {
    const button = document.querySelector("[data-test-toast]");
    const toneSelect = document.querySelector("[data-toast-tone]");
    if (!button || !toneSelect || !window.VCToast) {
      return;
    }

    button.addEventListener("click", () => {
      const tone = toneSelect.value || "info";
      const message = tone === "success"
        ? "設定を保存しました。"
        : tone === "warning"
          ? "設定に問題があります。"
          : tone === "error"
            ? "保存に失敗しました。"
            : "リアルタイム通知のテストです。";
      window.VCToast.show({ tone, message });
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (document.body.dataset.page !== "user-settings") {
      return;
    }
    bindThemeOptions();
    bindToastTest();
    syncThemeSummary();
  });

  document.addEventListener("vc-theme-changed", () => {
    if (document.body.dataset.page === "user-settings") {
      syncThemeSummary();
    }
  });
})();
