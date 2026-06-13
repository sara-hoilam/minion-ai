/**
 * Agent personalization wizard.
 * Flow: persona bubbles → editable JD → framework design (+ optional construction questions)
 */
const BackgroundWizard = (() => {
  const OTHER = "Other";
  const MAX_AGENT_SKILLS = 8;
  const PLATFORM_SKILL_KEYS = new Set(["first principles thinking", "current data awareness"]);

  let catalog = null;
  let mode = "initial";
  let editSessionId = null;
  let stepIndex = 0;
  let steps = [];
  let state = {
    agent_name: "",
    field_id: "",
    field_label: "",
    field_custom: "",
    industry: "",
    industry_custom: "",
    current_job: "",
    role_custom: "",
    skills: [],
    custom_skills: [],
    jdDraft: null,
    jdLoading: false,
    frameworkPreview: null,
    frameworkLoading: false,
    frameworkBuildProgress: null,
    jdBuildProgress: null,
    lastFrameworkJdSnapshot: null,
    lastFrameworkSkillsetSnapshot: null,
    constructionAnswers: {},
  };

  const els = {};
  let jdRevealTimer = null;
  let frameworkProgressTimer = null;
  let frameworkLoadGeneration = 0;
  let frameworkDisplayPercent = 0;
  let frameworkTargetPercent = 0;

  function cacheElements() {
    els.view = document.querySelector('[data-view="background"]');
    els.back = document.getElementById("bg-back");
    els.progress = document.getElementById("bg-progress");
    els.title = document.getElementById("bg-step-title");
    els.subtitle = document.getElementById("bg-step-subtitle");
    els.body = document.getElementById("bg-step-body");
    els.next = document.getElementById("bg-next");
    els.error = document.getElementById("background-error");
    els.customField = document.getElementById("bg-field-custom-wrap");
    els.customFieldInput = document.getElementById("bg-field-custom");
    els.industryCustomWrap = document.getElementById("bg-industry-custom-wrap");
    els.industryCustomInput = document.getElementById("bg-industry-custom");
    els.roleCustomWrap = document.getElementById("bg-role-custom-wrap");
    els.roleCustomInput = document.getElementById("bg-role-custom");
    els.skillsCustomWrap = document.getElementById("bg-skills-custom-wrap");
    els.skillCustomInput = document.getElementById("bg-skill-custom-input");
    els.skillAddBtn = document.getElementById("bg-skill-add-btn");
    els.customSkillsTags = document.getElementById("bg-custom-skills-tags");
    els.nameWrap = document.getElementById("bg-name-wrap");
    els.nameInput = document.getElementById("bg-name-input");
  }

  function hideCustomInputs() {
    els.customField?.classList.add("hidden");
    els.industryCustomWrap?.classList.add("hidden");
    els.roleCustomWrap?.classList.add("hidden");
    els.skillsCustomWrap?.classList.add("hidden");
    els.nameWrap?.classList.add("hidden");
  }

  function fieldLabel() {
    if (state.field_id === "other") return state.field_custom.trim() || OTHER;
    return state.field_label;
  }

  function resolvedIndustry() {
    if (state.industry === OTHER) return state.industry_custom.trim();
    return state.industry;
  }

  function resolvedRole() {
    if (state.current_job === OTHER) return state.role_custom.trim();
    return state.current_job;
  }

  function allSkills() {
    return [...new Set([...state.skills, ...state.custom_skills]
      .map((s) => s.trim())
      .filter(Boolean)
      .filter((s) => !PLATFORM_SKILL_KEYS.has(s.toLowerCase())))];
  }

  function skillsetString() {
    return allSkills().slice(0, MAX_AGENT_SKILLS).join(", ");
  }

  function skillsAtCapacity() {
    return allSkills().length >= MAX_AGENT_SKILLS;
  }

  function enforceSkillLimit() {
    const merged = allSkills();
    if (merged.length <= MAX_AGENT_SKILLS) return;
    const kept = new Set(merged.slice(0, MAX_AGENT_SKILLS));
    state.skills = state.skills.filter((s) => kept.has(s));
    state.custom_skills = state.custom_skills.filter((s) => kept.has(s));
  }

  function updateSkillsCapacityUI() {
    const atCap = skillsAtCapacity();
    const count = allSkills().length;
    if (els.skillAddBtn) {
      els.skillAddBtn.disabled = atCap;
      els.skillAddBtn.classList.toggle("hidden", atCap);
    }
    if (els.skillCustomInput) {
      els.skillCustomInput.disabled = atCap;
      els.skillCustomInput.placeholder = atCap
        ? `Maximum ${MAX_AGENT_SKILLS} skills reached`
        : "Type a skill and press Add";
    }
    if (els.skillsCustomWrap) {
      els.skillsCustomWrap.classList.toggle("skills-at-capacity", atCap);
    }
    if (els.subtitle && steps[stepIndex] === "skills") {
      els.subtitle.textContent = `Choose up to ${MAX_AGENT_SKILLS} skills from suggestions or add your own. (${count}/${MAX_AGENT_SKILLS} selected)`;
    }
    if (els.subtitle && steps[stepIndex] === "framework") {
      els.subtitle.textContent = `Adjust skills or review the framework below. (${count}/${MAX_AGENT_SKILLS} skills)`;
    }
  }

  function onSkillsChanged() {
    updateSkillsCapacityUI();
    if (steps[stepIndex] === "framework") {
      syncConstructionAnswersFromDOM();
      state.frameworkPreview = null;
    }
    renderStep();
  }

  function removeSkill(skill) {
    state.skills = state.skills.filter((s) => s !== skill);
    state.custom_skills = state.custom_skills.filter((s) => s !== skill);
    els.error.innerHTML = "";
    onSkillsChanged();
  }

  function showSkillLimitError() {
    if (!els.error) return;
    els.error.innerHTML = `<div class="alert alert-error">Maximum ${MAX_AGENT_SKILLS} skills per agent — remove one to add another.</div>`;
  }

  function buildSteps() {
    return ["name", "field", "industry", "role", "skills", "jd", "framework"];
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function buildJdThoughtChain() {
    const name = state.agent_name || "your agent";
    const field = fieldLabel();
    const role = resolvedRole() || "Specialist";
    const industry = resolvedIndustry() || "your industry";
    const skills = allSkills();
    const skillPreview = skills.length
      ? `${skills.slice(0, 4).join(", ")}${skills.length > 4 ? ` +${skills.length - 4} more` : ""}`
      : "core domain skills";
    return [
      `Reviewing profile for ${name} (${role} in ${field})`,
      `Grounding the role in ${industry} context`,
      `Mapping responsibilities to skills: ${skillPreview}`,
      "Drafting a concise role summary (2–3 sentences)",
      "Writing 4–6 specific, actionable responsibility bullets",
      "Aligning language with hiring-manager review standards",
      "Polishing title format and stakeholder-ready wording",
    ];
  }

  function renderBuildProgressPanel(progress, fallbackPhase) {
    const p = progress || { percent: 0, phase: fallbackPhase, logs: [] };
    const displayPercent = Math.round(p.displayPercent ?? p.percent ?? 0);
    const logs = p.logs || [];
    const logsHtml = logs.length
      ? logs.map((entry) => {
          const status = entry.status || "done";
          const icon = status === "active"
            ? '<span class="framework-build-spinner" aria-hidden="true"></span>'
            : status === "done"
              ? '<span class="framework-build-check" aria-hidden="true">✓</span>'
              : '<span class="framework-build-dot" aria-hidden="true">○</span>';
          return `<li class="framework-build-log-item status-${status}">${icon}<span>${escapeHtml(entry.message || "")}</span></li>`;
        }).join("")
      : `<li class="framework-build-log-item status-active"><span class="framework-build-spinner" aria-hidden="true"></span><span>${escapeHtml(fallbackPhase)}</span></li>`;

    return `
      <div class="framework-build-panel">
        <div class="framework-build-header">
          <span class="framework-build-phase">${escapeHtml(p.phase || fallbackPhase)}</span>
          <span class="framework-build-percent">${displayPercent}%</span>
        </div>
        <div class="framework-build-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${displayPercent}">
          <div class="framework-build-bar-fill" style="width: ${Math.max(4, displayPercent)}%"></div>
        </div>
        <ol class="framework-build-log">${logsHtml}</ol>
      </div>`;
  }

  function renderJdBuildProgress() {
    return renderBuildProgressPanel(state.jdBuildProgress, "Drafting job description…");
  }

  function updateJdBuildUI() {
    if (!state.jdLoading || !els.body || steps[stepIndex] !== "jd") return;
    els.body.innerHTML = renderJdBuildProgress();
    const log = els.body.querySelector(".framework-build-log");
    if (log) log.scrollTop = log.scrollHeight;
  }

  function clearJdRevealTimer() {
    if (jdRevealTimer) {
      clearInterval(jdRevealTimer);
      jdRevealTimer = null;
    }
  }

  function startJdThoughtReveal() {
    clearJdRevealTimer();
    const chain = buildJdThoughtChain();
    let reveal = 0;

    const tick = () => {
      if (!state.jdLoading) return;
      if (reveal >= chain.length) return;
      reveal += 1;
      const logs = chain.slice(0, reveal).map((message, i) => ({
        message,
        status: i === reveal - 1 ? "active" : "done",
      }));
      const percent = Math.min(92, Math.round((reveal / chain.length) * 88) + 8);
      state.jdBuildProgress = {
        phase: chain[reveal - 1],
        logs,
        percent,
      };
      updateJdBuildUI();
    };

    tick();
    jdRevealTimer = setInterval(tick, 900);
  }

  function clearFrameworkProgressTimer() {
    if (frameworkProgressTimer) {
      clearInterval(frameworkProgressTimer);
      frameworkProgressTimer = null;
    }
  }

  function startFrameworkProgressAnimation() {
    clearFrameworkProgressTimer();
    frameworkDisplayPercent = 0;
    frameworkTargetPercent = 0;
    frameworkProgressTimer = setInterval(() => {
      if (!state.frameworkLoading) return;
      const gap = frameworkTargetPercent - frameworkDisplayPercent;
      if (gap > 0.05) {
        frameworkDisplayPercent += Math.max(0.35, gap * 0.14);
        if (frameworkDisplayPercent > frameworkTargetPercent) {
          frameworkDisplayPercent = frameworkTargetPercent;
        }
      } else if (frameworkTargetPercent < 96) {
        frameworkDisplayPercent = Math.min(
          frameworkDisplayPercent + 0.18,
          frameworkTargetPercent + 2.5,
          95,
        );
      }
      if (state.frameworkBuildProgress) {
        state.frameworkBuildProgress.displayPercent = frameworkDisplayPercent;
        updateFrameworkBuildUI();
      }
    }, 100);
  }

  function stopFrameworkProgressAnimation(finalPercent) {
    clearFrameworkProgressTimer();
    if (finalPercent != null) {
      frameworkDisplayPercent = finalPercent;
      frameworkTargetPercent = finalPercent;
    }
  }

  function renderFrameworkBuildProgress() {
    const p = state.frameworkBuildProgress || { percent: 0, phase: "Starting…", logs: [] };
    return renderBuildProgressPanel(
      { ...p, displayPercent: p.displayPercent ?? frameworkDisplayPercent ?? p.percent },
      "Designing framework…",
    );
  }

  function updateFrameworkBuildUI() {
    if (!state.frameworkLoading || !els.body) return;
    els.body.innerHTML = renderFrameworkBuildProgress();
    const log = els.body.querySelector(".framework-build-log");
    if (log) log.scrollTop = log.scrollHeight;
  }

  async function pollFrameworkBuildJob(jobId, loadId) {
    while (true) {
      if (loadId !== frameworkLoadGeneration) return null;
      const status = await window.api(`/agents/framework-preview/jobs/${jobId}`);
      frameworkTargetPercent = status.percent ?? 0;
      state.frameworkBuildProgress = {
        percent: status.percent ?? 0,
        displayPercent: frameworkDisplayPercent,
        phase: status.phase || "Designing framework…",
        logs: status.logs || [],
      };
      updateFrameworkBuildUI();

      if (status.status === "complete") {
        stopFrameworkProgressAnimation(100);
        state.frameworkBuildProgress = {
          ...state.frameworkBuildProgress,
          percent: 100,
          displayPercent: 100,
        };
        updateFrameworkBuildUI();
        return status.result;
      }
      if (status.status === "failed") {
        throw new Error(status.error || "Framework build failed");
      }
      await sleep(450);
    }
  }

  function renderBubbles(items, { multi = false, selected = [], onSelect, getKey = (x) => x, getLabel = (x) => x }) {
    const wrap = document.createElement("div");
    wrap.className = multi ? "bubble-grid bubble-grid-multi" : "bubble-grid";

    items.forEach((item) => {
      const key = getKey(item);
      const label = getLabel(item);
      const isSelected = multi ? selected.includes(key) : selected === key;
      const atCap = multi && skillsAtCapacity() && !isSelected;

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "bubble" + (isSelected ? " selected" : "") + (atCap ? " bubble-disabled" : "");
      btn.disabled = atCap;
      if (atCap) btn.setAttribute("aria-disabled", "true");
      btn.innerHTML = `
        <span class="bubble-label">${escapeHtml(label)}</span>
        <span class="bubble-check" aria-hidden="true">${multi ? (isSelected ? "✓" : "+") : (isSelected ? "✓" : "")}</span>
      `;

      btn.addEventListener("click", () => {
        if (multi) {
          const idx = selected.indexOf(key);
          if (idx >= 0) {
            selected.splice(idx, 1);
            els.error.innerHTML = "";
          } else if (skillsAtCapacity()) {
            showSkillLimitError();
            return;
          } else {
            selected.push(key);
            els.error.innerHTML = "";
          }
        } else {
          onSelect(key, item);
          renderStep();
          return;
        }
        onSkillsChanged();
      });

      wrap.appendChild(btn);
    });

    return wrap;
  }

  function renderCustomSkillTags() {
    if (!els.customSkillsTags) return;
    els.customSkillsTags.innerHTML = state.custom_skills
      .map((skill) => `
        <span class="skill-tag skill-tag-removable">
          ${escapeHtml(skill)}
          <button type="button" class="skill-tag-remove" data-skill="${escapeHtml(skill)}" aria-label="Remove">×</button>
        </span>
      `)
      .join("");

    els.customSkillsTags.querySelectorAll(".skill-tag-remove").forEach((btn) => {
      btn.addEventListener("click", () => removeSkill(btn.dataset.skill));
    });
  }

  function addCustomSkill() {
    const value = els.skillCustomInput?.value?.trim();
    if (!value) return;
    if (skillsAtCapacity() && !state.custom_skills.includes(value) && !state.skills.includes(value)) {
      showSkillLimitError();
      return;
    }
    if (!state.custom_skills.includes(value) && !state.skills.includes(value)) {
      state.custom_skills.push(value);
      els.error.innerHTML = "";
    }
    if (els.skillCustomInput) els.skillCustomInput.value = "";
    renderCustomSkillTags();
    onSkillsChanged();
  }

  function autoResizeField(el) {
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }

  function syncJdFromDOM() {
    if (!state.jdDraft) return;

    const titleInput = document.getElementById("jd-edit-title");
    const summaryInput = document.getElementById("jd-edit-summary");
    if (titleInput) state.jdDraft.title = titleInput.value;
    if (summaryInput) state.jdDraft.summary = summaryInput.value;

    state.jdDraft.responsibilities = [];
    document.querySelectorAll(".jd-doc-bullet").forEach((input) => {
      const val = input.value.trim();
      if (val) state.jdDraft.responsibilities.push(val);
    });
  }

  function appendResponsibilityRow(text = "") {
    const list = document.getElementById("jd-resp-list");
    if (!list) return;

    const li = document.createElement("li");
    li.className = "jd-doc-item";
    li.innerHTML = `
      <span class="jd-doc-bullet-marker" aria-hidden="true">•</span>
      <textarea class="jd-doc-bullet" rows="1" placeholder="Add a responsibility…">${escapeHtml(text)}</textarea>
      <button type="button" class="jd-resp-remove" aria-label="Remove">×</button>
    `;

    const textarea = li.querySelector(".jd-doc-bullet");
    const removeBtn = li.querySelector(".jd-resp-remove");

    textarea.addEventListener("input", () => {
      autoResizeField(textarea);
      syncJdFromDOM();
    });
    removeBtn.addEventListener("click", () => {
      syncJdFromDOM();
      const idx = [...list.querySelectorAll(".jd-doc-item")].indexOf(li);
      if (idx >= 0) state.jdDraft.responsibilities.splice(idx, 1);
      li.remove();
      if (!list.querySelector(".jd-doc-item")) appendResponsibilityRow("");
    });

    list.appendChild(li);
    autoResizeField(textarea);
    textarea.focus();
  }

  function attachJdDocumentHandlers() {
    const title = document.getElementById("jd-edit-title");
    const summary = document.getElementById("jd-edit-summary");

    title?.addEventListener("input", syncJdFromDOM);
    summary?.addEventListener("input", () => {
      autoResizeField(summary);
      syncJdFromDOM();
    });

    document.querySelectorAll(".jd-doc-bullet").forEach((ta) => {
      ta.addEventListener("input", () => {
        autoResizeField(ta);
        syncJdFromDOM();
      });
    });

    document.querySelectorAll(".jd-resp-remove").forEach((btn) => {
      btn.addEventListener("click", () => {
        syncJdFromDOM();
        const li = btn.closest(".jd-doc-item");
        const list = document.getElementById("jd-resp-list");
        const idx = [...list.querySelectorAll(".jd-doc-item")].indexOf(li);
        if (idx >= 0) state.jdDraft.responsibilities.splice(idx, 1);
        li?.remove();
        if (list && !list.querySelector(".jd-doc-item")) appendResponsibilityRow("");
      });
    });

    document.getElementById("jd-add-resp")?.addEventListener("click", () => {
      syncJdFromDOM();
      state.jdDraft.responsibilities.push("");
      appendResponsibilityRow("");
    });
  }

  function renderJdStep() {
    const jd = state.jdDraft;
    const responsibilities = jd.responsibilities?.length ? jd.responsibilities : [""];

    const respHtml = responsibilities.map((r) => `
      <li class="jd-doc-item">
        <span class="jd-doc-bullet-marker" aria-hidden="true">•</span>
        <textarea class="jd-doc-bullet" rows="1" placeholder="Add a responsibility…">${escapeHtml(r)}</textarea>
        <button type="button" class="jd-resp-remove" aria-label="Remove">×</button>
      </li>
    `).join("");

    els.body.innerHTML = `
      <p class="validation-hint">Edit directly on the document below — like a notes page.</p>
      <div class="jd-document" id="jd-document">
        <p class="validation-heading jd-doc-label">Proposed job description</p>
        <textarea id="jd-edit-title" class="jd-doc-title" rows="1" placeholder="Role title…">${escapeHtml(jd.title || "")}</textarea>
        <textarea id="jd-edit-summary" class="jd-doc-summary" rows="2" placeholder="Role summary…">${escapeHtml(jd.summary || "")}</textarea>
        <p class="jd-doc-label">Responsibilities</p>
        <ul class="jd-doc-list" id="jd-resp-list">${respHtml}</ul>
        <button type="button" class="jd-doc-add" id="jd-add-resp">+ Add responsibility</button>
      </div>
    `;

    autoResizeField(document.getElementById("jd-edit-title"));
    autoResizeField(document.getElementById("jd-edit-summary"));
    document.querySelectorAll(".jd-doc-bullet").forEach(autoResizeField);
    attachJdDocumentHandlers();
  }

  function jdSnapshot() {
    return JSON.stringify(state.jdDraft || {});
  }

  function skillsetSnapshot() {
    return JSON.stringify(allSkills());
  }

  function renderSelectedSkillsTagsHtml() {
    const skills = allSkills();
    if (!skills.length) {
      return `<p class="validation-hint framework-skills-empty">No skills selected — add at least one below.</p>`;
    }
    return `<div class="skill-tags framework-selected-skills">${skills.map((skill) => `
      <span class="skill-tag skill-tag-removable">
        ${escapeHtml(skill)}
        <button type="button" class="skill-tag-remove framework-skill-remove" data-skill="${escapeHtml(skill)}" aria-label="Remove ${escapeHtml(skill)}">×</button>
      </span>
    `).join("")}</div>`;
  }

  function renderFrameworkSkillsCustomInputHtml() {
    const atCap = skillsAtCapacity();
    return `
      <div class="framework-skills-custom${atCap ? " skills-at-capacity" : ""}">
        <label class="framework-skills-custom-label">Add custom skill</label>
        <div class="skill-tag-input-row">
          <input type="text" id="framework-skill-custom-input" placeholder="${atCap ? `Maximum ${MAX_AGENT_SKILLS} skills reached` : "Type a skill and press Add"}"${atCap ? " disabled" : ""}>
          <button type="button" class="btn btn-secondary btn-sm" id="framework-skill-add-btn"${atCap ? " disabled" : ""}>Add</button>
        </div>
      </div>`;
  }

  function attachFrameworkSkillsHandlers() {
    document.querySelectorAll(".framework-skill-remove").forEach((btn) => {
      btn.addEventListener("click", () => removeSkill(btn.dataset.skill));
    });

    const addBtn = document.getElementById("framework-skill-add-btn");
    const input = document.getElementById("framework-skill-custom-input");
    const catalogSkills = catalog?.skills_by_field?.[state.field_id] || catalog?.skills_by_field?.other || [];

    const addFromFramework = () => {
      const value = input?.value?.trim();
      if (!value) return;
      if (skillsAtCapacity() && !allSkills().includes(value)) {
        showSkillLimitError();
        return;
      }
      if (!state.skills.includes(value) && !state.custom_skills.includes(value)) {
        if (catalogSkills.includes(value)) {
          state.skills.push(value);
        } else {
          state.custom_skills.push(value);
        }
        els.error.innerHTML = "";
      }
      if (input) input.value = "";
      onSkillsChanged();
    };

    addBtn?.addEventListener("click", addFromFramework);
    input?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); addFromFramework(); }
    });

    const bubblesWrap = document.getElementById("framework-skills-bubbles");
    if (bubblesWrap) {
      bubblesWrap.appendChild(renderBubbles(catalogSkills, { multi: true, selected: state.skills }));
    }
  }

  function defaultConstructionAnswer() {
    return { choice: "", manual_text: "" };
  }

  function normalizeConstructionAnswer(raw) {
    if (!raw || typeof raw !== "object") {
      const text = typeof raw === "string" ? raw.trim() : "";
      return text ? { choice: "manual", manual_text: text } : defaultConstructionAnswer();
    }
    return {
      choice: raw.choice || "",
      manual_text: raw.manual_text || "",
    };
  }

  function constructionAnswerText(question, answer) {
    const normalized = normalizeConstructionAnswer(answer);
    if (normalized.choice === "manual") return normalized.manual_text.trim();
    if (normalized.choice) {
      const opt = (question.options || []).find((o) => o.id === normalized.choice);
      return opt ? `${normalized.choice}: ${opt.label}` : normalized.choice;
    }
    return normalized.manual_text.trim();
  }

  function syncConstructionAnswersFromDOM() {
    document.querySelectorAll(".construction-manual").forEach((ta) => {
      const qid = ta.dataset.qid;
      const current = normalizeConstructionAnswer(state.constructionAnswers[qid]);
      current.manual_text = ta.value;
      if (current.choice !== "manual" && current.manual_text.trim()) {
        current.choice = "manual";
      }
      state.constructionAnswers[qid] = current;
    });
  }

  function attachConstructionQuestionHandlers() {
    document.querySelectorAll(".construction-choice").forEach((btn) => {
      btn.addEventListener("click", () => {
        const qid = btn.dataset.qid;
        const choice = btn.dataset.choice;
        const current = normalizeConstructionAnswer(state.constructionAnswers[qid]);
        current.choice = choice;
        if (choice !== "manual") current.manual_text = "";
        state.constructionAnswers[qid] = current;

        const block = btn.closest(".validation-question");
        block?.querySelectorAll(".construction-choice").forEach((b) => {
          b.classList.toggle("selected", b.dataset.choice === choice);
        });
        const manualWrap = block?.querySelector(".construction-manual-wrap");
        if (manualWrap) {
          manualWrap.classList.toggle("hidden", choice !== "manual");
          if (choice === "manual") manualWrap.querySelector(".construction-manual")?.focus();
        }
      });
    });

    document.querySelectorAll(".construction-manual").forEach((ta) => {
      ta.addEventListener("input", () => {
        const qid = ta.dataset.qid;
        const current = normalizeConstructionAnswer(state.constructionAnswers[qid]);
        current.manual_text = ta.value;
        if (ta.value.trim()) current.choice = "manual";
        state.constructionAnswers[qid] = current;

        const block = ta.closest(".validation-question");
        block?.querySelectorAll(".construction-choice").forEach((b) => {
          b.classList.toggle("selected", b.dataset.choice === "manual");
        });
      });
    });
  }

  function renderFrameworkStep() {
    const preview = state.frameworkPreview;
    const skillCount = allSkills().length;

    els.body.innerHTML = `
      <section class="validation-block framework-skills-block">
        <h3 class="validation-heading">Agent skills (${skillCount}/${MAX_AGENT_SKILLS})</h3>
        <p class="validation-hint">Add or remove skills — the framework updates automatically.</p>
        ${renderSelectedSkillsTagsHtml()}
        <p class="framework-skills-suggestions-label">Suggested skills</p>
        <div id="framework-skills-bubbles" class="framework-skills-bubbles"></div>
        ${renderFrameworkSkillsCustomInputHtml()}
      </section>
    `;
    attachFrameworkSkillsHandlers();
  }

  async function loadJdDraft() {
    state.jdLoading = true;
    state.jdBuildProgress = { percent: 6, phase: "Starting job description draft…", logs: [] };
    renderStep();
    startJdThoughtReveal();
    try {
      const res = await window.api("/agents/jd-draft", {
        method: "POST",
        body: JSON.stringify(buildBasePayload()),
      });
      state.jdBuildProgress = {
        percent: 100,
        phase: "Job description ready",
        logs: [
          ...buildJdThoughtChain().map((message) => ({ message, status: "done" })),
          { message: "Draft complete — review and edit below", status: "done" },
        ],
      };
      updateJdBuildUI();
      await sleep(400);
      state.jdDraft = res.job_description || { title: "", summary: "", responsibilities: [] };
    } catch (e) {
      els.error.innerHTML = `<div class="alert alert-error">${escapeHtml(e.message)}</div>`;
    } finally {
      clearJdRevealTimer();
      state.jdLoading = false;
      state.jdBuildProgress = null;
      renderStep();
    }
  }

  async function loadFrameworkPreview() {
    const loadId = ++frameworkLoadGeneration;
    state.frameworkLoading = true;
    state.frameworkBuildProgress = { percent: 0, phase: "Starting framework design…", logs: [] };
    startFrameworkProgressAnimation();
    renderStep();
    try {
      const jd = state.jdDraft ? { ...state.jdDraft } : null;
      const startRes = await window.api("/agents/framework-preview/jobs", {
        method: "POST",
        body: JSON.stringify({
          ...buildBasePayload(),
          job_description: jd,
        }),
      });
      const res = await pollFrameworkBuildJob(startRes.job_id, loadId);
      if (loadId !== frameworkLoadGeneration || !res) return;
      state.frameworkPreview = res;
      state.lastFrameworkJdSnapshot = jdSnapshot();
      state.lastFrameworkSkillsetSnapshot = skillsetSnapshot();
      (res.construction_questions || []).forEach((q) => {
        if (state.constructionAnswers[q.id] === undefined) {
          state.constructionAnswers[q.id] = defaultConstructionAnswer();
        }
      });
    } catch (e) {
      if (loadId !== frameworkLoadGeneration) return;
      els.error.innerHTML = `<div class="alert alert-error">${escapeHtml(e.message)}</div>`;
    } finally {
      if (loadId !== frameworkLoadGeneration) return;
      stopFrameworkProgressAnimation();
      state.frameworkLoading = false;
      state.frameworkBuildProgress = null;
      renderStep();
    }
  }

  function renderStep() {
    const step = steps[stepIndex];
    els.error.innerHTML = "";
    els.back.classList.toggle("hidden", stepIndex === 0);
    els.progress.style.width = `${((stepIndex + 1) / steps.length) * 100}%`;
    els.body.innerHTML = "";
    hideCustomInputs();
    if (els.next && step !== "framework") els.next.disabled = false;

    if (step === "name") {
      els.title.textContent = "Name your agent";
      els.subtitle.textContent = "Give your agent a name — this is how it will appear on your dashboard.";
      els.nameWrap?.classList.remove("hidden");
      if (els.nameInput) els.nameInput.value = state.agent_name;
      els.next.textContent = "Next";
      return;
    }

    if (step === "field") {
      els.title.textContent = "What field should this agent specialize in?";
      els.subtitle.textContent = "Choose the professional area that best matches this agent.";
      els.body.appendChild(renderBubbles(catalog?.fields || [], {
        selected: state.field_id,
        getKey: (f) => f.id,
        getLabel: (f) => `${f.icon} ${f.label}`,
        onSelect: (id, field) => {
          state.field_id = id;
          state.field_label = field.label;
          if (id !== "other") state.field_custom = "";
        },
      }));
      if (state.field_id === "other") {
        els.customField?.classList.remove("hidden");
        if (els.customFieldInput) els.customFieldInput.value = state.field_custom;
      }
      els.next.textContent = "Next";
      return;
    }

    if (step === "industry") {
      els.title.textContent = "What industry is this agent for?";
      els.subtitle.textContent = "Pick the industry context your agent should understand.";
      els.body.appendChild(renderBubbles(catalog?.industries || [], {
        selected: state.industry,
        onSelect: (ind) => { state.industry = ind; },
      }));
      if (state.industry === OTHER) {
        els.industryCustomWrap?.classList.remove("hidden");
        if (els.industryCustomInput) els.industryCustomInput.value = state.industry_custom;
      }
      els.next.textContent = "Next";
      return;
    }

    if (step === "role") {
      const roles = [
        ...(catalog?.roles_by_field?.[state.field_id] || catalog?.roles_by_field?.other || []),
        OTHER,
      ];
      els.title.textContent = "What's the job title?";
      els.subtitle.textContent = `Roles common in ${fieldLabel()}, or choose Other.`;
      els.body.appendChild(renderBubbles(roles, {
        selected: state.current_job,
        onSelect: (role) => { state.current_job = role; },
      }));
      if (state.current_job === OTHER) {
        els.roleCustomWrap?.classList.remove("hidden");
        if (els.roleCustomInput) els.roleCustomInput.value = state.role_custom;
      }
      els.next.textContent = "Next";
      return;
    }

    if (step === "skills") {
      enforceSkillLimit();
      const catalogSkills = catalog?.skills_by_field?.[state.field_id] || catalog?.skills_by_field?.other || [];
      els.title.textContent = "Select core skills";
      els.subtitle.textContent = `Choose up to ${MAX_AGENT_SKILLS} skills from suggestions or add your own. (${allSkills().length}/${MAX_AGENT_SKILLS} selected)`;
      els.body.appendChild(renderBubbles(catalogSkills, { multi: true, selected: state.skills }));
      els.skillsCustomWrap?.classList.remove("hidden");
      renderCustomSkillTags();
      updateSkillsCapacityUI();
      els.next.textContent = "Next";
      els.next.disabled = allSkills().length === 0;
      return;
    }

    if (step === "jd") {
      els.title.textContent = "Review the job description";
      els.subtitle.textContent = "You're the hiring manager — edit the role and responsibilities, then confirm.";
      els.next.textContent = "Confirm & design framework";

      if (state.jdLoading) {
        els.body.innerHTML = renderJdBuildProgress();
        return;
      }
      if (!state.jdDraft) {
        els.body.innerHTML = `<p class="wizard-loading">Loading…</p>`;
        loadJdDraft();
        return;
      }
      renderJdStep();
      return;
    }

    if (step === "framework") {
      enforceSkillLimit();
      els.title.textContent = "Multi-agent framework";
      updateSkillsCapacityUI();
      els.next.textContent = mode === "edit_agent" ? "Save changes" : "Create agent";
      if (els.next) {
        els.next.disabled = !!state.frameworkLoading || allSkills().length === 0;
      }

      if (state.frameworkLoading) {
        els.body.innerHTML = renderFrameworkBuildProgress();
        return;
      }
      const needsReload = !state.frameworkPreview
        || state.lastFrameworkJdSnapshot !== jdSnapshot()
        || state.lastFrameworkSkillsetSnapshot !== skillsetSnapshot();
      if (needsReload) {
        els.body.innerHTML = renderFrameworkBuildProgress();
        loadFrameworkPreview();
        return;
      }
      renderFrameworkStep();
    }
  }

  function validateStep() {
    const step = steps[stepIndex];
    if (step === "name") {
      state.agent_name = els.nameInput?.value?.trim() || "";
      if (!state.agent_name) return "Please enter an agent name.";
    }
    if (step === "field") {
      if (!state.field_id) return "Please select a field.";
      if (state.field_id === "other") {
        state.field_custom = els.customFieldInput?.value?.trim() || "";
        if (!state.field_custom) return "Please describe your field.";
      }
    }
    if (step === "industry") {
      if (!state.industry) return "Please select an industry.";
      if (state.industry === OTHER) {
        state.industry_custom = els.industryCustomInput?.value?.trim() || "";
        if (!state.industry_custom) return "Please enter your industry.";
      }
    }
    if (step === "role") {
      if (!state.current_job) return "Please select a job title.";
      if (state.current_job === OTHER) {
        state.role_custom = els.roleCustomInput?.value?.trim() || "";
        if (!state.role_custom) return "Please enter a job title.";
      }
    }
    if (step === "skills") {
      enforceSkillLimit();
      if (allSkills().length === 0) return "Select or add at least one skill.";
      if (allSkills().length > MAX_AGENT_SKILLS) {
        return `Maximum ${MAX_AGENT_SKILLS} skills per agent — remove ${allSkills().length - MAX_AGENT_SKILLS} to continue.`;
      }
    }
    if (step === "jd") {
      syncJdFromDOM();
      if (!state.jdDraft?.title?.trim()) return "Please enter a role title.";
      if (!state.jdDraft?.summary?.trim()) return "Please enter a role summary.";
      if (!state.jdDraft?.responsibilities?.length) return "Add at least one responsibility.";
    }
    if (step === "framework") {
      enforceSkillLimit();
      if (allSkills().length === 0) return "Select or add at least one skill.";
      if (state.frameworkLoading || !state.frameworkPreview) {
        return "Framework is still being designed — please wait.";
      }
    }
    return null;
  }

  function buildBasePayload() {
    return {
      full_name: state.agent_name,
      field: fieldLabel(),
      industry: resolvedIndustry(),
      current_job: resolvedRole(),
      skillset: skillsetString(),
    };
  }

  function resolvedConstructionAnswers() {
    const questions = state.frameworkPreview?.construction_questions || [];
    const answers = {};
    questions.forEach((q) => {
      const text = constructionAnswerText(q, state.constructionAnswers[q.id]);
      if (text) answers[q.id] = text;
    });
    return answers;
  }

  function buildPayload() {
    syncJdFromDOM();
    return {
      ...buildBasePayload(),
      job_description: state.jdDraft ? { ...state.jdDraft } : null,
      framework_design: {
        framework: state.frameworkPreview?.framework,
        construction_answers: resolvedConstructionAnswers(),
      },
    };
  }

  async function submit() {
    const payload = buildPayload();

    if (mode === "edit_agent") {
      await window.api(`/agents/${editSessionId}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      if (window.trackEvent) window.trackEvent("agent_updated", { field: payload.field });
    } else {
      if (mode === "initial") {
        await window.api("/profile/background", {
          method: "POST",
          body: JSON.stringify(buildBasePayload()),
        });
        if (window.trackEvent) window.trackEvent("background_step_completed");
      } else {
        await window.api("/profile", {
          method: "PUT",
          body: JSON.stringify(buildBasePayload()),
        });
      }

      await window.api("/agents/create", { method: "POST", body: JSON.stringify(payload) });

      if (window.trackEvent) {
        window.trackEvent(mode === "new_agent" ? "new_agent_created" : "first_agent_created", {
          field: payload.field,
        });
      }
    }

    if (window.loadHome) await window.loadHome();
    window.showView("home");
    window.ChatWorkspace?.showWelcome?.();
  }

  async function onNext() {
    const err = validateStep();
    if (err) {
      els.error.innerHTML = `<div class="alert alert-error">${escapeHtml(err)}</div>`;
      return;
    }

    if (steps[stepIndex] === "framework") {
      els.next.disabled = true;
      try {
        await submit();
      } catch (e) {
        els.error.innerHTML = `<div class="alert alert-error">${escapeHtml(e.message)}</div>`;
      } finally {
        els.next.disabled = false;
      }
      return;
    }

    if (steps[stepIndex] === "skills") {
      state.jdDraft = null;
      state.frameworkPreview = null;
      state.constructionAnswers = {};
    }
    if (steps[stepIndex] === "jd") {
      syncJdFromDOM();
      state.frameworkPreview = null;
      state.lastFrameworkJdSnapshot = null;
      state.constructionAnswers = {};
    }

    stepIndex += 1;
    renderStep();
  }

  function onBack() {
    if (stepIndex > 0) {
      if (steps[stepIndex] === "framework") {
        state.frameworkPreview = null;
        state.lastFrameworkJdSnapshot = null;
        state.lastFrameworkSkillsetSnapshot = null;
        state.constructionAnswers = {};
      }
      stepIndex -= 1;
      renderStep();
    }
  }

  function prefill(data) {
    if (!data) return;
    if (data.full_name) state.agent_name = data.full_name;
    if (data.field) {
      const match = (catalog?.fields || []).find(
        (f) => f.label.toLowerCase() === data.field.toLowerCase() || f.id === data.field.toLowerCase()
      );
      if (match) {
        state.field_id = match.id;
        state.field_label = match.label;
      } else {
        state.field_id = "other";
        state.field_custom = data.field;
        state.field_label = data.field;
      }
    }
    if (data.industry) {
      if ((catalog?.industries || []).includes(data.industry)) state.industry = data.industry;
      else {
        state.industry = OTHER;
        state.industry_custom = data.industry;
      }
    }
    if (data.current_job) {
      const roles = catalog?.roles_by_field?.[state.field_id] || [];
      if (roles.includes(data.current_job)) state.current_job = data.current_job;
      else {
        state.current_job = OTHER;
        state.role_custom = data.current_job;
      }
    }
    if (data.skillset) {
      const all = data.skillset.split(",").map((s) => s.trim()).filter(Boolean).slice(0, MAX_AGENT_SKILLS);
      const catalogSkills = new Set(
        catalog?.skills_by_field?.[state.field_id] || catalog?.skills_by_field?.other || []
      );
      state.skills = all.filter((s) => catalogSkills.has(s));
      state.custom_skills = all.filter((s) => !catalogSkills.has(s));
    }
    if (data.job_description) {
      state.jdDraft = {
        title: data.job_description.title || "",
        summary: data.job_description.summary || "",
        responsibilities: [...(data.job_description.responsibilities || [])],
      };
    }
    if (data.framework_design?.framework) {
      state.frameworkPreview = {
        framework: data.framework_design.framework,
        construction_questions: [],
        job_description_used: data.job_description || state.jdDraft,
      };
      state.lastFrameworkJdSnapshot = JSON.stringify(state.jdDraft || {});
      state.lastFrameworkSkillsetSnapshot = skillsetSnapshot();
      const answers = data.framework_design.construction_answers || {};
      Object.entries(answers).forEach(([qid, text]) => {
        const raw = String(text || "").trim();
        const match = raw.match(/^([A-D]):\s*(.*)$/);
        if (match) {
          state.constructionAnswers[qid] = { choice: match[1], manual_text: "" };
        } else if (raw) {
          state.constructionAnswers[qid] = { choice: "manual", manual_text: raw };
        }
      });
    }
  }

  async function open(options = {}) {
    cacheElements();
    mode = options.mode || "initial";
    editSessionId = options.sessionId || null;
    if (!catalog) catalog = await window.api("/profile/catalog");

    stepIndex = 0;
    steps = buildSteps();
    state = {
      agent_name: "",
      field_id: "",
      field_label: "",
      field_custom: "",
      industry: "",
      industry_custom: "",
      current_job: "",
      role_custom: "",
      skills: [],
      custom_skills: [],
      jdDraft: null,
      jdLoading: false,
      frameworkPreview: null,
      frameworkLoading: false,
      frameworkBuildProgress: null,
      lastFrameworkJdSnapshot: null,
      lastFrameworkSkillsetSnapshot: null,
      constructionAnswers: {},
    };

    prefill(options.prefill);
    if (mode === "edit_agent") {
      els.next.textContent = "Save changes";
    }
    renderStep();
    window.showView("background");
  }

  function init() {
    cacheElements();
    els.next?.addEventListener("click", onNext);
    els.back?.addEventListener("click", onBack);
    els.customFieldInput?.addEventListener("input", () => { state.field_custom = els.customFieldInput.value; });
    els.industryCustomInput?.addEventListener("input", () => { state.industry_custom = els.industryCustomInput.value; });
    els.roleCustomInput?.addEventListener("input", () => { state.role_custom = els.roleCustomInput.value; });
    els.skillAddBtn?.addEventListener("click", addCustomSkill);
    els.skillCustomInput?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); addCustomSkill(); }
    });
  }

  return { init, open };
})();

window.BackgroundWizard = BackgroundWizard;
