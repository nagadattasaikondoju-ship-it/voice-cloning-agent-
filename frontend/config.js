// Where the dashboard finds the Rust API.
// - Served by the API itself (the public site, or localhost:8080): same origin.
// - Local static server on :5500 (docker compose "frontend"): the API on localhost:8080.
// - The static copy on Vercel: the public API below.
// A value saved in localStorage ("api_base_url") overrides all of these.
const PUBLIC_API_URL = "https://voice-cloning-agent.onrender.com";

function defaultApiBase() {
  const { hostname, port } = window.location;
  if (port === "5500") return `http://${hostname}:8080`;
  if (hostname.endsWith(".vercel.app")) return PUBLIC_API_URL;
  return window.location.origin;
}

window.APP_CONFIG = {
  apiBaseUrl: window.localStorage.getItem("api_base_url") || defaultApiBase(),
};
