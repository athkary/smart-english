// Tiny DOM helpers. User data is always set via textContent (never innerHTML).
import { t } from "./i18n.js";

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, String(v));
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

/** An English island inside an Arabic page (and vice versa). */
export const en = (text, cls = "") => h("span", { dir: "ltr", lang: "en", class: cls }, text);
export const ar = (text, cls = "") => h("span", { dir: "rtl", lang: "ar", class: cls }, text);

export function mount(root, ...nodes) {
  root.replaceChildren(...nodes);
  window.scrollTo(0, 0);
  const first = root.querySelector("h1, h2");
  if (first) { first.setAttribute("tabindex", "-1"); first.focus({ preventScroll: true }); }
}

let toastTimer;
export function toast(message, kind = "info") {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.className = `toast show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.className = "toast"), 3200);
}

export function field(label, input, hint) {
  const id = input.id || `f-${Math.random().toString(36).slice(2, 8)}`;
  input.id = id;
  return h("div", { class: "field" }, h("label", { for: id }, label), input, hint && h("small", { class: "hint" }, hint));
}

export function busy(button, on) {
  button.disabled = on;
  button.classList.toggle("loading", on);
}

/** Generic modal. Resolves with the value returned by onConfirm, or null when cancelled. */
export function modal({ title, body, confirmText = t("confirm"), danger = false, onConfirm }) {
  return new Promise((resolve) => {
    const err = h("p", { class: "form-error", role: "alert" });
    const okBtn = h("button", { class: `btn ${danger ? "btn-danger" : "btn-primary"}`, type: "submit" }, confirmText);
    const cancel = h("button", { class: "btn btn-ghost", type: "button" }, t("cancel"));
    const form = h("form", { class: "modal-card", role: "dialog", "aria-modal": "true", "aria-label": title },
      h("h2", {}, title), ...(Array.isArray(body) ? body : [body]), err,
      h("div", { class: "modal-actions" }, cancel, okBtn));
    const backdrop = h("div", { class: "modal-backdrop" }, form);
    const close = (v) => { backdrop.remove(); document.removeEventListener("keydown", onKey); resolve(v); };
    const onKey = (e) => e.key === "Escape" && close(null);
    cancel.addEventListener("click", () => close(null));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      err.textContent = "";
      busy(okBtn, true);
      try {
        const v = await onConfirm(form);
        close(v === undefined ? true : v);
      } catch (ex) {
        err.textContent = ex.userMessage || ex.message;
        busy(okBtn, false);
      }
    });
    document.addEventListener("keydown", onKey);
    document.body.append(backdrop);
    form.querySelector("input")?.focus();
  });
}

export function pinInput(placeholder) {
  return h("input", { type: "password", inputmode: "numeric", autocomplete: "off", pattern: "\\d{4,6}",
                      maxlength: 6, minlength: 4, required: true, class: "pin-input", placeholder, name: "pin" });
}
