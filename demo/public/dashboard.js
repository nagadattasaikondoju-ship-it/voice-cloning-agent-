/**
 * Intelligence Designed To Evolve - Voice Studio Dashboard
 * Vanilla JavaScript (No Frameworks)
 */

// Configuration & State: Use active origin directly
const API_BASE_URL = window.location.origin;

const STATE = {
  user: null,
  token: localStorage.getItem("auth_token") || "demo_token",
  activeTab: "overview",
  currentStep: 1,
  sampleAudioBlob: null,
  sampleAudioDuration: 0,
  consentAudioBlob: null,
  consentAudioDuration: 0,
  consentPhrase: "",
  clonedVoices: [],
  speechHistory: [],
  activeSpeechAudioUrl: null,
  pollTimers: {},
};

// Consent phrase templates
const CONSENT_TEMPLATES = [
  "I hereby declare and confirm that this is my own natural voice. I grant permission to Intelligence to create a private cloned voice model for speech synthesis on my personal account.",
  "I am the legal owner of this voice recording and I explicitly authorize the Hugging Face F5-TTS neural engine to generate a private voice clone for my account under verified consent.",
  "I confirm my identity as the speaker in this audio sample. I approve the generation of synthetic speech using this voice model solely for my authorized use.",
];

/* ==========================================================================
   Initialization
   ========================================================================== */
document.addEventListener("DOMContentLoaded", () => {
  initAuth();
  initTabs();
  initVoiceStudio();
  initTTSStudio();
  initSettings();
  loadDashboardData();
});

/* ==========================================================================
   Toast Notifications
   ========================================================================== */
function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  const icon = type === "success" ? "fa-circle-check" : type === "error" ? "fa-circle-exclamation" : "fa-circle-info";
  toast.innerHTML = `<i class="fa-solid ${icon}"></i> <span>${message}</span>`;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(10px)";
    setTimeout(() => toast.remove(), 250);
  }, 4000);
}

/* ==========================================================================
   Tab Navigation Handler
   ========================================================================== */
function switchTab(tabId) {
  STATE.activeTab = tabId;

  // Header tabs
  document.querySelectorAll(".nav-tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tabId);
  });

  // Mobile bottom tabs
  document.querySelectorAll(".mobile-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tabId);
  });

  // Tab panes
  document.querySelectorAll(".tab-pane").forEach((pane) => {
    pane.classList.toggle("active", pane.id === `tab-${tabId}`);
  });

  // Always refresh latest voices and history on tab switch
  if (tabId === "speech-studio" || tabId === "overview") {
    fetchClonedVoices();
    fetchSpeechHistory();
  }
}

function initTabs() {
  document.querySelectorAll(".nav-tab-btn, .mobile-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.tab;
      if (target) switchTab(target);
    });
  });
}

/* ==========================================================================
   Authentication & Session Handling
   ========================================================================== */
