// ⚙️ The ONLY line to change after deploying the backend on Render:
const PRODUCTION_API = "https://smart-english-api.onrender.com";

// Local development: page served from localhost/127.0.0.1 talks to a local API on :8000.
const isLocal = ["localhost", "127.0.0.1"].includes(location.hostname);
export const API_BASE = (window.SE_API_BASE || (isLocal ? `http://${location.hostname}:8000` : PRODUCTION_API))
  .replace(/\/$/, "");

// No API keys here — ever. All AI/voice keys live on the server.
