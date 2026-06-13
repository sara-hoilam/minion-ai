const API = "/api";

class ApiError extends Error {
  constructor(message, extra = {}) {
    super(message);
    this.name = "ApiError";
    this.extra = extra;
  }
}

let currentUser = null;
let authRequired = true;
let studioSession = null;
let currentTask = null;
let taskStartTime = null;
let timerInterval = null;

async function api(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  const res = await fetch(`${API}${path}`, {
    headers: isFormData ? { ...options.headers } : { "Content-Type": "application/json", ...options.headers },
    credentials: "same-origin",
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(data.error || res.statusText, data);
  return data;
}

async function uploadResume(file) {
  const formData = new FormData();
  formData.append("resume", file);
  return api("/profile/resume", { method: "POST", body: formData });
}

async function trackEvent(eventType, payload = {}) {
  try {
    if (currentUser) {
      await api("/events", {
        method: "POST",
        body: JSON.stringify({ event_type: eventType, payload }),
      });
    }
  } catch (_) {}
}

function isCollabHash(hash) {
  const h = (hash ?? location.hash.replace(/^#\/?/, "") ?? "").replace(/^#\/?/, "");
  return /^(chat\/|project\/|agents(\/|$)|workspace\/)/.test(h);
}

let landingAuthMode = "login";
let recoveryTokens = null;

function showView(viewId) {
  document.querySelectorAll("[data-view]").forEach((el) => el.classList.add("hidden"));
  const view = document.querySelector(`[data-view="${viewId}"]`);
  if (view) view.classList.remove("hidden");
  document.body.classList.toggle("home-workspace", viewId === "home");
  document.body.classList.toggle(
    "auth-page",
    viewId === "login" || viewId === "register" || viewId === "forgot-password"
      || viewId === "reset-password" || viewId === "plans" || viewId === "plans/success",
  );
  document.body.classList.toggle("landing-active", viewId === "landing");
  updateHeaderForView(viewId);
  if (viewId === "home") {
    if (!isCollabHash()) location.hash = "home";
  } else {
    location.hash = viewId;
  }
}

function updateHeaderForView(viewId) {
  const navGuest = document.getElementById("nav-guest");
  const navAuthed = document.getElementById("nav-authed");
  const hideAllNav = viewId === "login" || viewId === "register" || viewId === "forgot-password"
    || viewId === "reset-password" || viewId === "plans" || viewId === "plans/success";

  if (hideAllNav) {
    navGuest?.classList.add("hidden");
    navAuthed?.classList.add("hidden");
    if (navAuthed) navAuthed.style.display = "none";
    return;
  }

  if (currentUser) {
    navGuest?.classList.add("hidden");
    navAuthed?.classList.remove("hidden");
    if (navAuthed) navAuthed.style.display = "flex";
    return;
  }

  navAuthed?.classList.add("hidden");
  if (navAuthed) navAuthed.style.display = "none";
  if (authRequired) {
    navGuest?.classList.remove("hidden");
  } else {
    navGuest?.classList.add("hidden");
  }
}

function showError(containerId, message) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = `<div class="alert alert-error">${message}</div>`;
  setTimeout(() => { el.innerHTML = ""; }, 5000);
}

function showSuccess(containerId, message) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const alert = document.createElement("div");
  alert.className = "alert alert-success";
  alert.textContent = message;
  el.innerHTML = "";
  el.appendChild(alert);
  setTimeout(() => { el.innerHTML = ""; }, 8000);
}

function fillBackgroundForm(data) {
  // Legacy helper — wizard uses BackgroundWizard.prefill via open()
}

function showResumeStatus() {
  // Resume upload removed from onboarding flow
}

// --- Auth ---

function initPasswordToggles() {
  document.querySelectorAll(".password-toggle").forEach((btn) => {
    if (btn.dataset.bound === "1") return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", () => {
      const input = document.getElementById(btn.dataset.target);
      if (!input) return;
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.setAttribute("aria-pressed", show ? "true" : "false");
      btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
      btn.querySelector(".icon-eye-open")?.classList.toggle("hidden", show);
      btn.querySelector(".icon-eye-closed")?.classList.toggle("hidden", !show);
    });
  });
}

function passwordsMatch(password, confirmPassword) {
  return password === confirmPassword;
}

function validateRegisterPasswords(password, confirmPassword, errorContainerId) {
  if (password.length < 8) {
    showError(errorContainerId, "Password must be at least 8 characters.");
    return false;
  }
  if (!passwordsMatch(password, confirmPassword)) {
    showError(errorContainerId, "Passwords do not match.");
    return false;
  }
  return true;
}

function redirectToRegister(email, { preferLanding = false } = {}) {
  const onLanding = preferLanding
    || !document.querySelector('[data-view="landing"]')?.classList.contains("hidden");
  if (onLanding) {
    setLandingAuthMode("register");
    const emailEl = document.getElementById("landing-auth-email");
    if (emailEl && email) emailEl.value = email;
    scrollToLandingAuth("register");
    return;
  }
  showView("register");
  const regEmail = document.getElementById("register-email");
  if (regEmail && email) regEmail.value = email;
}

function handleAuthRedirect(err) {
  if (err instanceof ApiError && err.extra.redirect === "register") {
    redirectToRegister(err.extra.email || "", { preferLanding: landingAuthMode === "login" });
    return true;
  }
  return false;
}

function setLandingAuthMode(mode) {
  landingAuthMode = mode;
  const isLogin = mode === "login";
  const submitBtn = document.getElementById("landing-auth-submit");
  const toggleBtn = document.getElementById("landing-auth-toggle");
  const toggleText = document.getElementById("landing-auth-toggle-text");
  const passwordInput = document.getElementById("landing-auth-password");
  const confirmWrap = document.getElementById("landing-auth-confirm-wrap");
  const confirmInput = document.getElementById("landing-auth-password-confirm");
  const forgotWrap = document.getElementById("landing-auth-forgot-wrap");

  if (submitBtn) submitBtn.textContent = isLogin ? "Continue with email" : "Create account";
  if (toggleBtn) toggleBtn.textContent = isLogin ? "Sign up" : "Log in";
  if (toggleText) toggleText.textContent = isLogin ? "Don't have an account?" : "Already have an account?";
  if (passwordInput) {
    passwordInput.placeholder = isLogin ? "Password" : "At least 8 characters";
    passwordInput.minLength = isLogin ? 0 : 8;
    passwordInput.autocomplete = isLogin ? "current-password" : "new-password";
  }
  confirmWrap?.classList.toggle("hidden", isLogin);
  forgotWrap?.classList.toggle("hidden", !isLogin);
  if (confirmInput) {
    confirmInput.required = !isLogin;
    if (isLogin) confirmInput.value = "";
  }
}

function parseSupabaseRecoveryHash() {
  const raw = location.hash.slice(1);
  if (!raw || !raw.includes("access_token=")) return null;
  const query = raw.includes("access_token=")
    ? raw.replace(/^reset-password&?/, "").replace(/^[^&]*&(?=access_token=)/, "")
    : "";
  const params = new URLSearchParams(query.startsWith("access_token=") ? query : raw);
  if (params.get("type") !== "recovery" || !params.get("access_token")) return null;
  return {
    access_token: params.get("access_token"),
    refresh_token: params.get("refresh_token"),
  };
}

function stripRecoveryHashFromUrl() {
  if (location.hash.includes("access_token=")) {
    history.replaceState(null, "", `${location.pathname}${location.search}#reset-password`);
  }
}

function clearRecoverySession() {
  recoveryTokens = null;
}