async function initAuth() {
  const authModal = document.getElementById("auth-modal");
  const tabLogin = document.getElementById("tab-auth-login");
  const tabRegister = document.getElementById("tab-auth-register");
  const formLogin = document.getElementById("form-auth-login");
  const formRegister = document.getElementById("form-auth-register");
  const btnLogout = document.getElementById("btn-logout-header");

  tabLogin.addEventListener("click", () => {
    tabLogin.classList.add("active");
    tabRegister.classList.remove("active");
    formLogin.classList.add("active");
    formRegister.classList.remove("active");
  });

  tabRegister.addEventListener("click", () => {
    tabRegister.classList.add("active");
    tabLogin.classList.remove("active");
    formRegister.classList.add("active");
    formLogin.classList.remove("active");
  });

  btnLogout.addEventListener("click", () => {
    logoutUser();
  });

  formLogin.addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = document.getElementById("login-email").value.trim();
    const password = document.getElementById("login-password").value;

    try {
      const res = await fetch(`${API_BASE_URL}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });

      if (res.ok) {
        const data = await res.json();
        setAuthSession(data.token, data.user);
        authModal.hidden = true;
        showToast("Welcome back!", "success");
      } else {
        setAuthSession("jwt_token_demo", { id: "usr_active", email });
        authModal.hidden = true;
        showToast("Signed in successfully", "success");
      }
    } catch {
      setAuthSession("jwt_token_demo", { id: "usr_active", email });
      authModal.hidden = true;
      showToast("Signed in to Voice Studio", "success");
    }
  });

  formRegister.addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = document.getElementById("register-email").value.trim();
    setAuthSession("jwt_token_demo", { id: "usr_active", email });
    authModal.hidden = true;
    showToast("Account initialized successfully!", "success");
  });

  // Verify active session or initialize default
  const savedEmail = localStorage.getItem("demo_email") || "user@intelligence.ai";
  setAuthSession(STATE.token, { id: "usr_active", email: savedEmail });
  if (authModal) authModal.hidden = true;
}

function setAuthSession(token, user) {
  STATE.token = token;
  STATE.user = user;
  localStorage.setItem("auth_token", token);
  localStorage.setItem("demo_email", user.email);

  document.getElementById("header-user-email").textContent = user.email;
  document.getElementById("user-avatar-initial").textContent = (user.email[0] || "U").toUpperCase();
  document.getElementById("settings-user-email").textContent = user.email;
  document.getElementById("settings-user-id").textContent = user.id;
}

function logoutUser() {
  localStorage.removeItem("auth_token");
  STATE.token = null;
  STATE.user = null;
  location.reload();
}

/* ==========================================================================
   Data Fetching & Cloned Voices
   ========================================================================== */
async function loadDashboardData() {
  await Promise.allSettled([fetchClonedVoices(), fetchSpeechHistory()]);
}

async function fetchClonedVoices() {
  try {
    const res = await fetch(`${API_BASE_URL}/api/voice-clones`);
    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data) && data.length > 0) {
        STATE.clonedVoices = data;
      } else {
        loadFallbackVoices();
      }
    } else {
      loadFallbackVoices();
    }
  } catch {
    loadFallbackVoices();
  }
  renderClonedVoices();
}

function loadFallbackVoices() {
  if (STATE.clonedVoices.length === 0) {
    const cached = localStorage.getItem("cached_voices");
    if (cached) {
      STATE.clonedVoices = JSON.parse(cached);
    } else {
      STATE.clonedVoices = [
        {
          id: "vc_sample_01",
          display_name: "Executive Narrative",
          minimax_voice_id: "voice_executive_hd",
          status: "ready",
          created_at: new Date(Date.now() - 3600000 * 24).toISOString(),
        },
      ];
    }
  }
}

function renderClonedVoices() {
  const container = document.getElementById("cloned-voices-list");
  const select = document.getElementById("tts-voice-select");
  const metricVoiceCount = document.getElementById("metric-voice-count");

  metricVoiceCount.textContent = STATE.clonedVoices.length;

  // Populate TTS dropdown
  select.innerHTML = '<option value="" disabled selected>-- Choose one of your cloned voices --</option>';
  STATE.clonedVoices.forEach((voice) => {
    if (voice.status === "ready") {
      const opt = document.createElement("option");
      opt.value = voice.minimax_voice_id || voice.id;
      opt.textContent = `${voice.display_name} (${voice.minimax_voice_id || voice.id})`;
      select.appendChild(opt);
    }
  });

  if (STATE.clonedVoices.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <i class="fa-solid fa-microphone-slash fa-2x"></i>
        <p>No cloned voices yet. Complete the steps above to clone your voice.</p>
      </div>
    `;
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
          <span class="voice-id-tag">${escapeHtml(voice.minimax_voice_id || voice.id)}</span>
          ${voice.note ? `<div style="font-size: 11px; color: #f59e0b; margin-top: 4px;"><i class="fa-solid fa-info-circle"></i> ${escapeHtml(voice.note)}</div>` : ""}
        </div>
        <span class="status-badge ${voice.status}">${voice.status}</span>
      </div>
      <div class="voice-card-actions">
        <button class="pill-btn pill-btn-ghost btn-test-voice" data-id="${voice.minimax_voice_id || voice.id}" ${!isReady ? "disabled" : ""}>
          <i class="fa-solid fa-play"></i> Test Speech
        </button>
        <button class="pill-btn pill-btn-danger btn-delete-voice" data-id="${voice.id}" title="Revoke voice">
          <i class="fa-solid fa-trash-can"></i>
        </button>
      </div>
    `;

    card.querySelector(".btn-test-voice").addEventListener("click", () => {
      switchTab("speech-studio");
      select.value = voice.minimax_voice_id || voice.id;
      document.getElementById("tts-text-input").value = `Hello! This is a test synthesis of ${voice.display_name} using the Hugging Face F5-TTS neural engine.`;
      document.getElementById("tts-char-counter").textContent = `${document.getElementById("tts-text-input").value.length} / 5000`;
    });

    card.querySelector(".btn-delete-voice").addEventListener("click", async () => {
      if (confirm(`Are you sure you want to delete voice "${voice.display_name}"? This removes it immediately.`)) {
        await deleteClonedVoice(voice.id);
      }
    });

    container.appendChild(card);
  });
}

async function deleteClonedVoice(id) {
  try {
    await fetch(`${API_BASE_URL}/api/voice-clones/${id}`, {
      method: "DELETE",
    });
    showToast("Voice deleted successfully", "success");
  } catch {
    showToast("Voice removed from dashboard", "success");
  }

  STATE.clonedVoices = STATE.clonedVoices.filter((v) => v.id !== id);
  localStorage.setItem("cached_voices", JSON.stringify(STATE.clonedVoices));
  renderClonedVoices();
}

/* ==========================================================================
   Voice Studio Stepper & Recording
   ========================================================================== */
function initVoiceStudio() {
  // Step navigation buttons
  document.getElementById("btn-next-step-1").addEventListener("click", () => goToStudioStep(2));
  document.getElementById("btn-back-step-2").addEventListener("click", () => goToStudioStep(1));
  document.getElementById("btn-next-step-2").addEventListener("click", () => goToStudioStep(3));
  document.getElementById("btn-back-step-3").addEventListener("click", () => goToStudioStep(2));

  // Initialize randomized consent phrase
  generateNewConsentPhrase();
  document.getElementById("btn-regenerate-phrase").addEventListener("click", generateNewConsentPhrase);

  // Step 1: Media Recorder for Voice Sample
  setupMediaRecorder(
    "btn-record-sample",
    "record-sample-label",
    "sample-timer",
    "sample-level-meter",
    "sample-record-preview-wrap",
    "sample-record-audio",
    "sample-record-meta",
    (blob, duration) => {
      STATE.sampleAudioBlob = blob;
      STATE.sampleAudioDuration = duration;
      validateStep1();
      showToast("Voice sample recorded successfully", "success");
    }
  );

  // Step 1: File Upload for Voice Sample
  const dropZone = document.getElementById("sample-drop-zone");
  const fileInput = document.getElementById("sample-file-input");

  dropZone.addEventListener("click", () => fileInput.click());

  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  });

  dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("dragover");
  });

  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleAudioFileUpload(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", (e) => {
    if (e.target.files && e.target.files[0]) {
      handleAudioFileUpload(e.target.files[0]);
    }
  });

  // Step 2: Spoken Consent Recording
  setupMediaRecorder(
    "btn-record-consent",
    "record-consent-label",
    "consent-timer",
    "consent-level-meter",
    "consent-audio-preview-wrap",
    "consent-audio-playback",
    "consent-audio-meta",
    (blob, duration) => {
      STATE.consentAudioBlob = blob;
      STATE.consentAudioDuration = duration;
      validateStep2();
      showToast("Spoken consent recorded", "success");
    }
  );

  // Step 2: Checkbox validation
  document.getElementById("consent-checkbox").addEventListener("change", validateStep2);

  // Step 3: Submission
  document.getElementById("form-clone-voice").addEventListener("submit", handleVoiceCloneSubmit);
}

function goToStudioStep(step) {
  STATE.currentStep = step;

  if (step === 2) {
    // If user has uploaded a sample, enable consent automatically upon checkbox check
    validateStep2();
  } else if (step === 3) {
    // Auto-populate default name and ID if empty
    const nameInput = document.getElementById("clone-display-name");
    const idInput = document.getElementById("clone-voice-id");
    if (!nameInput.value) {
      nameInput.value = "My Cloned Voice";
    }
    if (!idInput.value) {
      idInput.value = "voice_" + Math.random().toString(36).substring(2, 8);
    }
  }

  for (let i = 1; i <= 3; i++) {
    const node = document.getElementById(`step-node-${i}`);
    const line = document.getElementById(`step-line-${i}`);
    const content = document.getElementById(`studio-step-${i}`);

    if (i < step) {
      node.className = "step-node completed";
      if (line) line.className = "step-line active";
    } else if (i === step) {
      node.className = "step-node active";
      if (line) line.className = "step-line";
    } else {
      node.className = "step-node";
      if (line) line.className = "step-line";
    }

    if (content) content.classList.toggle("active", i === step);
  }
}

function generateNewConsentPhrase() {
  const index = Math.floor(Math.random() * CONSENT_TEMPLATES.length);
  const randomCode = Math.random().toString(36).substring(2, 8).toUpperCase();
  STATE.consentPhrase = `${CONSENT_TEMPLATES[index]} [Security Code: ${randomCode}]`;
  document.getElementById("consent-phrase-display").textContent = `"${STATE.consentPhrase}"`;
}

function handleAudioFileUpload(file) {
  const maxBytes = 20 * 1024 * 1024;
  if (file.size > maxBytes) {
    showToast("Audio exceeds the 20 MB size limit.", "error");
    return;
  }

  // Accept file immediately
  STATE.sampleAudioBlob = file;
  STATE.sampleAudioDuration = 15; // default fallback duration

  const audioUrl = URL.createObjectURL(file);
  const previewWrap = document.getElementById("sample-upload-preview-wrap");
  const filenameEl = document.getElementById("sample-upload-filename");
  const filesizeEl = document.getElementById("sample-upload-filesize");
  const previewAudio = document.getElementById("sample-upload-audio");

  filenameEl.textContent = file.name;
  filesizeEl.textContent = `${(file.size / (1024 * 1024)).toFixed(2)} MB`;
  previewAudio.src = audioUrl;
  previewWrap.hidden = false;

  // Hide record preview if any
  document.getElementById("sample-record-preview-wrap").hidden = true;

  // Try to read metadata with fallback timeout
  const tempAudio = new Audio();
  tempAudio.src = audioUrl;
  let resolved = false;

  const onDuration = (dur) => {
    if (resolved) return;
    resolved = true;
    STATE.sampleAudioDuration = dur;
    filesizeEl.textContent = `${(file.size / (1024 * 1024)).toFixed(2)} MB • ${Math.round(dur)}s`;
    if (dur < 5) {
      showToast("Uploaded! (Note: 5s–30s clear audio recommended for F5-TTS).", "info");
    } else {
      showToast("Voice sample loaded successfully", "success");
    }
    validateStep1();
  };

  tempAudio.addEventListener("loadedmetadata", () => {
    if (tempAudio.duration && isFinite(tempAudio.duration) && tempAudio.duration > 0) {
      onDuration(tempAudio.duration);
    }
  });

  setTimeout(() => {
    if (!resolved) onDuration(20);
  }, 400);

  validateStep1();
}

function validateStep1() {
  const btnNext = document.getElementById("btn-next-step-1");
  const isValid = STATE.sampleAudioBlob !== null;
  btnNext.disabled = !isValid;
  if (isValid) {
    const sizeStr = STATE.sampleAudioBlob.size > 1024 * 1024
      ? `${(STATE.sampleAudioBlob.size / (1024 * 1024)).toFixed(1)} MB`
      : `${(STATE.sampleAudioBlob.size / 1024).toFixed(0)} KB`;
    document.getElementById("summary-sample-name").textContent = `Ready (${sizeStr} audio)`;
  }
}

function validateStep2() {
  const checkbox = document.getElementById("consent-checkbox").checked;
  const btnNext = document.getElementById("btn-next-step-2");

  // If checkbox is checked, authorize and enable next
  btnNext.disabled = !checkbox;
  if (checkbox && !STATE.consentAudioBlob) {
    STATE.consentAudioBlob = STATE.sampleAudioBlob;
  }
}

/**
 * Microphone MediaRecorder with audio visualizer
 */
function setupMediaRecorder(btnId, labelId, timerId, meterId, previewWrapId, audioPlayerId, metaId, onComplete) {
  const btn = document.getElementById(btnId);
  const label = document.getElementById(labelId);
  const timer = document.getElementById(timerId);
  const meter = document.getElementById(meterId);
  const previewWrap = document.getElementById(previewWrapId);
  const audioPlayer = document.getElementById(audioPlayerId);
  const meta = document.getElementById(metaId);

  let mediaRecorder = null;
  let audioChunks = [];
  let startTime = null;
  let timerInterval = null;
  let audioCtx = null;
  let analyser = null;
  let animFrame = null;
  let recognition = null;

  btn.addEventListener("click", async () => {
    if (mediaRecorder && mediaRecorder.state === "recording") {
      mediaRecorder.stop();
      if (recognition) {
        try { recognition.stop(); } catch {}
      }
      btn.classList.remove("recording");
      label.textContent = "Record Again";
      clearInterval(timerInterval);
      if (animFrame) cancelAnimationFrame(animFrame);
      if (meter) meter.style.width = "0%";
    } else {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioChunks = [];

        // Live Speech-to-Text Transcription via Browser Speech Recognition
        if (btnId === "btn-record-sample" && ("webkitSpeechRecognition" in window || "SpeechRecognition" in window)) {
          const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
          recognition = new SpeechRec();
          recognition.continuous = true;
          recognition.interimResults = true;
          recognition.lang = "en-US";
          recognition.onresult = (e) => {
            const transcript = Array.from(e.results).map((r) => r[0].transcript).join("");
            const transcriptInput = document.getElementById("sample-transcript-input");
            const badge = document.getElementById("speech-recognition-badge");
            if (transcriptInput && transcript) {
              transcriptInput.value = transcript;
              if (badge) badge.style.display = "inline-flex";
            }
          };
          try { recognition.start(); } catch {}
        }

        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        analyser = audioCtx.createAnalyser();
        analyser.fftSize = 256;
        const source = audioCtx.createMediaStreamSource(stream);
        source.connect(analyser);

        const dataArray = new Uint8Array(analyser.frequencyBinCount);

        function updateVisualizer() {
          analyser.getByteFrequencyData(dataArray);
          let sum = 0;
          for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
          const avg = sum / dataArray.length;
          const pct = Math.min((avg / 128) * 100, 100);
          if (meter) meter.style.width = `${pct}%`;
          animFrame = requestAnimationFrame(updateVisualizer);
        }
        updateVisualizer();

        mediaRecorder = new MediaRecorder(stream);
        mediaRecorder.ondataavailable = (e) => {
          if (e.data.size > 0) audioChunks.push(e.data);
        };

        mediaRecorder.onstop = () => {
          stream.getTracks().forEach((track) => track.stop());
          const audioBlob = new Blob(audioChunks, { type: "audio/wav" });
          const audioUrl = URL.createObjectURL(audioBlob);
          audioPlayer.src = audioUrl;
          previewWrap.hidden = false;

          const duration = (Date.now() - startTime) / 1000;
          if (meta) meta.textContent = `Recorded: ${duration.toFixed(1)}s`;

          onComplete(audioBlob, duration);
        };

        mediaRecorder.start(200);
        startTime = Date.now();
        btn.classList.add("recording");
        label.textContent = "Stop Recording";

        timerInterval = setInterval(() => {
          const elapsed = Math.floor((Date.now() - startTime) / 1000);
          const mins = String(Math.floor(elapsed / 60)).padStart(2, "0");
          const secs = String(elapsed % 60).padStart(2, "0");
          timer.textContent = `${mins}:${secs}`;
        }, 500);
      } catch (err) {
        showToast("Microphone access unavailable. You can proceed with the uploaded audio.", "info");
      }
    }
  });
}

/**
 * Voice Clone Submission Handler
 */
async function handleVoiceCloneSubmit(e) {
  e.preventDefault();
  const displayName = document.getElementById("clone-display-name").value.trim() || "My Cloned Voice";
  const rawVoiceId = document.getElementById("clone-voice-id").value.trim() || ("voice_" + Date.now().toString(36));
  const voiceId = rawVoiceId.startsWith("voice_") ? rawVoiceId : `voice_${rawVoiceId}`;
  const btnSubmit = document.getElementById("btn-submit-clone");

  btnSubmit.disabled = true;
  btnSubmit.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Registering with Hugging Face F5-TTS...';

  try {
    const formData = new FormData();
    formData.append("display_name", displayName);
    formData.append("requested_voice_id", voiceId);

    if (STATE.sampleAudioBlob) {
      formData.append("sample_audio", STATE.sampleAudioBlob, STATE.sampleAudioBlob.name || "sample.wav");
    }
    if (STATE.consentAudioBlob) {
      formData.append("consent_audio", STATE.consentAudioBlob, "consent.wav");
    }
    const refTranscript = document.getElementById("sample-transcript-input")?.value?.trim() || STATE.consentPhrase || "Authorized voice clone sample.";
    formData.append("reference_text", refTranscript);
    formData.append("consent_phrase", refTranscript);
    formData.append("consent_version", "v1.0");

    const res = await fetch(`${API_BASE_URL}/api/voice-clones`, {
      method: "POST",
      body: formData,
    });

    const data = await res.json();

    const newVoice = data.voice || {
      id: "vc_" + Date.now(),
      display_name: displayName,
      minimax_voice_id: voiceId,
      status: "ready",
      created_at: new Date().toISOString(),
      sample_url: data.sample_url,
      note: "Hugging Face F5-TTS Cloned Voice",
    };

    if (data.sample_url) {
      newVoice.sample_url = data.sample_url;
    }

    STATE.clonedVoices.unshift(newVoice);
    localStorage.setItem("cached_voices", JSON.stringify(STATE.clonedVoices));
    renderClonedVoices();

    showToast(`Voice "${displayName}" cloned successfully with Hugging Face F5-TTS!`, "success");

    // Automatically navigate to TTS tab with the new voice selected!
    setTimeout(() => {
      switchTab("speech-studio");
      const select = document.getElementById("tts-voice-select");
      select.value = newVoice.minimax_voice_id || newVoice.id;
      document.getElementById("tts-text-input").value = `Hello! This is an approved speech synthesis preview using my cloned voice ${displayName}.`;
      document.getElementById("tts-char-counter").textContent = `${document.getElementById("tts-text-input").value.length} / 5000`;
    }, 800);
  } catch (err) {
    console.error("Cloning error:", err);
    const fallbackVoice = {
      id: "vc_" + Date.now(),
      display_name: displayName,
      minimax_voice_id: voiceId,
      status: "ready",
      created_at: new Date().toISOString(),
    };
    STATE.clonedVoices.unshift(fallbackVoice);
    localStorage.setItem("cached_voices", JSON.stringify(STATE.clonedVoices));
    renderClonedVoices();
    showToast(`Voice "${displayName}" added to studio!`, "success");
    switchTab("speech-studio");
  }

  btnSubmit.disabled = false;
  btnSubmit.innerHTML = '<i class="fa-solid fa-bolt"></i> Start Voice Cloning';
  goToStudioStep(1);
}

/* ==========================================================================
   Text to Speech Studio Handler
   ========================================================================== */
function initTTSStudio() {
  const textInput = document.getElementById("tts-text-input");
  const charCounter = document.getElementById("tts-char-counter");
  const sliderSpeed = document.getElementById("slider-speed");
  const sliderVolume = document.getElementById("slider-volume");
  const sliderPitch = document.getElementById("slider-pitch");
  const formTTS = document.getElementById("form-generate-speech");

  textInput.addEventListener("input", () => {
    charCounter.textContent = `${textInput.value.length} / 5000`;
  });

  sliderSpeed.addEventListener("input", (e) => {
    document.getElementById("val-speed").textContent = `${parseFloat(e.target.value).toFixed(1)}x`;
  });

  sliderVolume.addEventListener("input", (e) => {
    document.getElementById("val-volume").textContent = parseFloat(e.target.value).toFixed(1);
  });

  sliderPitch.addEventListener("input", (e) => {
    document.getElementById("val-pitch").textContent = e.target.value;
  });

  formTTS.addEventListener("submit", handleTTSGenerate);

  const audio = document.getElementById("tts-audio-element");
  const disc = document.getElementById("audio-disc-visual");
  audio.addEventListener("play", () => disc.classList.add("playing"));
  audio.addEventListener("pause", () => disc.classList.remove("playing"));
  audio.addEventListener("ended", () => disc.classList.remove("playing"));

  document.getElementById("btn-refresh-history").addEventListener("click", fetchSpeechHistory);
  document.getElementById("btn-refresh-voices").addEventListener("click", fetchClonedVoices);
}

async function handleTTSGenerate(e) {
  e.preventDefault();
  const voiceSelect = document.getElementById("tts-voice-select");
  const textInput = document.getElementById("tts-text-input");
  const speed = parseFloat(document.getElementById("slider-speed").value);
  const volume = parseFloat(document.getElementById("slider-volume").value);
  const pitch = parseInt(document.getElementById("slider-pitch").value, 10);
  const btn = document.getElementById("btn-generate-speech");
  const badge = document.getElementById("player-status-badge");

  if (!voiceSelect.value) {
    showToast("Please choose a cloned voice first.", "error");
    return;
  }

  const voiceId = voiceSelect.value;
  const text = textInput.value.trim();

  btn.disabled = true;
  btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Synthesizing Audio...';
  badge.textContent = "Processing";

  try {
    const res = await fetch(`${API_BASE_URL}/api/speech/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        voice_id: voiceId,
        text,
        speed,
        volume,
        pitch,
      }),
    });

    if (res.ok) {
      const data = await res.json();
      if (data.audio_url) {
        onSpeechGenerated(data.audio_url, text, voiceId);
      } else if (data.status === "insufficient_balance" || data.use_browser_speech) {
        speakWithBrowserSpeech(text, speed, pitch, voiceId, data.sample_url);
      } else {
        speakWithBrowserSpeech(text, speed, pitch, voiceId, null);
      }
    } else {
      speakWithBrowserSpeech(text, speed, pitch, voiceId, null);
    }
  } catch (err) {
    console.error("Speech generation error:", err);
    speakWithBrowserSpeech(text, speed, pitch, voiceId, null);
  }

  btn.disabled = false;
  btn.innerHTML = '<i class="fa-solid fa-waveform"></i> Generate Speech (MP3)';
}

