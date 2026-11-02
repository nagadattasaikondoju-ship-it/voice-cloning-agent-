/**
 * Voice Studio: vanilla JS client for the Rust API.
 * Voices tab: sample -> spoken consent (Whisper-verified) -> name -> clone job.
 * Speak tab:  voice + script -> speech job -> private MP3 (fetched with the JWT).
 */
const API = ((window.APP_CONFIG && window.APP_CONFIG.apiBaseUrl) || "http://localhost:8080").replace(/\/$/, "");
const MAX_BYTES = 20 * 1024 * 1024;
const MIN_SECONDS = 6;
const MAX_SECONDS = 300;
const MAX_CHARS = 5000;

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const state = {
  token: localStorage.getItem("auth_token"),
  user: null,
  engineReady: false,
  sample: null, // { blob, name, seconds }
  consent: null, // server consent record
  consentBlob: null,
  voices: [],
  history: [],
  audioUrls: new Map(), // audio id -> blob URL
  timers: {},
};

/* ---------------- API ---------------- */
class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function api(path, { method = "GET", json, form, raw = false } = {}) {
  const headers = state.token ? { Authorization: `Bearer ${state.token}` } : {};
  let body = form;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  }
  let res;
  try {
    res = await fetch(API + path, { method, headers, body });
  } catch {
    throw new ApiError(`Cannot reach the server at ${API}. Is it running?`, 0);
  }
  if (res.status === 401 && !path.startsWith("/api/auth/")) {
    signOut(false);
    throw new ApiError("Your session expired. Please sign in again.", 401);
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new ApiError(data.message || `Request failed (${res.status})`, res.status);
  }
  if (raw) return res;
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

/* ---------------- helpers ---------------- */
function toast(message, type = "info") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  $("toasts").appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    setTimeout(() => el.remove(), 250);
  }, type === "error" ? 6000 : 3500);
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/** Disable a button and show `html` while `fn` runs. */
async function busy(btn, html, fn) {
  const idle = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> ${html}`;
  try {
    return await fn((text) => (btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> ${text}`));
  } finally {
    btn.disabled = false;
    btn.innerHTML = idle;
  }
}

function extFor(mime = "") {
  if (mime.includes("webm")) return "webm";
  if (mime.includes("ogg")) return "ogg";
  if (mime.includes("mp4") || mime.includes("m4a") || mime.includes("aac")) return "m4a";
  if (mime.includes("mpeg") || mime.includes("mp3")) return "mp3";
  return "wav";
}

/* ---------------- auth ---------------- */
let registering = false;

function showAuth() {
  $("auth-modal").hidden = false;
  $("auth-email").focus();
}

function setAuthMode(register) {
  registering = register;
  $("auth-title").textContent = register ? "Create account" : "Sign in";
  $("btn-auth").textContent = register ? "Create account" : "Sign in";
  $("btn-auth-switch").textContent = register ? "Have an account? Sign in" : "No account? Create one";
  $("auth-password").autocomplete = register ? "new-password" : "current-password";
}

async function signIn(token, user) {
  state.token = token;
  state.user = user;
  localStorage.setItem("auth_token", token);
  $("auth-modal").hidden = true;
  $("user-email").textContent = user.email;
  await Promise.all([loadVoices(), loadHistory()]);
}

function signOut(reload = true) {
  state.token = null;
  state.user = null;
  localStorage.removeItem("auth_token");
  if (reload) location.reload();
  else showAuth();
}

/* ---------------- engine status ---------------- */
async function loadEngine() {
  let e;
  try {
    e = await api("/api/engine");
  } catch (err) {
    e = { status: "offline", problem: err.message };
  }
  state.engineReady = e.status === "ready";
  const device = e.device === "cuda" ? "GPU" : e.device === "cpu" ? "CPU" : "";
  const label = { ready: `Ready${device ? " · " + device : ""}`, loading: "Loading model…", error: "Engine error", offline: "Engine offline" };
  $("engine-pill").className = `engine-pill ${e.status}`;
  $("engine-text").textContent = label[e.status] || e.status;
  $("engine-alert").hidden = state.engineReady || e.status === "loading" || !e.problem;
  $("engine-alert").textContent = e.problem || "";
  clearTimeout(state.timers.engine);
  state.timers.engine = setTimeout(loadEngine, state.engineReady ? 30000 : 5000);
}