document.getElementById("landing-auth-forgot")?.addEventListener("click", async () => {
  const email = document.getElementById("landing-auth-email")?.value?.trim();
  if (!email) {
    showError("landing-auth-error", "Enter your email address first.");
    return;
  }
  const btn = document.getElementById("landing-auth-forgot");
  try {
    if (btn) btn.disabled = true;
    const res = await api("/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    });
    showSuccess(
      "landing-auth-error",
      res.message || "If an account exists for that email, a reset link has been sent.",
    );
  } catch (err) {
    showError("landing-auth-error", err.message);
  } finally {
    if (btn) btn.disabled = false;
  }
});

document.getElementById("landing-auth-toggle")?.addEventListener("click", () => {
  setLandingAuthMode(landingAuthMode === "login" ? "register" : "login");
});

document.getElementById("landing-auth-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const submitBtn = document.getElementById("landing-auth-submit");
  const email = document.getElementById("landing-auth-email")?.value;
  const password = document.getElementById("landing-auth-password")?.value;
  try {
    submitBtn.disabled = true;
    if (!authRequired) {
      await initApp();
      return;
    }
    if (landingAuthMode === "register") {
      const confirmPassword = document.getElementById("landing-auth-password-confirm")?.value || "";
      if (!validateRegisterPasswords(password, confirmPassword, "landing-auth-error")) return;
      await api("/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, password, password_confirm: confirmPassword }),
      });
      trackEvent("signup_completed");
    } else {
      await api("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
    }
    await initApp();
  } catch (err) {
    if (handleAuthRedirect(err)) return;
    showError("landing-auth-error", err.message);
  } finally {
    submitBtn.disabled = false;
  }
});

document.getElementById("login-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    if (!authRequired) {
      await initApp();
      return;
    }
    await api("/auth/login", {
      method: "POST",
      body: JSON.stringify({
        email: document.getElementById("login-email").value,
        password: document.getElementById("login-password").value,
      }),
    });
    await initApp();
  } catch (err) {
    if (handleAuthRedirect(err)) return;
    showError("login-error", err.message);
  }
});

document.getElementById("register-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const submitBtn = e.target.querySelector('button[type="submit"]');
  try {
    submitBtn.disabled = true;
    if (!authRequired) {
      await initApp();
      return;
    }
    const password = document.getElementById("register-password").value;
    const confirmPassword = document.getElementById("register-password-confirm").value;
    if (!validateRegisterPasswords(password, confirmPassword, "register-error")) return;
    const res = await api("/auth/register", {
      method: "POST",
      body: JSON.stringify({
        email: document.getElementById("register-email").value,
        password,
        password_confirm: confirmPassword,
      }),
    });
    if (res.email_confirmation_required) {
      showError("register-error", res.message || "Check your email to confirm your account, then log in.");
      showView("login");
      return;
    }
    trackEvent("signup_completed");
    await initApp();
  } catch (err) {
    showError("register-error", err.message);
  } finally {
    submitBtn.disabled = false;
  }
});

document.getElementById("forgot-password-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const submitBtn = e.target.querySelector('button[type="submit"]');
  const successEl = document.getElementById("forgot-password-success");
  try {
    submitBtn.disabled = true;
    const res = await api("/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email: document.getElementById("forgot-email").value }),
    });
    if (successEl) {
      successEl.innerHTML = `<div class="alert alert-success">${escapeHtml(res.message || "Check your email for a reset link.")}</div>`;
    }
    document.getElementById("forgot-password-error").innerHTML = "";
  } catch (err) {
    showError("forgot-password-error", err.message);
  } finally {
    submitBtn.disabled = false;
  }
});

document.getElementById("show-forgot-password")?.addEventListener("click", () => {
  const landingEmail = document.getElementById("landing-auth-email")?.value?.trim();
  const forgotEmail = document.getElementById("forgot-email");
  if (landingEmail && forgotEmail) forgotEmail.value = landingEmail;
  showView("forgot-password");
});
document.getElementById("back-to-login")?.addEventListener("click", () => showView("login"));
document.getElementById("reset-password-back-login")?.addEventListener("click", () => {
  clearRecoverySession();
  showView("login");
});

document.getElementById("reset-password-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const submitBtn = e.target.querySelector('button[type="submit"]');
  const password = document.getElementById("reset-password-new")?.value || "";
  const confirmPassword = document.getElementById("reset-password-confirm")?.value || "";
  if (!validateRegisterPasswords(password, confirmPassword, "reset-password-error")) return;
  if (!recoveryTokens?.access_token) {
    showError("reset-password-error", "Invalid or expired reset link. Request a new reset email.");
    return;
  }
  try {
    submitBtn.disabled = true;
    await api("/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({
        password,
        password_confirm: confirmPassword,
        access_token: recoveryTokens.access_token,
        refresh_token: recoveryTokens.refresh_token,
      }),
    });
    clearRecoverySession();
    await initApp();
  } catch (err) {
    showError("reset-password-error", err.message);
  } finally {
    submitBtn.disabled = false;
  }
});

document.getElementById("logout-btn")?.addEventListener("click", async () => {
  await api("/auth/logout", { method: "POST" });
  currentUser = null;
  showView("landing");
});

// --- Background wizard ---

// --- Studio ---

async function loadStudioIntro() {
  const template = await api("/studio/template");
  document.getElementById("studio-name").textContent = template.name;
  document.getElementById("studio-desc").textContent = template.description;
  document.getElementById("studio-time").textContent = template.estimated_minutes;
  document.getElementById("studio-task-count").textContent = template.tasks.length;
}

document.getElementById("start-studio-btn")?.addEventListener("click", async () => {
  try {
    const res = await api("/studio/start", { method: "POST" });
    trackEvent("studio_entered", { session_id: res.session_id });
    await loadCurrentTask();
    showView("studio");
  } catch (err) {
    showError("studio-intro-error", err.message);
  }
});

function startTimer() {
  taskStartTime = Date.now();
  clearInterval(timerInterval);
  timerInterval = setInterval(() => {
    const elapsed = Math.floor((Date.now() - taskStartTime) / 1000);
    const mins = Math.floor(elapsed / 60);
    const secs = elapsed % 60;
    const el = document.getElementById("task-timer");
    if (el) el.textContent = `${mins}:${secs.toString().padStart(2, "0")}`;
  }, 1000);
}

function renderTaskForm(task) {
  currentTask = task;
  startTimer();

  document.getElementById("task-title").textContent = task.title;
  document.getElementById("task-prompt").textContent = task.prompt;
  document.getElementById("task-instructions").textContent = task.instructions;

  const schemaEl = document.getElementById("task-schema");
  if (task.schema) {
    schemaEl.textContent = task.schema;
    schemaEl.parentElement.classList.remove("hidden");
  } else {
    schemaEl.parentElement.classList.add("hidden");
  }

  const form = document.getElementById("task-form-fields");
  form.innerHTML = "";

  (task.fields || []).forEach((field) => {
    const group = document.createElement("div");
    group.className = "form-group";

    const label = document.createElement("label");
    label.textContent = field.label;
    label.htmlFor = `field-${field.name}`;
    group.appendChild(label);

    let input;
    if (field.type === "textarea" || field.type === "ordered_list") {
      input = document.createElement("textarea");
      if (field.type === "ordered_list") {
        input.placeholder = "One step per line";
        input.dataset.fieldType = "ordered_list";
      }
    } else if (field.type === "code") {
      input = document.createElement("textarea");
      input.className = "code";
    } else if (field.type === "select") {
      input = document.createElement("select");
      (field.options || []).forEach((opt) => {
        const o = document.createElement("option");
        o.value = opt;
        o.textContent = opt;
        input.appendChild(o);
      });
    } else {
      input = document.createElement("input");
      input.type = "text";
    }

    input.id = `field-${field.name}`;
    input.name = field.name;
    input.required = true;
    group.appendChild(input);
    form.appendChild(group);
  });
}