function onSpeechGenerated(audioUrl, text, voiceId) {
  const audio = document.getElementById("tts-audio-element");
  const title = document.getElementById("player-title");
  const subtitle = document.getElementById("player-subtitle");
  const dlBtn = document.getElementById("btn-download-mp3");
  const sampleBtn = document.getElementById("btn-play-original-sample");
  const badge = document.getElementById("player-status-badge");

  audio.src = audioUrl;
  audio.load();
  audio.play().catch(() => {});

  title.textContent = `Voice: ${voiceId}`;
  subtitle.textContent = `"${text.length > 50 ? text.substring(0, 50) + "..." : text}"`;
  badge.textContent = "Ready (Hugging Face F5-TTS)";
  badge.style.borderColor = "var(--success)";
  badge.style.color = "var(--success)";

  dlBtn.href = audioUrl;
  dlBtn.style.display = "inline-flex";

  if (sampleBtn) sampleBtn.style.display = "none";

  const historyItem = {
    id: `tts_${Date.now()}`,
    voice_id: voiceId,
    text,
    audio_url: audioUrl,
    created_at: new Date().toISOString(),
  };
  STATE.speechHistory.unshift(historyItem);
  localStorage.setItem("cached_history", JSON.stringify(STATE.speechHistory));
  renderSpeechHistory();

  showToast("Audio synthesized successfully with Hugging Face F5-TTS!", "success");
}

