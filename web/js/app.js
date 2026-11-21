import { api, session, onSlowServer, ApiError } from "./api.js";
import { t, getLang, setLang, applyDocumentLang, errorText } from "./i18n.js";
import { h, en, ar, mount, toast, field, busy, modal, pinInput } from "./ui.js";
import { speak, speechSupported } from "./speech.js";

const root = document.getElementById("app");
const CONSENT_VERSION = "2026-11";
const AVATARS = { lion: "🦁", cat: "🐱", owl: "🦉", fox: "🦊", panda: "🐼", rabbit: "🐰", turtle: "🐢", penguin: "🐧" };
const TEACHERS = [
  { code: "emma", name: "Emma", ar: "معلمة ودودة للمبتدئين", en: "Friendly teacher for beginners", available: true },
  { code: "daniel", name: "Daniel", ar: "معلم ودود لممارسة المحادثة", en: "Friendly teacher for conversation", available: true },
  { code: "alex", name: "Alex", ar: "معلم للمستويات المتقدمة", en: "Teacher for higher levels", available: false },
];
// Bilingual sample content (spec §3 format). Real lesson content arrives in Phase 5.
const WORDS = [
  { en: "Apple", ar: "تفاحة", ph: "أَبُل", exEn: "I eat an apple.", exAr: "أنا آكل تفاحة.", icon: "🍎" },
  { en: "Cat", ar: "قطة", ph: "كات", exEn: "The cat is small.", exAr: "القطة صغيرة.", icon: "🐈" },
  { en: "Book", ar: "كتاب", ph: "بُك", exEn: "This is my book.", exAr: "هذا كتابي.", icon: "📘" },
  { en: "Sun", ar: "شمس", ph: "سَن", exEn: "The sun is hot.", exAr: "الشمس حارة.", icon: "☀️" },
  { en: "Water", ar: "ماء", ph: "ووتَر", exEn: "I drink water.", exAr: "أنا أشرب الماء.", icon: "💧" },
];

// ---------------- shell ----------------
function topbar({ showLang = true, extra = [] } = {}) {
  return h("header", { class: "topbar" },
    h("a", { href: "#/", class: "brand", "aria-label": t("app.name") }, h("span", { class: "brand-mark" }, "SE"), h("span", {}, t("app.name"))),
    h("div", { class: "topbar-actions" }, ...extra,
      showLang && h("button", { class: "btn btn-ghost btn-sm", type: "button", lang: getLang() === "ar" ? "en" : "ar",
                                onclick: () => { setLang(getLang() === "ar" ? "en" : "ar"); render(); } }, t("lang.switch"))));
}

function page(...content) { return h("main", { class: "page" }, ...content); }

function showError(el, e) { el.textContent = errorText(e); }

// ---------------- welcome ----------------
function viewWelcome() {
  mount(root, topbar(), page(
    h("section", { class: "hero" },
      h("div", { class: "hero-art", "aria-hidden": "true" }, "🎓"),
      h("h1", {}, t("welcome.title")),
      h("p", { class: "tagline" }, en("Learn English. Speak with Confidence."), h("br"), ar("تعلّم الإنجليزية. تحدّث بثقة.", "muted")),
      h("p", { class: "lead" }, t("welcome.body")),
      h("div", { class: "stack" },
        h("a", { class: "btn btn-primary btn-lg", href: "#/signup" }, t("welcome.signup")),
        h("a", { class: "btn btn-secondary btn-lg", href: "#/login" }, t("welcome.login"))),
      h("p", { class: "muted small" }, t("welcome.note"))),
    installHint()));
}

function installHint() {
  const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  if (standalone) return null;
  const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  if (isIOS) return h("p", { class: "install-hint" }, "📲 ", t("install.ios"));
  if (deferredInstall) {
    return h("button", { class: "btn btn-ghost install-hint", type: "button",
                         onclick: async () => { deferredInstall.prompt(); deferredInstall = null; render(); } }, "📲 ", t("install.button"));
  }
  return null;
}
let deferredInstall = null;
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); deferredInstall = e; if (location.hash in { "": 1, "#/": 1 }) render(); });

