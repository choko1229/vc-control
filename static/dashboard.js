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
  if (nameEl) nameEl.innerText = data.user.username;
  if (idEl) idEl.innerText = `ID: ${data.user.id}`;

  const avatar = data.user.avatar
    ? `https://cdn.discordapp.com/avatars/${data.user.id}/${data.user.avatar}.png`
    : `https://cdn.discordapp.com/embed/avatars/${Number(data.user.discriminator || 0) % 5}.png`;
  const avatarEl = document.getElementById("user-avatar");
  if (avatarEl) {
    avatarEl.src = avatar;
    avatarEl.alt = `${data.user.username} avatar`;
  }
}

window.addEventListener("DOMContentLoaded", loadUserInfo);