async function loadCurrentTask(forceStudio = false) {
  studioSession = await api("/studio/session");

  if (!forceStudio && (studioSession.status === "completed" || studioSession.status === "agent_ready")) {
    await loadResults(studioSession);
    showView("results");
    return;
  }

  if (studioSession.status === "not_started") {
    showView("studio-intro");
    return;
  }

  if (!studioSession.current_task) {
    await loadResults(studioSession);
    showView("results");
    return;
  }

  const idx = studioSession.current_task_index;
  const total = studioSession.total_tasks;
  const pct = (idx / total) * 100;

  document.getElementById("studio-progress-fill").style.width = `${pct}%`;
  document.getElementById("studio-progress-label").textContent = `Task ${idx + 1} of ${total}`;

  const dots = document.getElementById("step-dots");
  dots.innerHTML = "";
  for (let i = 0; i < total; i++) {
    const dot = document.createElement("div");
    dot.className = "step-dot";
    if (i < idx) dot.classList.add("done");
    if (i === idx) dot.classList.add("active");
    dots.appendChild(dot);
  }

  renderTaskForm(studioSession.current_task);
}

document.getElementById("task-submit-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = document.getElementById("task-form-fields");
  const responseData = {};

  form.querySelectorAll("input, textarea, select").forEach((el) => {
    responseData[el.name] = el.value;
  });

  const timeSpent = taskStartTime ? Math.floor((Date.now() - taskStartTime) / 1000) : 0;

  try {
    const res = await api("/studio/task/submit", {
      method: "POST",
      body: JSON.stringify({
        task_id: currentTask.id,
        response_data: responseData,
        time_spent_seconds: timeSpent,
      }),
    });

    studioSession = { ...studioSession, ...res };

    if (res.agent_ready) {
      trackEvent("agent_created", { tasks_completed: res.tasks_completed });
    }

    if (res.session_status === "completed") {
      trackEvent("studio_test_completed");
      await loadResults(res);
      showView("results");
    } else if (res.agent_ready && res.tasks_completed === 1) {
      await loadResults(res);
      showView("results");
    } else if (res.next_task) {
      studioSession.current_task_index = res.current_task_index;
      renderTaskForm(res.next_task);
      const total = res.total_tasks;
      const pct = (res.current_task_index / total) * 100;
      document.getElementById("studio-progress-fill").style.width = `${pct}%`;
      document.getElementById("studio-progress-label").textContent = `Task ${res.current_task_index + 1} of ${total}`;
      if (res.agent_ready) {
        await loadResults(res);
      }
    }
  } catch (err) {
    showError("task-error", err.message);
  }
});

// --- Results ---

async function loadResults(sessionInfo) {
  const session = sessionInfo || await api("/studio/session");
  const completed = session.tasks_completed ?? session.completed ?? 0;
  const total = session.total_tasks ?? session.total ?? 5;
  const hasMore = session.has_more_tasks ?? (completed < total && session.status !== "completed");

  const progressEl = document.getElementById("training-progress");
  const continueBtn = document.getElementById("continue-training-btn");
  const alertEl = document.getElementById("results-alert");

  if (progressEl) {
    progressEl.textContent = `${completed} / ${total} tasks`;
  }

  if (continueBtn) {
    if (hasMore) {
      continueBtn.classList.remove("hidden");
    } else {
      continueBtn.classList.add("hidden");
    }
  }

  if (alertEl) {
    if (session.status === "completed") {
      alertEl.textContent = "Studio complete! Your agent is fully trained. Download your artifacts below.";
    } else {
      alertEl.textContent = "Your agent has been created. Complete more tasks to improve it, or download what you have now.";
    }
  }

  await loadArtifacts();
}

async function loadArtifacts() {
  const artifacts = await api("/studio/artifacts");
  const list = document.getElementById("artifact-list");
  list.innerHTML = "";

  artifacts.forEach((a) => {
    const li = document.createElement("li");
    const label = a.artifact_type === "agent_profile_md" ? "Agent Profile (.md)" : "Multi-Agent Framework (.json)";
    li.innerHTML = `
      <span>${label}<br><small style="color:var(--muted)">${new Date(a.generated_at).toLocaleDateString()}</small></span>
      <div class="artifact-actions">
        <button class="btn btn-secondary btn-view" data-id="${a.id}" style="padding:0.5rem 1rem;font-size:0.85rem">View</button>
        <a class="btn btn-primary" href="/api/studio/artifacts/${a.id}/download" style="padding:0.5rem 1rem;font-size:0.85rem">Download</a>
      </div>
    `;
    list.appendChild(li);
  });

  list.querySelectorAll(".btn-view").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const data = await api(`/studio/artifacts/${btn.dataset.id}/content`);
      document.getElementById("artifact-preview").textContent = data.content;
      document.getElementById("artifact-preview-panel").classList.remove("hidden");
    });
  });
}

document.getElementById("continue-training-btn")?.addEventListener("click", async () => {
  try {
    showView("studio");
    await loadCurrentTask(true);
    trackEvent("studio_training_resumed");
  } catch (err) {
    showError("results-alert", err.message);
  }
});

// --- Home ---

let homeUserData = null;
let pendingRenameSessionId = null;
let pendingDeleteSessionId = null;
let pendingDeleteAgentName = "";
let pendingAgentAction = "delete"; // delete | hide_roster

function buildResumeMenuHtml(includeRemove = false) {
  return `
    <button type="button" class="resume-menu-trigger" aria-label="Resume options">⋮</button>
    <div class="resume-menu-dropdown hidden">
      <button type="button" data-action="view">View</button>
      <button type="button" data-action="replace">Replace resume</button>
      ${includeRemove ? '<button type="button" data-action="remove" class="danger">Remove</button>' : ""}
    </div>
  `;
}

function closeAllResumeMenus() {
  document.querySelectorAll(".resume-menu-dropdown").forEach((el) => el.classList.add("hidden"));
}

function attachResumeMenu(container, user, options = {}) {
  if (!container || !user?.resume?.has_resume) return;

  container.innerHTML = buildResumeMenuHtml(options.includeRemove);
  const trigger = container.querySelector(".resume-menu-trigger");
  const dropdown = container.querySelector(".resume-menu-dropdown");

  trigger.addEventListener("click", (e) => {
    e.stopPropagation();
    const isOpen = !dropdown.classList.contains("hidden");
    closeAllResumeMenus();
    if (!isOpen) dropdown.classList.remove("hidden");
  });

  dropdown.querySelector('[data-action="view"]')?.addEventListener("click", (e) => {
    e.stopPropagation();
    closeAllResumeMenus();
    openResumeModal(user.resume);
  });

  dropdown.querySelector('[data-action="replace"]')?.addEventListener("click", (e) => {
    e.stopPropagation();
    closeAllResumeMenus();
    if (options.onReplace) {
      options.onReplace();
    } else {
      document.getElementById("home-resume-replace-input").click();
    }
  });

  dropdown.querySelector('[data-action="remove"]')?.addEventListener("click", async (e) => {
    e.stopPropagation();
    closeAllResumeMenus();
    if (!confirm("Remove your resume from this account?")) return;
    try {
      await api("/profile/resume", { method: "DELETE" });
      if (options.onRemove) await options.onRemove();
    } catch (err) {
      showError(options.errorTarget || "home-edit-error", err.message);
    }
  });
}