// ---------------- signup / login ----------------
function viewAuth(kind) {
  const isSignup = kind === "signup";
  const err = h("p", { class: "form-error", role: "alert" });
  const email = h("input", { type: "email", name: "email", autocomplete: "email", required: true, dir: "ltr" });
  const password = h("input", { type: "password", name: "password", required: true, dir: "ltr",
                                minlength: isSignup ? 10 : 1, autocomplete: isSignup ? "new-password" : "current-password" });
  const name = h("input", { type: "text", name: "display_name", required: true, maxlength: 80, autocomplete: "name" });
  const langSel = h("select", { name: "preferred_language" },
    h("option", { value: "ar", selected: getLang() === "ar" }, "العربية"), h("option", { value: "en", selected: getLang() === "en" }, "English"));
  const consent = h("input", { type: "checkbox", name: "consent", required: true, id: "consent" });
  const submit = h("button", { class: "btn btn-primary btn-lg", type: "submit" }, t(isSignup ? "auth.submit.signup" : "auth.submit.login"));

  const form = h("form", { class: "card form", novalidate: false },
    h("h1", {}, t(isSignup ? "auth.signup.title" : "auth.login.title")),
    isSignup && field(t("auth.name"), name),
    field(t("auth.email"), email),
    field(t("auth.password"), password, isSignup ? t("auth.password.hint") : null),
    isSignup && field(t("auth.language"), langSel),
    isSignup && h("p", { class: "privacy-box" }, "🔒 ", t("auth.privacy.summary")),
    isSignup && h("label", { class: "check", for: "consent" }, consent, h("span", {}, t("auth.consent"))),
    err, submit,
    h("a", { href: isSignup ? "#/login" : "#/signup", class: "link-center" }, t(isSignup ? "auth.switch.to_login" : "auth.switch.to_signup")));

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    err.textContent = "";
    busy(submit, true);
    try {
      const tokens = isSignup
        ? await api.signup({ email: email.value, password: password.value, display_name: name.value,
                             preferred_language: langSel.value, consent_version: CONSENT_VERSION })
        : await api.login({ email: email.value, password: password.value });
      session.saveTokens("parent", tokens);
      session.mode = "parent";
      if (isSignup && langSel.value !== getLang()) setLang(langSel.value);
      go("#/parent");
    } catch (ex) { showError(err, ex); busy(submit, false); }
  });
  mount(root, topbar(), page(h("a", { href: "#/", class: "back" }, "‹ ", t("back")), form));
}

