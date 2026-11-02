const http = require("http");
const https = require("https");
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

/**
 * LOCAL DEMO ONLY — not the production backend.
 *
 * In-memory, no real authentication, no server-side consent enforcement.
 * The real stack is backend-rust + worker-python + speech_pipeline (see README).
 * Serves a frozen copy of the original dashboard from ./public on 127.0.0.1 only.
 */
const PORT = Number(process.env.DEMO_PORT || 5600);
const HOST = "127.0.0.1";
const PUBLIC_DIR = path.join(__dirname, "public");
const REPO_ROOT = path.resolve(__dirname, "..");
const UPLOADS_DIR = path.join(__dirname, "uploads");

if (!fs.existsSync(UPLOADS_DIR)) {
  fs.mkdirSync(UPLOADS_DIR, { recursive: true });
}

// ElevenLabs Integration
const {
  isConfigured: isElevenConfigured,
  synthesizeWithElevenLabs,
  PRESET_ELEVEN_VOICES,
} = require("./elevenlabs_service");

// In-memory store for active session
const inMemoryStore = {
  users: [{ id: "usr_default_01", email: "user@intelligence.ai" }],
  clonedVoices: [
    {
      id: "vc_sample_01",
      display_name: "Executive Narrative",
      minimax_voice_id: "voice_executive_hd",
      status: "ready",
      engine: "Hugging Face F5-TTS (100% Free)",
      created_at: new Date(Date.now() - 3600000 * 24).toISOString(),
      note: "Standard Reference Voice",
    },
  ],
  speechHistory: [],
  generatedAudio: new Map(),
  uploadedSamples: new Map(),
};

// Pre-load all available voice samples for instant multi-voice cloning
const voicePresets = [
  {
    voiceId: "voice_nature_female",
    displayName: "Mother Nature (Cinematic Female)",
    file: "female_narrator_sample.wav",
    mime: "audio/wav",
    referenceText: "Some call me nature. Others call me mother nature.",
    note: "Cinematic Female Voice Model (Zero-Shot Neural)",
  },
  {
    voiceId: "voice_sai_user",
    displayName: "Sai (User Voice)",
    file: "sai_user_voice.webm",
    mime: "audio/webm",
    referenceText: "Okay let's do one thing, remove MiniMax or whatever and use Hugging Face as the main voice cloner.",
    note: "Conversational Male Voice Model (Zero-Shot Neural)",
  },
  {
    voiceId: "voice_prahalad_free",
    displayName: "Prahalad (Commercial Male)",
    file: "prahalad_clean_slice.mp3",
    mime: "audio/mpeg",
    referenceText: "Hi everyone, looking for a comfortable kurta you can wear everyday?",
    note: "Commercial Voice Model (Zero-Shot Neural)",
  },
];

for (const preset of voicePresets) {
  const sPath = path.join(UPLOADS_DIR, preset.file);
  if (fs.existsSync(sPath)) {
    try {
      const buf = fs.readFileSync(sPath);
      inMemoryStore.uploadedSamples.set(preset.voiceId, {
        data: buf,
        filename: preset.file,
        contentType: preset.mime,
        displayName: preset.displayName,
        consentPhrase: preset.referenceText,
        referenceText: preset.referenceText,
      });
      inMemoryStore.clonedVoices.push({
        id: "vc_" + preset.voiceId,
        display_name: preset.displayName,
        minimax_voice_id: preset.voiceId,
        voice_id: preset.voiceId,
        status: "ready",
        engine: "Hugging Face F5-TTS (100% Free)",
        created_at: new Date().toISOString(),
        sample_url: `/api/voice-samples/${preset.voiceId}`,
        note: preset.note,
      });
      console.log(`[Server] Pre-loaded voice sample "${preset.displayName}" (${buf.length} bytes) from ${sPath}`);
    } catch (e) {
      console.error(`[Server] Could not pre-load sample ${preset.file}:`, e.message);
    }
  }
}

