(function () {
  const state = {
    session: null,
    pendingAssignments: {},
    selectedUserId: null,
    dirty: false,
    socket: null,
    reconnectTimerId: null,
    timerId: null,
    timelineEvents: [],
    mobileMenuUserId: null,
    touch: {
      longPressTimerId: null,
      pointerId: null,
      userId: null,
      startX: 0,
      startY: 0,
      moved: false,
    },
  };

  function toId(value) {
    if (value === null || value === undefined || value === "") {
      return "";
    }
    return String(value);
  }

  function sameId(left, right) {
    const leftId = toId(left);
    const rightId = toId(right);
    return leftId !== "" && leftId === rightId;
  }

  function voiceApiUrl(guildId, rootChannelId, suffix = "") {
    const normalizedGuildId = encodeURIComponent(toId(guildId));
    const normalizedRootChannelId = encodeURIComponent(toId(rootChannelId));
    return `/api/voice/${normalizedGuildId}/${normalizedRootChannelId}${suffix}`;
  }

  function currentUserId() {
    return toId(document.body.dataset.currentUserId);
  }

  function rootIds() {
    const guildId = toId(document.body.dataset.guildId);
    const rootChannelId = toId(document.body.dataset.rootChannelId);
    if (!guildId || !rootChannelId) {
      throw new Error("VC管理ページのID設定が不正です。ページを再読み込みしてください。");
    }
    return { guildId, rootChannelId };
  }

  function teamAssignmentFor(session, userId) {
    const pendingValue = state.pendingAssignments[userId];
    if (pendingValue !== undefined) {
      return pendingValue;
    }
    return session.team_assignments?.[String(userId)] || "";
  }

  function deriveLocation(raw, session) {
    if (raw.current_channel_id == null) {
      return { label: "離席中", kind: "away" };
    }
    if (sameId(raw.current_channel_id, session.root_channel_id)) {
      return { label: "メインVC", kind: "root" };
    }
    const matchedTeam = Object.entries(session.team_channels || {}).find(([, channelId]) => sameId(channelId, raw.current_channel_id));
    if (matchedTeam) {
      return { label: `${matchedTeam[0]} チームVC`, kind: "team" };
    }
    return { label: "チームVC", kind: "team" };
  }

  function deriveStatusFlags(raw) {
    const flags = [];
    if (raw.self_muted) flags.push({ icon: "🎙", label: "自己ミュート" });
    if (raw.self_deafened) flags.push({ icon: "🔇", label: "自己デフェン" });
    if (raw.in_afk_channel) flags.push({ icon: "💤", label: "AFK" });
    return flags;
  }

  function normalizeParticipant(raw, session) {
    const displayName = raw.user?.display_name || raw.user_name || `User ${raw.user_id}`;
    const location = deriveLocation(raw, session);
    return {
      ...raw,
      user: raw.user || {
        id: toId(raw.user_id),
        display_name: displayName,
        avatar_url: null,
        initials: window.VCApp.initials(displayName),
      },
      user_id: toId(raw.user_id),
      current_channel_id: raw.current_channel_id == null ? null : toId(raw.current_channel_id),
      current_team: raw.current_team || session.team_assignments?.[String(raw.user_id)] || "",
      location_label: location.label,
      location_kind: location.kind,
      status_flags: deriveStatusFlags(raw),
    };
  }

  function normalizeSession(payload) {
    const previous = state.session || {};
    const session = {
      ...payload,
      root_channel: payload.root_channel || previous.root_channel || {
        id: toId(payload.root_channel_id),
        name: payload.root_channel_name || "VC",
        user_limit: 0,
        bitrate: 64000,
      },
      guild: payload.guild || previous.guild || {
        id: toId(payload.guild_id),
        name: payload.guild_name || "Guild",
        avatar_url: null,
        initials: window.VCApp.initials(payload.guild_name || "G"),
      },
      guild_id: toId(payload.guild_id),
      root_channel_id: toId(payload.root_channel_id),
      team_assignments: payload.team_assignments || previous.team_assignments || {},
      team_channels: payload.team_channels || previous.team_channels || {},
      elapsed_seconds: Number(payload.elapsed_seconds || previous.elapsed_seconds || 0),
      can_edit: Boolean(payload.can_edit),
      can_assign_others: Boolean(payload.can_assign_others),
      participants: [],
    };

    session.participants = (payload.participants || []).map((participant) => normalizeParticipant(participant, session));
    session.activeParticipants = session.participants.filter((participant) => participant.current_channel_id !== null);
    session.teamNames = payload.team_names || previous.teamNames || [];
    return session;
  }

  function syncPendingAssignments(session) {
    const nextAssignments = {};
    session.activeParticipants.forEach((participant) => {
      const userId = toId(participant.user_id);
      const serverValue = session.team_assignments?.[String(userId)] || participant.current_team || "";
      if (state.dirty && Object.prototype.hasOwnProperty.call(state.pendingAssignments, userId)) {
        nextAssignments[userId] = state.pendingAssignments[userId];
      } else {
        nextAssignments[userId] = serverValue;
      }
    });
    state.pendingAssignments = nextAssignments;

    if (
      state.selectedUserId &&
      !session.activeParticipants.some((participant) => sameId(participant.user_id, state.selectedUserId))
    ) {
      state.selectedUserId = null;
    }
  }

  function canMoveParticipant(participant) {
    return Boolean(state.session?.can_assign_others || sameId(participant.user_id, currentUserId()));
  }

  function pendingChangeCount(session) {
    return session.activeParticipants.filter((participant) => {
      const serverValue = session.team_assignments?.[String(participant.user_id)] || "";
      return teamAssignmentFor(session, participant.user_id) !== serverValue;
    }).length;
  }

  function selectedParticipant() {
    if (!state.session || !state.selectedUserId) {
      return null;
    }
    return state.session.activeParticipants.find((participant) => sameId(participant.user_id, state.selectedUserId)) || null;
  }

  function setNotice(message, tone = "info") {
    const notice = document.querySelector("[data-inline-notice]");
    if (!notice) return;
    notice.textContent = message;
    notice.dataset.tone = tone;
  }

  function renderSummary(session) {
    const pending = pendingChangeCount(session);
    const mappings = [
      ["[data-session-name]", session.root_channel.name],
      ["[data-session-channel]", session.root_channel.name],
      ["[data-session-count]", `${session.activeParticipants.length}人参加中`],
      ["[data-session-participants]", String(session.activeParticipants.length)],
      ["[data-session-elapsed]", window.VCApp.formatDuration(session.elapsed_seconds)],
      ["[data-session-duration]", window.VCApp.formatDuration(session.elapsed_seconds)],
      ["[data-session-status]", pending ? `仮配置 ${pending}件` : "稼働中"],
      ["[data-session-state]", pending ? "仮配置あり" : "稼働中"],
      ["[data-participant-meta]", `${session.activeParticipants.length}人が参加中`],
    ];

    mappings.forEach(([selector, value]) => {
      const node = document.querySelector(selector);
      if (node) node.textContent = value;
    });

  }

  function renderChannelList(session) {
    const root = document.querySelector("[data-channel-list]");
    if (!root) return;

    const teamCounts = {};
    session.activeParticipants.forEach((participant) => {
      const assigned = teamAssignmentFor(session, participant.user_id) || "";
      if (!assigned) return;
      teamCounts[assigned] = (teamCounts[assigned] || 0) + 1;
    });

    const rows = [
      `
        <div class="channel-list-row is-active">
          <span class="channel-symbol">🔊</span>
          <span class="channel-list-copy">
            <strong>${window.VCApp.escapeHtml(session.root_channel.name)}</strong>
            <small>メインVC / ${session.activeParticipants.length}人</small>
          </span>
        </div>
      `,
    ];

    session.teamNames.forEach((teamName) => {
      rows.push(`
        <div class="channel-list-row">
          <span class="channel-symbol">≡</span>
          <span class="channel-list-copy">
            <strong>${window.VCApp.escapeHtml(teamName)}</strong>
            <small>${teamCounts[teamName] || 0}人 / ${session.team_channels?.[teamName] ? "チームVCあり" : "未分割"}</small>
          </span>
        </div>
      `);
    });

    root.innerHTML = rows.join("");
  }

  function statePillsMarkup(participant) {
    const pills = [
      participant.location_kind === "team"
        ? `<span class="state-pill">${window.VCApp.escapeHtml(participant.location_label)}</span>`
        : `<span class="state-pill">${window.VCApp.escapeHtml(teamAssignmentFor(state.session, participant.user_id) || "未所属")}</span>`,
    ];

    participant.status_flags.forEach((flag) => {
      pills.push(`<span class="state-pill">${window.VCApp.escapeHtml(flag.icon)} ${window.VCApp.escapeHtml(flag.label)}</span>`);
    });

    return pills.join("");
  }

  function participantRowMarkup(participant) {
    const isSelected = sameId(state.selectedUserId, participant.user_id);
    const canMove = canMoveParticipant(participant);
    const canRecall = state.session.can_edit && !sameId(participant.current_channel_id, state.session.root_channel_id);

    return `
      <article class="member-row${isSelected ? " is-selected" : ""}" data-user-id="${participant.user_id}" draggable="${canMove}">
        <div class="member-main">
          <div class="row-primary">
            ${window.VCApp.avatarMarkup(participant.user, "avatar-sm")}
            <div class="row-copy">
              <div class="member-name-line">
                <strong>${window.VCApp.escapeHtml(participant.user.display_name)}</strong>
                ${statePillsMarkup(participant)}
              </div>
              <div class="member-state-line">
                <small>${window.VCApp.escapeHtml(participant.location_label)}</small>
                <small>通話 ${window.VCApp.formatDuration(participant.talk_seconds)}</small>
                <small>AFK ${window.VCApp.formatDuration(participant.afk_seconds)}</small>
              </div>
            </div>
          </div>

          <div class="member-row-actions">
            <button type="button" class="inline-button primary" data-member-action="select" data-user-id="${participant.user_id}">移動</button>
            <button type="button" class="inline-button ${canRecall ? "" : "danger"}" data-member-action="recall" data-user-id="${participant.user_id}" ${canRecall ? "" : "disabled"}>戻す</button>
            <button type="button" class="inline-button" data-member-action="mute" data-user-id="${participant.user_id}" ${state.session.can_edit ? "" : "disabled"}>ミュート</button>
            <button type="button" class="inline-button" data-member-action="deafen" data-user-id="${participant.user_id}" ${state.session.can_edit ? "" : "disabled"}>デフェン</button>
          </div>
        </div>
      </article>
    `;
  }

  function teamMemberMarkup(participant, teamName) {
    const isSelected = sameId(state.selectedUserId, participant.user_id);
    return `
      <div class="team-member-row${isSelected ? " is-selected" : ""}" data-user-id="${participant.user_id}" data-team-slot="${window.VCApp.escapeHtml(teamName)}" draggable="${canMoveParticipant(participant)}">
        <div class="row-primary">
          ${window.VCApp.avatarMarkup(participant.user, "avatar-xs")}
          <div class="row-copy">
            <strong>${window.VCApp.escapeHtml(participant.user.display_name)}</strong>
            <small>${window.VCApp.escapeHtml(participant.location_label)}</small>
          </div>
        </div>
        <span class="muted-text">${window.VCApp.formatDuration(participant.talk_seconds)}</span>
      </div>
    `;
  }

  function teamGroupMarkup(teamName, members, isUnassigned = false) {
    const slot = isUnassigned ? "" : teamName;
    const title = isUnassigned ? "未所属 / メインVC" : teamName;
    return `
      <article class="team-group" data-team-slot="${window.VCApp.escapeHtml(slot)}">
        <div class="team-group-header">
          <div class="row-copy">
            <strong>${window.VCApp.escapeHtml(title)}</strong>
            <small>${members.length}人 / ${state.selectedUserId ? "タップで移動先に設定" : "ドラッグ&ドロップまたはタップ選択"}</small>
          </div>
          <span class="badge neutral">${members.length}</span>
        </div>
        <div class="team-group-members" data-team-slot="${window.VCApp.escapeHtml(slot)}">
          ${
            members.length
              ? members.map((participant) => teamMemberMarkup(participant, slot)).join("")
              : '<div class="sidebar-empty">ここへドロップ</div>'
          }
        </div>
      </article>
    `;
  }

  function renderParticipants(session) {
    const list = document.querySelector("[data-participant-list]");
    if (!list) return;

    list.innerHTML = session.activeParticipants.length
      ? session.activeParticipants.map(participantRowMarkup).join("")
      : '<div class="empty-panel"><strong>参加者がいません</strong><p>参加者が入るとここへ一覧が表示されます。</p></div>';
  }

  function renderTeamBoard(session) {
    const root = document.querySelector("[data-team-board]");
    if (!root) return;

    const unassigned = session.activeParticipants.filter((participant) => !teamAssignmentFor(session, participant.user_id));
    const groups = [
      teamGroupMarkup("", unassigned, true),
      ...session.teamNames.map((teamName) => {
        const members = session.activeParticipants.filter((participant) => teamAssignmentFor(session, participant.user_id) === teamName);
        return teamGroupMarkup(teamName, members);
      }),
    ];
    root.innerHTML = groups.join("");

    const banner = document.querySelector("[data-selected-user-banner]");
    if (!banner) return;
    const selected = selectedParticipant();
    if (!selected) {
      banner.hidden = true;
      return;
    }
    banner.hidden = false;
    banner.textContent = `${selected.user.display_name} を選択中です。移動先のチームをクリックするか、ドラッグして仮配置してください。`;
  }

  function renderRecallList(session) {
    const root = document.querySelector("[data-recall-list]");
    if (!root) return;

    if (!session.can_edit) {
      root.innerHTML = '<div class="sidebar-empty">集合 / 呼び戻しは開始ユーザーまたはサーバー管理者のみ実行できます。</div>';
      return;
    }

    const targets = session.activeParticipants.filter((participant) => !sameId(participant.current_channel_id, session.root_channel_id));
    root.innerHTML = targets.length
      ? targets
          .map(
            (participant) => `
              <div class="compact-table-row">
                <div class="row-primary">
                  ${window.VCApp.avatarMarkup(participant.user, "avatar-xs")}
                  <div class="row-copy">
                    <strong>${window.VCApp.escapeHtml(participant.user.display_name)}</strong>
                    <small>${window.VCApp.escapeHtml(participant.location_label)}</small>
                  </div>
                </div>
                <button type="button" class="button button-secondary" data-member-action="recall" data-user-id="${participant.user_id}">戻す</button>
              </div>
            `,
          )
          .join("")
      : '<div class="sidebar-empty">呼び戻し対象はいません。</div>';
  }

  function renderMemberFormSelect(session) {
    document.querySelectorAll("[name='user_id']").forEach((select) => {
      const options = session.activeParticipants
        .map((participant) => `<option value="${participant.user_id}">${window.VCApp.escapeHtml(participant.user.display_name)}</option>`)
        .join("");
      select.innerHTML = options || '<option value="">対象なし</option>';
    });
  }

  function renderTimelineUserFilter(session) {
    const select = document.querySelector("[data-timeline-user-filter]");
    if (!select) return;
    const selected = select.value;
    const options = session.participants
      .map((participant) => `<option value="${participant.user_id}">${window.VCApp.escapeHtml(participant.user.display_name)}</option>`)
      .join("");
    select.innerHTML = `<option value="">All users</option>${options}`;
    select.value = selected;
  }

  function renderMobileTeamSelect(session) {
    const select = document.querySelector("[data-mobile-team-select]");
    if (!select) return;
    const selected = state.mobileMenuUserId ? teamAssignmentFor(session, state.mobileMenuUserId) : "";
    const options = [
      '<option value="">Main VC / Unassigned</option>',
      ...session.teamNames.map((teamName) => `<option value="${window.VCApp.escapeHtml(teamName)}">${window.VCApp.escapeHtml(teamName)}</option>`),
    ];
    select.innerHTML = options.join("");
    select.value = selected || "";
  }

  function timelineEventMarkup(event) {
    const created = event.created_at ? new Date(event.created_at).toLocaleString() : "";
    const actor = event.display_actor || event.user_name || "System";
    return `
      <article class="timeline-item" data-timeline-event-id="${window.VCApp.escapeHtml(event.id)}">
        <div class="timeline-item-meta">
          <strong>${window.VCApp.escapeHtml(event.event_label || event.event_type)}</strong>
          <small>${window.VCApp.escapeHtml(created)}</small>
        </div>
        <div class="timeline-item-copy">
          <strong>${window.VCApp.escapeHtml(actor)}</strong>
          <p>${window.VCApp.escapeHtml(event.message || "")}</p>
        </div>
      </article>
    `;
  }

  function renderTimeline() {
    const root = document.querySelector("[data-timeline-list]");
    if (!root) return;
    root.innerHTML = state.timelineEvents.length
      ? state.timelineEvents.map(timelineEventMarkup).join("")
      : '<div class="sidebar-empty">No timeline events yet.</div>';
  }

  function renderSelectedMember(session) {
    const root = document.querySelector("[data-selected-member]");
    if (!root) return;

    const participant = selectedParticipant();
    if (!participant) {
      root.innerHTML = `
        <strong>選択中のメンバーなし</strong>
        <p>参加者一覧またはチーム欄のメンバーを選ぶと、ここに詳細と操作ヒントを表示します。</p>
      `;
      return;
    }

    root.innerHTML = `
      <div class="row-primary">
        ${window.VCApp.avatarMarkup(participant.user, "avatar-sm")}
        <div class="row-copy">
          <strong>${window.VCApp.escapeHtml(participant.user.display_name)}</strong>
          <small>${window.VCApp.escapeHtml(participant.location_label)}</small>
        </div>
      </div>
      <div class="stacked-metrics">
        <span>所属チーム: ${window.VCApp.escapeHtml(teamAssignmentFor(session, participant.user_id) || "未所属")}</span>
        <span>通話時間: ${window.VCApp.formatDuration(participant.talk_seconds)}</span>
        <span>AFK時間: ${window.VCApp.formatDuration(participant.afk_seconds)}</span>
      </div>
    `;
  }

  function renderErrorState(message) {
    const safeMessage = window.VCApp.escapeHtml(message || "VC情報の取得に失敗しました。");
    const errorMarkup = `<div class="empty-panel"><strong>セッション情報を取得できません</strong><p>${safeMessage}</p></div>`;
    const compactErrorMarkup = `<div class="sidebar-empty">${safeMessage}</div>`;

    const participantList = document.querySelector("[data-participant-list]");
    if (participantList) participantList.innerHTML = errorMarkup;

    const teamBoard = document.querySelector("[data-team-board]");
    if (teamBoard) teamBoard.innerHTML = errorMarkup;

    const recallList = document.querySelector("[data-recall-list]");
    if (recallList) recallList.innerHTML = compactErrorMarkup;

    const selectedMember = document.querySelector("[data-selected-member]");
    if (selectedMember) {
      selectedMember.innerHTML = `<strong>セッションが見つかりません</strong><p>${safeMessage}</p>`;
    }
  }

  function render(session) {
    renderSummary(session);
    renderChannelList(session);
    renderParticipants(session);
    renderTeamBoard(session);
    renderRecallList(session);
    renderSelectedMember(session);
    renderMemberFormSelect(session);
    renderTimelineUserFilter(session);
    renderMobileTeamSelect(session);

    const pending = pendingChangeCount(session);
    setNotice(
      pending
        ? `未反映のチーム仮配置が ${pending} 件あります。「分割を反映」を押すまで Discord 側には適用されません。`
        : "リアルタイム同期中です。チーム移動は仮配置のあと「分割を反映」で適用されます。",
      pending ? "warning" : "info",
    );
  }

  function setPendingAssignment(userId, teamName) {
    if (!state.session) return;
    const normalizedUserId = toId(userId);
    state.pendingAssignments[normalizedUserId] = teamName || "";
    state.selectedUserId = normalizedUserId;
    state.dirty = true;
    state.session = normalizeSession(state.session);
    render(state.session);
  }

  async function applyPendingAssignments() {
    if (!state.session) return;
    const { guildId, rootChannelId } = rootIds();
    const changes = state.session.activeParticipants.filter((participant) => {
      const serverValue = state.session.team_assignments?.[String(participant.user_id)] || "";
      return teamAssignmentFor(state.session, participant.user_id) !== serverValue;
    });

    for (const participant of changes) {
      await window.VCApp.api(voiceApiUrl(guildId, rootChannelId, "/team/assign"), {
        method: "POST",
        body: JSON.stringify({
          user_id: participant.user_id,
          team_name: teamAssignmentFor(state.session, participant.user_id) || null,
        }),
      });
    }
    state.dirty = false;
  }

  async function savePendingAssignments() {
    if (!state.session) return;
    const pending = pendingChangeCount(state.session);
    if (!pending) {
      window.VCToast?.info("保存するチーム移動はありません。");
      return;
    }
    await applyPendingAssignments();
    window.VCToast?.success("チーム移動を保存しました。");
    await refreshSession();
  }

  async function updateServerState(userId, payload) {
    const { guildId, rootChannelId } = rootIds();
    await window.VCApp.api(voiceApiUrl(guildId, rootChannelId, "/member-state"), {
      method: "POST",
      body: JSON.stringify({
        user_id: userId,
        ...payload,
      }),
    });
  }

  async function refreshSession() {
    const { guildId, rootChannelId } = rootIds();
    const payload = await window.VCApp.api(voiceApiUrl(guildId, rootChannelId, "/state"));
    const session = normalizeSession(payload);
    syncPendingAssignments(session);
    state.session = session;
    render(session);
  }

  async function refreshTimeline() {
    const { guildId, rootChannelId } = rootIds();
    const params = new URLSearchParams();
    const form = document.querySelector("[data-timeline-filters]");
    if (form) {
      const formData = new FormData(form);
      ["user_id", "event_type", "date_from", "date_to"].forEach((key) => {
        const value = String(formData.get(key) || "").trim();
        if (value) params.set(key, value);
      });
    }
    const suffix = params.toString() ? `?${params.toString()}` : "";
    const payload = await window.VCApp.api(voiceApiUrl(guildId, rootChannelId, `/timeline${suffix}`));
    state.timelineEvents = payload.events || [];
    renderTimeline();
  }

  async function submitVoiceSettings(form) {
    const { guildId, rootChannelId } = rootIds();
    const formData = new FormData(form);
    await window.VCApp.api(voiceApiUrl(guildId, rootChannelId, "/settings"), {
      method: "POST",
      body: JSON.stringify({
        name: formData.get("name"),
        user_limit: formData.get("user_limit"),
        bitrate: formData.get("bitrate"),
      }),
    });
    window.VCToast?.success("VC設定を保存しました。");
    await refreshSession();
  }

  async function submitMemberState(form) {
    const formData = new FormData(form);
    const action = formData.get("action");
    const payload = { user_id: formData.get("user_id") };
    if (action === "mute_on") payload.mute = true;
    if (action === "mute_off") payload.mute = false;
    if (action === "deafen_on") payload.deafen = true;
    if (action === "deafen_off") payload.deafen = false;

    await updateServerState(formData.get("user_id"), payload);
    window.VCToast?.success("メンバー状態を更新しました。");
    await refreshSession();
  }

  async function submitAccessSettings(form) {
    const { guildId, rootChannelId } = rootIds();
    const formData = new FormData(form);
    await window.VCApp.api(voiceApiUrl(guildId, rootChannelId, "/access"), {
      method: "POST",
      body: JSON.stringify({
        access_mode: formData.get("access_mode"),
        invited_user_ids: formData.getAll("invited_user_ids"),
        access_role_ids: formData.getAll("access_role_ids"),
      }),
    });
    window.VCToast?.success("VC access settings saved.");
    await refreshSession();
  }

  async function executeSplit() {
    const { guildId, rootChannelId } = rootIds();
    if (pendingChangeCount(state.session)) {
      await applyPendingAssignments();
    }
    await window.VCApp.api(voiceApiUrl(guildId, rootChannelId, "/team/split"), {
      method: "POST",
      body: "{}",
    });
    state.dirty = false;
    window.VCToast?.success("チーム分割を反映しました。");
    await refreshSession();
  }

  async function executeAssemble() {
    const { guildId, rootChannelId } = rootIds();
    await window.VCApp.api(voiceApiUrl(guildId, rootChannelId, "/team/assemble"), {
      method: "POST",
      body: "{}",
    });
    state.dirty = false;
    window.VCToast?.success("集合を実行しました。");
    await refreshSession();
  }

  async function executeRecall(userId) {
    const { guildId, rootChannelId } = rootIds();
    await window.VCApp.api(voiceApiUrl(guildId, rootChannelId, "/team/recall"), {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    });
    window.VCToast?.success("メンバーを呼び戻しました。");
    await refreshSession();
  }

  function closeMobileMemberMenu() {
    state.mobileMenuUserId = null;
    const menu = document.querySelector("[data-mobile-member-menu]");
    if (menu) menu.hidden = true;
  }

  function openMobileMemberMenu(userId) {
    if (!state.session) return;
    const participant = state.session.activeParticipants.find((item) => sameId(item.user_id, userId));
    if (!participant) return;
    state.mobileMenuUserId = toId(userId);
    state.selectedUserId = toId(userId);
    render(state.session);
    const menu = document.querySelector("[data-mobile-member-menu]");
    const name = document.querySelector("[data-mobile-member-menu-name]");
    if (name) name.textContent = participant.user.display_name;
    if (menu) menu.hidden = false;
  }

  function clearLongPressTimer() {
    window.clearTimeout(state.touch.longPressTimerId);
    state.touch.longPressTimerId = null;
  }

  function handleSwipe(userId, deltaX, deltaY) {
    if (!state.session || Math.abs(deltaX) < 54 || Math.abs(deltaX) < Math.abs(deltaY) * 1.4) return false;
    const participant = state.session.activeParticipants.find((item) => sameId(item.user_id, userId));
    if (!participant) return false;
    if (deltaX > 0 && canMoveParticipant(participant)) {
      state.selectedUserId = toId(userId);
      render(state.session);
      window.VCToast?.info("移動先のチームをタップしてください。");
      return true;
    }
    if (deltaX < 0) {
      openMobileMemberMenu(userId);
      return true;
    }
    return false;
  }

  function handleRealtimeMessage(message) {
    if (message.event === "session_update") {
      const session = normalizeSession(message.payload);
      syncPendingAssignments(session);
      state.session = session;
      render(session);
      return;
    }
    if (message.event === "session_event" && message.payload?.session) {
      const session = normalizeSession(message.payload.session);
      syncPendingAssignments(session);
      state.session = session;
      render(session);
      return;
    }
    if (message.event === "timeline_event" && message.payload?.event) {
      const event = message.payload.event;
      if (!state.timelineEvents.some((item) => item.id === event.id)) {
        state.timelineEvents.push(event);
        renderTimeline();
      }
    }
  }

  function startElapsedTicker() {
    window.clearInterval(state.timerId);
    state.timerId = window.setInterval(() => {
      if (!state.session) return;
      state.session.elapsed_seconds += 1;
      renderSummary(state.session);
    }, 1000);
  }

  function bindDragAndDrop() {
    const root = document.querySelector("[data-voice-board-root]");
    if (!root) return;

    root.addEventListener("dragstart", (event) => {
      const target = event.target.closest("[data-user-id]");
      if (!target) return;
      target.classList.add("is-dragging");
      event.dataTransfer?.setData("text/plain", String(target.dataset.userId));
    });

    root.addEventListener("dragend", (event) => {
      const target = event.target.closest("[data-user-id]");
      if (target) target.classList.remove("is-dragging");
      document.querySelectorAll(".team-group").forEach((group) => group.classList.remove("is-drop-target"));
    });

    root.addEventListener("dragover", (event) => {
      const zone = event.target.closest("[data-team-slot]");
      if (!zone) return;
      event.preventDefault();
      zone.closest(".team-group")?.classList.add("is-drop-target");
    });

    root.addEventListener("dragleave", (event) => {
      event.target.closest(".team-group")?.classList.remove("is-drop-target");
    });

    root.addEventListener("drop", (event) => {
      const zone = event.target.closest("[data-team-slot]");
      if (!zone) return;
      event.preventDefault();
      const userId = toId(event.dataTransfer?.getData("text/plain"));
      if (!userId) return;
      const participant = state.session?.activeParticipants.find((item) => sameId(item.user_id, userId));
      if (!participant || !canMoveParticipant(participant)) return;
      setPendingAssignment(userId, zone.dataset.teamSlot || "");
      document.querySelectorAll(".team-group").forEach((group) => group.classList.remove("is-drop-target"));
    });
  }

  function bindClicks() {
    document.addEventListener("click", async (event) => {
      if (document.body.dataset.page !== "voice" || !state.session) return;

      const selectTarget = event.target.closest("[data-user-id]");
      if (selectTarget && !event.target.closest("[data-member-action]")) {
        const participant = state.session.activeParticipants.find((item) => sameId(item.user_id, selectTarget.dataset.userId));
        if (participant && canMoveParticipant(participant)) {
          state.selectedUserId = toId(selectTarget.dataset.userId);
          render(state.session);
        }
      }

      const teamSlot = event.target.closest("[data-team-slot]");
      if (teamSlot && state.selectedUserId && !event.target.closest("[data-user-id]")) {
        const participant = selectedParticipant();
        if (participant && canMoveParticipant(participant)) {
          setPendingAssignment(state.selectedUserId, teamSlot.dataset.teamSlot || "");
        }
      }

      const actionButton = event.target.closest("[data-member-action]");
      if (actionButton) {
        const userId = toId(actionButton.dataset.userId);
        const action = actionButton.dataset.memberAction;
        try {
          if (action === "select") {
            state.selectedUserId = userId;
            render(state.session);
          } else if (action === "recall") {
            await executeRecall(userId);
          } else if (action === "mute") {
            await updateServerState(userId, { mute: true });
            window.VCToast?.success("サーバーミュートを設定しました。");
            await refreshSession();
          } else if (action === "deafen") {
            await updateServerState(userId, { deafen: true });
            window.VCToast?.success("サーバーデフェンを設定しました。");
            await refreshSession();
          }
        } catch (error) {
          window.VCToast?.error(error.message || "操作に失敗しました。");
        }
      }

      if (event.target.closest("[data-action='split']")) {
        try {
          await executeSplit();
        } catch (error) {
          window.VCToast?.error(error.message || "分割に失敗しました。");
        }
      }

      if (event.target.closest("[data-action='assemble']")) {
        try {
          await executeAssemble();
        } catch (error) {
          window.VCToast?.error(error.message || "集合に失敗しました。");
        }
      }
      if (event.target.closest("[data-mobile-action='save']")) {
        try {
          await savePendingAssignments();
        } catch (error) {
          window.VCToast?.error(error.message || "保存に失敗しました。");
        }
      }

      const mobileMenuAction = event.target.closest("[data-mobile-menu-action]");
      if (mobileMenuAction) {
        const userId = state.mobileMenuUserId;
        if (!userId) return;
        try {
          if (mobileMenuAction.dataset.mobileMenuAction === "move") {
            const select = document.querySelector("[data-mobile-team-select]");
            setPendingAssignment(userId, select?.value || "");
            closeMobileMemberMenu();
          } else if (mobileMenuAction.dataset.mobileMenuAction === "recall") {
            await executeRecall(userId);
            closeMobileMemberMenu();
          } else if (mobileMenuAction.dataset.mobileMenuAction === "details") {
            state.selectedUserId = userId;
            closeMobileMemberMenu();
            render(state.session);
            document.querySelector("[data-selected-member]")?.scrollIntoView({ behavior: "smooth", block: "center" });
          }
        } catch (error) {
          window.VCToast?.error(error.message || "操作に失敗しました。");
        }
      }

      if (event.target.closest("[data-mobile-menu-close]") || event.target.matches("[data-mobile-member-menu]")) {
        closeMobileMemberMenu();
      }
    });
  }

  function bindMobileGestures() {
    const root = document.querySelector("[data-voice-board-root]");
    if (!root) return;

    root.addEventListener("pointerdown", (event) => {
      if (event.pointerType === "mouse") return;
      const target = event.target.closest("[data-user-id]");
      if (!target || event.target.closest("[data-member-action]")) return;
      state.touch.pointerId = event.pointerId;
      state.touch.userId = toId(target.dataset.userId);
      state.touch.startX = event.clientX;
      state.touch.startY = event.clientY;
      state.touch.moved = false;
      clearLongPressTimer();
      state.touch.longPressTimerId = window.setTimeout(() => {
        if (!state.touch.moved && state.touch.userId) {
          openMobileMemberMenu(state.touch.userId);
        }
      }, 520);
    });

    root.addEventListener("pointermove", (event) => {
      if (state.touch.pointerId !== event.pointerId) return;
      const deltaX = event.clientX - state.touch.startX;
      const deltaY = event.clientY - state.touch.startY;
      if (Math.abs(deltaX) > 12 || Math.abs(deltaY) > 12) {
        state.touch.moved = true;
        clearLongPressTimer();
      }
    });

    root.addEventListener("pointerup", (event) => {
      if (state.touch.pointerId !== event.pointerId) return;
      clearLongPressTimer();
      const userId = state.touch.userId;
      const deltaX = event.clientX - state.touch.startX;
      const deltaY = event.clientY - state.touch.startY;
      state.touch.pointerId = null;
      state.touch.userId = null;
      if (userId) handleSwipe(userId, deltaX, deltaY);
    });

    root.addEventListener("pointercancel", () => {
      clearLongPressTimer();
      state.touch.pointerId = null;
      state.touch.userId = null;
    });
  }

  function bindForms() {
    const voiceSettingsForm = document.querySelector("[data-voice-settings]");
    const memberStateForm = document.querySelector("[data-member-state]");
    const accessSettingsForm = document.querySelector("[data-access-settings]");

    voiceSettingsForm?.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        await submitVoiceSettings(voiceSettingsForm);
      } catch (error) {
        window.VCToast?.error(error.message || "VC設定の保存に失敗しました。");
      }
    });

    memberStateForm?.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        await submitMemberState(memberStateForm);
      } catch (error) {
        window.VCToast?.error(error.message || "メンバー状態の更新に失敗しました。");
      }
    });

    accessSettingsForm?.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        await submitAccessSettings(accessSettingsForm);
      } catch (error) {
        window.VCToast?.error(error.message || "VC access update failed.");
      }
    });
  }

  document.addEventListener("submit", async (event) => {
    const form = event.target.closest("[data-timeline-filters]");
    if (!form || document.body.dataset.page !== "voice") return;
    event.preventDefault();
    try {
      await refreshTimeline();
    } catch (error) {
      window.VCToast?.error(error.message || "Timeline refresh failed.");
    }
  });

  document.addEventListener("DOMContentLoaded", async () => {
    if (document.body.dataset.page !== "voice" || !window.VCApp) return;

    bindDragAndDrop();
    bindClicks();
    bindMobileGestures();
    bindForms();
    window.addEventListener("vc:realtime", (event) => handleRealtimeMessage(event.detail));

    try {
      await refreshSession();
      await refreshTimeline();
      startElapsedTicker();
    } catch (error) {
      console.error(error);
      window.VCToast?.error(error.message || "VC情報の取得に失敗しました。");
      setNotice(error.message || "VC情報の取得に失敗しました。", "error");
      renderErrorState(error.message || "VC情報の取得に失敗しました。");
    }
  });
})();
