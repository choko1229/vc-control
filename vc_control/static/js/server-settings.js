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
  });
})();
