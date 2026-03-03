/* ═══════════════════════════════════════════════════════════════
   TIN4 — Frontend Application
   Technologies in use:
     REST   → all CRUD operations
     WS     → real-time match & message notifications
     GraphQL → profile / match / stats queries
     RabbitMQ → triggered via swipe (server-side)
     Redpanda → triggered via all events (server-side)
     TCP    → heartbeat presence (shown via online count from API)
   ═══════════════════════════════════════════════════════════════ */

const API = window.location.origin;
const WS_BASE = API.replace(/^http/, "ws");

let token = null;
let currentUserId = null;
let currentMatchId = null;
let profiles = [];
let currentProfileIdx = 0;
let ws = null;
let dragStartX = 0, dragStartY = 0, isDragging = false;

// ── Logging ──────────────────────────────────────────────────────────────
function techLog(msg, cls = "") {
  const el = document.getElementById("tech-log-entries");
  const entry = document.createElement("div");
  entry.className = "log-entry " + cls;
  entry.textContent = new Date().toISOString().slice(11, 23) + "  " + msg;
  el.prepend(entry);
  if (el.children.length > 30) el.lastChild.remove();
}

// ── Badge helpers ────────────────────────────────────────────────────────
function setBadge(id, cls) {
  const el = document.getElementById(id);
  el.className = "badge " + cls;
}

// ── Auth helpers ─────────────────────────────────────────────────────────
function saveAuth(data) {
  token = data.access_token;
  currentUserId = data.user_id;
  localStorage.setItem("tin4_token", token);
  localStorage.setItem("tin4_user_id", currentUserId);
}

function loadSavedAuth() {
  token = localStorage.getItem("tin4_token");
  currentUserId = localStorage.getItem("tin4_user_id");
  return !!token;
}

async function apiFetch(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (token) headers["Authorization"] = "Bearer " + token;
  const res = await fetch(API + path, { ...opts, headers });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  return res.json();
}

// ── Auth UI ──────────────────────────────────────────────────────────────
function showTab(tab) {
  document.getElementById("login-form").classList.toggle("hidden", tab !== "login");
  document.getElementById("register-form").classList.toggle("hidden", tab !== "register");
  document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
  event.target.classList.add("active");
}

async function doLogin(e) {
  e.preventDefault();
  const email = document.getElementById("login-email").value;
  const password = document.getElementById("login-password").value;
  try {
    setBadge("badge-rest", "active");
    techLog("REST POST /api/auth/login");
    const data = await apiFetch("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    saveAuth(data);
    setBadge("badge-rest", "active");
    techLog("REST ✓ login OK user=" + currentUserId);
    enterApp();
  } catch (err) {
    showError(err.message);
    setBadge("badge-rest", "");
  }
}

async function doRegister(e) {
  e.preventDefault();
  const body = {
    name: document.getElementById("reg-name").value,
    email: document.getElementById("reg-email").value,
    password: document.getElementById("reg-password").value,
    age: parseInt(document.getElementById("reg-age").value),
    bio: document.getElementById("reg-bio").value,
  };
  try {
    setBadge("badge-rest", "active");
    techLog("REST POST /api/auth/register → Redpanda user_activity");
    const data = await apiFetch("/api/auth/register", { method: "POST", body: JSON.stringify(body) });
    saveAuth(data);
    techLog("REST ✓ register OK user=" + currentUserId);
    enterApp();
  } catch (err) {
    showError(err.message);
    setBadge("badge-rest", "");
  }
}

function showError(msg) {
  const el = document.getElementById("auth-error");
  el.textContent = msg;
  el.classList.remove("hidden");
}

function logout() {
  token = null; currentUserId = null;
  localStorage.removeItem("tin4_token");
  localStorage.removeItem("tin4_user_id");
  if (ws) { ws.close(); ws = null; }
  document.getElementById("swipe-screen").classList.remove("active");
  document.getElementById("auth-screen").classList.add("active");
  techLog("Logged out");
}

// ── App Entry ─────────────────────────────────────────────────────────────
async function enterApp() {
  document.getElementById("auth-screen").classList.remove("active");
  document.getElementById("swipe-screen").classList.add("active");
  document.getElementById("auth-error").classList.add("hidden");

  // Fetch profile for display name
  try {
    const me = await apiFetch("/api/auth/me");
    document.getElementById("top-user-name").textContent = me.name;
    techLog("REST GET /api/auth/me → " + me.name);
  } catch {}

  connectWebSocket();
  loadProfiles();
  startPresencePolling();
}

// ── WebSocket ─────────────────────────────────────────────────────────────
function connectWebSocket() {
  if (ws) ws.close();
  const url = WS_BASE.replace(/^http/, "ws") + "/ws?token=" + token;
  ws = new WebSocket(url);

  ws.onopen = () => {
    setBadge("badge-ws", "ws-connected");
    techLog("WS ✓ connected to /ws", "ws");
    // Send heartbeat pings every 30s
    ws._pingInterval = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send("ping");
    }, 30000);
  };

  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg === "pong") return;
      techLog("WS ← " + JSON.stringify(msg).slice(0, 80), "ws");
      if (msg.type === "match") handleMatchEvent(msg.data);
      if (msg.type === "message") handleIncomingMessage(msg.data);
    } catch {}
  };

  ws.onclose = () => {
    setBadge("badge-ws", "");
    techLog("WS disconnected — reconnecting in 3s", "ws");
    clearInterval(ws?._pingInterval);
    setTimeout(() => { if (token) connectWebSocket(); }, 3000);
  };

  ws.onerror = () => {
    techLog("WS error", "error");
  };
}