/* ---------------- recorder ---------------- */
/** Mic recorder with a level meter. Calls onDone(blob, seconds) with the recorder's real MIME type. */
function recorder(btn, meter, onDone) {
  let rec = null;
  btn.addEventListener("click", async () => {
    if (rec && rec.state === "recording") return rec.stop();
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      return toast("Microphone access was denied or is unavailable.", "error");
    }
    const chunks = [];
    const ctx = new AudioContext();
    const analyser = ctx.createAnalyser();
    ctx.createMediaStreamSource(stream).connect(analyser);
    const data = new Uint8Array(analyser.frequencyBinCount);
    let frame;
    const draw = () => {
      analyser.getByteFrequencyData(data);
      meter.style.width = `${Math.min(100, (data.reduce((a, b) => a + b, 0) / data.length / 128) * 100)}%`;
      frame = requestAnimationFrame(draw);
    };
    const started = Date.now();
    const tick = setInterval(() => {
      const s = Math.floor((Date.now() - started) / 1000);
      btn.querySelector(".timer").textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
    }, 250);

    rec = new MediaRecorder(stream);
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    rec.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      cancelAnimationFrame(frame);
      clearInterval(tick);
      ctx.close();
      meter.style.width = "0";
      btn.classList.remove("recording");
      btn.querySelector(".label").textContent = "Record again";
      onDone(new Blob(chunks, { type: rec.mimeType || "audio/webm" }), (Date.now() - started) / 1000);
    };
    rec.start(200);
    draw();
    btn.classList.add("recording");
    btn.querySelector(".label").textContent = "Stop";
  });
}

/* ---------------- create a voice ---------------- */
function goStep(n) {
  document.querySelectorAll(".step").forEach((el) => el.classList.toggle("active", el.id === `step-${n}`));
  document.querySelectorAll(".steps li").forEach((li) => {
    const s = Number(li.dataset.step);
    li.className = s < n ? "done" : s === n ? "active" : "";
  });
  if (n === 2 && !state.consent) newPhrase();
  if (n === 3) $("voice-name").focus();
}

function setSample(blob, name, seconds) {
  const okLength = seconds >= MIN_SECONDS && seconds <= MAX_SECONDS;
  state.sample = okLength && blob.size <= MAX_BYTES ? { blob, name, seconds } : null;
  $("sample-audio").src = URL.createObjectURL(blob);
  $("sample-preview").hidden = false;
  $("sample-info").textContent = `${seconds.toFixed(1)} s · ${(blob.size / 1048576).toFixed(2)} MB`;
  $("btn-step-1").disabled = !state.sample;
  if (!okLength) toast(`Use ${MIN_SECONDS} s to 5 min of speech (this is ${seconds.toFixed(1)} s).`, "error");
  else if (blob.size > MAX_BYTES) toast("Audio must be under 20 MB.", "error");
}

function loadSampleFile(file) {
  const probe = new Audio();
  probe.preload = "metadata";
  probe.onloadedmetadata = () => setSample(file, file.name, isFinite(probe.duration) ? probe.duration : 0);
  probe.onerror = () => toast("That file could not be read as audio.", "error");
  probe.src = URL.createObjectURL(file);
}

async function newPhrase() {
  $("consent-phrase").textContent = "Loading…";
  state.consentBlob = null;
  $("consent-preview").hidden = true;
  $("consent-result").hidden = true;
  updateVerifyButton();
  try {
    state.consent = await api("/api/consents", { method: "POST", json: {} });
    $("consent-phrase").textContent = state.consent.spoken_phrase;
  } catch (err) {
    state.consent = null;
    $("consent-phrase").textContent = "Could not load a phrase.";
    toast(err.message, "error");
  }
}

function updateVerifyButton() {
  $("btn-step-2").disabled = !(state.consent && state.consentBlob && $("consent-check").checked);
}

function showResult(ok, html) {
  const el = $("consent-result");
  el.className = `result ${ok ? "ok" : "bad"}`;
  el.innerHTML = html;
  el.hidden = false;
}