// ---------------- parent home ----------------
async function viewParent() {
  mount(root, topbar(), page(h("div", { class: "spinner", "aria-busy": "true" })));
  let me, list;
  try { [me, { students: list }] = await Promise.all([api.parent.me(), api.parent.students()]); }
  catch (e) { return handleAuthError(e); }

  const childCard = (s) => h("article", { class: "card child-card" },
    h("div", { class: "avatar", "aria-hidden": "true" }, AVATARS[s.avatar_code] || "🙂"),
    h("div", { class: "child-info" },
      h("h3", {}, s.nickname),
      h("p", { class: "muted small" }, `${t("child.level")}: ${s.current_level} · ${t("child.teacher")}: ${teacherName(s.preferred_teacher)}`)),
    h("div", { class: "child-actions" },
      h("button", { class: "btn btn-primary", type: "button", onclick: (e) => startChild(s, me, e.currentTarget) }, "▶ ", t("parent.start")),
      h("a", { class: "btn btn-ghost", href: `#/parent/child/${s.id}` }, "⚙︎ ", t("parent.edit"))));

  const canAdd = list.length < me.max_students;
  mount(root, topbar({ extra: [h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: logout }, t("parent.logout"))] }), page(
    h("h1", {}, `${t("parent.hello")} ${me.display_name} 👋`),
    h("section", {},
      h("div", { class: "section-head" }, h("h2", {}, t("parent.children")),
        canAdd && h("a", { class: "btn btn-secondary btn-sm", href: "#/parent/child/new" }, "＋ ", t("parent.add_child"))),
      list.length ? h("div", { class: "grid" }, list.map(childCard))
                  : h("div", { class: "card empty" }, h("p", {}, t("parent.no_children")),
                      h("a", { class: "btn btn-primary", href: "#/parent/child/new" }, "＋ ", t("parent.add_child"))),
      h("p", { class: "muted small" }, t("parent.limit_hint", { n: me.max_students }))),
    h("section", { class: "card" },
      h("h2", {}, t("parent.account")),
      h("div", { class: "row" },
        h("div", {}, h("strong", {}, t("parent.pin")), h("p", { class: "muted small" }, t("parent.pin.explain"))),
        h("button", { class: "btn btn-secondary", type: "button", onclick: () => setPinFlow().then((ok) => ok && render()) },
          me.has_pin ? t("parent.pin.change") : t("parent.pin.set"))),
      h("hr"),
      h("div", { class: "row wrap" },
        h("button", { class: "btn btn-ghost", type: "button", onclick: exportData }, "⬇︎ ", t("parent.export")),
        h("button", { class: "btn btn-danger-ghost", type: "button", onclick: deleteAccount }, t("parent.delete_account")))),
  ));
}

function teacherName(code) { return (TEACHERS.find((x) => x.code === code) || TEACHERS[0]).name; }

async function setPinFlow() {
  const pin = pinInput("••••");
  const pw = h("input", { type: "password", name: "password", required: true, autocomplete: "current-password", dir: "ltr" });
  const ok = await modal({ title: t("parent.pin"), body: [field(t("pin.new"), pin), field(t("pin.password"), pw)],
    onConfirm: async () => {
      try { await api.parent.setPin(pin.value, pw.value); }
      catch (e) { e.userMessage = errorText(e); throw e; }
    } });
  if (ok) toast(t("child.saved"), "success");
  return ok;
}

async function startChild(student, me, btn) {
  if (!me.has_pin) {
    toast(t("parent.pin.required"), "warn");
    const ok = await setPinFlow();
    if (!ok) return;
  }
  busy(btn, true);
  try { await api.parent.startChild(student.id); go("#/learn"); }
  catch (e) { toast(errorText(e), "error"); busy(btn, false); }
}

async function exportData() {
  try {
    const data = await api.parent.export();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = h("a", { href: URL.createObjectURL(blob), download: "smart-english-data.json" });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  } catch (e) { toast(errorText(e), "error"); }
}

async function deleteAccount() {
  const pw = h("input", { type: "password", required: true, autocomplete: "current-password", dir: "ltr" });
  const typed = h("input", { type: "text", required: true, dir: "ltr", autocomplete: "off", placeholder: "DELETE" });
  const ok = await modal({ title: t("parent.delete_account"), danger: true, confirmText: t("parent.delete_account"),
    body: [h("p", { class: "warn-box" }, "⚠️ ", t("parent.delete_account.warn")), field(t("auth.password"), pw), field(t("parent.delete_account.type"), typed)],
    onConfirm: async () => {
      if (typed.value.trim() !== "DELETE") { const e = new Error(t("parent.delete_account.type")); e.userMessage = e.message; throw e; }
      try { await api.parent.deleteAccount(pw.value); }
      catch (e) { e.userMessage = errorText(e); throw e; }
    } });
  if (ok) { session.clearAll(); go("#/"); }
}

async function logout() { await api.logout(); go("#/"); }