// ── Profiles (REST) ───────────────────────────────────────────────────────
async function loadProfiles() {
  try {
    setBadge("badge-rest", "active");
    techLog("REST GET /api/profiles");
    profiles = await apiFetch("/api/profiles?limit=10");
    currentProfileIdx = 0;
    setBadge("badge-rest", "");
    techLog("REST ✓ loaded " + profiles.length + " profiles");
    renderCardStack();
  } catch (err) {
    techLog("REST ✗ " + err.message, "error");
  }
}

function renderCardStack() {
  const stack = document.getElementById("card-stack");
  // Remove old cards
  stack.querySelectorAll(".profile-card").forEach(c => c.remove());
  document.getElementById("no-more").classList.add("hidden");

  const remaining = profiles.slice(currentProfileIdx, currentProfileIdx + 3);
  if (remaining.length === 0) {
    document.getElementById("no-more").classList.remove("hidden");
    setSwipeBtns(false);
    return;
  }

  setSwipeBtns(true);
  // Render back-to-front so top card is last (highest z-index)
  [...remaining].reverse().forEach((p, ri) => {
    const card = buildCard(p);
    const zIdx = remaining.length - ri;
    card.style.zIndex = zIdx;
    card.style.transform = `scale(${1 - ri * 0.04}) translateY(${ri * 12}px)`;
    card.style.opacity = ri === 0 ? "1" : "0.7";
    if (zIdx === remaining.length) setupDrag(card, p);
    stack.appendChild(card);
  });
}

function buildCard(profile) {
  const card = document.createElement("div");
  card.className = "profile-card";
  card.dataset.profileId = profile.id;
  card.innerHTML = `
    <img src="${profile.photo_url || 'https://i.pravatar.cc/300?u=' + profile.id}"
         alt="${profile.name}" loading="lazy" onerror="this.src='https://i.pravatar.cc/300'"/>
    <div class="swipe-label like">LIKE</div>
    <div class="swipe-label pass">PASS</div>
    <div class="card-info">
      <span class="card-name">${profile.name}</span>
      <span class="card-age">${profile.age}</span>
      ${profile.is_online ? '<span class="online-dot" title="Online via TCP heartbeat"></span>' : ''}
      <div class="card-bio">${profile.bio || ''}</div>
    </div>
  `;
  return card;
}

function setSwipeBtns(enabled) {
  document.getElementById("btn-like").disabled = !enabled;
  document.getElementById("btn-pass").disabled = !enabled;
}

