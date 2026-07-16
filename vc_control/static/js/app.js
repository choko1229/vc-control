(function () {
  function qs(selector, root = document) {
    return root.querySelector(selector);
  }

  function qsa(selector, root = document) {
    return Array.from(root.querySelectorAll(selector));
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function initials(name) {
    const text = String(name || "?").trim();
    if (!text) return "?";
    const parts = text.replaceAll("_", " ").split(/\s+/).filter(Boolean);
    if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
    return text.slice(0, 2).toUpperCase();
  }

  function formatDuration(total) {
    const value = Math.max(0, Number(total) || 0);
    const hours = Math.floor(value / 3600);
    const minutes = Math.floor((value % 3600) / 60);
    const seconds = Math.floor(value % 60);
    if (hours) return `${hours}時間${minutes}分`;
    if (minutes) return `${minutes}分${seconds}秒`;
    return `${seconds}秒`;
  }

  function debounce(callback, delay = 450) {
    let timerId = null;
    return (...args) => {
      window.clearTimeout(timerId);
      timerId = window.setTimeout(() => callback(...args), delay);
    };
  }

  async function api(url, options = {}) {
    const response = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
      ...options,
    });

    let payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      payload = null;
    }

    if (!response.ok) {
      throw new Error(payload?.detail || payload?.message || "APIエラーが発生しました。");
    }
    return payload;
  }

  function avatarMarkup(user, sizeClass = "avatar-sm") {
    const displayName = user?.display_name || user?.name || "Unknown";
    if (user?.avatar_url) {
      return `<span class="avatar ${sizeClass}"><img src="${escapeHtml(user.avatar_url)}" alt="${escapeHtml(displayName)}"></span>`;
    }
    return `<span class="avatar ${sizeClass}"><span>${escapeHtml(user?.initials || initials(displayName))}</span></span>`;
  }

  function setSidebarOpen(open) {
    document.body.classList.toggle("is-page-sidebar-open", open);
    const overlay = qs("[data-page-overlay]");
    if (overlay) {
      overlay.hidden = !open;
    }
  }

  function bindSidebarToggle() {
    qsa("[data-page-sidebar-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        setSidebarOpen(!document.body.classList.contains("is-page-sidebar-open"));
      });
    });

    qs("[data-page-overlay]")?.addEventListener("click", () => {
      setSidebarOpen(false);
    });

    qsa(".sidebar-nav-link, .sidebar-guild-row, .sidebar-session-row").forEach((link) => {
      link.addEventListener("click", () => {
        if (window.innerWidth <= 900) {
          setSidebarOpen(false);
        }
      });
    });
  }

  function showQueryToasts() {
    const params = new URLSearchParams(window.location.search);
    if (params.get("saved") === "1" && window.VCToast) {
      window.VCToast.success("設定を保存しました。");
    }
    if (params.get("oauth_error") === "1" && window.VCToast) {
      window.VCToast.warning("OAuth設定に不足があります。Redirect URI を含めて確認してください。");
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindSidebarToggle();
    showQueryToasts();
  });

  window.VCApp = {
    api,
    avatarMarkup,
    debounce,
    escapeHtml,
    formatDuration,
    initials,
    qs,
    qsa,
    setSidebarOpen,
  };
})();
