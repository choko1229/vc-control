(function () {
  const TOAST_ROOT_ID = "toast-stack";

  function ensureRoot() {
    let root = document.getElementById(TOAST_ROOT_ID);
    if (!root) {
      root = document.createElement("div");
      root.id = TOAST_ROOT_ID;
      root.className = "toast-stack";
      document.body.appendChild(root);
    }
    return root;
  }

  function show(options) {
    const root = ensureRoot();
    const toast = document.createElement("article");
    const tone = options.tone || "info";
    const title = options.title || (tone === "success" ? "完了" : tone === "warning" ? "警告" : tone === "error" ? "失敗" : "通知");
    const message = options.message || "";
    const duration = Number(options.duration || 3600);

    toast.className = `toast ${tone}`;
    toast.innerHTML = `
      <div class="toast-title">${title}</div>
      <div class="toast-message">${message}</div>
    `;

    root.appendChild(toast);

    window.setTimeout(() => {
      toast.classList.add("is-leaving");
      window.setTimeout(() => toast.remove(), 220);
    }, duration);
  }

  window.VCToast = {
    show,
    success(message, title = "設定を保存しました") {
      show({ tone: "success", title, message });
    },
    warning(message, title = "設定に問題があります") {
      show({ tone: "warning", title, message });
    },
    error(message, title = "保存に失敗しました") {
      show({ tone: "error", title, message, duration: 4600 });
    },
    info(message, title = "通知") {
      show({ tone: "info", title, message });
    },
  };
})();