// ---------------- child form (new / edit + settings) ----------------
async function viewChildForm(id) {
  const isNew = id === "new";
  let s = { nickname: "", birth_year: null, avatar_code: "lion", preferred_teacher: "emma", show_arabic: true, daily_goal_minutes: 15, current_level: "A0" };
  let st = null;
  if (!isNew) {
    mount(root, topbar(), page(h("div", { class: "spinner" })));
    try { [s, st] = await Promise.all([api.parent.student(id), api.parent.settings(id)]); }
    catch (e) { return handleAuthError(e); }
  }
  const err = h("p", { class: "form-error", role: "alert" });
  const nickname = h("input", { type: "text", required: true, maxlength: 40, value: s.nickname, autocomplete: "off" });
  const year = h("input", { type: "number", min: 2005, max: 2026, inputmode: "numeric", value: s.birth_year ?? "", dir: "ltr" });
  let avatar = s.avatar_code;
  const avatarGrid = h("div", { class: "avatar-grid", role: "radiogroup", "aria-label": t("child.avatar") },
    Object.entries(AVATARS).map(([code, emoji]) => h("button", {
      type: "button", class: `avatar-pick ${code === avatar ? "selected" : ""}`, role: "radio", "aria-checked": String(code === avatar),
      "aria-label": code, onclick: (e) => { avatar = code; avatarGrid.querySelectorAll(".avatar-pick").forEach((b) => { b.classList.toggle("selected", b === e.currentTarget); b.setAttribute("aria-checked", String(b === e.currentTarget)); }); },
    }, emoji)));
  const teacher = h("select", {}, TEACHERS.filter((x) => x.available).map((x) =>
    h("option", { value: x.code, selected: x.code === s.preferred_teacher }, `${x.name} — ${getLang() === "ar" ? x.ar : x.en}`)));
  const showAr = h("input", { type: "checkbox", checked: s.show_arabic });
  const goal = h("input", { type: "number", min: 5, max: 120, value: s.daily_goal_minutes, inputmode: "numeric", dir: "ltr" });
  const level = h("select", {}, ["A0", "A1", "A2"].map((l) => h("option", { value: l, selected: l === s.current_level }, l)));

  // limits & privacy (edit only)
  let limitsFields = null, readLimits = null;
  if (st) {
    const limit = h("input", { type: "number", min: 5, max: 240, value: st.daily_limit_minutes ?? "", placeholder: t("settings.no_limit"), dir: "ltr" });
    const start = h("input", { type: "time", value: st.allowed_start_time ?? "", dir: "ltr" });
    const end = h("input", { type: "time", value: st.allowed_end_time ?? "", dir: "ltr" });
    const free = h("input", { type: "checkbox", checked: st.free_conversation_enabled });
    const role = h("input", { type: "checkbox", checked: st.role_play_enabled });
    const keep = h("input", { type: "checkbox", checked: st.store_transcripts });
    const ret = h("input", { type: "number", min: 0, max: 365, value: st.transcript_retention_days, dir: "ltr" });
    limitsFields = h("fieldset", { class: "card" }, h("legend", {}, t("settings.section")),
      field(t("settings.daily_limit"), limit),
      h("div", { class: "field" }, h("label", {}, t("settings.window")), h("div", { class: "row" }, start, h("span", {}, t("settings.and")), end)),
      toggle(t("settings.free_conv"), free), toggle(t("settings.role_play"), role), toggle(t("settings.store_transcripts"), keep),
      field(t("settings.retention"), ret));
    readLimits = () => ({ daily_limit_minutes: limit.value ? Number(limit.value) : null,
      allowed_start_time: start.value || null, allowed_end_time: end.value || null,
      free_conversation_enabled: free.checked, role_play_enabled: role.checked, store_transcripts: keep.checked,
      transcript_retention_days: Number(ret.value || 0), weekly_report_email: st.weekly_report_email });
  }

  const save = h("button", { class: "btn btn-primary btn-lg", type: "submit" }, t("child.save"));
  const form = h("form", { class: "form" },
    h("h1", {}, t(isNew ? "child.form.title.new" : "child.form.title.edit")),
    h("div", { class: "card" },
      field(t("child.nickname"), nickname), field(t("child.birth_year"), year),
      h("div", { class: "field" }, h("label", {}, t("child.avatar")), avatarGrid),
      field(t("child.teacher"), teacher), toggle(t("child.show_arabic"), showAr),
      !isNew && field(t("child.daily_goal"), goal), !isNew && field(t("child.level"), level)),
    limitsFields, err, save,
    !isNew && h("button", { class: "btn btn-danger-ghost", type: "button", onclick: async () => {
      const ok = await modal({ title: t("child.delete"), danger: true, confirmText: t("child.delete"),
        body: h("p", {}, t("child.delete.confirm")), onConfirm: async () => {
          try { await api.parent.deleteStudent(id); } catch (e) { e.userMessage = errorText(e); throw e; } } });
      if (ok) go("#/parent");
    } }, "🗑 ", t("child.delete")));

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    err.textContent = "";
    busy(save, true);
    const body = { nickname: nickname.value, avatar_code: avatar, preferred_teacher: teacher.value, show_arabic: showAr.checked };
    if (year.value) body.birth_year = Number(year.value);
    try {
      if (isNew) {
        await api.parent.addStudent({ nickname: body.nickname, birth_year: body.birth_year ?? null, avatar_code: avatar, preferred_teacher: teacher.value })
          .then((c) => (body.show_arabic ? c : api.parent.updateStudent(c.id, { show_arabic: false })));
      } else {
        await api.parent.updateStudent(id, { ...body, daily_goal_minutes: Number(goal.value), current_level: level.value });
        await api.parent.putSettings(id, readLimits());
      }
      toast(t("child.saved"), "success");
      go("#/parent");
    } catch (ex) { showError(err, ex); busy(save, false); }
  });
  mount(root, topbar(), page(h("a", { href: "#/parent", class: "back" }, "‹ ", t("back")), form));
}