// Pre-load ElevenLabs voices if configured
if (isElevenConfigured()) {
  for (const ev of PRESET_ELEVEN_VOICES) {
    inMemoryStore.clonedVoices.push({
      id: "el_" + ev.voiceId,
      display_name: ev.displayName,
      voice_id: ev.voiceId,
      status: "ready",
      engine: "ElevenLabs Neural",
      created_at: new Date().toISOString(),
      note: ev.note,
    });
  }
  console.log(`[Server] Pre-loaded ${PRESET_ELEVEN_VOICES.length} ElevenLabs voices.`);
}

/**
 * Text Preprocessing & Script Sanitization for Neural TTS
 */
function cleanSpeechScript(rawText) {
  if (!rawText) return "";
  return rawText
    // Remove emojis that cause flow-matching phoneme corruption
    .replace(/[\u{1F600}-\u{1F64F}\u{1F300}-\u{1F5FF}\u{1F680}-\u{1F6FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}\u{1F900}-\u{1F9FF}\u{1F1E0}-\u{1F1FF}]/gu, " ")
    // Convert hashtag run-ons into spoken phrases
    .replace(/#([a-zA-Z0-9_]+)/g, (match, p1) => " " + p1.replace(/([A-Z])/g, " $1").toLowerCase() + " ")
    // Normalize curly quotes
    .replace(/[\u201C\u201D]/g, '"')
    .replace(/[\u2018\u2019]/g, "'")
    // Normalize whitespaces and newlines
    .replace(/[\r\n]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Free Hugging Face F5-TTS Engine Connection
 */
let gradioClient = null;
const HF_TOKEN = process.env.HF_TOKEN || "";

async function getGradioClient() {
  if (!gradioClient) {
    const { Client } = require("@gradio/client");
    console.log("[Server] Connecting to Free Hugging Face F5-TTS Engine (mrfakename/E2-F5-TTS)...");
    const options = HF_TOKEN ? { hf_token: HF_TOKEN } : {};
    gradioClient = await Client.connect("mrfakename/E2-F5-TTS", options);
    console.log("[Server] Connected to Free Hugging Face F5-TTS Engine successfully!");
  }
  return gradioClient;
}

/**
 * Synthesize speech using 100% Free Hugging Face F5-TTS Zero-Shot Voice Cloning
 */
async function synthesizeWithFreeF5(audioBuffer, audioMime, referenceText, targetText) {
  const client = await getGradioClient();
  const audioBlob = new Blob([audioBuffer], { type: audioMime || "audio/mpeg" });
  const cleanedTarget = cleanSpeechScript(targetText);

  console.log(`[Server] Running Free Hugging Face F5-TTS voice synthesis for text: "${cleanedTarget.slice(0, 40)}..."`);

  const res = await client.predict("/predict", [
    audioBlob,
    referenceText || "This is an authorized voice clone sample.",
    cleanedTarget,
    true, // remove silence
  ]);

  if (res && res.data && res.data[0] && res.data[0].url) {
    const fileUrl = res.data[0].url;
    console.log(`[Server] Free F5-TTS generated audio file: ${fileUrl}`);

    return new Promise((resolve, reject) => {
      https.get(fileUrl, (resp) => {
        const chunks = [];
        resp.on("data", (c) => chunks.push(c));
        resp.on("end", () => resolve(Buffer.concat(chunks)));
        resp.on("error", reject);
      });
    });
  }

  throw new Error("No audio returned from Hugging Face Space");
}

// MIME Types for static files
const MIME_TYPES = {
  ".html": "text/html",
  ".css": "text/css",
  ".js": "text/javascript",
  ".json": "application/json",
  ".webp": "image/webp",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
  ".mp3": "audio/mpeg",
  ".wav": "audio/wav",
  ".mp4": "video/mp4",
};

/**
 * Parse Multipart/form-data request body
 */
function parseMultipart(req) {
  return new Promise((resolve, reject) => {
    const contentType = req.headers["content-type"] || "";
    const match = contentType.match(/boundary=(?:"([^"]+)"|([^;]+))/i);
    if (!match) return reject(new Error("No boundary in multipart header"));
    const boundary = match[1] || match[2];

    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      const buffer = Buffer.concat(chunks);
      const boundaryBuf = Buffer.from(`--${boundary}`);
      const fields = {};
      const files = {};

      let start = 0;
      while (true) {
        const bStart = buffer.indexOf(boundaryBuf, start);
        if (bStart === -1) break;

        const partStart = bStart + boundaryBuf.length + 2; // skip boundary + \r\n
        const nextB = buffer.indexOf(boundaryBuf, partStart);
        if (nextB === -1) break;

        const partBuf = buffer.slice(partStart, nextB - 2); // strip trailing \r\n
        const headerEnd = partBuf.indexOf(Buffer.from("\r\n\r\n"));
        if (headerEnd !== -1) {
          const headerStr = partBuf.slice(0, headerEnd).toString("utf8");
          const bodyBuf = partBuf.slice(headerEnd + 4);

          const nameMatch = headerStr.match(/name="([^"]+)"/i);
          const fileMatch = headerStr.match(/filename="([^"]+)"/i);

          if (nameMatch) {
            const fieldName = nameMatch[1];
            if (fileMatch) {
              files[fieldName] = {
                filename: fileMatch[1],
                data: bodyBuf,
              };
            } else {
              fields[fieldName] = bodyBuf.toString("utf8");
            }
          }
        }
        start = nextB;
      }
      resolve({ fields, files });
    });
  });
}

