/**
 * Intelligence Designed To Evolve - Voice Studio Dashboard
 * Vanilla JavaScript client for the Rust API (backend-rust).
 *
 * Flow: sign in -> record/upload sample -> server-issued consent phrase -> record phrase
 * -> Whisper verification on the server -> create clone (queued for the Python worker)
 * -> generate speech (queued) -> poll -> play private MP3 via authenticated fetch.
 */

const API_BASE_URL = ((window.APP_CONFIG && window.APP_CONFIG.apiBaseUrl) || "http://localhost:8080").replace(/\/$/, "");
const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;
const MIN_SAMPLE_SECONDS = 6;
const MAX_SAMPLE_SECONDS = 300;

const STATE = {
  token: localStorage.getItem("auth_token"),
  user: null,
  engine: null,
  currentStep: 1,
  sampleBlob: null,
  sampleFileName: null,
  sampleDuration: 0,
  consent: null, // { id, spoken_phrase, verified, ... }
  consentBlob: null,
  clonedVoices: [],
  speechHistory: [],
  blobUrls: new Map(), // audio id -> object URL
  voicePollTimer: null,
};

/* ==========================================================================
   API client
   ========================================================================== */
class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function api(path, { method = "GET", json, form, raw = false } = {}) {
  const headers = {};
  if (STATE.token) headers.Authorization = `Bearer ${STATE.token}`;
  let body;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  } else if (form) {
    body = form;
  }

  let res;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, { method, headers, body });
  } catch {
    throw new ApiError(`Cannot reach the API at ${API_BASE_URL}. Is the backend running?`, 0);
  }

  if (res.status === 401 && !path.startsWith("/api/auth/login") && !path.startsWith("/api/auth/register")) {
    clearSession();
    showAuthModal();
    throw new ApiError("Your session has expired. Please sign in again.", 401);
  }
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      if (data && data.message) message = data.message;
    } catch {}
    throw new ApiError(message, res.status);
  }
  if (raw) return res;
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

/* ==========================================================================
   Initialization
   ========================================================================== */
document.addEventListener("DOMContentLoaded", async () => {
  initAuthUI();
  initTabs();
  initVoiceStudio();
  initTTSStudio();
  initSettings();

  loadEngine();
  loadHealth();

  if (!STATE.token) {
    showAuthModal();
    return;
  }
  try {
    const user = await api("/api/auth/me");
    onSignedIn(STATE.token, user);
  } catch (err) {
    if (err.status !== 401) showToast(err.message, "error");
    showAuthModal();
  }
});

/* ==========================================================================
   Toasts & helpers
   ========================================================================== */