function openResumeModal(resume) {
  const modal = document.getElementById("resume-modal");
  const frame = document.getElementById("resume-modal-frame");
  const fallback = document.getElementById("resume-modal-fallback");
  const title = document.getElementById("resume-modal-title");
  const name = resume.original_name || "Resume";

  title.textContent = name;
  frame.src = "";
  frame.classList.add("hidden");
  fallback.classList.add("hidden");

  const ext = name.split(".").pop()?.toLowerCase();
  if (ext === "pdf" || ext === "html" || ext === "htm") {
    frame.src = resume.view_url;
    frame.classList.remove("hidden");
  } else {
    fallback.classList.remove("hidden");
  }

  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
}

function closeResumeModal() {
  const modal = document.getElementById("resume-modal");
  const frame = document.getElementById("resume-modal-frame");
  modal.classList.add("hidden");
  modal.setAttribute("aria-hidden", "true");
  frame.src = "";
}

function initResumeModal() {
  const modal = document.getElementById("resume-modal");
  if (!modal || modal.dataset.bound === "1") return;
  modal.dataset.bound = "1";

  document.getElementById("resume-modal-close")?.addEventListener("click", closeResumeModal);
  document.getElementById("resume-modal-backdrop")?.addEventListener("click", closeResumeModal);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.classList.contains("hidden")) {
      closeResumeModal();
    }
  });
}

document.addEventListener("click", closeAllResumeMenus);

initResumeModal();

document.getElementById("home-resume-replace-input")?.addEventListener("change", async (e) => {
  const file = e.target.files?.[0];
  if (!file) return;
  try {
    await uploadResume(file);
    await loadHome();
    showHomeProfileView();
  } catch (err) {
    alert(err.message);
  } finally {
    e.target.value = "";
  }
});

function renderHomeProfileView(user) {
  const nameEl = document.getElementById("home-user-name");
  const emailEl = document.getElementById("home-user-email");
  const avatarEl = document.getElementById("home-user-avatar");
  if (nameEl) nameEl.textContent = user.full_name || "Your agent";
  if (emailEl) emailEl.textContent = user.email || "";
  if (avatarEl) {
    avatarEl.textContent = (user.full_name || "?").split(" ").map((n) => n[0]).join("").slice(0, 2).toUpperCase();
  }

  const details = document.getElementById("home-profile-details");
  const fields = [
    ["Agent", user.full_name],
    ["Role", user.current_job],
    ["Field", user.field],
    ["Industry", user.industry],
    ["Skills", user.skillset],
  ].filter(([, v]) => v);

  if (details) {
    details.innerHTML = fields
      .map(([label, value]) => `<dt>${label}</dt><dd>${escapeHtml(String(value))}</dd>`)
      .join("");
  }

  const resumeSection = document.getElementById("home-resume-section");
  const resumeCard = document.getElementById("home-resume-card");
  if (resumeSection && resumeCard) {
    if (user.resume?.has_resume) {
      resumeSection.classList.remove("hidden");
      resumeCard.innerHTML = `
        <div class="resume-card-info">
          <strong>${escapeHtml(user.resume.original_name || "Resume")}</strong>
          <span>Uploaded ${user.resume.uploaded_at ? new Date(user.resume.uploaded_at).toLocaleDateString() : ""}</span>
        </div>
        <div class="resume-menu" id="home-resume-menu"></div>
      `;
      attachResumeMenu(document.getElementById("home-resume-menu"), user);
    } else {
      resumeSection.classList.add("hidden");
    }
  }
}

function fillHomeEditForm(user) {
  const setVal = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.value = val || "";
  };
  setVal("edit-name", user.full_name);
  setVal("edit-job", user.current_job);
  setVal("edit-field", user.field);
  setVal("edit-industry", user.industry);
  setVal("edit-skillset", user.skillset);

  const resumeCurrent = document.getElementById("edit-resume-current");
  const uploadWrap = document.getElementById("edit-resume-upload-wrap");
  if (!resumeCurrent || !uploadWrap) return;

  if (user.resume?.has_resume) {
    resumeCurrent.classList.remove("hidden");
    uploadWrap.classList.add("hidden");
    const resumeName = document.getElementById("edit-resume-name");
    if (resumeName) resumeName.textContent = user.resume.original_name || "Resume";
    attachResumeMenu(document.getElementById("edit-resume-menu"), user, {
      includeRemove: true,
      onReplace: () => document.getElementById("edit-resume-replace-input")?.click(),
      onRemove: async () => {
        homeUserData.resume = { has_resume: false };
        fillHomeEditForm(homeUserData);
      },
      errorTarget: "home-edit-error",
    });
  } else {
    resumeCurrent.classList.add("hidden");
    uploadWrap.classList.remove("hidden");
  }
}

function showHomeProfileView() {
  document.getElementById("home-profile-view")?.classList.remove("hidden");
  document.getElementById("home-profile-edit")?.classList.add("hidden");
  const editBtn = document.getElementById("home-edit-profile");
  if (editBtn) editBtn.textContent = "Edit";
  const err = document.getElementById("home-edit-error");
  if (err) err.innerHTML = "";
}

function showHomeProfileEdit() {
  if (!homeUserData) return;
  fillHomeEditForm(homeUserData);
  document.getElementById("home-profile-view")?.classList.add("hidden");
  document.getElementById("home-profile-edit")?.classList.remove("hidden");
  const editBtn = document.getElementById("home-edit-profile");
  if (editBtn) editBtn.textContent = "Cancel";
  const resumeFile = document.getElementById("edit-resume-file");
  const replaceInput = document.getElementById("edit-resume-replace-input");
  if (resumeFile) resumeFile.value = "";
  if (replaceInput) replaceInput.value = "";
}

function closeAllPersonaMenus() {
  document.querySelectorAll(".persona-menu-dropdown").forEach((el) => el.classList.add("hidden"));
}

window.attachPersonaMenu = function attachPersonaMenu(card, persona) {
  const menu = card.querySelector(".persona-menu");
  if (!menu) return;

  const trigger = menu.querySelector(".resume-menu-trigger");
  const dropdown = menu.querySelector(".resume-menu-dropdown");

  trigger?.addEventListener("click", (e) => {
    e.stopPropagation();
    const isOpen = !dropdown.classList.contains("hidden");
    closeAllPersonaMenus();
    if (!isOpen) dropdown.classList.remove("hidden");
  });

  dropdown.querySelector('[data-action="rename"]')?.addEventListener("click", (e) => {
    e.stopPropagation();
    closeAllPersonaMenus();
    openRenameAgentModal(persona);
  });

  dropdown.querySelector('[data-action="edit"]')?.addEventListener("click", async (e) => {
    e.stopPropagation();
    closeAllPersonaMenus();
    await openEditAgent(persona);
  });

  dropdown.querySelector('[data-action="delete"]')?.addEventListener("click", (e) => {
    e.stopPropagation();
    closeAllPersonaMenus();
    openDeleteAgentModal(persona);
  });
};

function openRenameAgentModal(persona) {
  pendingRenameSessionId = persona.session_id;
  const input = document.getElementById("agent-rename-input");
  const err = document.getElementById("agent-rename-error");
  if (input) input.value = persona.name || "";
  if (err) {
    err.textContent = "";
    err.classList.add("hidden");
  }
  const modal = document.getElementById("agent-rename-modal");
  modal?.classList.remove("hidden");
  modal?.setAttribute("aria-hidden", "false");
  input?.focus();
}