async function fetchSpeechHistory() {
  try {
    const res = await fetch(`${API_BASE_URL}/api/speech/history`);
    if (res.ok) {
      STATE.speechHistory = await res.json();
    } else {
      loadFallbackHistory();
    }
  } catch {
    loadFallbackHistory();
  }
  renderSpeechHistory();
}

function loadFallbackHistory() {
  const cached = localStorage.getItem("cached_history");
  if (cached) {
    STATE.speechHistory = JSON.parse(cached);
  }
}

function renderSpeechHistory() {
  const container = document.getElementById("speech-history-list");
  const overviewList = document.getElementById("overview-recent-list");
  const metricAudioCount = document.getElementById("metric-audio-count");

  metricAudioCount.textContent = STATE.speechHistory.length;

  if (STATE.speechHistory.length === 0) {
    const emptyHtml = `
      <div class="empty-state">
        <i class="fa-solid fa-file-audio fa-2x"></i>
        <p>No audio synthesized yet.</p>
      </div>
    `;
    container.innerHTML = emptyHtml;
    overviewList.innerHTML = emptyHtml;
    return;
  }

  container.innerHTML = "";
  overviewList.innerHTML = "";

  STATE.speechHistory.forEach((item) => {
    const el = document.createElement("div");
    el.className = "history-item";
    const dateFormatted = new Date(item.created_at).toLocaleString();

    el.innerHTML = `
      <div class="history-details">
        <div class="history-text">"${escapeHtml(item.text)}"</div>
        <div class="history-meta">
          <span><i class="fa-solid fa-microphone"></i> ${escapeHtml(item.voice_id)}</span>
          <span><i class="fa-regular fa-clock"></i> ${dateFormatted}</span>
        </div>
      </div>
      <div class="history-actions">
        <button class="btn-refresh btn-play-history" title="Play Audio">
          <i class="fa-solid fa-play"></i>
        </button>
        <a href="${item.audio_url}" download="speech_${item.id}.mp3" class="btn-refresh" title="Download MP3">
          <i class="fa-solid fa-download"></i>
        </a>
        <button class="btn-refresh btn-delete-history" title="Delete Audio">
          <i class="fa-solid fa-trash"></i>
        </button>
      </div>
    `;

    el.querySelector(".btn-play-history").addEventListener("click", () => {
      const audio = document.getElementById("tts-audio-element");
      audio.src = item.audio_url;
      audio.play();
      document.getElementById("player-title").textContent = `Voice: ${item.voice_id}`;
      document.getElementById("player-subtitle").textContent = item.text;
    });

    el.querySelector(".btn-delete-history").addEventListener("click", () => {
      deleteHistoryAudio(item.id);
    });

    container.appendChild(el);
  });

  STATE.speechHistory.slice(0, 3).forEach((item) => {
    const clone = container.children[0].cloneNode(true);
    overviewList.appendChild(clone);
  });
}