function toggle(label, input) {
  input.classList.add("switch");
  return h("label", { class: "toggle" }, h("span", {}, label), input);
}

// ---------------- child home ----------------
async function viewLearn() {
  mount(root, page(h("div", { class: "spinner" })));
  let me;
  try { me = await api.child.me(); }
  catch (e) {
    if (e.status === 401 || e.status === 404) { session.clearChild(); session.mode = session.hasParent() ? "parent" : null; return go(session.hasParent() ? "#/parent" : "#/"); }
    return mount(root, page(h("p", { class: "form-error" }, errorText(e)), h("button", { class: "btn btn-primary", onclick: render }, "↻")));
  }
  const word = WORDS[new Date().getDate() % WORDS.length];
  const showAr = me.show_arabic;

  const teacherPicker = h("div", { class: "teacher-row", role: "radiogroup", "aria-label": t("child.choose_teacher") },
    TEACHERS.map((x) => h("button", {
      type: "button", role: "radio", "aria-checked": String(x.code === me.preferred_teacher), disabled: !x.available,
      class: `teacher-card t-${x.code} ${x.code === me.preferred_teacher ? "selected" : ""}`,
      onclick: async () => {
        try { me = await api.child.prefs({ preferred_teacher: x.code }); viewLearnRender(); }
        catch (e) { toast(errorText(e), "error"); }
      } },
      h("span", { class: "teacher-face", "aria-hidden": "true" }, x.name[0]),
      h("strong", {}, x.name),
      h("small", {}, x.available ? (getLang() === "ar" ? x.ar : x.en) : t("teacher.later")))));

  const listen = (text, slow) => {
    if (!speechSupported()) return toast(t("speech.unsupported"), "warn");
    speak(text, { slow });
  };

  const wordCard = h("article", { class: "card word-card" },
    h("p", { class: "eyebrow" }, t("child.word_of_day")),
    h("div", { class: "word-icon", "aria-hidden": "true" }, word.icon),
    h("div", { class: "word-line" }, en(word.en.toUpperCase(), "word-en"),
      h("button", { class: "btn-icon", type: "button", "aria-label": `${t("child.listen")}: ${word.en}`, onclick: () => listen(word.en, true) }, "🔊")),
    showAr && h("p", { class: "word-ar" }, ar(word.ar)),
    showAr && h("p", { class: "muted" }, ar(`${t("child.phonetic")}: ${word.ph}`)),
    h("hr"),
    h("div", { class: "word-line" }, en(word.exEn, "example-en"),
      h("button", { class: "btn-icon", type: "button", "aria-label": `${t("child.listen")}: ${word.exEn}`, onclick: () => listen(word.exEn, false) }, "🔊")),
    showAr && h("p", {}, ar(word.exAr)));

  const stats = h("div", { class: "stats" },
    h("div", { class: "stat" }, h("strong", {}, String(me.total_points)), h("span", {}, t("child.points"))),
    me.minutes_left_today != null && h("div", { class: "stat" }, h("strong", {}, String(me.minutes_left_today)), h("span", {}, t("child.minutes_left"))));

  function viewLearnRender() { viewLearn(); }

  mount(root,
    h("header", { class: "topbar kid" },
      h("div", { class: "brand" }, h("span", { class: "avatar sm", "aria-hidden": "true" }, AVATARS[me.avatar_code] || "🙂"),
        h("span", {}, `${t("child.hello")} ${me.nickname}!`)),
      h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: parentGate }, "🔒 ", t("child.parent_area"))),
    page(
      h("h1", { class: "kid-title" }, en(`Hello, ${me.nickname}!`), showAr && h("span", { class: "sub" }, ar(`مرحباً يا ${me.nickname}!`))),
      stats,
      h("section", {}, h("h2", {}, t("child.choose_teacher")), teacherPicker),
      h("div", { class: "grid" }, wordCard,
        h("article", { class: "card classroom-soon" },
          h("div", { class: "mic-disabled", "aria-hidden": "true" }, "🎤"),
          h("h3", {}, t("child.classroom")),
          h("p", { class: "muted" }, t("child.classroom.soon"))))));
}