function closeRenameAgentModal() {
  pendingRenameSessionId = null;
  const modal = document.getElementById("agent-rename-modal");
  modal?.classList.add("hidden");
  modal?.setAttribute("aria-hidden", "true");
}

async function saveRenameAgent() {
  const input = document.getElementById("agent-rename-input");
  const err = document.getElementById("agent-rename-error");
  const name = input?.value?.trim();
  if (!name) {
    if (err) {
      err.textContent = "Please enter an agent name.";
      err.classList.remove("hidden");
    }
    return;
  }
  try {
    await api(`/agents/${pendingRenameSessionId}`, {
      method: "PUT",
      body: JSON.stringify({ full_name: name }),
    });
    closeRenameAgentModal();
    await loadHome();
  } catch (e) {
    if (err) {
      err.textContent = e.message;
      err.classList.remove("hidden");
    }
  }
}

function setAgentDeleteModalMode(mode) {
  const titleEl = document.getElementById("agent-delete-title");
  const bodyEl = document.getElementById("agent-delete-body");
  const confirmBtn = document.getElementById("agent-delete-confirm");
  const nameEl = document.getElementById("agent-delete-name");
  if (!nameEl) return;

  if (mode === "hide_roster") {
    if (titleEl) titleEl.textContent = "Remove from agents?";
    if (bodyEl) {
      bodyEl.innerHTML = `This removes <strong id="agent-delete-name">${escapeHtml(pendingDeleteAgentName)}</strong> from your AI agents list. Direct messages and chat history are kept.`;
    }
    if (confirmBtn) {
      confirmBtn.textContent = "Remove";
      confirmBtn.classList.remove("btn-danger");
      confirmBtn.classList.add("btn-primary");
    }
    return;
  }

  if (titleEl) titleEl.textContent = "Delete agent?";
  if (bodyEl) {
    bodyEl.innerHTML = `This will permanently delete <strong id="agent-delete-name">${escapeHtml(pendingDeleteAgentName)}</strong> and all associated artifacts (profile, skills, framework). This action cannot be undone.`;
  }
  if (confirmBtn) {
    confirmBtn.textContent = "Delete permanently";
    confirmBtn.classList.remove("btn-primary");
    confirmBtn.classList.add("btn-danger");
  }
}

function openDeleteAgentModal(persona) {
  pendingAgentAction = "delete";
  pendingDeleteSessionId = persona.session_id;
  pendingDeleteAgentName = persona.name || "this agent";
  const err = document.getElementById("agent-delete-error");
  if (err) {
    err.textContent = "";
    err.classList.add("hidden");
  }
  setAgentDeleteModalMode("delete");
  const modal = document.getElementById("agent-delete-modal");
  modal?.classList.remove("hidden");
  modal?.setAttribute("aria-hidden", "false");
}

function openRemoveFromRosterModal(agent) {
  pendingAgentAction = "hide_roster";
  pendingDeleteSessionId = agent.session_id;
  pendingDeleteAgentName = agent.name || "this agent";
  const err = document.getElementById("agent-delete-error");
  if (err) {
    err.textContent = "";
    err.classList.add("hidden");
  }
  setAgentDeleteModalMode("hide_roster");
  const modal = document.getElementById("agent-delete-modal");
  modal?.classList.remove("hidden");
  modal?.setAttribute("aria-hidden", "false");
}

function closeDeleteAgentModal() {
  pendingDeleteSessionId = null;
  pendingDeleteAgentName = "";
  pendingAgentAction = "delete";
  const modal = document.getElementById("agent-delete-modal");
  modal?.classList.add("hidden");
  modal?.setAttribute("aria-hidden", "true");
}

async function confirmDeleteAgent() {
  const err = document.getElementById("agent-delete-error");
  const btn = document.getElementById("agent-delete-confirm");
  if (!pendingDeleteSessionId) return;
  btn.disabled = true;
  try {
    if (pendingAgentAction === "hide_roster") {
      await api(`/agents/${pendingDeleteSessionId}/hide-from-roster`, { method: "POST" });
      closeDeleteAgentModal();
      const home = await api("/home");
      window.homePersonas = home.personas;
      await window.ChatWorkspace?.refresh?.(home);
    } else {
      await api(`/agents/${pendingDeleteSessionId}`, { method: "DELETE" });
      closeDeleteAgentModal();
      await loadHome();
    }
  } catch (e) {
    if (err) {
      err.textContent = e.message;
      err.classList.remove("hidden");
    }
  } finally {
    btn.disabled = false;
  }
}

async function openEditAgent(persona) {
  const agent = await api(`/agents/${persona.session_id}`);
  const ctx = agent.agent_context || {};
  await BackgroundWizard.open({
    mode: "edit_agent",
    sessionId: persona.session_id,
    prefill: {
      full_name: ctx.full_name,
      field: ctx.field,
      industry: ctx.industry,
      current_job: ctx.current_job,
      skillset: ctx.skillset,
      job_description: ctx.job_description,
      framework_design: ctx.framework_design,
    },
  });
}

function initAgentModals() {
  document.getElementById("agent-rename-close")?.addEventListener("click", closeRenameAgentModal);
  document.getElementById("agent-rename-cancel")?.addEventListener("click", closeRenameAgentModal);
  document.getElementById("agent-rename-backdrop")?.addEventListener("click", closeRenameAgentModal);
  document.getElementById("agent-rename-save")?.addEventListener("click", saveRenameAgent);
  document.getElementById("agent-rename-input")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); saveRenameAgent(); }
  });

  document.getElementById("agent-delete-close")?.addEventListener("click", closeDeleteAgentModal);
  document.getElementById("agent-delete-cancel")?.addEventListener("click", closeDeleteAgentModal);
  document.getElementById("agent-delete-backdrop")?.addEventListener("click", closeDeleteAgentModal);
  document.getElementById("agent-delete-confirm")?.addEventListener("click", confirmDeleteAgent);

  document.addEventListener("click", closeAllPersonaMenus);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeRenameAgentModal();
      closeDeleteAgentModal();
    }
  });
}