function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  const icon = type === "success" ? "fa-circle-check" : type === "error" ? "fa-circle-exclamation" : "fa-circle-info";
  toast.innerHTML = `<i class="fa-solid ${icon}"></i> <span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(10px)";
    setTimeout(() => toast.remove(), 250);
  }, type === "error" ? 6000 : 4000);
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function setButtonBusy(btn, busy, busyHtml) {
  if (busy) {
    btn.dataset.idleHtml = btn.dataset.idleHtml || btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = busyHtml;
  } else {
    btn.disabled = false;
    if (btn.dataset.idleHtml) btn.innerHTML = btn.dataset.idleHtml;
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function extensionForMime(mime) {
  const m = (mime || "").toLowerCase();
  if (m.includes("webm")) return "webm";
  if (m.includes("ogg")) return "ogg";
  if (m.includes("mp4") || m.includes("m4a") || m.includes("aac")) return "m4a";
  if (m.includes("mpeg") || m.includes("mp3")) return "mp3";
  return "wav";
}

/* ==========================================================================
   Tabs
   ========================================================================== */
function switchTab(tabId) {
  document.querySelectorAll(".nav-tab-btn, .mobile-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tabId);
  });
  document.querySelectorAll(".tab-pane").forEach((pane) => {
    pane.classList.toggle("active", pane.id === `tab-${tabId}`);
  });
  if (STATE.user && (tabId === "speech-studio" || tabId === "overview")) {
    fetchClonedVoices();
    fetchSpeechHistory();
  }
}
window.switchTab = switchTab;

function initTabs() {
  document.querySelectorAll(".nav-tab-btn, .mobile-tab").forEach((btn) => {
    btn.addEventListener("click", () => btn.dataset.tab && switchTab(btn.dataset.tab));
  });
}

/* ==========================================================================
   Authentication
   ========================================================================== */
function showAuthModal() {
  document.getElementById("auth-modal").hidden = false;
}

function clearSession() {
  STATE.token = null;
  STATE.user = null;
  localStorage.removeItem("auth_token");
}

function initAuthUI() {
  const tabLogin = document.getElementById("tab-auth-login");
  const tabRegister = document.getElementById("tab-auth-register");
  const formLogin = document.getElementById("form-auth-login");
  const formRegister = document.getElementById("form-auth-register");

  const showForm = (login) => {
    tabLogin.classList.toggle("active", login);
    tabRegister.classList.toggle("active", !login);
    formLogin.classList.toggle("active", login);
    formRegister.classList.toggle("active", !login);
  };
  tabLogin.addEventListener("click", () => showForm(true));
  tabRegister.addEventListener("click", () => showForm(false));

  document.getElementById("btn-logout-header").addEventListener("click", async () => {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } catch {}
    clearSession();
    location.reload();
  });

  formLogin.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("btn-submit-login");
    setButtonBusy(btn, true, '<i class="fa-solid fa-spinner fa-spin"></i> Signing in...');
    try {
      const data = await api("/api/auth/login", {
        method: "POST",
        json: {
          email: document.getElementById("login-email").value.trim(),
          password: document.getElementById("login-password").value,
        },
      });
      onSignedIn(data.token, data.user);
      showToast("Welcome back!", "success");
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setButtonBusy(btn, false);
    }
  });

  formRegister.addEventListener("submit", async (e) => {
    e.preventDefault();
    const password = document.getElementById("register-password").value;
    if (password !== document.getElementById("register-confirm").value) {
      showToast("Passwords do not match.", "error");
      return;
    }
    const btn = document.getElementById("btn-submit-register");
    setButtonBusy(btn, true, '<i class="fa-solid fa-spinner fa-spin"></i> Creating account...');
    try {
      const data = await api("/api/auth/register", {
        method: "POST",
        json: { email: document.getElementById("register-email").value.trim(), password },
      });
      onSignedIn(data.token, data.user);
      showToast("Account created.", "success");
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setButtonBusy(btn, false);
    }
  });
}

function onSignedIn(token, user) {
  STATE.token = token;
  STATE.user = user;
  localStorage.setItem("auth_token", token);
  document.getElementById("auth-modal").hidden = true;

  document.getElementById("header-user-email").textContent = user.email;
  document.getElementById("user-avatar-initial").textContent = (user.email[0] || "U").toUpperCase();
  document.getElementById("settings-user-email").textContent = user.email;
  document.getElementById("settings-user-id").textContent = user.id;

  fetchClonedVoices();
  fetchSpeechHistory();
  fetchConsents();
}

/* ==========================================================================
   Engines & health
   ========================================================================== */
/** Engine status from the worker heartbeat; polled while the model is loading. */
async function loadEngine() {
  let e;
  try {
    e = await api("/api/engine");
  } catch (err) {
    e = { ok: false, status: "offline", problem: err.message };
  }
  STATE.engine = e;
  const label = e.model_label ? `Chatterbox · ${e.model_label}` : "Chatterbox";
  const where = e.device ? (e.device === "cuda" ? "GPU" : "CPU") : "";
  const statusText = { ready: "Ready", loading: "Loading model…", error: "Error", offline: "Offline" }[e.status] || e.status;

  document.getElementById("engine-banner-badge").textContent = `${label} · ${statusText}${where ? " on " + where : ""}`;
  document.getElementById("engine-banner-desc").textContent = e.ok
    ? "Every clone requires a spoken consent phrase that is transcribed by Whisper and matched on the server."
    : e.problem || "The voice engine is not ready.";
  document.getElementById("metric-model-name").textContent = e.ok ? where || "Ready" : statusText;
  document.getElementById("summary-engine-name").textContent = label;
  document.getElementById("engine-status-list").innerHTML = `
    <div class="engine-status-item">
      <div><strong>${escapeHtml(label)}</strong>
        <p>Device: ${escapeHtml(where || "—")} · English</p>
        ${e.problem ? `<p class="engine-problem"><i class="fa-solid fa-triangle-exclamation"></i> ${escapeHtml(e.problem)}</p>` : ""}
      </div>
      <span class="status-badge ${e.ok ? "ready" : e.status === "loading" ? "processing" : "failed"}">${escapeHtml(statusText)}</span>
    </div>`;

  if (e.status === "loading") setTimeout(loadEngine, 5000);
}

async function loadHealth() {
  const list = document.getElementById("system-status-list");
  const row = (label, ok, okText = "Connected", badText = "Unavailable") =>
    `<li><span>${label}</span><strong class="${ok ? "text-success" : "text-danger"}">
       <i class="fa-solid ${ok ? "fa-circle-check" : "fa-circle-xmark"}"></i> ${ok ? okText : badText}</strong></li>`;
  try {
    const h = await api("/api/health");
    list.innerHTML =
      row("Rust API (Axum)", true, "Online") +
      row("PostgreSQL", h.database) +
      row("Redis job queue", h.redis) +
      row("Whisper speech pipeline", h.speech_pipeline, "Online", "Offline (consent checks will fail)") +
      row("Voice worker", h.worker === "ready", "Ready", h.worker === "loading" ? "Loading model…" : "Not running (jobs will not run)");
  } catch {
    list.innerHTML = row("Rust API (Axum)", false, "Online", `Offline (${API_BASE_URL})`);
  }
}

/* ==========================================================================
   Voices
   ========================================================================== */
async function fetchClonedVoices() {
  if (!STATE.user) return;
  try {
    STATE.clonedVoices = await api("/api/voice-clones");
  } catch (err) {
    showToast(err.message, "error");
  }
  renderClonedVoices();
  scheduleVoicePolling();
}

function scheduleVoicePolling() {
  clearTimeout(STATE.voicePollTimer);
  const pending = STATE.clonedVoices.some((v) => v.status === "queued" || v.status === "processing");
  if (pending) STATE.voicePollTimer = setTimeout(fetchClonedVoices, 3000);
}

function renderClonedVoices() {
  const container = document.getElementById("cloned-voices-list");
  const select = document.getElementById("tts-voice-select");
  const previous = select.value;
  document.getElementById("metric-voice-count").textContent = STATE.clonedVoices.length;

  select.innerHTML = '<option value="" disabled selected>-- Choose one of your cloned voices --</option>';
  STATE.clonedVoices
    .filter((v) => v.status === "ready")
    .forEach((v) => {
      const opt = document.createElement("option");
      opt.value = v.id;
      opt.textContent = v.display_name;
      select.appendChild(opt);
    });
  if (previous && [...select.options].some((o) => o.value === previous)) select.value = previous;

  if (STATE.clonedVoices.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <i class="fa-solid fa-microphone-slash fa-2x"></i>
        <p>No cloned voices yet. Complete the steps above to clone your voice.</p>
      </div>`;
    return;
  }

  container.innerHTML = "";
  STATE.clonedVoices.forEach((voice) => {
    const card = document.createElement("div");
    card.className = "voice-card";
    const isReady = voice.status === "ready";
    card.innerHTML = `
      <div class="voice-card-top">
        <div>
          <h4 class="voice-name">${escapeHtml(voice.display_name)}</h4>
          <span class="voice-id-tag">${escapeHtml(voice.voice_id)}</span>
          ${voice.error_message ? `<div class="voice-error"><i class="fa-solid fa-triangle-exclamation"></i> ${escapeHtml(voice.error_message)}</div>` : ""}
        </div>
        <span class="status-badge ${escapeHtml(voice.status)}">${escapeHtml(voice.status)}</span>
      </div>
      <div class="voice-card-actions">
        <button class="pill-btn pill-btn-ghost btn-test-voice" ${isReady ? "" : "disabled"}>
          <i class="fa-solid fa-play"></i> Use Voice
        </button>
        <button class="pill-btn pill-btn-danger btn-delete-voice" title="Delete voice">
          <i class="fa-solid fa-trash-can"></i>
        </button>
      </div>`;

    card.querySelector(".btn-test-voice").addEventListener("click", () => {
      switchTab("speech-studio");
      select.value = voice.id;
          const input = document.getElementById("tts-text-input");
      if (!input.value.trim()) {
        input.value = `Hello! This is a preview of my cloned voice, ${voice.display_name}.`;
        document.getElementById("tts-char-counter").textContent = `${input.value.length} / 5000`;
      }
    });
    card.querySelector(".btn-delete-voice").addEventListener("click", async () => {
      if (confirm(`Delete voice "${voice.display_name}"?`)) {
        await deleteClonedVoice(voice.id);
      }
    });
    container.appendChild(card);
  });
}

