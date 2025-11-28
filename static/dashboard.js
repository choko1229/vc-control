// static/dashboard.js

async function loadUserInfo() {
    const res = await fetch("/api/user");
    const data = await res.json();

    const loginBox = document.getElementById("login-box");
    const userBox = document.getElementById("user-box");

    if (!data.authenticated) {
        loginBox.style.display = "block";
        userBox.style.display = "none";
        return;
    }

    loginBox.style.display = "none";
    userBox.style.display = "block";

    document.getElementById("user-name").innerText = data.user.username;
    document.getElementById("user-id").innerText = data.user.id;

    const avatar = `https://cdn.discordapp.com/avatars/${data.user.id}/${data.user.avatar}.png`;
    document.getElementById("user-avatar").src = avatar;
}

window.onload = loadUserInfo;