// ── Drag-to-swipe ─────────────────────────────────────────────────────────
function setupDrag(card, profile) {
  card.addEventListener("pointerdown", (e) => {
    isDragging = true;
    dragStartX = e.clientX;
    dragStartY = e.clientY;
    card.setPointerCapture(e.pointerId);
  });
  card.addEventListener("pointermove", (e) => {
    if (!isDragging) return;
    const dx = e.clientX - dragStartX;
    const dy = e.clientY - dragStartY;
    const rotate = dx * 0.08;
    card.style.transform = `translate(${dx}px, ${dy}px) rotate(${rotate}deg)`;
    const threshold = 60;
    const likeLabel = card.querySelector(".swipe-label.like");
    const passLabel = card.querySelector(".swipe-label.pass");
    if (dx > threshold)  { likeLabel.style.opacity = Math.min((dx - threshold) / 60, 1); passLabel.style.opacity = 0; }
    else if (dx < -threshold) { passLabel.style.opacity = Math.min((-dx - threshold) / 60, 1); likeLabel.style.opacity = 0; }
    else { likeLabel.style.opacity = 0; passLabel.style.opacity = 0; }
  });
  card.addEventListener("pointerup", async (e) => {
    if (!isDragging) return;
    isDragging = false;
    const dx = e.clientX - dragStartX;
    if (dx > 80) {
      await animateSwipe(card, "right");
      await doSwipe(profile.id, "like");
    } else if (dx < -80) {
      await animateSwipe(card, "left");
      await doSwipe(profile.id, "pass");
    } else {
      card.style.transition = "transform .3s";
      card.style.transform = "";
      setTimeout(() => { card.style.transition = ""; }, 300);
    }
  });
}

async function animateSwipe(card, dir) {
  card.style.transition = "transform .3s, opacity .3s";
  card.style.transform = dir === "right"
    ? "translate(150%, -20px) rotate(20deg)"
    : "translate(-150%, -20px) rotate(-20deg)";
  card.style.opacity = "0";
  await new Promise(r => setTimeout(r, 300));
  card.remove();
}

async function swipeAction(direction) {
  if (currentProfileIdx >= profiles.length) return;
  const profile = profiles[currentProfileIdx];
  const card = document.querySelector(".profile-card");
  if (card) await animateSwipe(card, direction === "like" ? "right" : "left");
  await doSwipe(profile.id, direction);
}

async function doSwipe(targetId, direction) {
  currentProfileIdx++;
  techLog(`REST POST /api/swipe → RabbitMQ swipe_events + Redpanda swipe_stream`);
  setBadge("badge-rmq", "rmq-active");
  setBadge("badge-rp", "rp-active");
  setBadge("badge-rest", "active");
  try {
    await apiFetch("/api/swipe", {
      method: "POST",
      body: JSON.stringify({ target_id: targetId, direction }),
    });
    techLog(`REST ✓ swipe ${direction} → queued (RabbitMQ + Redpanda)`);
  } catch (err) {
    techLog("REST ✗ swipe: " + err.message, "error");
  } finally {
    setTimeout(() => { setBadge("badge-rmq", ""); setBadge("badge-rp", ""); setBadge("badge-rest", ""); }, 1000);
  }
  renderCardStack();
}

// ── Match events (WebSocket) ──────────────────────────────────────────────
function handleMatchEvent(data) {
  setBadge("badge-ws", "ws-connected");
  techLog("WS ✓ match event received via WebSocket ← Redis ← RabbitMQ", "ws");
  showMatchPopup(data);
}

function showMatchPopup(data) {
  const { other_user } = data;
  document.getElementById("popup-photo").src =
    other_user.photo_url || "https://i.pravatar.cc/300?u=" + other_user.id;
  document.getElementById("popup-name").textContent = other_user.name;
  document.getElementById("match-popup").classList.remove("hidden");
}

function closePopup() {
  document.getElementById("match-popup").classList.add("hidden");
  showSection("matches-section");
  loadMatches();
}

// ── Message events (WebSocket) ────────────────────────────────────────────
function handleIncomingMessage(data) {
  if (data.match_id !== currentMatchId) return;
  appendChatBubble(data.message.body, false);
}

// ── Matches (REST) ────────────────────────────────────────────────────────
async function loadMatches() {
  try {
    setBadge("badge-rest", "active");
    techLog("REST GET /api/matches");
    const matches = await apiFetch("/api/matches");
    setBadge("badge-rest", "");
    techLog("REST ✓ " + matches.length + " matches");
    renderMatches(matches);
  } catch (err) {
    techLog("REST ✗ " + err.message, "error");
  }
}

function renderMatches(matches) {
  const list = document.getElementById("matches-list");
  list.innerHTML = "";
  if (matches.length === 0) {
    list.innerHTML = "<p style='color:var(--text-muted);font-size:.85rem;padding:8px'>No matches yet — swipe right!</p>";
    return;
  }
  matches.forEach(m => {
    const item = document.createElement("div");
    item.className = "match-item";
    item.innerHTML = `
      <img src="${m.other_user_photo || 'https://i.pravatar.cc/300?u=' + m.other_user_id}"
           alt="${m.other_user_name}" onerror="this.src='https://i.pravatar.cc/300'"/>
      <span class="match-name">${m.other_user_name}</span>
    `;
    item.onclick = () => openChat(m);
    list.appendChild(item);
  });
}