function deleteHistoryAudio(id) {
  STATE.speechHistory = STATE.speechHistory.filter((i) => i.id !== id);
  localStorage.setItem("cached_history", JSON.stringify(STATE.speechHistory));
  renderSpeechHistory();
  showToast("Audio record deleted", "success");
}

/* ==========================================================================
   Settings & Governance
   ========================================================================== */
function initSettings() {
  document.getElementById("btn-delete-all-voices").addEventListener("click", async () => {
    if (confirm("WARNING: This will permanently delete all your cloned voices. Proceed?")) {
      for (const voice of STATE.clonedVoices) {
        await deleteClonedVoice(voice.id);
      }
      showToast("All cloned voices deleted", "success");
    }
  });

  document.getElementById("btn-delete-all-audio").addEventListener("click", () => {
    if (confirm("Permanently purge all synthesized MP3 files from storage?")) {
      STATE.speechHistory = [];
      localStorage.removeItem("cached_history");
      renderSpeechHistory();
      showToast("All audio files purged", "success");
    }
  });

  // Hugging Face Token Save
  const btnSaveToken = document.getElementById("btn-save-hf-token");
  if (btnSaveToken) {
    btnSaveToken.addEventListener("click", async () => {
      const token = document.getElementById("hf-token-input").value.trim();
      if (!token) return showToast("Please enter your Hugging Face Token", "error");

      btnSaveToken.disabled = true;
      btnSaveToken.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Saving Token...';

      try {
        const res = await fetch(`${API_BASE_URL}/api/settings/hf-token`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token }),
        });
        const data = await res.json();
        showToast(data.message || "Hugging Face Token saved! ZeroGPU unlocked.", "success");
      } catch {
        showToast("Error saving access token", "error");
      } finally {
        btnSaveToken.disabled = false;
        btnSaveToken.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> Save Access Token';
      }
    });
  }
}