async function deleteClonedVoice(id, quiet = false) {
  try {
    await api(`/api/voice-clones/${id}`, { method: "DELETE" });
    if (!quiet) showToast("Voice deleted", "success");
  } catch (err) {
    showToast(err.message, "error");
  }
  await fetchClonedVoices();
}

async function fetchConsents() {
  try {
    const consents = await api("/api/consents");
    const verified = consents.filter((c) => c.verified).length;
    document.getElementById("metric-consent-status").textContent = String(verified);
    document.getElementById("settings-consent-status").textContent = verified
      ? `${verified} verified spoken consent${verified > 1 ? "s" : ""}`
      : "No verified consent yet";
  } catch {}
}

/* ==========================================================================
   Voice Studio (3 steps)
   ========================================================================== */
function initVoiceStudio() {
  document.getElementById("btn-next-step-1").addEventListener("click", () => goToStudioStep(2));
  document.getElementById("btn-back-step-2").addEventListener("click", () => goToStudioStep(1));
  document.getElementById("btn-next-step-2").addEventListener("click", verifyConsent);
  document.getElementById("btn-back-step-3").addEventListener("click", () => goToStudioStep(2));
  document.getElementById("btn-regenerate-phrase").addEventListener("click", () => issueConsentPhrase(true));
  document.getElementById("btn-next-step-1").disabled = true;

  setupMediaRecorder({
    btnId: "btn-record-sample",
    labelId: "record-sample-label",
    timerId: "sample-timer",
    meterId: "sample-level-meter",
    previewWrapId: "sample-record-preview-wrap",
    audioId: "sample-record-audio",
    metaId: "sample-record-meta",
    onComplete: (blob, duration) => {
      setSample(blob, `sample.${extensionForMime(blob.type)}`, duration);
      document.getElementById("sample-upload-preview-wrap").hidden = true;
    },
  });

  const dropZone = document.getElementById("sample-drop-zone");
  const fileInput = document.getElementById("sample-file-input");
  dropZone.addEventListener("click", () => fileInput.click());
  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    if (e.dataTransfer.files && e.dataTransfer.files[0]) handleAudioFileUpload(e.dataTransfer.files[0]);
  });
  fileInput.addEventListener("change", (e) => {
    if (e.target.files && e.target.files[0]) handleAudioFileUpload(e.target.files[0]);
  });

  setupMediaRecorder({
    btnId: "btn-record-consent",
    labelId: "record-consent-label",
    timerId: "consent-timer",
    meterId: "consent-level-meter",
    previewWrapId: "consent-audio-preview-wrap",
    audioId: "consent-audio-playback",
    metaId: "consent-audio-meta",
    onComplete: (blob) => {
      STATE.consentBlob = blob;
      hideConsentResult();
      validateStep2();
    },
  });
  document.getElementById("consent-checkbox").addEventListener("change", validateStep2);
  document.getElementById("form-clone-voice").addEventListener("submit", handleVoiceCloneSubmit);
}