async function verifyConsent() {
  if (state.consent.verified) return goStep(3);
  await busy($("btn-step-2"), "Checking…", async () => {
    try {
      const form = new FormData();
      form.append("audio", state.consentBlob, `consent.${extFor(state.consentBlob.type)}`);
      const r = await api(`/api/consents/${state.consent.id}/verify`, { method: "POST", form });
      state.consent = r.consent;
      const heard = `<em>Heard: "${esc(r.transcript || "no speech detected")}"</em>`;
      if (r.verified) {
        showResult(true, `<strong>Verified</strong> (${Math.round(r.match_score * 100)}% match)${heard}`);
        setTimeout(() => goStep(3), 600);
      } else {
        showResult(false, `<strong>Didn't match</strong> (${Math.round(r.match_score * 100)}%). Read the phrase exactly and try again. ${r.attempts_remaining} attempt(s) left.${heard}`);
        state.consentBlob = null;
        if (r.attempts_remaining <= 0) await newPhrase();
      }
    } catch (err) {
      showResult(false, esc(err.message));
      if (err.status === 429) await newPhrase();
    }
  });
  updateVerifyButton();
}

async function createVoice(e) {
  e.preventDefault();
  await busy($("btn-create"), "Uploading…", async (say) => {
    try {
      const form = new FormData();
      form.append("audio", state.sample.blob, state.sample.name);
      form.append("duration", state.sample.seconds.toFixed(2));
      const sample = await api("/api/voice-samples", { method: "POST", form });
      say("Creating…");
      const voice = await api("/api/voice-clones", {
        method: "POST",
        json: { consent_id: state.consent.id, sample_id: sample.id, display_name: $("voice-name").value.trim() },
      });
      toast(`"${voice.display_name}" is being prepared.`, "success");
      resetCreate();
      await loadVoices();
    } catch (err) {
      toast(err.message, "error");
    }
  });
}

function resetCreate() {
  Object.assign(state, { sample: null, consent: null, consentBlob: null });
  $("sample-preview").hidden = true;
  $("consent-preview").hidden = true;
  $("consent-result").hidden = true;
  $("consent-check").checked = false;
  $("voice-name").value = "";
  $("btn-step-1").disabled = true;
  document.querySelectorAll(".btn-record .label").forEach((l, i) => (l.textContent = i ? "Record phrase" : "Record"));
  document.querySelectorAll(".btn-record .timer").forEach((t) => (t.textContent = "00:00"));
  goStep(1);
}

/* ---------------- voices ---------------- */
async function loadVoices() {
  try {
    state.voices = await api("/api/voice-clones");
  } catch (err) {
    return toast(err.message, "error");
  }
  renderVoices();
  clearTimeout(state.timers.voices);
  if (state.voices.some((v) => v.status === "queued" || v.status === "processing")) {
    state.timers.voices = setTimeout(loadVoices, 2000);
  }
}

function renderVoices() {
  const ready = state.voices.filter((v) => v.status === "ready");
  const select = $("voice-select");
  const keep = select.value;
  select.innerHTML = ready.length
    ? ready.map((v) => `<option value="${v.id}">${esc(v.display_name)}</option>`).join("")
    : `<option value="">No ready voices yet. Create one in Voices.</option>`;
  if (ready.some((v) => v.id === keep)) select.value = keep;

  $("voice-list").innerHTML = state.voices.length
    ? state.voices
        .map(
          (v) => `
      <li class="item">
        <div class="item-main">
          <div class="item-title">${esc(v.display_name)}</div>
          <div class="item-sub">${new Date(v.created_at).toLocaleString()}</div>
          ${v.error_message ? `<div class="item-error">${esc(v.error_message)}</div>` : ""}
        </div>
        <span class="badge ${esc(v.status)}">${esc(v.status)}</span>
        <button class="icon-btn" data-use="${v.id}" title="Use this voice" aria-label="Use this voice" ${v.status === "ready" ? "" : "disabled"}><i class="fa-solid fa-play"></i></button>
        <button class="icon-btn" data-delete-voice="${v.id}" title="Delete" aria-label="Delete voice"><i class="fa-solid fa-trash"></i></button>
      </li>`
        )
        .join("")
    : `<li class="empty">No voices yet.</li>`;
}

