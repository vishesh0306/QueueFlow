const API_BASE = "";

const state = {
  token: sessionStorage.getItem("qf_token"),
  role: sessionStorage.getItem("qf_role"),
  clinicId: sessionStorage.getItem("qf_clinic_id"),
};

let ws = null;

// ---- Security -------------------------------------------------------------

// patient_contact (and, less critically, display_number) come straight from
// patient-controlled input -- a patient could join with a value like
// "<img src=x onerror=...>" and have it execute in an authenticated staff
// session the moment the queue renders. Route every such value through this
// before interpolating it into an innerHTML template string.
function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value ?? "";
  return div.innerHTML;
}

// ---- API helper -----------------------------------------------------------

async function apiFetch(path, options = {}) {
  const headers = options.headers || {};
  if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
  if (options.body) headers["Content-Type"] = "application/json";

  const response = await fetch(API_BASE + path, { ...options, headers });
  if (response.status === 204) return null;

  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const message = body && body.error ? body.error.message : `Request failed (${response.status})`;
    throw new Error(message);
  }
  return body;
}

// ---- Auth -------------------------------------------------------------

function isPrivilegedRole() {
  return state.role === "doctor" || state.role === "admin";
}

function showLogin() {
  document.getElementById("login-screen").classList.remove("hidden");
  document.getElementById("dashboard-screen").classList.add("hidden");
  if (ws) { ws.close(); ws = null; }
}

function showDashboard() {
  document.getElementById("login-screen").classList.add("hidden");
  document.getElementById("dashboard-screen").classList.remove("hidden");
  document.getElementById("clinic-role").textContent = `Signed in as ${state.role}`;
  document.getElementById("clinic-id-display").textContent = state.clinicId;
  document.getElementById("override-card").classList.toggle("hidden", !isPrivilegedRole());
  document.getElementById("pause-resume-btn").classList.toggle("hidden", !isPrivilegedRole());
  connectWebSocket();
  refreshQueue();
}

function patientLinkForThisClinic() {
  return `${window.location.origin}/patient-app/?clinic=${state.clinicId}`;
}

async function login(contact, password) {
  const body = await apiFetch("/staff/login", {
    method: "POST",
    body: JSON.stringify({ contact, password }),
  });
  state.token = body.access_token;
  state.role = body.role;
  state.clinicId = body.clinic_id;
  sessionStorage.setItem("qf_token", state.token);
  sessionStorage.setItem("qf_role", state.role);
  sessionStorage.setItem("qf_clinic_id", state.clinicId);
}

function logout() {
  sessionStorage.clear();
  state.token = null;
  state.role = null;
  state.clinicId = null;
  showLogin();
}

// ---- Live updates -------------------------------------------------------

function connectWebSocket() {
  if (ws) ws.close();
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${protocol}//${window.location.host}/ws/queue/${state.clinicId}`);
  ws.onmessage = () => refreshQueue();
  ws.onclose = () => {
    // Reconnect after a short delay if we're still logged in.
    if (state.token) setTimeout(connectWebSocket, 3000);
  };
}

// ---- Rendering ------------------------------------------------------------

function showBanner(message) {
  const banner = document.getElementById("banner");
  banner.textContent = message;
  banner.classList.remove("hidden");
  setTimeout(() => banner.classList.add("hidden"), 5000);
}

function tokenRow(token, actionsHtml) {
  const div = document.createElement("div");
  div.className = "token-row";
  div.innerHTML = `
    <div class="info">
      <span class="display-number">${escapeHtml(token.display_number) || escapeHtml(token.token_id.slice(0, 8))}</span>
      <span class="meta">${escapeHtml(token.tier)}${token.emergency_override ? " · EMERGENCY" : ""} · ${escapeHtml(token.patient_contact)}</span>
    </div>
    <div class="btn-group">${actionsHtml}</div>
  `;
  return div;
}

function renderCalled(tokens) {
  const container = document.getElementById("called-list");
  const callNextBtn = document.getElementById("call-next-btn");
  container.innerHTML = "";

  // v1 assumes one doctor: only one patient can be called at a time, so "Call next"
  // stays disabled until the current one is resolved (served/no-show) -- the server
  // enforces this too, this just avoids surprising the user with an error banner.
  callNextBtn.disabled = tokens.length > 0;
  callNextBtn.title = tokens.length > 0 ? "Resolve the currently called patient first" : "";

  if (tokens.length === 0) {
    container.innerHTML = '<p class="empty-state">No one is currently called.</p>';
    return;
  }
  for (const token of tokens) {
    const row = tokenRow(token, `
      <button data-action="mark-served" data-id="${token.token_id}">Served</button>
      <button data-action="mark-paid" data-id="${token.token_id}" class="secondary">Paid</button>
      <button data-action="no-show" data-id="${token.token_id}" class="danger">No-show</button>
    `);
    container.appendChild(row);
  }
}