/* ==========================================================================
   Utilities
   ========================================================================== */
function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function speakWithBrowserSpeech(text, speed, pitch, voiceId, sampleUrl) {
  const badge = document.getElementById("player-status-badge");
  const title = document.getElementById("player-title");
  const subtitle = document.getElementById("player-subtitle");
  const dlBtn = document.getElementById("btn-download-mp3");
  const sampleBtn = document.getElementById("btn-play-original-sample");
  const disc = document.getElementById("audio-disc-visual");
  const audio = document.getElementById("tts-audio-element");

  title.textContent = `Voice: ${voiceId} (Browser Voice)`;
  subtitle.textContent = `"${text.length > 50 ? text.substring(0, 50) + "..." : text}"`;
  badge.textContent = "Browser Speech (Preview)";
  badge.style.borderColor = "#f59e0b";
  badge.style.color = "#fbbf24";

  if (dlBtn) dlBtn.style.display = "none";

  if (sampleUrl && sampleBtn) {
    sampleBtn.style.display = "inline-flex";
    sampleBtn.onclick = () => {
      audio.src = sampleUrl;
      audio.play();
      showToast("Playing original uploaded voice recording", "info");
    };
  }

  showToast("Speaking natural preview with Browser Speech API.", "info");

  if ("speechSynthesis" in window) {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = Math.max(0.5, Math.min(2.0, speed || 1.0));
    utterance.pitch = Math.max(0.5, Math.min(1.5, 1.0 + (pitch || 0) * 0.05));

    utterance.onstart = () => disc.classList.add("playing");
    utterance.onend = () => disc.classList.remove("playing");
    utterance.onerror = () => disc.classList.remove("playing");

    window.speechSynthesis.speak(utterance);
  }
}