async function parentGate() {
  const pin = pinInput("••••");
  const ok = await modal({ title: t("pin.title"), body: field(t("pin.enter"), pin), onConfirm: async () => {
    try { await api.parent.verifyPin(pin.value); }
    catch (e) { e.userMessage = errorText(e); throw e; }
  } });
  if (ok) { await api.endChild(); go("#/parent"); }
}

// ---------------- routing ----------------
function handleAuthError(e) {
  if (e instanceof ApiError && e.status === 401) { session.clearAll(); return go("#/login"); }
  mount(root, topbar(), page(h("div", { class: "card" }, h("p", { class: "form-error" }, errorText(e)),
    h("button", { class: "btn btn-primary", type: "button", onclick: render }, "↻"))));
}

function go(hash) { if (location.hash === hash) render(); else location.hash = hash; }

function render() {
  applyDocumentLang();
  const hash = location.hash || "#/";
  // A child session is locked to the learning area until the parent PIN is entered.
  if (session.mode === "child" && session.hasChild()) { if (hash !== "#/learn") return go("#/learn"); return viewLearn(); }
  if (hash === "#/learn") return go(session.hasParent() ? "#/parent" : "#/");
  if (hash.startsWith("#/parent")) {
    if (!session.hasParent()) return go("#/login");
    const m = hash.match(/^#\/parent\/child\/([\w-]+)$/);
    return m ? viewChildForm(m[1]) : viewParent();
  }
  if (session.hasParent() && ["#/", "#/login", "#/signup"].includes(hash)) return go("#/parent");
  if (hash === "#/signup") return viewAuth("signup");
  if (hash === "#/login") return viewAuth("login");
  return viewWelcome();
}

onSlowServer((on) => {
  const b = document.getElementById("waking");
  if (b) b.hidden = !on;
});
window.addEventListener("hashchange", render);
window.addEventListener("offline", () => toast(t("offline"), "warn"));
if ("serviceWorker" in navigator && location.protocol === "https:") {
  navigator.serviceWorker.register("./sw.js").catch(() => {});
}
document.getElementById("waking").textContent = t("error.waking");
render();
