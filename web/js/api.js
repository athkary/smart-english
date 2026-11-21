// API client + session handling.
// Access tokens live in memory only; refresh tokens in localStorage (needed for a PWA
// that talks to an API on a different site). The page loads no third-party scripts.
import { API_BASE } from "./config.js";
import { getLang } from "./i18n.js";

const KEY = { parent: "se.parent.refresh", child: "se.child.refresh", mode: "se.mode" };
const access = { parent: null, child: null };
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* ignore */ } },
};

export class ApiError extends Error {
  constructor(status, body, network = false) {
    super(body?.error?.message || `HTTP ${status}`);
    this.status = status; this.body = body; this.network = network;
  }
  get code() { return this.body?.error?.code; }
}

export const session = {
  get mode() { return store.get(KEY.mode) || (store.get(KEY.parent) ? "parent" : null); },
  set mode(m) { store.set(KEY.mode, m); },
  hasParent() { return !!store.get(KEY.parent); },
  hasChild() { return !!store.get(KEY.child); },
  saveTokens(role, tokens) {
    access[role] = tokens.access_token;
    store.set(role === "parent" ? KEY.parent : KEY.child, tokens.refresh_token);
  },
  clearChild() { access.child = null; store.set(KEY.child, null); },
  clearAll() { access.parent = access.child = null; Object.values(KEY).forEach((k) => store.set(k, null)); },
};

const refreshing = {};
async function refreshToken(role) {
  if (refreshing[role]) return refreshing[role];
  const rt = store.get(role === "parent" ? KEY.parent : KEY.child);
  if (!rt) throw new ApiError(401, null);
  refreshing[role] = (async () => {
    try {
      const tokens = await raw("POST", "/v1/auth/refresh", { refresh_token: rt });
      session.saveTokens(role, tokens);
    } catch (e) {
      if (e.status === 401) role === "parent" ? session.clearAll() : session.clearChild();
      throw e;
    } finally { delete refreshing[role]; }
  })();
  return refreshing[role];
}

let slowNotice = null;
export function onSlowServer(fn) { slowNotice = fn; }

async function raw(method, path, body, token) {
  const headers = { "Accept": "application/json", "Accept-Language": getLang() };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;
  // Free hosting sleeps when idle; tell the user if the first request is slow.
  const timer = setTimeout(() => slowNotice && slowNotice(true), 4000);
  let res;
  try {
    res = await fetch(API_BASE + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body),
                                         mode: "cors", credentials: "omit", cache: "no-store" });
  } catch {
    throw new ApiError(0, null, true);
  } finally {
    clearTimeout(timer); slowNotice && slowNotice(false);
  }
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON */ }
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

/** Authenticated call as "parent" or "child", refreshing the access token once if needed. */
export async function call(role, method, path, body) {
  if (!access[role]) await refreshToken(role);
  try {
    return await raw(method, path, body, access[role]);
  } catch (e) {
    if (e.status !== 401) throw e;
    await refreshToken(role);
    return raw(method, path, body, access[role]);
  }
}

export const api = {
  meta: () => raw("GET", "/v1/meta"),
  signup: (d) => raw("POST", "/v1/auth/parents/signup", d),
  login: (d) => raw("POST", "/v1/auth/login", d),
  async logout() {
    const rt = store.get(KEY.parent);
    const ct = store.get(KEY.child);
    session.clearAll();
    await Promise.allSettled([rt && raw("POST", "/v1/auth/logout", { refresh_token: rt }),
                              ct && raw("POST", "/v1/auth/logout", { refresh_token: ct })]);
  },
  parent: {
    me: () => call("parent", "GET", "/v1/parents/me"),
    update: (d) => call("parent", "PATCH", "/v1/parents/me", d),
    setPin: (pin, password) => call("parent", "PUT", "/v1/parents/me/pin", { pin, password }),
    verifyPin: (pin) => call("parent", "POST", "/v1/parents/me/pin/verify", { pin }),
    export: () => call("parent", "GET", "/v1/parents/me/export"),
    deleteAccount: (password) => call("parent", "DELETE", "/v1/parents/me", { password, confirm: "DELETE" }),
    students: () => call("parent", "GET", "/v1/students"),
    student: (id) => call("parent", "GET", `/v1/students/${encodeURIComponent(id)}`),
    addStudent: (d) => call("parent", "POST", "/v1/students", d),
    updateStudent: (id, d) => call("parent", "PATCH", `/v1/students/${encodeURIComponent(id)}`, d),
    deleteStudent: (id) => call("parent", "DELETE", `/v1/students/${encodeURIComponent(id)}`),
    settings: (id) => call("parent", "GET", `/v1/students/${encodeURIComponent(id)}/settings`),
    putSettings: (id, d) => call("parent", "PUT", `/v1/students/${encodeURIComponent(id)}/settings`, d),
    async startChild(studentId) {
      const tokens = await call("parent", "POST", "/v1/auth/students/session", { student_id: studentId });
      session.saveTokens("child", tokens);
      session.mode = "child";
    },
  },
  async endChild() {
    const ct = store.get(KEY.child);
    session.clearChild();
    session.mode = "parent";
    if (ct) await raw("POST", "/v1/auth/logout", { refresh_token: ct }).catch(() => {});
  },
  child: {
    me: () => call("child", "GET", "/v1/me/student"),
    prefs: (d) => call("child", "PATCH", "/v1/me/student/preferences", d),
  },
};