function renderWaiting(tokens) {
  // The server already returns this list in true predicted call order (what
  // call-next would actually do next), not raw join order -- the index here is
  // literally "how many more calls until this patient," so it's shown as-is.
  const body = document.getElementById("waiting-body");
  body.innerHTML = "";
  if (tokens.length === 0) {
    body.innerHTML = '<tr><td colspan="6" class="empty-state">Queue is empty.</td></tr>';
    return;
  }
  tokens.forEach((token, index) => {
    const tr = document.createElement("tr");
    const joined = new Date(token.joined_at).toLocaleTimeString();
    const canUpgrade = token.tier === "standard" && !token.emergency_override;
    tr.innerHTML = `
      <td>${index + 1}</td>
      <td>${escapeHtml(token.display_number) || "-"}</td>
      <td>${escapeHtml(token.tier)}${token.emergency_override ? " (EMERGENCY)" : ""}</td>
      <td>${escapeHtml(token.patient_contact)}</td>
      <td>${joined}</td>
      <td>${canUpgrade ? `<button data-action="change-tier" data-id="${token.token_id}" class="secondary">Make priority</button>` : ""}</td>
    `;
    body.appendChild(tr);
  });
}

function renderSessionStatus(status) {
  const badge = document.getElementById("session-status");
  badge.textContent = status;
  badge.classList.toggle("paused", status === "paused");

  const pauseBtn = document.getElementById("pause-resume-btn");
  pauseBtn.textContent = status === "paused" ? "Resume queue" : "Pause queue";
  pauseBtn.dataset.action = status === "paused" ? "resume" : "pause";
}

async function refreshQueue() {
  try {
    const data = await apiFetch("/staff/queue");
    renderSessionStatus(data.session_status);
    renderCalled(data.called);
    renderWaiting(data.waiting);
  } catch (err) {
    if (err.message.includes("Invalid or expired token")) {
      logout();
    } else {
      showBanner(err.message);
    }
  }
}

// ---- Actions ------------------------------------------------------------

async function callNext() {
  try {
    await apiFetch("/staff/queue/call-next", { method: "POST" });
    refreshQueue();
  } catch (err) {
    showBanner(err.message);
  }
}

async function handleTokenAction(action, tokenId) {
  try {
    if (action === "no-show") {
      await apiFetch(`/staff/queue/tokens/${tokenId}/no-show`, { method: "POST" });
    } else if (action === "mark-served") {
      await apiFetch(`/staff/queue/tokens/${tokenId}/mark-served`, { method: "POST" });
    } else if (action === "mark-paid") {
      const amount = prompt("Fee amount in paise (e.g. 20000 = ₹200):", "0");
      if (amount === null) return;
      await apiFetch(`/staff/queue/tokens/${tokenId}/mark-paid`, {
        method: "POST",
        body: JSON.stringify({ fee_amount_paise: parseInt(amount, 10) || 0 }),
      });
    } else if (action === "change-tier") {
      await apiFetch(`/staff/queue/tokens/${tokenId}/change-tier`, {
        method: "POST",
        body: JSON.stringify({ tier: "priority" }),
      });
    }
    refreshQueue();
  } catch (err) {
    showBanner(err.message);
  }
}

async function togglePauseResume(action) {
  try {
    await apiFetch(`/staff/queue/${action}`, { method: "POST" });
    refreshQueue();
  } catch (err) {
    showBanner(err.message);
  }
}

// ---- Wiring ---------------------------------------------------------------

document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById("login-error");
  errorEl.textContent = "";
  try {
    await login(
      document.getElementById("login-contact").value,
      document.getElementById("login-password").value,
    );
    showDashboard();
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

document.getElementById("logout-btn").addEventListener("click", logout);
document.getElementById("call-next-btn").addEventListener("click", callNext);

document.getElementById("copy-patient-link-btn").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(patientLinkForThisClinic());
  } catch {
    prompt("Copy this link:", patientLinkForThisClinic());
    return;
  }
  const confirmEl = document.getElementById("copy-confirm");
  confirmEl.classList.remove("hidden");
  setTimeout(() => confirmEl.classList.add("hidden"), 2000);
});

document.getElementById("pause-resume-btn").addEventListener("click", (e) => {
  togglePauseResume(e.target.dataset.action);
});

document.getElementById("called-list").addEventListener("click", (e) => {
  const action = e.target.dataset.action;
  const id = e.target.dataset.id;
  if (action && id) handleTokenAction(action, id);
});

document.getElementById("waiting-body").addEventListener("click", (e) => {
  const action = e.target.dataset.action;
  const id = e.target.dataset.id;
  if (action && id) handleTokenAction(action, id);
});

document.getElementById("walkin-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await apiFetch("/staff/queue/walk-in", {
      method: "POST",
      body: JSON.stringify({
        patient_contact: {
          type: document.getElementById("walkin-contact-type").value,
          value: document.getElementById("walkin-contact-value").value,
        },
        patient_email: document.getElementById("walkin-email").value || null,
        tier: document.getElementById("walkin-tier").value,
      }),
    });
    e.target.reset();
    refreshQueue();
  } catch (err) {
    showBanner(err.message);
  }
});

document.getElementById("override-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await apiFetch("/staff/queue/emergency-override", {
      method: "POST",
      body: JSON.stringify({
        patient_contact: {
          type: document.getElementById("override-contact-type").value,
          value: document.getElementById("override-contact-value").value,
        },
      }),
    });
    e.target.reset();
    refreshQueue();
  } catch (err) {
    showBanner(err.message);
  }
});

// ---- Boot -------------------------------------------------------------

if (state.token) {
  showDashboard();
} else {
  showLogin();
}