function setSample(blob, fileName, duration) {
  STATE.sampleBlob = blob;
  STATE.sampleFileName = fileName;
  STATE.sampleDuration = duration;
  const ok = duration >= MIN_SAMPLE_SECONDS && duration <= MAX_SAMPLE_SECONDS && blob.size <= MAX_UPLOAD_BYTES;
  document.getElementById("btn-next-step-1").disabled = !ok;
  if (!ok) {
    showToast(`Samples must be ${MIN_SAMPLE_SECONDS}s–5min and under 20 MB (got ${duration.toFixed(1)}s).`, "error");
    return;
  }
  const size = blob.size > 1024 * 1024 ? `${(blob.size / 1048576).toFixed(1)} MB` : `${Math.round(blob.size / 1024)} KB`;
  document.getElementById("summary-sample-name").textContent = `${duration.toFixed(1)}s · ${size}`;
  showToast("Voice sample ready", "success");
}

function handleAudioFileUpload(file) {
  if (file.size > MAX_UPLOAD_BYTES) {
    showToast("Audio exceeds the 20 MB size limit.", "error");
    return;
  }
  const url = URL.createObjectURL(file);
  document.getElementById("sample-upload-filename").textContent = file.name;
  document.getElementById("sample-upload-filesize").textContent = `${(file.size / 1048576).toFixed(2)} MB`;
  document.getElementById("sample-upload-audio").src = url;
  document.getElementById("sample-upload-preview-wrap").hidden = false;
  document.getElementById("sample-record-preview-wrap").hidden = true;

  const probe = new Audio();
  probe.preload = "metadata";
  probe.addEventListener("loadedmetadata", () => {
    const d = isFinite(probe.duration) ? probe.duration : 0;
    document.getElementById("sample-upload-filesize").textContent = `${(file.size / 1048576).toFixed(2)} MB • ${Math.round(d)}s`;
    setSample(file, file.name, d);
  });
  probe.addEventListener("error", () => showToast("This file could not be decoded as audio.", "error"));
  probe.src = url;
}