async function loadHome() {
  const data = await api("/home");
  homeUserData = data.user;
  window.homePersonas = data.personas || [];

  if (homeUserData) {
    renderHomeProfileView(homeUserData);
    showHomeProfileView();
    await window.ChatWorkspace?.refresh?.(data);
  }

  const list = document.getElementById("personas-list");
  if (!list || list.classList.contains("collab-legacy-hidden")) return;

  const empty = document.getElementById("personas-empty");
  list.innerHTML = "";
  if (!window.homePersonas.length) return;

  window.homePersonas.forEach((persona) => {
    const card = document.createElement("div");
    card.className = "persona-card";
    card.dataset.sessionId = persona.session_id;

    const trainingLabel = persona.status === "configured"
      ? "Personalized"
      : `${persona.training.completed}/${persona.training.total} tasks`;
    const statusBadge = persona.status === "completed"
      ? '<span class="persona-badge complete">Fully trained</span>'
      : persona.status === "configured"
        ? '<span class="persona-badge">Framework ready</span>'
        : '<span class="persona-badge">In training</span>';

    const skillsHtml = (persona.skills || [])
      .map((s) => `<span class="skill-tag">${escapeHtml(s)}</span>`)
      .join("");

    const jdHtml = window.renderJobDescriptionHtml?.(persona.job_description) || "";

    card.innerHTML = `
      <div class="persona-header">
        <div class="persona-icon">${persona.icon}</div>
        <div class="persona-meta">
          <h3>${escapeHtml(persona.name)}</h3>
          <p>${escapeHtml([persona.job_title, persona.field, persona.industry].filter(Boolean).join(" · ") || "Agent")}</p>
          <div class="persona-badges">
            <span class="persona-badge">${escapeHtml(trainingLabel)}</span>
            ${statusBadge}
          </div>
        </div>
        <div class="persona-header-actions">
          <button type="button" class="btn btn-primary btn-sm persona-chat-btn" data-session-id="${persona.session_id}">Chat</button>
          <div class="persona-menu resume-menu">
            <button type="button" class="resume-menu-trigger" aria-label="Agent options">⋮</button>
            <div class="resume-menu-dropdown hidden">
              <button type="button" data-action="rename">Rename</button>
              <button type="button" data-action="edit">Edit</button>
              <button type="button" data-action="delete" class="danger">Delete</button>
            </div>
          </div>
          <span class="persona-chevron">▾</span>
        </div>
      </div>
      <div class="persona-body">
        <div class="persona-section">
          <h4>Skills</h4>
          <div class="skill-tags">${skillsHtml || '<span class="skill-tag">No skills listed</span>'}</div>
        </div>
        ${jdHtml}
        <div class="persona-actions">
          ${persona.artifacts.skill_md_id ? `<a class="btn btn-secondary" href="/api/studio/artifacts/${persona.artifacts.skill_md_id}/download" style="padding:0.5rem 1rem;font-size:0.85rem">Download skills</a>` : ""}
          ${persona.artifacts.framework_json_id ? `<a class="btn btn-secondary" href="/api/studio/artifacts/${persona.artifacts.framework_json_id}/download" style="padding:0.5rem 1rem;font-size:0.85rem">Download framework</a>` : ""}
        </div>
      </div>
    `;

    card.querySelector(".persona-header").addEventListener("click", (e) => {
      if (e.target.closest(".persona-menu") || e.target.closest(".persona-chat-btn")) return;
      card.classList.toggle("expanded");
    });

    card.querySelector(".persona-chat-btn")?.addEventListener("click", (e) => {
      e.stopPropagation();
      openWorkspace(persona.session_id);
    });

    attachPersonaMenu(card, persona);
    list.appendChild(card);
  });
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

let collabNavGen = 0;

async function navigateCollabHash() {
  if (!window.ChatWorkspace) return;
  const gen = ++collabNavGen;
  const hash = location.hash.replace(/^#\/?/, "") || "";

  if (hash === "agents/browse") {
    await ChatWorkspace.showPrebuiltAgentsBrowse();
  } else if (hash.startsWith("agents/")) {
    const segment = hash.split("/")[1];
    const sessionId = parseInt(segment, 10);
    if (!Number.isNaN(sessionId)) {
      await ChatWorkspace.showAgentDetail(sessionId);
    } else {
      ChatWorkspace.showAgentsRoster();
    }
  } else if (hash === "agents") {
    ChatWorkspace.showAgentsRoster();
  } else if (hash.startsWith("chat/agent/")) {
    const sessionId = parseInt(hash.split("/")[2], 10);
    if (!Number.isNaN(sessionId)) await ChatWorkspace.openAgentDm(sessionId);
  } else if (hash.startsWith("project/")) {
    const parts = hash.split("/");
    const projectId = parseInt(parts[1], 10);
    const agentId = parts[2] === "agent" && parts[3] ? parseInt(parts[3], 10) : null;
    if (!Number.isNaN(projectId)) {
      await ChatWorkspace.openProject(projectId, null, Number.isNaN(agentId) ? null : agentId);
    }
  } else if (hash.startsWith("chat/thread/")) {
    const threadId = parseInt(hash.split("/")[2], 10);
    if (!Number.isNaN(threadId)) await ChatWorkspace.openThread(threadId);
  } else if (hash.startsWith("workspace/")) {
    const sessionId = parseInt(hash.split("/")[1], 10);
    if (!Number.isNaN(sessionId)) await ChatWorkspace.openAgentDm(sessionId);
  } else if (hash === "home" || hash === "") {
    if (gen === collabNavGen) ChatWorkspace.showWelcome();
  }

  if (gen !== collabNavGen) return;
}

async function goHome() {
  if (!currentUser) {
    showView("landing");
    return;
  }
  try {
    await loadHome();
    showView("home");
    ChatWorkspace.showWelcome();
  } catch {
    await initApp();
  }
}

async function openWorkspace(sessionId) {
  if (!currentUser) {
    showView("login");
    return;
  }
  showView("home");
  if (sessionId) await ChatWorkspace.openAgentDm(sessionId);
  else await navigateCollabHash();
}

window.goHome = goHome;
window.openWorkspace = openWorkspace;
window.showHomeProfileEdit = showHomeProfileEdit;
window.openDeleteAgentModal = openDeleteAgentModal;
window.openRemoveFromRosterModal = openRemoveFromRosterModal;

document.getElementById("home-edit-profile")?.addEventListener("click", () => {
  const editPanel = document.getElementById("home-profile-edit");
  const editing = editPanel && !editPanel.classList.contains("hidden");
  if (editing) {
    showHomeProfileView();
  } else {
    showHomeProfileEdit();
  }
});

document.getElementById("home-cancel-edit")?.addEventListener("click", showHomeProfileView);

document.getElementById("home-profile-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/profile", {
      method: "PUT",
      body: JSON.stringify({
        full_name: document.getElementById("edit-name").value,
        current_job: document.getElementById("edit-job").value,
        field: document.getElementById("edit-field").value,
        industry: document.getElementById("edit-industry").value,
        skillset: document.getElementById("edit-skillset").value,
      }),
    });

    const resumeFile = document.getElementById("edit-resume-file").files[0]
      || document.getElementById("edit-resume-replace-input").files[0];
    if (resumeFile) {
      await uploadResume(resumeFile);
    }

    await loadHome();
    showHomeProfileView();
  } catch (err) {
    showError("home-edit-error", err.message);
  }
});

document.getElementById("edit-resume-replace-input")?.addEventListener("change", (e) => {
  const file = e.target.files?.[0];
  if (!file) return;
  document.getElementById("edit-resume-name").textContent = file.name + " (pending save)";
});

document.getElementById("logo-home")?.addEventListener("click", goHome);
document.getElementById("logo-home")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    goHome();
  }
});
document.getElementById("collab-logo-home")?.addEventListener("click", goHome);
document.getElementById("collab-logo-home")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    goHome();
  }
});

document.getElementById("home-start-studio")?.addEventListener("click", async () => {
  await BackgroundWizard.open({
    mode: "new_agent",
    prefill: homeUserData || {},
  });
});

document.getElementById("home-new-agent")?.addEventListener("click", async () => {
  await BackgroundWizard.open({
    mode: "new_agent",
    prefill: {},
  });
});

// --- Billing / plans ---

let billingConfig = null;
let billingSubscription = null;

function formatUsd(amount) {
  return `$${Number(amount).toFixed(2)}`;
}

function formatTokenCount(count) {
  const n = Number(count || 0);
  if (n >= 1_000_000) {
    const millions = n / 1_000_000;
    const text = millions % 1 === 0 ? String(millions) : millions.toFixed(1);
    return `${text}M tokens`;
  }
  if (n >= 1_000) {
    const thousands = n / 1_000;
    const text = thousands % 1 === 0 ? String(thousands) : thousands.toFixed(1);
    return `${text}K tokens`;
  }
  return `${n.toLocaleString()} tokens`;
}

function formatPlanTokenAllowance(plan) {
  if (!plan) return "";
  return `${formatTokenCount(plan.monthly_token_count)}/mo`;
}

function formatPlanDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

