// Where the dashboard finds the Rust API. Override per deployment.
window.APP_CONFIG = {
  apiBaseUrl: window.localStorage.getItem("api_base_url") || "http://localhost:8080",
};