function goToStudioStep(step) {
  STATE.currentStep = step;
  if (step === 2) {
    if (!STATE.consent || STATE.consent.attempts_exhausted) issueConsentPhrase(false);
    validateStep2();
  }
  if (step === 3) {
    const nameInput = document.getElementById("clone-display-name");
    if (!nameInput.value) nameInput.value = "My Voice";
  }
  for (let i = 1; i <= 3; i++) {
    const node = document.getElementById(`step-node-${i}`);
    const line = document.getElementById(`step-line-${i}`);
    node.className = i < step ? "step-node completed" : i === step ? "step-node active" : "step-node";
    if (line) line.className = i < step ? "step-line active" : "step-line";
    document.getElementById(`studio-step-${i}`).classList.toggle("active", i === step);
  }
}

async function issueConsentPhrase(userRequested) {
  if (!STATE.user) return;
  const display = document.getElementById("consent-phrase-display");
  display.textContent = "Requesting a verification phrase…";
  try {
    STATE.consent = await api("/api/consents", { method: "POST", json: { consent_version: "v1.0" } });
    STATE.consentBlob = null;
    display.textContent = `"${STATE.consent.spoken_phrase}"`;
    document.getElementById("consent-audio-preview-wrap").hidden = true;
    document.getElementById("summary-consent-status").textContent = "Not verified";
    hideConsentResult();
    validateStep2();
    if (userRequested) showToast("New phrase issued. Record it again.", "info");
  } catch (err) {
    display.textContent = "Could not get a verification phrase.";
    showToast(err.message, "error");
  }
}

function validateStep2() {
  const ready = !!(STATE.consent && STATE.consentBlob && document.getElementById("consent-checkbox").checked);
  document.getElementById("btn-next-step-2").disabled = !ready;
}

function hideConsentResult() {
  document.getElementById("consent-verify-result").hidden = true;
}

function showConsentResult(ok, html) {
  const el = document.getElementById("consent-verify-result");
  el.className = `consent-verify-result ${ok ? "success" : "error"}`;
  el.innerHTML = html;
  el.hidden = false;
}

async function verifyConsent() {
  if (!STATE.consent || !STATE.consentBlob) return;
  if (STATE.consent.verified) return goToStudioStep(3);

  const btn = document.getElementById("btn-next-step-2");
  setButtonBusy(btn, true, '<i class="fa-solid fa-spinner fa-spin"></i> Transcribing with Whisper…');
  try {
    const form = new FormData();
    form.append("audio", STATE.consentBlob, `consent.${extensionForMime(STATE.consentBlob.type)}`);
    const result = await api(`/api/consents/${STATE.consent.id}/verify`, { method: "POST", form });
    STATE.consent = result.consent;
    const pct = Math.round(result.match_score * 100);
    const transcript = `<span class="transcript">Heard: "${escapeHtml(result.transcript || "(no speech detected)")}"</span>`;
    if (result.verified) {
      showConsentResult(true, `<strong><i class="fa-solid fa-shield-halved"></i> Consent verified</strong> — ${pct}% match.${transcript}`);
      document.getElementById("summary-consent-status").textContent = `Verified (${pct}% match)`;
      fetchConsents();
      showToast("Spoken consent verified", "success");
      setTimeout(() => goToStudioStep(3), 700);
    } else {
      const need = Math.round(result.threshold * 100);
      showConsentResult(
        false,
        `<strong>Not verified</strong> — ${pct}% match, ${need}% required. ${result.attempts_remaining} attempt(s) left for this phrase.${transcript}`
      );
      STATE.consentBlob = null;
      STATE.consent.attempts_exhausted = result.attempts_remaining <= 0;
      if (STATE.consent.attempts_exhausted) await issueConsentPhrase(false);
    }
  } catch (err) {
    showConsentResult(false, escapeHtml(err.message));
    if (err.status === 429) await issueConsentPhrase(false);
  } finally {
    setButtonBusy(btn, false);
    validateStep2();
  }
}