async function loadBillingData() {
  billingConfig = await api("/billing/config");
  if (currentUser) {
    try {
      billingSubscription = await api("/billing/subscription");
    } catch {
      billingSubscription = null;
    }
  } else {
    billingSubscription = null;
  }
  return { billingConfig, billingSubscription };
}

function planPriceRank(planId) {
  const plans = billingConfig?.plans || [];
  return plans.findIndex((p) => p.id === planId);
}

function getCurrentPlanLabel() {
  const sub = billingSubscription;
  if (!sub?.access_granted) return "No plan";
  return sub.plan_name || sub.plan_id || "Active";
}

function getNextPlanTier() {
  const plans = billingConfig?.plans || [];
  const sub = billingSubscription;
  if (!sub?.access_granted) return plans[0] || null;
  const currentIdx = planPriceRank(sub.plan_id);
  if (currentIdx < 0 || currentIdx >= plans.length - 1) return null;
  return plans[currentIdx + 1];
}

function planActionLabel(planId) {
  const sub = billingSubscription;
  const hasAccess = Boolean(sub?.access_granted);
  const currentId = sub?.plan_id;
  const currentRank = hasAccess && currentId ? planPriceRank(currentId) : -1;
  const rank = planPriceRank(planId);
  const isCurrent = hasAccess && planId === currentId;

  if (isCurrent) return { label: "Current plan", disabled: true };
  if (hasAccess && currentRank >= 0 && rank > currentRank) return { label: "Upgrade", disabled: false };
  if (hasAccess && currentRank >= 0 && rank < currentRank) return { label: "Downgrade unavailable", disabled: true };
  return { label: "Subscribe", disabled: false };
}

function planCardHtml(plan, { buttonClass = "plan-select-btn" } = {}) {
  const action = planActionLabel(plan.id);
  const sub = billingSubscription;
  const isCurrent = Boolean(sub?.access_granted && sub?.plan_id === plan.id);
  const buyLabel = action.label === "Upgrade" || action.label === "Subscribe" ? action.label : action.label;

  return `
    <div class="plan-card${isCurrent ? " plan-card-current" : ""}" data-plan-id="${escapeHtml(plan.id)}">
      ${isCurrent ? '<span class="plan-card-badge">Current</span>' : ""}
      <div class="plan-card-name">${escapeHtml(plan.name)}</div>
      <div class="plan-card-price">${escapeHtml(plan.price_display)}<span>/mo</span></div>
      <div class="plan-card-tokens">${escapeHtml(formatPlanTokenAllowance(plan))}</div>
      <p class="plan-card-desc">${escapeHtml(plan.description)}</p>
      <button type="button" class="btn btn-primary btn-block ${buttonClass}"
        data-plan-id="${escapeHtml(plan.id)}"
        ${action.disabled ? "disabled" : ""}>${escapeHtml(buyLabel)}</button>
    </div>`;
}

function bindPlanSelectButtons(root, onSelect) {
  root?.querySelectorAll(".plan-select-btn:not([disabled])").forEach((btn) => {
    btn.addEventListener("click", () => onSelect(btn.dataset.planId, btn));
  });
}

function renderPlansUsage() {
  const wrap = document.getElementById("plans-usage");
  if (!wrap) return;

  const sub = billingSubscription;
  if (!sub?.access_granted) {
    wrap.classList.add("hidden");
    wrap.innerHTML = "";
    return;
  }

  const used = Number(sub.token_used_count ?? sub.token_used_usd ?? 0);
  const budget = Number(sub.token_budget_count ?? sub.token_budget_usd ?? 0);
  const pct = budget > 0 ? Math.min(100, (used / budget) * 100) : 0;
  const cancelNote = sub.cancel_at_period_end
    ? `<p class="plans-usage-cancel">Cancels on ${formatPlanDate(sub.current_period_end)}</p>`
    : "";

  wrap.classList.remove("hidden");
  wrap.innerHTML = `
    <p class="plans-usage-title">Current plan — ${escapeHtml(sub.plan_name || sub.plan_id || "Active")}</p>
    <div class="plans-usage-row">
      <div class="plans-usage-stat">
        <div>Token usage</div>
        <strong>${escapeHtml(formatTokenCount(used))} / ${escapeHtml(formatTokenCount(budget))}</strong>
        <div class="plans-usage-bar"><div class="plans-usage-bar-fill" style="width:${pct}%"></div></div>
      </div>
      <div class="plans-usage-stat">
        <div>Billing period ends</div>
        <strong>${formatPlanDate(sub.current_period_end)}</strong>
      </div>
    </div>
    ${cancelNote}
    <div class="plans-usage-actions">
      ${sub.cancel_at_period_end
        ? '<button type="button" class="btn btn-primary btn-sm" id="plans-reactivate-btn">Reactivate subscription</button>'
        : '<button type="button" class="btn btn-secondary btn-sm" id="plans-cancel-btn">Cancel at period end</button>'}
    </div>
  `;

  document.getElementById("plans-cancel-btn")?.addEventListener("click", handlePlansCancel);
  document.getElementById("plans-reactivate-btn")?.addEventListener("click", handlePlansReactivate);
}

function renderPlansGrid() {
  const grid = document.getElementById("plans-grid");
  if (!grid || !billingConfig?.plans) return;

  grid.innerHTML = billingConfig.plans.map((plan) => planCardHtml(plan)).join("");
  bindPlanSelectButtons(grid, (planId) => checkoutPlan(planId));
}

async function renderPlansPage() {
  const msg = document.getElementById("plans-message");
  if (msg) msg.innerHTML = "";
  await loadBillingData();
  renderPlansUsage();
  renderPlansGrid();
}

async function checkoutPlan(planId, options = {}) {
  const {
    messageElId = "plans-message",
    errorElId = "plans-error",
    refreshPlansPage = true,
    onUpdated,
  } = options;

  const msgEl = messageElId ? document.getElementById(messageElId) : null;
  const errEl = errorElId ? document.getElementById(errorElId) : null;
  if (msgEl) msgEl.innerHTML = "";
  if (errEl) errEl.innerHTML = "";

  const sub = billingSubscription;
  const isUpgrade = Boolean(sub?.access_granted && sub?.plan_id);
  const endpoint = isUpgrade && planPriceRank(planId) > planPriceRank(sub.plan_id)
    ? "/billing/upgrade"
    : "/billing/checkout";

  try {
    const res = await api(endpoint, {
      method: "POST",
      body: JSON.stringify({
        plan_id: planId,
        success_url: `${window.location.origin}/#/plans/success`,
        cancel_url: `${window.location.origin}/#/home`,
      }),
    });
    if (res.checkout_url) {
      window.location.href = res.checkout_url;
      return res;
    }
    billingSubscription = res.subscription || await api("/billing/subscription");
    if (msgEl) {
      msgEl.innerHTML = `<div class="alert alert-success">${escapeHtml(res.message || "Plan updated.")}</div>`;
    }
    trackEvent(isUpgrade ? "plan_upgraded" : "subscription_activated", { plan_id: planId });
    if (refreshPlansPage) await renderPlansPage();
    if (onUpdated) await onUpdated(res);
    else if (billingSubscription?.access_granted && refreshPlansPage) {
      await enterWorkspaceAfterSubscribe();
    }
    return res;
  } catch (err) {
    if (errEl) {
      errEl.innerHTML = `<div class="alert alert-error">${escapeHtml(err.message)}</div>`;
    } else {
      showError(errorElId || "plans-error", err.message);
    }
    throw err;
  }
}

