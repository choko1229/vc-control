(function () {
  function serializeForm(form) {
    const payload = {};
    for (const element of Array.from(form.elements)) {
      if (!element.name) continue;
      if (element.type === "checkbox") {
        if (form.querySelectorAll(`[name="${CSS.escape(element.name)}"]`).length > 1) {
          if (!Array.isArray(payload[element.name])) payload[element.name] = [];
          if (element.checked) payload[element.name].push(element.value);
          continue;
        }
        payload[element.name] = element.checked;
        continue;
      }
      payload[element.name] = element.value;
    }
    return payload;
  }

  function renderDiagnostics(items) {
    if (!Array.isArray(items) || items.length === 0) return "";
    const escape = window.VCApp.escapeHtml;
    return items
      .map((item) => `
        <article class="status-box ${escape(item.level || "warning")}">
          <strong>${escape(item.title || "確認")}</strong>
          <p>${escape(item.message || "")}</p>
        </article>
      `)
      .join("");
  }

  function updateSaveStatus(form, text, className) {
    const status = form.querySelector("[data-save-status]");
    if (!status) return;
    status.textContent = text;
    status.className = `save-status ${className || ""}`.trim();
  }

  async function submitForm(form) {
    const endpoint = form.dataset.endpoint;
    if (!endpoint) return;
    const isGuildForm = endpoint.includes("/api/admin/guilds/");
    const diagnosticsRoot = document.querySelector("[data-diagnostics]");
    const globalWarningsRoot = document.querySelector("[data-global-warnings]");
    try {
      updateSaveStatus(form, "保存中...", "is-saving");
      const result = await window.VCApp.api(endpoint, {
        method: "POST",
        body: JSON.stringify(serializeForm(form)),
      });
      updateSaveStatus(form, "保存済み", "is-saved");
      if (window.VCToast) {
        window.VCToast.success(result.message || "設定を保存しました。");
      }
      if (isGuildForm && diagnosticsRoot && result.diagnostics) {
        diagnosticsRoot.innerHTML = renderDiagnostics(result.diagnostics);
        const warnings = result.diagnostics.filter((item) => item.level === "warning" || item.level === "danger");
        if (warnings.length && window.VCToast) {
          window.VCToast.warning("設定に問題があります。警告パネルを確認してください。");
        }
      }
      if (!isGuildForm && globalWarningsRoot) {
        const warnings = result.warnings || [];
        globalWarningsRoot.innerHTML = renderDiagnostics(warnings);
        if (warnings.length && window.VCToast) {
          window.VCToast.warning("設定に問題があります。OAuth 周りの警告を確認してください。");
        }
      }
    } catch (error) {
      updateSaveStatus(form, "保存失敗", "is-error");
      if (window.VCToast) {
        window.VCToast.error(error.message || "保存に失敗しました。");
      }
    }
  }

  async function postRankingNow(button) {
    const guildId = button.dataset.guildId;
    if (!guildId) return;
    button.disabled = true;
    try {
      const result = await window.VCApp.api(`/api/admin/guilds/${encodeURIComponent(guildId)}/rankings/post`, {
        method: "POST",
        body: "{}",
      });
      window.VCToast?.success(result.message || "ランキングを手動投稿しました。");
    } catch (error) {
      window.VCToast?.error(error.message || "ランキング投稿に失敗しました。");
    } finally {
      button.disabled = false;
    }
  }

  const ADMIN_TAB_STORAGE_KEY = "vc-control-admin-tab";

  function setActiveAdminTab(tabId) {
    const tabButtons = window.VCApp.qsa("[data-admin-tab]");
    const panels = window.VCApp.qsa("[data-tab-panel]");
    const availableTabs = tabButtons.map((button) => button.dataset.adminTab);
    const resolvedTab = availableTabs.includes(tabId) ? tabId : availableTabs[0];
    if (!resolvedTab) return;

    tabButtons.forEach((button) => {
      button.classList.toggle("is-active", button.dataset.adminTab === resolvedTab);
    });
    panels.forEach((panel) => {
      const tokens = (panel.dataset.tabPanel || "").split(/\s+/).filter(Boolean);
      panel.hidden = !tokens.includes(resolvedTab);
    });

    try {
      window.localStorage.setItem(ADMIN_TAB_STORAGE_KEY, resolvedTab);
    } catch (error) {
      /* localStorage unavailable, ignore */
    }
  }

  function bindAdminTabs() {
    const tabButtons = window.VCApp.qsa("[data-admin-tab]");
    if (!tabButtons.length) return;
    tabButtons.forEach((button) => {
      button.addEventListener("click", () => setActiveAdminTab(button.dataset.adminTab));
    });
    let storedTab = null;
    try {
      storedTab = window.localStorage.getItem(ADMIN_TAB_STORAGE_KEY);
    } catch (error) {
      storedTab = null;
    }
    setActiveAdminTab(storedTab || tabButtons[0].dataset.adminTab);
  }

  function applySoloModeVisibility(select) {
    const form = select.closest("form");
    if (!form) return;
    const mode = select.value;
    form.querySelectorAll("[data-solo-visible-for]").forEach((row) => {
      row.hidden = row.dataset.soloVisibleFor !== mode;
    });
  }

  function bindSoloModeVisibility() {
    window.VCApp.qsa("[data-solo-mode-select]").forEach((select) => {
      applySoloModeVisibility(select);
      select.addEventListener("change", () => applySoloModeVisibility(select));
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (document.body.dataset.page !== "admin" || !window.VCApp) return;

    const forms = window.VCApp.qsa("[data-auto-save-form]");
    forms.forEach((form) => {
      const debouncedSave = window.VCApp.debounce(() => submitForm(form), 550);
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        submitForm(form);
      });
      form.addEventListener("change", () => debouncedSave());
      form.addEventListener("input", (event) => {
        if (event.target.matches("input[type='text'], input[type='url'], input[type='number'], input[type='password']")) {
          debouncedSave();
        }
      });
    });

    window.VCApp.qsa("[data-post-ranking-now]").forEach((button) => {
      button.addEventListener("click", () => postRankingNow(button));
    });

    bindAdminTabs();
    bindSoloModeVisibility();
  });
})();
