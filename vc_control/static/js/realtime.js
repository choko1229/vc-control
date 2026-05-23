(function () {
  const state = {
    socket: null,
    reconnectTimerId: null,
    reconnectAttempts: 0,
    notifications: [],
    unreadCount: 0,
  };

  function pageScopes() {
    const scopes = ["global"];
    const userId = document.body.dataset.currentUserId;
    const guildId = document.body.dataset.guildId;
    const rootChannelId = document.body.dataset.rootChannelId;
    if (userId) scopes.push(`user:${userId}`);
    if (guildId) scopes.push(`guild:${guildId}`);
    if (rootChannelId) scopes.push(`session:${rootChannelId}`);
    return Array.from(new Set(scopes));
  }

  function setStatus(status) {
    const root = document.querySelector("[data-realtime-status]");
    const label = document.querySelector("[data-realtime-status-label]");
    if (!root || !label) return;
    root.dataset.realtimeStatus = status;
    label.textContent = status === "connected" || status === "connecting" ? "接続中" : status === "reconnecting" ? "再接続中" : "切断";
  }

  function escapeHtml(value) {
    return window.VCApp?.escapeHtml ? window.VCApp.escapeHtml(value) : String(value ?? "");
  }

  function renderNotifications() {
    const count = document.querySelector("[data-notification-count]");
    if (count) {
      count.textContent = String(state.unreadCount);
      count.hidden = state.unreadCount <= 0;
    }

    const list = document.querySelector("[data-notification-list]");
    if (!list) return;
    if (!state.notifications.length) {
      list.innerHTML = '<div class="sidebar-empty">通知はありません。</div>';
      return;
    }
    list.innerHTML = state.notifications
      .slice(0, 30)
      .map((item) => {
        const created = item.created_at ? new Date(item.created_at).toLocaleString() : "";
        return `
          <article class="notification-item" data-notification-id="${escapeHtml(item.id)}">
            <strong>${escapeHtml(item.title || item.event_type || "通知")}</strong>
            <p>${escapeHtml(item.message || "")}</p>
            <small>${escapeHtml(created)}</small>
          </article>
        `;
      })
      .join("");
  }

  async function loadNotifications() {
    try {
      const payload = await window.VCApp.api("/api/notifications");
      state.notifications = payload.notifications || [];
      state.unreadCount = Number(payload.unread_count || 0);
      renderNotifications();
    } catch (error) {
      console.warn(error);
    }
  }

  function addNotification(notification) {
    if (!notification) return;
    if (notification.id && state.notifications.some((item) => item.id === notification.id)) return;
    state.notifications.unshift(notification);
    state.notifications = state.notifications.slice(0, 30);
    state.unreadCount += 1;
    renderNotifications();
  }

  function updateDashboardSessions(payload) {
    if (document.body.dataset.page !== "dashboard") return;
    const sessions = payload?.active_sessions || [];
    document.querySelectorAll("[data-realtime-session-count]").forEach((node) => {
      node.textContent = `${sessions.length}件`;
    });
  }

  function dispatchRealtimeMessage(message) {
    window.dispatchEvent(new CustomEvent("vc:realtime", { detail: message }));
    if (message.event === "important_notification") {
      addNotification(message.payload?.notification);
      window.VCToast?.info(message.payload?.notification?.message || "重要通知を受信しました。", message.payload?.notification?.title || "通知");
    }
    if (message.event === "global_state") {
      updateDashboardSessions(message.payload);
    }
  }

  async function connect() {
    if (!document.body.dataset.currentUserId || !window.VCApp) return;
    setStatus(state.reconnectAttempts ? "reconnecting" : "connecting");
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const tokenPayload = await window.VCApp.api("/api/ws-token");
    const scopes = pageScopes().join(",");
    const socket = new WebSocket(
      `${protocol}://${window.location.host}/ws?token=${encodeURIComponent(tokenPayload.token)}&scopes=${encodeURIComponent(scopes)}`,
    );
    state.socket = socket;

    socket.addEventListener("open", () => {
      state.reconnectAttempts = 0;
      setStatus("connected");
    });

    socket.addEventListener("message", (event) => {
      if (event.data === "pong") return;
      try {
        dispatchRealtimeMessage(JSON.parse(event.data));
      } catch (error) {
        console.warn(error);
      }
    });

    socket.addEventListener("close", () => {
      setStatus("disconnected");
      scheduleReconnect();
    });

    socket.addEventListener("error", () => {
      setStatus("disconnected");
    });
  }

  function scheduleReconnect() {
    window.clearTimeout(state.reconnectTimerId);
    state.reconnectAttempts += 1;
    const delay = Math.min(30000, 1000 * Math.max(1, state.reconnectAttempts));
    if (state.reconnectAttempts >= 5) {
      window.VCToast?.warning("リアルタイム同期の再接続に失敗しています。");
    }
    setStatus("reconnecting");
    state.reconnectTimerId = window.setTimeout(() => {
      connect().catch(() => scheduleReconnect());
    }, delay);
  }

  function bindNotifications() {
    document.querySelector("[data-notification-toggle]")?.addEventListener("click", () => {
      const drawer = document.querySelector("[data-notification-drawer]");
      if (drawer) drawer.hidden = !drawer.hidden;
    });
    document.querySelector("[data-notification-close]")?.addEventListener("click", () => {
      const drawer = document.querySelector("[data-notification-drawer]");
      if (drawer) drawer.hidden = true;
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (!document.body.dataset.currentUserId || !window.VCApp) return;
    bindNotifications();
    loadNotifications();
    connect().catch(() => scheduleReconnect());
  });
})();
