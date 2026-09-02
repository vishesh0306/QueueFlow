const API_BASE = "";
const SESSION_KEY = "qf_patient_session"; // {clinicId, tokenId} -- one active visit at a time (v1: no patient identity beyond a visit)

let ws = null;

function urlClinicId() {
  return new URLSearchParams(window.location.search).get("clinic");
}

function loadSession() {
  try {
    return JSON.parse(localStorage.getItem(SESSION_KEY));
  } catch {
    return null;
  }
}

function saveSession(clinicId, tokenId) {
  localStorage.setItem(SESSION_KEY, JSON.stringify({ clinicId, tokenId }));
}

function clearSession() {
  localStorage.removeItem(SESSION_KEY);
  if (ws) { ws.close(); ws = null; }
}

async function apiFetch(path, options = {}) {
  const headers = options.headers || {};
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

// ---- Screens ---------------------------------------------------------

function showJoinScreen() {
  document.getElementById("join-screen").classList.remove("hidden");
  document.getElementById("status-screen").classList.add("hidden");

  const clinicId = urlClinicId();
  const clinicInput = document.getElementById("clinic-id-input");
  const clinicMissing = document.getElementById("clinic-missing");
  if (!clinicId) {
    clinicInput.classList.remove("hidden");
    clinicMissing.classList.remove("hidden");
  }
}

function showStatusScreen() {
  document.getElementById("join-screen").classList.add("hidden");
  document.getElementById("status-screen").classList.remove("hidden");
}

function formatEta(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const minutes = Math.round(seconds / 60);
  return minutes <= 0 ? "< 1 min" : `${minutes} min`;
}

function renderStatus(data) {
  document.getElementById("display-number").textContent = data.display_number || "—";
  document.getElementById("status-line").textContent = data.status;

  const calledBanner = document.getElementById("called-banner");
  const pausedBanner = document.getElementById("paused-banner");
  const positionBlock = document.getElementById("position-block");

  if (data.status === "called") {
    calledBanner.classList.remove("hidden");
    positionBlock.classList.add("hidden");
  } else {
    calledBanner.classList.add("hidden");
    positionBlock.classList.remove("hidden");
    document.getElementById("position-value").textContent = data.position !== null ? data.position - 1 : "—";
    document.getElementById("eta-value").textContent = formatEta(data.estimated_wait_seconds);
  }

  // Only meaningful while still waiting -- once called, the queue being paused
  // elsewhere doesn't change that this patient's turn has already arrived.
  const isPaused = data.session_status === "paused" && data.status === "waiting";
  pausedBanner.classList.toggle("hidden", !isPaused);

  if (data.status === "served" || data.status === "cancelled") {
    clearSession();
    showJoinScreen();
  }
}

// ---- Live updates -------------------------------------------------------

function connectWebSocket(clinicId, tokenId) {
  if (ws) ws.close();
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${protocol}//${window.location.host}/ws/queue/${clinicId}?token_id=${tokenId}`);
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.your_token_id === tokenId) renderStatus(data);
  };
  ws.onclose = () => {
    const session = loadSession();
    if (session) setTimeout(() => connectWebSocket(session.clinicId, session.tokenId), 3000);
  };
}

// ---- Boot / resume an existing visit ---------------------------------

async function resumeExistingSession() {
  const session = loadSession();
  if (!session) return false;

  try {
    const data = await apiFetch(`/queue/tokens/${session.tokenId}/status`);
    if (data.status === "waiting" || data.status === "called") {
      showStatusScreen();
      renderStatus({ ...data, your_token_id: session.tokenId });
      connectWebSocket(session.clinicId, session.tokenId);
      return true;
    }
  } catch {
    // token gone / not found -- fall through to a fresh join
  }
  clearSession();
  return false;
}

// ---- Join ---------------------------------------------------------------

document.getElementById("join-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById("join-error");
  errorEl.textContent = "";

  const clinicId = urlClinicId() || document.getElementById("clinic-id-input").value.trim();
  if (!clinicId) {
    errorEl.textContent = "A clinic ID is required.";
    return;
  }

  const tier = document.querySelector('input[name="tier"]:checked').value;
  const contactType = document.getElementById("contact-type").value;
  const contactValue = document.getElementById("contact-value").value.trim();
  const fallbackEmail = document.getElementById("fallback-email").value.trim();

  try {
    const data = await apiFetch(`/clinics/${clinicId}/queue/join`, {
      method: "POST",
      body: JSON.stringify({
        patient_contact: { type: contactType, value: contactValue },
        patient_email: fallbackEmail || null,
        tier,
      }),
    });
    saveSession(clinicId, data.token_id);
    showStatusScreen();
    renderStatus({ ...data, your_token_id: data.token_id, status: "waiting" });
    connectWebSocket(clinicId, data.token_id);
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

// ---- Cancel -------------------------------------------------------------

document.getElementById("cancel-btn").addEventListener("click", async () => {
  const session = loadSession();
  if (!session) return;
  if (!confirm("Cancel your spot in the queue?")) return;

  try {
    await apiFetch(`/queue/tokens/${session.tokenId}`, { method: "DELETE" });
  } catch {
    // even if the request fails (e.g. already served), still drop the local session
  }
  clearSession();
  showJoinScreen();
});

// ---- Boot -------------------------------------------------------------

resumeExistingSession().then((resumed) => {
  if (!resumed) showJoinScreen();
});