async function cancelSubscription() {
  const res = await api("/billing/cancel", { method: "POST" });
  billingSubscription = res.subscription;
  return res;
}

async function reactivateSubscription() {
  const res = await api("/billing/reactivate", { method: "POST" });
  billingSubscription = res.subscription;
  return res;
}

async function handlePlansCancel() {
  try {
    const res = await cancelSubscription();
    const msgEl = document.getElementById("plans-message");
    if (msgEl && res.message) {
      msgEl.innerHTML = `<div class="alert alert-success">${escapeHtml(res.message)}</div>`;
    }
    renderPlansUsage();
    trackEvent("subscription_cancel_scheduled");
  } catch (err) {
    showError("plans-error", err.message);
  }
}

async function handlePlansReactivate() {
  try {
    await reactivateSubscription();
    renderPlansUsage();
    trackEvent("subscription_reactivated");
  } catch (err) {
    showError("plans-error", err.message);
  }
}

async function enterWorkspaceAfterSubscribe() {
  await loadHome();
  showView("home");
  if (window.ChatWorkspace) {
    await navigateCollabHash();
  }
}

document.getElementById("plans-go-home")?.addEventListener("click", () => {
  if (billingSubscription?.access_granted) {
    enterWorkspaceAfterSubscribe();
  } else {
    goHome();
  }
});

document.getElementById("plans-success-continue")?.addEventListener("click", async () => {
  await loadBillingData();
  await enterWorkspaceAfterSubscribe();
});

async function openAccountPlansModal() {
  const onHome = !document.querySelector('[data-view="home"]')?.classList.contains("hidden");
  if (!onHome) {
    await loadHome();
    showView("home");
    if (window.ChatWorkspace && window.navigateCollabHash) await navigateCollabHash();
  }
  await window.ChatWorkspace?.openAccountPlans?.();
}

// --- Init ---

async function initApp(options = {}) {
  const { skipView = false, preferView = null } = options;
  try {
    currentUser = await api("/auth/me");
    const userEmailEl = document.getElementById("user-email");
    if (userEmailEl) userEmailEl.textContent = currentUser.email;
    window.ChatWorkspace?.updateUserFooter?.();
    const navAuthed = document.getElementById("nav-authed");
    if (navAuthed) {
      navAuthed.classList.remove("hidden");
      navAuthed.style.display = "flex";
    }
    document.getElementById("nav-guest")?.classList.add("hidden");

    await loadBillingData();

    const hash = location.hash.replace(/^#\/?/, "") || "";
    if (preferView === "plans/success" || hash === "plans/success") {
      if (!skipView) showView("plans/success");
      return;
    }

    if (preferView === "plans" || hash === "plans") {
      await loadHome();
      if (!skipView) showView("home");
      if (window.ChatWorkspace) {
        await navigateCollabHash();
        if (!skipView) await window.ChatWorkspace.openAccountPlans?.();
      }
      return;
    }

    await loadHome();
    if (!skipView) showView("home");
    if (window.ChatWorkspace) {
      await navigateCollabHash();
    } else {
      console.error("ChatWorkspace failed to load — check the browser console for script errors.");
    }
  } catch (err) {
    console.error("initApp failed:", err);
    currentUser = null;
    showView("landing");
  }
}

function scrollToLandingAuth(mode = "login") {
  setLandingAuthMode(mode);
  showView("landing");
  document.getElementById("landing-auth-card")?.scrollIntoView({ behavior: "smooth", block: "center" });
  document.getElementById("landing-auth-email")?.focus();
}

document.getElementById("show-login")?.addEventListener("click", () => scrollToLandingAuth("login"));
document.getElementById("show-register")?.addEventListener("click", () => scrollToLandingAuth("register"));
document.getElementById("show-login-footer")?.addEventListener("click", () => scrollToLandingAuth("login"));
document.getElementById("show-register-footer")?.addEventListener("click", () => scrollToLandingAuth("register"));
document.getElementById("auth-go-register")?.addEventListener("click", () => showView("register"));
document.getElementById("auth-go-login")?.addEventListener("click", () => showView("login"));
document.getElementById("go-billing")?.addEventListener("click", () => {
  openAccountPlansModal();
});
document.getElementById("go-home")?.addEventListener("click", goHome);
document.getElementById("nav-workspace")?.addEventListener("click", () => {
  showView("home");
  ChatWorkspace.showWelcome();
});

function applyAuthUi(config) {
  authRequired = config.auth_required !== false;
  const devHintText = !authRequired
    ? (config.demo_login
        ? `Dev mode: login is optional. Demo account — ${config.demo_login.email} / ${config.demo_login.password}`
        : "Dev mode: login is optional. You'll be signed in automatically.")
    : "";

  ["login-dev-hint", "landing-auth-dev-hint"].forEach((id) => {
    const hint = document.getElementById(id);
    if (!hint) return;
    if (!authRequired) {
      hint.textContent = devHintText;
      hint.classList.remove("hidden");
    } else {
      hint.classList.add("hidden");
    }
  });
}

async function tryRestoreSession() {
  try {
    currentUser = await api("/auth/me");
    const userEmailEl = document.getElementById("user-email");
    if (userEmailEl) userEmailEl.textContent = currentUser.email;
    return true;
  } catch {
    currentUser = null;
    return false;
  }
}

async function bootstrap() {
  window.api = api;
  window.showView = showView;
  window.loadHome = loadHome;
  window.trackEvent = trackEvent;
  window.Billing = {
    load: loadBillingData,
    getConfig: () => billingConfig,
    getSubscription: () => billingSubscription,
    formatUsd,
    formatTokenCount,
    formatPlanTokenAllowance,
    formatPlanDate,
    getCurrentPlanLabel,
    getNextPlanTier,
    planPriceRank,
    planActionLabel,
    planCardHtml,
    bindPlanSelectButtons,
    checkoutPlan,
    cancel: cancelSubscription,
    reactivate: reactivateSubscription,
    renderPlansUsage,
    renderPlansGrid,
  };
  BackgroundWizard.init();
  if (!window.ChatWorkspace) {
    console.error("chat-workspace.js did not load. Collaboration features will be unavailable.");
  } else {
    ChatWorkspace.init();
  }
  initAgentModals();

  window.navigateCollabHash = navigateCollabHash;

  window.addEventListener("hashchange", () => {
    if (document.querySelector('[data-view="home"]')?.classList.contains("hidden")) return;
    if (window.ChatWorkspace?.shouldHandleHashChange?.() === false) return;
    navigateCollabHash();
  });

  let config = { auth_required: true };
  try {
    config = await fetch("/api/config").then((r) => r.json());
  } catch (_) {}
  applyAuthUi(config);

  const recovery = parseSupabaseRecoveryHash();
  if (recovery) {
    recoveryTokens = recovery;
    stripRecoveryHashFromUrl();
    showView("reset-password");
    initPasswordToggles();
    return;
  }

  const hash = location.hash.replace(/^#\/?/, "") || "";

  if (!authRequired) {
    await initApp();
    return;
  }

  if (hash === "plans" || hash === "plans/success") {
    if (await tryRestoreSession()) {
      await initApp({ preferView: hash });
    } else {
      showView("login");
    }
    return;
  }

  if (await tryRestoreSession()) {
    await initApp();
    if (hash === "login" || hash === "register" || hash === "landing") {
      showView("home");
    }
    return;
  }

  if (hash === "login" || hash === "register" || hash === "reset-password") {
    showView(hash);
    if (hash === "reset-password") initPasswordToggles();
  } else {
    showView("landing");
  }
}

setLandingAuthMode("login");
initPasswordToggles();
bootstrap();
