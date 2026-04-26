(function () {
  const STORAGE_KEY = "vc-control-theme-preference";
  const mediaQuery = window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null;

  function getSystemTheme() {
    return mediaQuery && mediaQuery.matches ? "light" : "dark";
  }

  function resolveTheme(preference) {
    if (preference === "system") {
      return getSystemTheme();
    }
    return preference === "light" ? "light" : "dark";
  }

  function getPreference() {
    try {
      return localStorage.getItem(STORAGE_KEY) || document.documentElement.dataset.themePreference || "dark";
    } catch (error) {
      return document.documentElement.dataset.themePreference || "dark";
    }
  }

  function updateState(preference, persist) {
    document.documentElement.dataset.themePreference = preference;
    document.documentElement.dataset.theme = resolveTheme(preference);
    if (persist) {
      try {
        localStorage.setItem(STORAGE_KEY, preference);
      } catch (error) {
        console.warn(error);
      }
    }
  }

  function applyThemePreference(preference, options = {}) {
    updateState(preference, options.persist !== false);
    document.dispatchEvent(
      new CustomEvent("vc-theme-changed", {
        detail: {
          preference,
          theme: document.documentElement.dataset.theme,
        },
      }),
    );
  }

  document.addEventListener("DOMContentLoaded", () => {
    updateState(getPreference(), false);
  });

  if (mediaQuery) {
    const syncSystemTheme = () => {
      if (getPreference() === "system") {
        updateState("system", false);
      }
    };

    if (typeof mediaQuery.addEventListener === "function") {
      mediaQuery.addEventListener("change", syncSystemTheme);
    } else if (typeof mediaQuery.addListener === "function") {
      mediaQuery.addListener(syncSystemTheme);
    }
  }

  window.VCTheme = {
    applyThemePreference,
    getPreference,
    getResolvedTheme() {
      return document.documentElement.dataset.theme || "dark";
    },
  };
})();