/**
 * Parse JSON body
 */
function parseJson(req) {
  return new Promise((resolve) => {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      try {
        resolve(JSON.parse(body || "{}"));
      } catch (e) {
        resolve({});
      }
    });
  });
}

const server = http.createServer(async (req, res) => {
  const parsedUrl = new URL(req.url, `http://${req.headers.host}`);
  const pathname = parsedUrl.pathname;

  // Set universal CORS headers
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");

  if (req.method === "OPTIONS") {
    res.writeHead(204);
    res.end();
    return;
  }

  // =========================================================================
  // API Endpoints
  // =========================================================================

  // Engine Status: GET /api/engine/status
  if (pathname === "/api/engine/status" && req.method === "GET") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        engine: "Hugging Face F5-TTS",
        space: "mrfakename/E2-F5-TTS",
        status: "online",
        free: true,
        cost: "$0.00 (100% Free)",
        message: "Hugging Face F5-TTS Zero-Shot Engine is active and ready for unlimited voice cloning.",
      })
    );
    return;
  }

  // Auth: /api/auth/me
  if (pathname === "/api/auth/me" && req.method === "GET") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(inMemoryStore.users[0]));
    return;
  }

  // Auth: /api/auth/login or register
  if ((pathname === "/api/auth/login" || pathname === "/api/auth/register") && req.method === "POST") {
    const body = await parseJson(req);
    const email = body.email || "user@intelligence.ai";
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        token: "jwt_token_" + Date.now(),
        user: { id: "usr_" + Date.now(), email },
      })
    );
    return;
  }

  // List Cloned Voices: GET /api/voice-clones
  if (pathname === "/api/voice-clones" && req.method === "GET") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(inMemoryStore.clonedVoices));
    return;
  }

  // Settings: POST /api/settings/hf-token
  if (pathname === "/api/settings/hf-token" && req.method === "POST") {
    const body = await parseJson(req);
    const token = (body.token || "").trim();
    if (token) {
      process.env.HF_TOKEN = token;
      gradioClient = null; // Re-initialize gradio client with new token
      console.log(`[Server] Configured Hugging Face Access Token: ${token.slice(0, 8)}... (ZeroGPU limits unlocked)`);
    }
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ status: "ok", message: "Hugging Face Access Token saved! ZeroGPU limits unlocked." }));
    return;
  }

  // Create Cloned Voice: POST /api/voice-clones
  if (pathname === "/api/voice-clones" && req.method === "POST") {
    try {
      let displayName = "My Voice";
      let requestedVoiceId = "voice_" + Date.now().toString(36);
      let audioFile = null;
      let consentPhrase = "Authorized voice clone sample.";
      let referenceText = "";

      const contentType = req.headers["content-type"] || "";
      if (contentType.includes("multipart/form-data")) {
        const parsed = await parseMultipart(req);
        displayName = parsed.fields.display_name || displayName;
        requestedVoiceId = parsed.fields.requested_voice_id || requestedVoiceId;
        consentPhrase = parsed.fields.consent_phrase || consentPhrase;
        referenceText = parsed.fields.reference_text || parsed.fields.consent_phrase || consentPhrase;
        audioFile = parsed.files.sample_audio || parsed.files.audio || parsed.files.file;
      } else {
        const parsed = await parseJson(req);
        displayName = parsed.display_name || displayName;
        requestedVoiceId = parsed.requested_voice_id || requestedVoiceId;
        consentPhrase = parsed.consent_phrase || consentPhrase;
        referenceText = parsed.reference_text || parsed.consent_phrase || consentPhrase;
      }

      console.log(`[Server] Registering Voice with Hugging Face F5-TTS: "${displayName}" (${requestedVoiceId})`);
      console.log(`[Server] Reference Transcript: "${referenceText.slice(0, 60)}..."`);

      // Store uploaded audio sample buffer and persist to disk in uploads/
      if (audioFile && audioFile.data && audioFile.data.length > 0) {
        const ext = (audioFile.filename && audioFile.filename.endsWith(".mp3"))
          ? ".mp3"
          : (audioFile.filename && audioFile.filename.endsWith(".m4a"))
          ? ".m4a"
          : (audioFile.filename && audioFile.filename.endsWith(".webm"))
          ? ".webm"
          : ".wav";
        const mime = ext === ".mp3" ? "audio/mpeg" : ext === ".m4a" ? "audio/m4a" : ext === ".webm" ? "audio/webm" : "audio/wav";

        // Auto-slice long samples to ~4-6 seconds so neural flow matching never suffers drift
        let processedData = audioFile.data;
        if (ext === ".mp3" && processedData.length > 80000) {
          processedData = processedData.subarray(0, 75000);
          console.log(`[Server] Auto-sliced MP3 sample (${audioFile.data.length}B -> ${processedData.length}B) for optimal 5s neural alignment.`);
        } else if (ext === ".wav" && processedData.length > 300000) {
          processedData = processedData.subarray(0, 250000);
          console.log(`[Server] Auto-sliced WAV sample for optimal 5s neural alignment.`);
        }

        const diskPath = path.join(UPLOADS_DIR, `${requestedVoiceId}_sample${ext}`);
        fs.writeFileSync(diskPath, processedData);

        inMemoryStore.uploadedSamples.set(requestedVoiceId, {
          data: processedData,
          filename: audioFile.filename || `sample${ext}`,
          contentType: mime,
          displayName,
          consentPhrase,
          referenceText,
          diskPath,
        });
        console.log(`[Server] Stored ${processedData.length} bytes sample for voice ${requestedVoiceId} at ${diskPath}`);
      }

      const sampleUrl = `/api/voice-samples/${requestedVoiceId}`;

      const newVoice = {
        id: "vc_" + Date.now(),
        display_name: displayName,
        minimax_voice_id: requestedVoiceId, // kept for backward compatibility with UI
        voice_id: requestedVoiceId,
        engine: "Hugging Face F5-TTS (100% Free)",
        status: "ready",
        created_at: new Date().toISOString(),
        sample_url: sampleUrl,
        note: "100% Free Zero-Shot Neural Voice Model",
      };

      inMemoryStore.clonedVoices.unshift(newVoice);

      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          job_id: newVoice.id,
          voice: newVoice,
          status: "ready",
          sample_url: sampleUrl,
          engine: "Hugging Face F5-TTS",
          message: `Voice "${displayName}" successfully registered with Hugging Face F5-TTS! Ready for 100% free speech synthesis.`,
        })
      );
      return;
    } catch (err) {
      console.error("[Server] Error creating voice clone:", err);
      res.writeHead(500, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ message: "Cloning registration error: " + err.message }));
      return;
    }
  }

  // Voice Sample Serving: GET /api/voice-samples/:id
  if (pathname.startsWith("/api/voice-samples/") && req.method === "GET") {
    const voiceId = pathname.split("/").pop();
    const sample = inMemoryStore.uploadedSamples.get(voiceId);
    if (!sample) {
      res.writeHead(404, { "Content-Type": "text/plain" });
      res.end("Voice sample not found");
      return;
    }
    res.writeHead(200, {
      "Content-Type": sample.contentType,
      "Content-Length": sample.data.length,
      "Access-Control-Allow-Origin": "*",
      "Cache-Control": "public, max-age=3600",
    });
    res.end(sample.data);
    return;
  }

  // Delete Voice: DELETE /api/voice-clones/:id
  if (pathname.startsWith("/api/voice-clones/") && req.method === "DELETE") {
    const voiceId = pathname.split("/").pop();
    inMemoryStore.clonedVoices = inMemoryStore.clonedVoices.filter((v) => v.id !== voiceId && v.minimax_voice_id !== voiceId);
    inMemoryStore.uploadedSamples.delete(voiceId);
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ message: "Voice deleted" }));
    return;
  }

  // Speech Synthesis: POST /api/speech/generate
  if (pathname === "/api/speech/generate" && req.method === "POST") {
    try {
      const body = await parseJson(req);
      const voiceId = body.voice_id || "voice_prahalad_free";
      const text = body.text || "Hello! This is voice cloning powered by Hugging Face.";

      console.log(`[Server] Generating Speech: voice="${voiceId}", text="${text.slice(0, 35)}..."`);

      // Retrieve sample for this voice
      let sampleData = inMemoryStore.uploadedSamples.get(voiceId);
      if (!sampleData && inMemoryStore.uploadedSamples.size > 0) {
        sampleData = Array.from(inMemoryStore.uploadedSamples.values())[0];
      }

      if (!sampleData) {
        res.writeHead(400, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ message: "No voice sample found for cloning. Please upload a voice sample first." }));
        return;
      }

      // Determine engine and synthesize audio
      let outputAudioBuffer;
      let usedEngine = "Hugging Face F5-TTS";

      const isElevenVoice = voiceId.startsWith("el_") || PRESET_ELEVEN_VOICES.some((p) => p.voiceId === voiceId);

      if (isElevenConfigured() && isElevenVoice) {
        const cleanVoiceId = voiceId.replace(/^el_/, "");
        outputAudioBuffer = await synthesizeWithElevenLabs(cleanVoiceId, text);
        usedEngine = "ElevenLabs Neural";
      } else if (isElevenConfigured() && !sampleData) {
        outputAudioBuffer = await synthesizeWithElevenLabs("21m00Tcm4TlvDq8ikWAM", text);
        usedEngine = "ElevenLabs Neural";
      } else {
        const refText = sampleData?.referenceText || sampleData?.consentPhrase || "Authorized voice clone sample.";
        try {
          outputAudioBuffer = await synthesizeWithFreeF5(
            sampleData.data,
            sampleData.contentType,
            refText,
            text
          );
        } catch (f5Err) {
          if (isElevenConfigured()) {
            console.warn("[Server] F5-TTS failed, falling back to ElevenLabs:", f5Err.message);
            outputAudioBuffer = await synthesizeWithElevenLabs("21m00Tcm4TlvDq8ikWAM", text);
            usedEngine = "ElevenLabs Neural (Fallback)";
          } else {
            throw f5Err;
          }
        }
      }

      const audioId = "audio_" + Date.now();
      inMemoryStore.generatedAudio.set(audioId, outputAudioBuffer);

      // Save to disk in uploads
      const isWavFormat = outputAudioBuffer.slice(0, 4).toString() === "RIFF";
      const diskExt = isWavFormat ? "wav" : "mp3";
      const diskAudio = path.join(UPLOADS_DIR, `${audioId}.${diskExt}`);
      fs.writeFileSync(diskAudio, outputAudioBuffer);

      const audioUrl = `/api/audio/${audioId}`;
      const sampleUrl = inMemoryStore.uploadedSamples.has(voiceId) ? `/api/voice-samples/${voiceId}` : null;

      const historyItem = {
        id: "tts_" + Date.now(),
        voice_id: voiceId,
        text,
        audio_url: audioUrl,
        engine: usedEngine,
        created_at: new Date().toISOString(),
      };
      inMemoryStore.speechHistory.unshift(historyItem);

      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          job_id: historyItem.id,
          status: "ready",
          audio_url: audioUrl,
          sample_url: sampleUrl,
          engine: usedEngine,
          message: `Voice synthesis completed with ${usedEngine}!`,
        })
      );
      return;
    } catch (err) {
      console.error("[Server] Speech synthesis error:", err.message);
      res.writeHead(500, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ message: "Hugging Face F5-TTS synthesis error: " + err.message }));
      return;
    }
  }

  // Audio Serving: GET /api/audio/:id
  if (pathname.startsWith("/api/audio/") && req.method === "GET") {
    const audioId = pathname.split("/").pop();
    const audioBuf = inMemoryStore.generatedAudio.get(audioId);
    if (!audioBuf) {
      res.writeHead(404, { "Content-Type": "text/plain" });
      res.end("Audio not found");
      return;
    }
    const isWav = audioBuf.slice(0, 4).toString() === "RIFF";
    res.writeHead(200, {
      "Content-Type": isWav ? "audio/wav" : "audio/mpeg",
      "Content-Length": audioBuf.length,
      "Content-Disposition": `inline; filename="${audioId}.${isWav ? "wav" : "mp3"}"`,
      "Cache-Control": "public, max-age=3600",
    });
    res.end(audioBuf);
    return;
  }

  // Speech History: GET /api/speech/history
  if (pathname === "/api/speech/history" && req.method === "GET") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(inMemoryStore.speechHistory));
    return;
  }

  // =========================================================================
  // Static File Serving
  // =========================================================================
  let reqPath = decodeURI(pathname);
  if (reqPath === "/") reqPath = "/dashboard.html";

  // Shared brand assets come from the repo; everything else from ./public
  const baseDir = reqPath.startsWith("/assets/") || reqPath.startsWith("/fonts/") ? REPO_ROOT : PUBLIC_DIR;
  const filePath = path.join(baseDir, reqPath);

  if (!filePath.startsWith(baseDir + path.sep)) {
    res.writeHead(403);
    res.end("Forbidden");
    return;
  }

  fs.stat(filePath, (err, stats) => {
    if (err || !stats.isFile()) {
      res.writeHead(404, { "Content-Type": "text/plain" });
      res.end("404 Not Found");
      return;
    }

    const ext = path.extname(filePath).toLowerCase();
    const contentType = MIME_TYPES[ext] || "application/octet-stream";

    res.writeHead(200, {
      "Content-Type": contentType,
      "Access-Control-Allow-Origin": "*",
      "Cache-Control": "no-cache",
    });

    const stream = fs.createReadStream(filePath);
    stream.pipe(res);
  });
});

server.listen(PORT, HOST, () => {
  console.log(`[Demo] LOCAL DEMO ONLY (no auth, in-memory) at http://localhost:${PORT}/`);
});