async function handleVoiceCloneSubmit(e) {
  e.preventDefault();
  if (!STATE.consent || !STATE.consent.verified) {
    showToast("Verify your spoken consent first.", "error");
    return goToStudioStep(2);
  }
  if (!STATE.sampleBlob) {
    showToast("Add a voice sample first.", "error");
    return goToStudioStep(1);
  }
  const btn = document.getElementById("btn-submit-clone");
  setButtonBusy(btn, true, '<i class="fa-solid fa-spinner fa-spin"></i> Uploading sample…');
  try {
    const form = new FormData();
    form.append("audio", STATE.sampleBlob, STATE.sampleFileName || "sample.wav");
    form.append("duration", STATE.sampleDuration.toFixed(2));
    const sample = await api("/api/voice-samples", { method: "POST", form });

    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Queuing clone job…';
    const clone = await api("/api/voice-clones", {
      method: "POST",
      json: {
        consent_id: STATE.consent.id,
        sample_id: sample.id,
        display_name: document.getElementById("clone-display-name").value.trim(),
      },
    });
    showToast(`"${clone.display_name}" queued. Status updates appear below.`, "success");
    resetStudio();
    await fetchClonedVoices();
    document.getElementById("cloned-voices-list").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    setButtonBusy(btn, false);
  }
}

function resetStudio() {
  STATE.sampleBlob = null;
  STATE.sampleDuration = 0;
  STATE.consentBlob = null;
  STATE.consent = null;
  document.getElementById("consent-checkbox").checked = false;
  document.getElementById("clone-display-name").value = "";
  ["sample-record-preview-wrap", "sample-upload-preview-wrap", "consent-audio-preview-wrap"].forEach(
    (id) => (document.getElementById(id).hidden = true)
  );
  document.getElementById("btn-next-step-1").disabled = true;
  hideConsentResult();
  goToStudioStep(1);
}

/** Microphone recorder with a level meter. Reports the recorder's real MIME type. */
function setupMediaRecorder({ btnId, labelId, timerId, meterId, previewWrapId, audioId, metaId, onComplete }) {
  const btn = document.getElementById(btnId);
  const label = document.getElementById(labelId);
  const timer = document.getElementById(timerId);
  const meter = document.getElementById(meterId);
  let recorder = null;
  let chunks = [];
  let startTime = 0;
  let timerInterval = null;
  let animFrame = null;
  let audioCtx = null;

  btn.addEventListener("click", async () => {
    if (recorder && recorder.state === "recording") {
      recorder.stop();
      return;
    }
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      showToast("Microphone access was denied or is unavailable.", "error");
      return;
    }
    chunks = [];
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    audioCtx.createMediaStreamSource(stream).connect(analyser);
    const data = new Uint8Array(analyser.frequencyBinCount);
    const draw = () => {
      analyser.getByteFrequencyData(data);
      const avg = data.reduce((a, b) => a + b, 0) / data.length;
      if (meter) meter.style.width = `${Math.min((avg / 128) * 100, 100)}%`;
      animFrame = requestAnimationFrame(draw);
    };
    draw();

    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (e) => e.data.size > 0 && chunks.push(e.data);
    recorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      cancelAnimationFrame(animFrame);
      clearInterval(timerInterval);
      if (audioCtx) audioCtx.close();
      if (meter) meter.style.width = "0%";
      btn.classList.remove("recording");
      label.textContent = "Record Again";

      const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      const duration = (Date.now() - startTime) / 1000;
      document.getElementById(audioId).src = URL.createObjectURL(blob);
      document.getElementById(previewWrapId).hidden = false;
      document.getElementById(metaId).textContent = `Recorded: ${duration.toFixed(1)}s`;
      onComplete(blob, duration);
    };
    recorder.start(200);
    startTime = Date.now();
    btn.classList.add("recording");
    label.textContent = "Stop Recording";
    timerInterval = setInterval(() => {
      const s = Math.floor((Date.now() - startTime) / 1000);
      timer.textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
    }, 500);
  });
}

/* ==========================================================================
   Text to Speech
   ========================================================================== */
function initTTSStudio() {
  const textInput = document.getElementById("tts-text-input");
  textInput.addEventListener("input", () => {
    document.getElementById("tts-char-counter").textContent = `${textInput.value.length} / 5000`;
  });
  document.getElementById("slider-speed").addEventListener("input", (e) => {
    document.getElementById("val-speed").textContent = `${parseFloat(e.target.value).toFixed(1)}x`;
  });
  document.getElementById("slider-volume").addEventListener("input", (e) => {
    document.getElementById("val-volume").textContent = parseFloat(e.target.value).toFixed(1);
  });
  const scriptInput = document.getElementById("script-file-input");
  document.getElementById("btn-import-script").addEventListener("click", () => scriptInput.click());
  scriptInput.addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = "";
    if (file) importScript(file);
  });
  document.getElementById("form-generate-speech").addEventListener("submit", handleTTSGenerate);

  const audio = document.getElementById("tts-audio-element");
  const disc = document.getElementById("audio-disc-visual");
  audio.addEventListener("play", () => disc.classList.add("playing"));
  audio.addEventListener("pause", () => disc.classList.remove("playing"));
  audio.addEventListener("ended", () => disc.classList.remove("playing"));

  document.getElementById("btn-refresh-history").addEventListener("click", fetchSpeechHistory);
  document.getElementById("btn-refresh-voices").addEventListener("click", fetchClonedVoices);
}

