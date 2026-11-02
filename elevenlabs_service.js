const path = require("path");
const { ElevenLabsClient } = require("@elevenlabs/elevenlabs-js");

// Load .env.local without exposing key in code
const envPath = path.resolve(__dirname, ".env.local");
if (typeof process.loadEnvFile === "function") {
  try {
    process.loadEnvFile(envPath);
  } catch (e) {
    // ignore if missing
  }
} else {
  try {
    require("dotenv").config({ path: envPath });
  } catch (e) {
    // ignore if missing
  }
}

// Initialize ElevenLabs client with environment key
const client = new ElevenLabsClient();

const PRESET_ELEVEN_VOICES = [
  {
    voiceId: "JBFqnCBsd6RMkjVDRZzb",
    displayName: "George (ElevenLabs Narrative Male)",
    category: "premade",
    note: "Studio Narrative Voice (ElevenLabs)",
  },
  {
    voiceId: "EXAVITQu4vr4xnSDxMaL",
    displayName: "Sarah (ElevenLabs Soft Female)",
    category: "premade",
    note: "Soft & Natural Delivery (ElevenLabs)",
  },
  {
    voiceId: "21m00Tcm4TlvDq8ikWAM",
    displayName: "Rachel (ElevenLabs Calm Female)",
    category: "premade",
    note: "Clear & Articulate (ElevenLabs)",
  },
  {
    voiceId: "onwK4e9ZLuTAKqWW03F9",
    displayName: "Daniel (ElevenLabs Authoritative Male)",
    category: "premade",
    note: "Deep Executive Voice (ElevenLabs)",
  },
  {
    voiceId: "XB0fDUnXU5powFXDhCwa",
    displayName: "Charlotte (ElevenLabs Conversational)",
    category: "premade",
    note: "Conversational & Friendly (ElevenLabs)",
  },
];

function isConfigured() {
  return Boolean(process.env.ELEVENLABS_API_KEY && process.env.ELEVENLABS_API_KEY.trim());
}

/**
 * Converts response stream into a Buffer
 */
async function streamToBuffer(stream) {
  const chunks = [];
  for await (const chunk of stream) {
    chunks.push(typeof chunk === "string" ? Buffer.from(chunk) : chunk);
  }
  return Buffer.concat(chunks);
}

/**
 * Synthesizes text to speech using ElevenLabs
 */
async function synthesizeWithElevenLabs(voiceId, text, options = {}) {
  if (!isConfigured()) {
    throw new Error("ELEVENLABS_API_KEY is not configured in .env.local");
  }

  const selectedVoice = voiceId || "21m00Tcm4TlvDq8ikWAM";
  const modelId = options.model_id || "eleven_multilingual_v2";

  console.log(`[ElevenLabs] Synthesizing speech with voice=${selectedVoice}, model=${modelId}`);

  const audioStream = await client.textToSpeech.convert(selectedVoice, {
    text,
    model_id: modelId,
    voice_settings: {
      stability: options.stability ?? 0.5,
      similarity_boost: options.similarity_boost ?? 0.75,
    },
  });

  return await streamToBuffer(audioStream);
}

module.exports = {
  client,
  isConfigured,
  synthesizeWithElevenLabs,
  PRESET_ELEVEN_VOICES,
};
