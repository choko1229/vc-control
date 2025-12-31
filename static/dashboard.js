// static/dashboard.js

async function loadUserInfo() {
  const res = await fetch("/api/user");
  const data = await res.json();

  const userBox = document.getElementById("user-box");
  const ctaArea = document.getElementById("cta-area");
  const statusBadge = document.getElementById("user-status");

  if (!data.authenticated) {
    if (userBox) userBox.style.display = "none";
    if (ctaArea) ctaArea.style.display = "flex";
    if (statusBadge) statusBadge.textContent = "未ログイン";
    return;
  }

  if (ctaArea) ctaArea.style.display = "none";
  if (userBox) userBox.style.display = "block";
  if (statusBadge) statusBadge.textContent = "ログイン中";

  const nameEl = document.getElementById("user-name");
  const idEl = document.getElementById("user-id");
  if (nameEl) nameEl.innerText = data.user.global_name || data.user.username;
  if (idEl) idEl.innerText = data.user.username ? `@${data.user.username}` : "";

  const avatar = data.user.avatar
    ? `https://cdn.discordapp.com/avatars/${data.user.id}/${data.user.avatar}.png`
    : `https://cdn.discordapp.com/embed/avatars/${Number(data.user.discriminator || 0) % 5}.png`;
  const avatarEl = document.getElementById("user-avatar");
  if (avatarEl) {
    avatarEl.src = avatar;
    avatarEl.alt = `${data.user.username} avatar`;
  }
}

async function loadUsage() {
  const usageBox = document.getElementById("usage-box");
  if (!usageBox) return;

  try {
    const res = await fetch("/api/usage");
    const data = await res.json();
    if (!res.ok || !data.ok) {
      usageBox.innerHTML = `<div class="helper">統計を読み込めませんでした: ${data.error || ""}</div>`;
      return;
    }

    const totalHours = (data.total_seconds / 3600).toFixed(1);
    const totalEl = document.getElementById("usage-total");
    if (totalEl) totalEl.textContent = `${totalHours} 時間`;

    const dailyWrap = document.getElementById("usage-daily");
    if (dailyWrap) {
      dailyWrap.innerHTML = "";
      const maxVal = Math.max(...data.daily.map((d) => d.seconds), 1);
      data.daily.forEach((item) => {
        const bar = document.createElement("div");
        bar.className = "bar";
        bar.style.height = `${(item.seconds / maxVal) * 100}%`;
        bar.title = `${item.label}: ${(item.seconds / 3600).toFixed(1)} 時間`;
        const cap = document.createElement("span");
        cap.textContent = item.label;
        cap.className = "bar-label";
        bar.appendChild(cap);
        dailyWrap.appendChild(bar);
      });
    }

    const hourlyWrap = document.getElementById("usage-hourly");
    if (hourlyWrap) {
      hourlyWrap.innerHTML = "";
      const maxVal = Math.max(...data.hourly, 1);
      data.hourly.forEach((seconds, hour) => {
        const bar = document.createElement("div");
        bar.className = "bar";
        bar.style.height = `${(seconds / maxVal) * 100}%`;
        bar.title = `${hour}時台: ${(seconds / 3600).toFixed(1)} 時間`;
        const cap = document.createElement("span");
        cap.textContent = hour;
        cap.className = "bar-label";
        bar.appendChild(cap);
        hourlyWrap.appendChild(bar);
      });
    }
  } catch (e) {
    usageBox.innerHTML = "<div class=\"helper\">統計の取得中にエラーが発生しました。</div>";
  }
}

window.addEventListener("DOMContentLoaded", () => {
  loadUserInfo();
  loadUsage();
});