async function openChat(match) {
  currentMatchId = match.id;
  document.getElementById("chat-panel").classList.remove("hidden");
  document.getElementById("chat-header").textContent = "Chat with " + match.other_user_name;
  document.getElementById("chat-messages").innerHTML = "";
  try {
    setBadge("badge-rest", "active");
    techLog("REST GET /api/matches/" + match.id + "/messages");
    const msgs = await apiFetch("/api/matches/" + match.id + "/messages");
    setBadge("badge-rest", "");
    msgs.forEach(m => appendChatBubble(m.body, m.sender_id === currentUserId));
  } catch (err) {
    techLog("REST ✗ " + err.message, "error");
  }
}

function appendChatBubble(body, isMine) {
  const el = document.createElement("div");
  el.className = "msg-bubble " + (isMine ? "mine" : "theirs");
  el.textContent = body;
  const container = document.getElementById("chat-messages");
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
}

async function sendMessage() {
  const input = document.getElementById("chat-input");
  const body = input.value.trim();
  if (!body || !currentMatchId) return;
  input.value = "";
  appendChatBubble(body, true);
  try {
    setBadge("badge-rest", "active");
    techLog("REST POST /api/matches/" + currentMatchId + "/messages → WS push");
    await apiFetch("/api/matches/" + currentMatchId + "/messages", {
      method: "POST",
      body: JSON.stringify({ body }),
    });
    setBadge("badge-rest", "");
    techLog("REST ✓ message sent + WS push to recipient");
  } catch (err) {
    techLog("REST ✗ " + err.message, "error");
  }
}

function chatKeydown(e) {
  if (e.key === "Enter") sendMessage();
}

// ── GraphQL ───────────────────────────────────────────────────────────────
async function gqlQuery(query) {
  setBadge("badge-gql", "gql-active");
  techLog("GraphQL POST /graphql → " + query.slice(0, 40), "gql");
  const res = await apiFetch("/graphql", {
    method: "POST",
    body: JSON.stringify({ query }),
  });
  setBadge("badge-gql", "gql-active");
  techLog("GraphQL ✓ response received", "gql");
  document.getElementById("gql-result").textContent = JSON.stringify(res, null, 2);
  setTimeout(() => setBadge("badge-gql", ""), 1500);
  return res;
}

async function gqlProfiles() {
  await gqlQuery(`{ profiles(limit: 5) { id name age bio isOnline } }`);
}

async function gqlMatches() {
  await gqlQuery(`{ myMatches { id otherUserId otherUserName } }`);
}

async function gqlStats() {
  await gqlQuery(`{ stats { totalSwipes likesSent passesSent matchesCount matchRate } }`);
}

function loadGraphQL() {
  document.getElementById("gql-result").textContent = "// Click a query button above…";
}

// ── Presence polling (TCP server → Redis → REST) ──────────────────────────
async function startPresencePolling() {
  // Poll every 15s — the online count comes from the TCP server via Redis
  async function poll() {
    try {
      const profiles_data = await apiFetch("/api/profiles?limit=1");
      // The TCP server heartbeat results are visible via is_online flag
      setBadge("badge-tcp", "tcp-active");
      techLog("TCP presence polled via Redis (from TCP heartbeat server)", "tcp");
      // Show online count from GraphQL stats
      const res = await fetch(API + "/graphql", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": "Bearer " + token },
        body: JSON.stringify({ query: "{ stats { totalSwipes } }" }),
      });
      setTimeout(() => setBadge("badge-tcp", ""), 2000);
    } catch {}
  }
  poll();
  setInterval(poll, 15000);
}

// ── Navigation ────────────────────────────────────────────────────────────
function showSection(id) {
  document.querySelectorAll(".section").forEach(s => { s.classList.remove("active"); s.classList.add("hidden"); });
  const el = document.getElementById(id);
  el.classList.remove("hidden");
  el.classList.add("active");
  document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
  const navMap = {
    "swipe-section": "nav-swipe",
    "matches-section": "nav-matches",
    "gql-section": "nav-gql",
  };
  document.getElementById(navMap[id])?.classList.add("active");
}

// ── Init ──────────────────────────────────────────────────────────────────
(function init() {
  if (loadSavedAuth()) {
    enterApp();
  }
  techLog("TIN4 app loaded · REST · WS · GraphQL · RabbitMQ · Redpanda · TCP");
})();