async function deleteVoice(id) {
  const v = state.voices.find((x) => x.id === id);
  if (!confirm(`Delete "${v ? v.display_name : "this voice"}"?`)) return;
  try {
    await api(`/api/voice-clones/${id}`, { method: "DELETE" });
    toast("Voice deleted", "success");
  } catch (err) {
    toast(err.message, "error");
  }
  loadVoices();
}

/* ---------------- speak ---------------- */
function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
}

function setScript(text) {
  $("script").value = text.slice(0, MAX_CHARS);
  $("char-count").textContent = `${$("script").value.length} / ${MAX_CHARS}`;
}

async function importScript(file) {
  const isAudio = (file.type || "").startsWith("audio/") || /\.(mp3|m4a|wav|webm|ogg)$/i.test(file.name);
  await busy($("btn-load-script"), isAudio ? "Transcribing…" : "Loading…", async () => {
    try {
      let text;
      if (isAudio) {
        if (file.size > MAX_BYTES) throw new Error("Audio must be under 20 MB.");
        const form = new FormData();
        form.append("audio", file, file.name);
        text = (await api("/api/transcribe", { method: "POST", form })).transcript;
        if (!text) throw new Error("No speech was found in that audio.");
      } else {
        text = await file.text();
        if (/\.(srt|vtt)$/i.test(file.name)) {
          text = text.split(/\r?\n/).filter((l) => l.trim() && !/^\d+$/.test(l.trim()) && !l.includes("-->") && !l.startsWith("WEBVTT")).join(" ");
        }
      }
      text = text.trim();
      if (text.length > MAX_CHARS) toast(`Only the first ${MAX_CHARS} characters were loaded.`, "info");
      setScript(text);
      toast("Script loaded", "success");
    } catch (err) {
      toast(err.message, "error");
    }
  });
}

async function generate(e) {
  e.preventDefault();
  const voiceId = $("voice-select").value;
  if (!voiceId) return toast("Create a voice first.", "error");
  await busy($("btn-generate"), "Queued…", async (say) => {
    try {
      let job = await api("/api/speech/generate", {
        method: "POST",
        json: { voice_clone_id: voiceId, text: $("script").value, speed: +$("speed").value, volume: +$("volume").value },
      });
      const started = Date.now();
      while (job.status === "queued" || job.status === "processing") {
        if (Date.now() - started > 15 * 60 * 1000) throw new Error("Timed out waiting for the audio.");
        await sleep(1500);
        job = await api(`/api/speech/jobs/${job.job_id}`);
        say(job.status === "processing" ? "Generating…" : "Queued…");
      }
      if (job.status !== "ready") throw new Error(job.error_message || "Generation failed.");
      const voice = state.voices.find((v) => v.id === voiceId);
      await play(job.audio_url.split("/").pop(), voice ? voice.display_name : "Voice");
      loadHistory();
    } catch (err) {
      toast(err.message, "error");
    }
  });
}

/** Audio is private: fetch it with the JWT and play from a blob URL. */
async function audioUrl(id) {
  if (!state.audioUrls.has(id)) {
    const res = await api(`/api/audio/${id}`, { raw: true });
    state.audioUrls.set(id, URL.createObjectURL(await res.blob()));
  }
  return state.audioUrls.get(id);
}

async function play(id, title) {
  try {
    const url = await audioUrl(id);
    $("player").hidden = false;
    $("player-title").textContent = title;
    $("player-audio").src = url;
    $("player-audio").play().catch(() => {});
    $("player-download").href = url;
    $("player-download").download = `${title.replace(/[^\w-]+/g, "_")}_${id.slice(0, 8)}.mp3`;
  } catch (err) {
    toast(err.message, "error");
  }
}

/* ---------------- history ---------------- */
async function loadHistory() {
  try {
    state.history = await api("/api/speech/history");
  } catch (err) {
    return toast(err.message, "error");
  }
  $("btn-clear-history").hidden = !state.history.length;
  $("history-list").innerHTML = state.history.length
    ? state.history
        .map(
          (h) => `
      <li class="item">
        <div class="item-main">
          <div class="item-title">${esc(h.text)}</div>
          <div class="item-sub">${esc(h.voice_name)} · ${h.duration_seconds ? Number(h.duration_seconds).toFixed(1) + " s · " : ""}${new Date(h.created_at).toLocaleString()}</div>
        </div>
        <button class="icon-btn" data-play="${h.id}" title="Play" aria-label="Play"><i class="fa-solid fa-play"></i></button>
        <button class="icon-btn" data-delete-audio="${h.id}" title="Delete" aria-label="Delete audio"><i class="fa-solid fa-trash"></i></button>
      </li>`
        )
        .join("")
    : `<li class="empty">Nothing generated yet.</li>`;
}