/** Fill the script box from a text/subtitle file, or from audio via Whisper. */
async function importScript(file) {
  const input = document.getElementById("tts-text-input");
  const hint = document.getElementById("script-import-hint");
  const btn = document.getElementById("btn-import-script");
  const isAudio = (file.type || "").startsWith("audio/") || /\.(mp3|m4a|wav|webm|ogg)$/i.test(file.name);
  let text;
  try {
    if (isAudio) {
      if (file.size > MAX_UPLOAD_BYTES) throw new Error("Audio exceeds the 20 MB limit.");
      setButtonBusy(btn, true, '<i class="fa-solid fa-spinner fa-spin"></i> Transcribing…');
      const form = new FormData();
      form.append("audio", file, file.name);
      text = (await api("/api/transcribe", { method: "POST", form })).transcript;
      if (!text) throw new Error("No speech was detected in that audio.");
    } else {
      text = await file.text();
      if (/\.(srt|vtt)$/i.test(file.name)) {
        text = text
          .split(/\r?\n/)
          .filter((l) => l.trim() && !/^\d+$/.test(l.trim()) && !/-->/.test(l) && !/^WEBVTT/.test(l))
          .join(" ");
      }
    }
    text = text.replace(/\s+\n/g, "\n").trim();
    if (text.length > 5000) {
      showToast(`Script is ${text.length} characters; only the first 5000 were loaded.`, "info");
      text = text.slice(0, 5000);
    }
    input.value = text;
    document.getElementById("tts-char-counter").textContent = `${text.length} / 5000`;
    hint.textContent = `Loaded from ${file.name}. Edit it before generating if needed.`;
    showToast("Script loaded", "success");
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    setButtonBusy(btn, false);
  }
}

