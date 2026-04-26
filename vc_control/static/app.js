const VCControl = (() => {
  async function fetchJson(url, options = {}) {
    const response = await fetch(url, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || "APIエラーが発生しました。");
    }
    return response.json();
  }

  async function getWsToken() {
    const data = await fetchJson("/api/ws-token");
    return data.token;
  }

  async function connectWebSocket(scopes, onEvent) {
    const token = await getWsToken();
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${protocol}://${location.host}/ws?token=${encodeURIComponent(token)}&scopes=${encodeURIComponent(scopes.join(","))}`);
    socket.addEventListener("message", (event) => {
      try {
        const payload = JSON.parse(event.data);
        onEvent(payload);
      } catch (error) {
        console.error(error);
      }
    });
    return socket;
  }

  function qs(selector, root = document) {
    return root.querySelector(selector);
  }

  function formatSeconds(total) {
    const value = Math.max(0, Number(total) || 0);
    const hours = Math.floor(value / 3600);
    const minutes = Math.floor((value % 3600) / 60);
    const seconds = Math.floor(value % 60);
    if (hours) return `${hours}時間${minutes}分${seconds}秒`;
    if (minutes) return `${minutes}分${seconds}秒`;
    return `${seconds}秒`;
  }

  async function initVoicePage() {
    const root = document.body.dataset.rootChannelId;
    const guild = document.body.dataset.guildId;
    if (!root || !guild) return;
    const participantsBox = qs("[data-participants]");
    const teamBox = qs("[data-team-state]");
    const noticeBox = qs("[data-notice]");
    const settingsForm = qs("[data-voice-settings]");
    const memberStateForm = qs("[data-member-state]");
    const splitButton = qs("[data-action='split']");
    const assembleButton = qs("[data-action='assemble']");
    const recallButton = qs("[data-action='recall']");
    const teamAssignForm = qs("[data-team-assign]");
    const recallForm = qs("[data-recall-form]");

    const renderSession = (session) => {
      if (!participantsBox || !teamBox) return;
      const participants = session.participants || [];
      participantsBox.innerHTML = participants.map((member) => `
        <tr>
          <td>${member.user_name}</td>
          <td>${member.current_channel_id === session.root_channel_id ? "メインVC" : member.current_channel_id ? "チームVC" : "離席"}</td>
          <td>${member.current_team || "未所属"}</td>
          <td>${formatSeconds(member.talk_seconds)}</td>
          <td>${formatSeconds(member.afk_seconds)}</td>
        </tr>
      `).join("");

      const teamChannels = session.team_channels || {};
      const assignments = session.team_assignments || {};
      teamBox.innerHTML = Object.keys(assignments).length
        ? Object.entries(assignments).map(([userId, team]) => `<div class="chip">${userId} → ${team}</div>`).join("")
        : `<div class="muted">まだチーム割り当てはありません。</div>`;

      if (teamAssignForm) {
        const select = teamAssignForm.querySelector("select[name='user_id']");
        if (select) {
          select.innerHTML = participants.length
            ? participants.map((member) => `<option value="${member.user_id}">${member.user_name}</option>`).join("")
            : `<option value="">対象なし</option>`;
        }
      }

      if (memberStateForm) {
        const select = memberStateForm.querySelector("select[name='user_id']");
        if (select) {
          select.innerHTML = participants.length
            ? participants.map((member) => `<option value="${member.user_id}">${member.user_name}</option>`).join("")
            : `<option value="">対象なし</option>`;
        }
      }

      if (recallForm) {
        const select = recallForm.querySelector("select[name='user_id']");
        if (select) {
          const active = participants.filter((member) => member.current_channel_id && member.current_channel_id !== session.root_channel_id);
          select.innerHTML = active.length
            ? active.map((member) => `<option value="${member.user_id}">${member.user_name}</option>`).join("")
            : `<option value="">対象なし</option>`;
        }
      }
    };

    async function refresh() {
      try {
        const session = await fetchJson(`/api/voice/${guild}/${root}`);
        renderSession(session);
      } catch (error) {
        if (noticeBox) noticeBox.textContent = error.message;
      }
    }

    if (settingsForm) {
      settingsForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = new FormData(settingsForm);
        try {
          await fetchJson(`/api/voice/${guild}/${root}/settings`, {
            method: "POST",
            body: JSON.stringify({
              name: form.get("name"),
              user_limit: form.get("user_limit"),
              bitrate: form.get("bitrate"),
            }),
          });
          if (noticeBox) noticeBox.textContent = "VC設定を更新しました。";
          refresh();
        } catch (error) {
          if (noticeBox) noticeBox.textContent = error.message;
        }
      });
    }

    if (teamAssignForm) {
      teamAssignForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = new FormData(teamAssignForm);
        try {
          const response = await fetchJson(`/api/voice/${guild}/${root}/team/assign`, {
            method: "POST",
            body: JSON.stringify({
              user_id: form.get("user_id"),
              team_name: form.get("team_name") || null,
            }),
          });
          if (noticeBox) noticeBox.textContent = response.message || "チーム割り当てを更新しました。";
          refresh();
        } catch (error) {
          if (noticeBox) noticeBox.textContent = error.message;
        }
      });
    }

    if (memberStateForm) {
      memberStateForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = new FormData(memberStateForm);
        const action = form.get("action");
        const payload = { user_id: form.get("user_id") };
        if (action === "mute_on") payload.mute = true;
        if (action === "mute_off") payload.mute = false;
        if (action === "deafen_on") payload.deafen = true;
        if (action === "deafen_off") payload.deafen = false;
        try {
          await fetchJson(`/api/voice/${guild}/${root}/member-state`, {
            method: "POST",
            body: JSON.stringify(payload),
          });
          if (noticeBox) noticeBox.textContent = "メンバー状態を更新しました。";
        } catch (error) {
          if (noticeBox) noticeBox.textContent = error.message;
        }
      });
    }

    if (splitButton) {
      splitButton.addEventListener("click", async () => {
        try {
          await fetchJson(`/api/voice/${guild}/${root}/team/split`, { method: "POST", body: "{}" });
          if (noticeBox) noticeBox.textContent = "チーム分割を実行しました。";
        } catch (error) {
          if (noticeBox) noticeBox.textContent = error.message;
        }
      });
    }

    if (assembleButton) {
      assembleButton.addEventListener("click", async () => {
        try {
          await fetchJson(`/api/voice/${guild}/${root}/team/assemble`, { method: "POST", body: "{}" });
          if (noticeBox) noticeBox.textContent = "集合を実行しました。";
        } catch (error) {
          if (noticeBox) noticeBox.textContent = error.message;
        }
      });
    }

    if (recallForm) {
      recallForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = new FormData(recallForm);
        try {
          await fetchJson(`/api/voice/${guild}/${root}/team/recall`, {
            method: "POST",
            body: JSON.stringify({ user_id: form.get("user_id") }),
          });
          if (noticeBox) noticeBox.textContent = "呼び戻しを実行しました。";
        } catch (error) {
          if (noticeBox) noticeBox.textContent = error.message;
        }
      });
    }

    await refresh();
    connectWebSocket([`session:${root}`, `guild:${guild}`], (event) => {
      if (event.event === "session_update") renderSession(event.payload);
    }).catch((error) => {
      if (noticeBox) noticeBox.textContent = error.message;
    });
  }

  return { initVoicePage };
})();

window.addEventListener("DOMContentLoaded", () => {
  if (document.body.dataset.page === "voice") {
    VCControl.initVoicePage();
  }
});