async function deleteAudio(id) {
  await api(`/api/speech/audio/${id}`, { method: "DELETE" });
  if (state.audioUrls.has(id)) URL.revokeObjectURL(state.audioUrls.get(id));
  state.audioUrls.delete(id);
}

/* ---------------- wiring ---------------- */
document.addEventListener("DOMContentLoaded", async () => {
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));
  $("btn-logout").addEventListener("click", async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => {});
    signOut();
  });

  // auth
  $("btn-auth-switch").addEventListener("click", () => setAuthMode(!registering));
  $("auth-form").addEventListener("submit", (e) => {
    e.preventDefault();
    busy($("btn-auth"), registering ? "Creating…" : "Signing in…", async () => {
      try {
        const r = await api(`/api/auth/${registering ? "register" : "login"}`, {
          method: "POST",
          json: { email: $("auth-email").value.trim(), password: $("auth-password").value },
        });
        await signIn(r.token, r.user);
      } catch (err) {
        toast(err.message, "error");
      }
    });
  });

  // create a voice
  recorder($("btn-record-sample"), $("sample-meter"), (blob, s) => setSample(blob, `sample.${extFor(blob.type)}`, s));
  $("sample-file").addEventListener("change", (e) => {
    if (e.target.files[0]) loadSampleFile(e.target.files[0]);
    e.target.value = "";
  });
  $("btn-step-1").addEventListener("click", () => goStep(2));
  recorder($("btn-record-consent"), $("consent-meter"), (blob) => {
    state.consentBlob = blob;
    $("consent-audio").src = URL.createObjectURL(blob);
    $("consent-preview").hidden = false;
    $("consent-result").hidden = true;
    updateVerifyButton();
  });
  $("btn-new-phrase").addEventListener("click", newPhrase);
  $("consent-check").addEventListener("change", updateVerifyButton);
  $("btn-step-2").addEventListener("click", verifyConsent);
  document.querySelectorAll("[data-back]").forEach((b) => b.addEventListener("click", () => goStep(Number(b.dataset.back))));
  $("step-3").addEventListener("submit", createVoice);

  // lists (event delegation)
  $("btn-refresh-voices").addEventListener("click", loadVoices);
  $("voice-list").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.use) {
      switchTab("speak");
      $("voice-select").value = b.dataset.use;
      $("script").focus();
    } else if (b.dataset.deleteVoice) deleteVoice(b.dataset.deleteVoice);
  });
  $("history-list").addEventListener("click", async (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.play) {
      const h = state.history.find((x) => x.id === b.dataset.play);
      play(h.id, h.voice_name);
    } else if (b.dataset.deleteAudio) {
      try {
        await deleteAudio(b.dataset.deleteAudio);
      } catch (err) {
        toast(err.message, "error");
      }
      loadHistory();
    }
  });
  $("btn-clear-history").addEventListener("click", async () => {
    if (!confirm("Delete all generated audio?")) return;
    await Promise.allSettled(state.history.map((h) => deleteAudio(h.id)));
    $("player").hidden = true;
    loadHistory();
  });

  // speak
  $("script").addEventListener("input", () => ($("char-count").textContent = `${$("script").value.length} / ${MAX_CHARS}`));
  $("btn-load-script").addEventListener("click", () => $("script-file").click());
  $("script-file").addEventListener("change", (e) => {
    if (e.target.files[0]) importScript(e.target.files[0]);
    e.target.value = "";
  });
  $("speed").addEventListener("input", (e) => ($("speed-out").textContent = `${(+e.target.value).toFixed(1)}×`));
  $("volume").addEventListener("input", (e) => ($("volume-out").textContent = (+e.target.value).toFixed(1)));
  $("speak-form").addEventListener("submit", generate);

  // start
  loadEngine();
  if (!state.token) return showAuth();
  try {
    await signIn(state.token, await api("/api/auth/me"));
  } catch (err) {
    if (err.status !== 401) toast(err.message, "error");
    showAuth();
  }
});