async function handleTTSGenerate(e) {
  e.preventDefault();
  const voiceId = document.getElementById("tts-voice-select").value;
  const text = document.getElementById("tts-text-input").value.trim();
  if (!voiceId) return showToast("Choose a ready voice first.", "error");
  if (!text) return showToast("Enter some text to speak.", "error");

  const btn = document.getElementById("btn-generate-speech");
  const badge = document.getElementById("player-status-badge");
  setButtonBusy(btn, true, '<i class="fa-solid fa-spinner fa-spin"></i> Queued…');
  badge.textContent = "Queued";
  try {
    const job = await api("/api/speech/generate", {
      method: "POST",
      json: {
        voice_clone_id: voiceId,
        text,
        speed: parseFloat(document.getElementById("slider-speed").value),
        volume: parseFloat(document.getElementById("slider-volume").value),
      },
    });

    const started = Date.now();
    let status = job;
    while (status.status === "queued" || status.status === "processing") {
      if (Date.now() - started > 10 * 60 * 1000) throw new Error("Timed out waiting for the speech job.");
      await sleep(2000);
      status = await api(`/api/speech/jobs/${job.job_id}`);
      badge.textContent = status.status === "processing" ? "Synthesizing" : "Queued";
      btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> ${badge.textContent}…`;
    }
    if (status.status !== "ready" || !status.audio_url) {
      throw new Error(status.error_message || "Speech generation failed.");
    }
    const voice = STATE.clonedVoices.find((v) => v.id === voiceId);
    await playAudio(status.audio_url.split("/").pop(), voice ? voice.display_name : "Voice", text);
    badge.textContent = "Ready";
    showToast("Speech generated", "success");
    fetchSpeechHistory();
  } catch (err) {
    badge.textContent = "Failed";
    showToast(err.message, "error");
  } finally {
    setButtonBusy(btn, false);
  }
}

/** Audio is private: fetch with the JWT, then play from a blob URL. */
async function getAudioUrl(audioId) {
  if (STATE.blobUrls.has(audioId)) return STATE.blobUrls.get(audioId);
  const res = await api(`/api/audio/${audioId}`, { raw: true });
  const url = URL.createObjectURL(await res.blob());
  STATE.blobUrls.set(audioId, url);
  return url;
}

async function playAudio(audioId, voiceName, text) {
  try {
    const url = await getAudioUrl(audioId);
    const audio = document.getElementById("tts-audio-element");
    audio.src = url;
    audio.play().catch(() => {});
    document.getElementById("player-title").textContent = `Voice: ${voiceName}`;
    document.getElementById("player-subtitle").textContent = `"${text.length > 60 ? text.slice(0, 60) + "…" : text}" · AI-generated`;
    const dl = document.getElementById("btn-download-mp3");
    dl.href = url;
    dl.download = `ai_generated_${audioId}.mp3`;
    dl.style.display = "inline-flex";
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function downloadAudio(audioId) {
  try {
    const a = document.createElement("a");
    a.href = await getAudioUrl(audioId);
    a.download = `ai_generated_${audioId}.mp3`;
    a.click();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function fetchSpeechHistory() {
  if (!STATE.user) return;
  try {
    STATE.speechHistory = await api("/api/speech/history");
  } catch (err) {
    showToast(err.message, "error");
  }
  renderSpeechHistory();
}

function renderSpeechHistory() {
  const container = document.getElementById("speech-history-list");
  const overview = document.getElementById("overview-recent-list");
  document.getElementById("metric-audio-count").textContent = STATE.speechHistory.length;

  if (STATE.speechHistory.length === 0) {
    const empty = `<div class="empty-state"><i class="fa-solid fa-file-audio fa-2x"></i><p>No audio generated yet.</p></div>`;
    container.innerHTML = empty;
    overview.innerHTML = empty;
    return;
  }
  container.innerHTML = "";
  overview.innerHTML = "";

  const build = (item, withDelete) => {
    const el = document.createElement("div");
    el.className = "history-item";
    el.innerHTML = `
      <div class="history-details">
        <div class="history-text">"${escapeHtml(item.text)}"</div>
        <div class="history-meta">
          <span><i class="fa-solid fa-microphone"></i> ${escapeHtml(item.voice_name)}</span>
          <span><i class="fa-regular fa-clock"></i> ${new Date(item.created_at).toLocaleString()}</span>
          ${item.duration_seconds ? `<span>${Number(item.duration_seconds).toFixed(1)}s</span>` : ""}
        </div>
      </div>
      <div class="history-actions">
        <button class="btn-refresh btn-play" title="Play"><i class="fa-solid fa-play"></i></button>
        <button class="btn-refresh btn-download" title="Download MP3"><i class="fa-solid fa-download"></i></button>
        ${withDelete ? '<button class="btn-refresh btn-delete" title="Delete"><i class="fa-solid fa-trash"></i></button>' : ""}
      </div>`;
    el.querySelector(".btn-play").addEventListener("click", () => {
      switchTab("speech-studio");
      playAudio(item.id, item.voice_name, item.text);
    });
    el.querySelector(".btn-download").addEventListener("click", () => downloadAudio(item.id));
    if (withDelete) el.querySelector(".btn-delete").addEventListener("click", () => deleteHistoryAudio(item.id));
    return el;
  };

  STATE.speechHistory.forEach((item) => container.appendChild(build(item, true)));
  STATE.speechHistory.slice(0, 3).forEach((item) => overview.appendChild(build(item, false)));
}

async function deleteHistoryAudio(id, quiet = false) {
  try {
    await api(`/api/speech/audio/${id}`, { method: "DELETE" });
    if (STATE.blobUrls.has(id)) {
      URL.revokeObjectURL(STATE.blobUrls.get(id));
      STATE.blobUrls.delete(id);
    }
    if (!quiet) showToast("Audio deleted", "success");
  } catch (err) {
    showToast(err.message, "error");
  }
  if (!quiet) fetchSpeechHistory();
}

/* ==========================================================================
   Settings
   ========================================================================== */
function initSettings() {
  document.getElementById("btn-delete-all-voices").addEventListener("click", async () => {
    if (!STATE.clonedVoices.length) return showToast("No voices to delete.", "info");
    if (!confirm("Permanently delete ALL your cloned voices?")) return;
    for (const v of [...STATE.clonedVoices]) await deleteClonedVoice(v.id, true);
    showToast("All cloned voices deleted", "success");
  });

  document.getElementById("btn-delete-all-audio").addEventListener("click", async () => {
    if (!STATE.speechHistory.length) return showToast("No audio to delete.", "info");
    if (!confirm("Permanently delete ALL generated audio files?")) return;
    for (const item of [...STATE.speechHistory]) await deleteHistoryAudio(item.id, true);
    await fetchSpeechHistory();
    showToast("All generated audio deleted", "success");
  });
}
