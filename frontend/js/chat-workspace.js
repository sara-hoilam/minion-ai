/**
 * Collaboration hub — Slack sidebar + Claude-style main workspace.
 */
const ChatWorkspace = (() => {
  const AVATAR_COLORS = ["#b8d9f0", "#fde68a"];

  let agents = [];
  let personas = [];
  let projects = [];
  let agentDms = [];
  let currentThread = null;
  let currentMode = "welcome"; // welcome | thread | project | agents-roster | agent-detail | prebuilt-browse
  let prebuiltAgents = [];
  let prebuiltSearch = "";
  let prebuiltSearchTimer = null;
  let currentAgentId = null;
  let currentProject = null;
  let pendingFile = null;
  let welcomePendingFile = null;
  let sending = false;
  let threadPollTimer = null;
  let pollingThreadId = null;
  let projectSort = "updated";
  let projectSearch = "";
  let currentProjectAgentId = null;
  let projectInstructionsTimer = null;
  let editingProjectId = null;
  let userProfile = null;
  const planRevisionSubmitted = new Map();

  function $(id) { return document.getElementById(id); }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function formatMarkdown(text) {
    if (window.MinionMarkdown?.render) {
      return window.MinionMarkdown.render(text);
    }
    if (!text) return "";
    let html = escapeHtml(text);
    html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\n/g, "<br>");
    return `<div class="chat-markdown">${html}</div>`;
  }

  function enhanceMarkdown(root) {
    window.MinionMarkdown?.enhance?.(root);
  }

  function agentColor(name, index) {
    if (typeof index === "number") {
      return AVATAR_COLORS[index % AVATAR_COLORS.length];
    }
    let hash = 0;
    for (let i = 0; i < (name || "").length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
    return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
  }

  function agentInitials(name) {
    const parts = (name || "A").trim().split(/\s+/);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return (parts[0][0] || "A").toUpperCase();
  }

  function agentAvatarStyle(name, deactivated = false, index) {
    return deactivated ? "#9ca3af" : agentColor(name, index);
  }

  function agentAvatarClass(size, deactivated = false) {
    return `workspace-agent-avatar ${size}${deactivated ? " deactivated" : ""}`;
  }

  function greeting() {
    const h = new Date().getHours();
    const name = accountFirstName();
    const part = h < 12 ? "morning" : h < 17 ? "afternoon" : "evening";
    return `Good ${part}, ${name}`;
  }

  let suppressHashChange = 0;

  function setHash(path) {
    const next = path || "home";
    const current = location.hash.replace(/^#\/?/, "") || "home";
    if (current === next) return;
    suppressHashChange += 1;
    location.hash = next;
    window.addEventListener("hashchange", () => {
      suppressHashChange = Math.max(0, suppressHashChange - 1);
    }, { once: true });
  }

  function shouldHandleHashChange() {
    return suppressHashChange <= 0;
  }

  function currentAgent() {
    return agents.find((a) => a.session_id === currentAgentId) || null;
  }

  async function loadSidebar() {
    const sidebar = await window.api("/chat/sidebar");
    agentDms = sidebar.agent_dms || [];
    agents = agentDms.map((a) => ({
      session_id: a.session_id,
      name: a.name,
      job_title: a.job_title,
      field: a.field,
      thread_id: a.thread_id,
      hidden_from_roster: !!a.hidden_from_roster,
    }));
    renderSidebar();
    try {
      await loadProjects();
    } catch (_) {}
  }

  async function loadProjects() {
    const data = await window.api(`/projects?sort=${projectSort}`);
    projects = data.projects || [];
    renderProjects();
  }

  function renderProjects() {
    const el = $("collab-project-list");
    if (!el) return;
    const q = (projectSearch || $("collab-project-search")?.value || "").trim().toLowerCase();
    const filtered = projects.filter((p) => !q || (p.name || "").toLowerCase().includes(q));
    if (!filtered.length) {
      el.innerHTML = '<p class="collab-list-empty">No projects yet</p>';
      return;
    }
    el.innerHTML = filtered.map((p) => {
      const active = currentMode === "project" && currentProject?.id === p.id;
      return `
        <button type="button" class="collab-nav-item project${active ? " active" : ""}" data-project-id="${p.id}">
          <span class="collab-nav-label"><strong>${escapeHtml(p.name)}</strong></span>
        </button>`;
    }).join("");
    el.querySelectorAll("[data-project-id]").forEach((btn) => {
      btn.addEventListener("click", () => openProject(parseInt(btn.dataset.projectId, 10)));
    });
  }

  function setProjectColumnVisible(show) {
    document.querySelector(".collab-shell")?.classList.toggle("project-open", !!currentProject);
    if (!show) closeProjectDrawer();
  }

  function closeProjectDrawer() {
    $("collab-project-drawer")?.classList.add("hidden");
    $("collab-project-drawer-toggle")?.classList.remove("active");
    updateDrawerLayout();
  }

  function closeAgentDrawer() {
    $("collab-agent-drawer")?.classList.add("hidden");
    $("collab-agent-drawer-toggle")?.classList.remove("active");
    updateDrawerLayout();
  }

  function closeAllDrawers() {
    closeProjectDrawer();
    closeAgentDrawer();
  }

  function updateDrawerLayout() {
    const open = !$("collab-project-drawer")?.classList.contains("hidden")
      || !$("collab-agent-drawer")?.classList.contains("hidden");
    document.querySelector(".collab-workspace")?.classList.toggle("drawer-open", open);
  }

  function toggleProjectDrawer() {
    const drawer = $("collab-project-drawer");
    const btn = $("collab-project-drawer-toggle");
    if (!drawer) return;
    const opening = drawer.classList.contains("hidden");
    closeAgentDrawer();
    drawer.classList.toggle("hidden", !opening);
    btn?.classList.toggle("active", opening);
    updateDrawerLayout();
  }

  async function toggleAgentDrawer() {
    const drawer = $("collab-agent-drawer");
    const btn = $("collab-agent-drawer-toggle");
    if (!drawer) return;
    const opening = drawer.classList.contains("hidden");
    closeProjectDrawer();
    drawer.classList.toggle("hidden", !opening);
    btn?.classList.toggle("active", opening);
    if (opening) await renderAgentDrawer();
    updateDrawerLayout();
  }

  function renderThreadBreadcrumb({ projectName, topic, agentName } = {}) {
    const el = $("collab-thread-title");
    if (!el) return;
    if (projectName) {
      el.innerHTML = `
        <span class="crumb-project">${escapeHtml(projectName)}</span>
        <span class="crumb-sep">/</span>
        <span class="crumb-topic">${escapeHtml(topic || agentName || "Chat")}</span>`;
      return;
    }
    if (agentName) {
      el.innerHTML = `<span class="crumb-project">${escapeHtml(agentName)}</span>`;
      return;
    }
    el.innerHTML = `<span class="crumb-project">Chat</span>`;
  }

  function updateThreadHeaderActions() {
    const inProject = currentMode === "project" && !!currentProject;
    const hasAgent = !!currentAgentId;
    const hasThread = !!currentThread?.id;

    $("collab-project-drawer-toggle")?.classList.toggle("hidden", !inProject);
    $("collab-agent-drawer-toggle")?.classList.toggle("hidden", !hasAgent && !hasThread);

    if ($("collab-agent-drawer-title")) {
      const agent = agents.find((a) => a.session_id === currentAgentId);
      $("collab-agent-drawer-title").textContent = agent?.name
        ? `${agent.name} — details`
        : "Agent details";
    }
  }

  let communicationStyleTimer = null;
  let skillsSaveTimer = null;
  let agentDrawerSkills = [];
  const MAX_AGENT_SKILLS = 8;
  const PLATFORM_SKILL_KEYS = new Set([
    "first principles thinking",
    "current data awareness",
  ]);

  function filterUserSkills(skills) {
    return (skills || [])
      .map((s) => String(s).trim())
      .filter((s) => s && !PLATFORM_SKILL_KEYS.has(s.toLowerCase()))
      .slice(0, MAX_AGENT_SKILLS);
  }

  function parseSkillsetString(skillset) {
    return filterUserSkills(
      (skillset || "").split(",").map((s) => s.trim()).filter(Boolean),
    );
  }

  let agentDetailSkills = [];
  let agentDetailSkillsSessionId = null;
  let agentDetailSkillsSaveTimer = null;

  async function loadAgentCommunicationStyle() {
    const select = $("collab-agent-communication-style");
    if (!select || !currentAgentId) return;
    try {
      const data = await window.api(`/agents/${currentAgentId}`);
      const style = (data.agent_context?.communication_style || "professional").toLowerCase();
      if ([...select.options].some((o) => o.value === style)) {
        select.value = style;
      } else {
        select.value = "professional";
      }
    } catch (_) {
      select.value = "professional";
    }
  }

  function scheduleCommunicationStyleSave() {
    if (!currentAgentId) return;
    clearTimeout(communicationStyleTimer);
    communicationStyleTimer = setTimeout(async () => {
      const select = $("collab-agent-communication-style");
      const statusEl = $("collab-agent-style-status");
      if (!select) return;
      try {
        await window.api(`/agents/${currentAgentId}/working-context`, {
          method: "PUT",
          body: JSON.stringify({ communication_style: select.value }),
        });
        if (statusEl) {
          statusEl.textContent = "Saved";
          statusEl.classList.remove("hidden");
          setTimeout(() => statusEl.classList.add("hidden"), 2000);
        }
      } catch (err) {
        if (statusEl) {
          statusEl.textContent = err.message || "Could not save style";
          statusEl.classList.remove("hidden");
        }
      }
    }, 400);
  }

  async function loadAgentDrawerFeedback() {
    const el = $("collab-agent-feedback-recent");
    if (!el || !currentAgentId) return;
    try {
      const inProject = currentMode === "project" && currentProject?.id && currentProjectAgentId;
      const data = inProject
        ? await window.api(`/projects/${currentProject.id}/agents/${currentProjectAgentId}/feedback`)
        : await window.api(`/agents/${currentAgentId}/feedback`);
      const items = data.feedback || [];
      if (!items.length) {
        el.innerHTML = "";
        return;
      }
      el.innerHTML = items.slice(0, 5).map((f) => `
        <div class="collab-feedback-item">
          <span class="badge">${escapeHtml(f.status || "approved")}</span>
          ${escapeHtml((f.content || "").slice(0, 80))}${(f.content || "").length > 80 ? "…" : ""}
        </div>`).join("");
    } catch (_) {
      el.innerHTML = "";
    }
  }

  function applyFeedbackSubmitStatus(statusEl, res) {
    if (!statusEl) return;
    const approved = res?.status === "approved";
    statusEl.textContent = res?.message || (approved ? "Sent" : "Feedback saved but not applied.");
    statusEl.className = `collab-feedback-status ${approved ? "approved" : "filtered"}`;
    statusEl.classList.remove("hidden");
  }

  async function submitAgentDrawerFeedback() {
    const statusEl = $("collab-agent-feedback-status");
    if (!currentAgentId) {
      if (statusEl) {
        statusEl.textContent = "Open an agent chat first.";
        statusEl.className = "collab-feedback-status filtered";
        statusEl.classList.remove("hidden");
      }
      return;
    }
    const content = $("collab-agent-feedback-input")?.value?.trim();
    if (!content) return;
    const inProject = currentMode === "project" && currentProject?.id && currentProjectAgentId;
    try {
      const res = inProject
        ? await window.api(
          `/projects/${currentProject.id}/agents/${currentProjectAgentId}/feedback`,
          {
            method: "POST",
            body: JSON.stringify({ content, thread_id: currentThread?.id }),
          },
        )
        : await window.api(`/agents/${currentAgentId}/feedback`, {
          method: "POST",
          body: JSON.stringify({ content, thread_id: currentThread?.id }),
        });
      if ($("collab-agent-feedback-input")) $("collab-agent-feedback-input").value = "";
      applyFeedbackSubmitStatus(statusEl, res);
      await loadAgentDrawerFeedback();
    } catch (err) {
      if (statusEl) {
        statusEl.textContent = err.message || "Could not send feedback.";
        statusEl.className = "collab-feedback-status filtered";
        statusEl.classList.remove("hidden");
      }
    }
  }

  async function loadAgentDrawerSkills() {
    if (!currentAgentId) {
      agentDrawerSkills = [];
      return;
    }
    try {
      const data = await window.api(`/agents/${currentAgentId}`);
      agentDrawerSkills = filterUserSkills(data.skills || parseSkillsetString(data.skillset));
    } catch (_) {
      const persona = personas.find((p) => p.session_id === currentAgentId);
      agentDrawerSkills = filterUserSkills(persona?.skills || []);
    }
  }

  function renderEditableSkillsHtml(skills, { containerId = "", removable = true } = {}) {
    if (!skills.length) {
      return '<span class="skill-tag skill-tag-empty">No skills listed</span>';
    }
    return skills.map((skill) => `
      <span class="skill-tag${removable ? " skill-tag-removable" : ""}">
        ${escapeHtml(skill)}
        ${removable ? `<button type="button" class="skill-tag-remove" data-skill="${escapeHtml(skill)}" aria-label="Remove ${escapeHtml(skill)}">×</button>` : ""}
      </span>`).join("");
  }

  function bindEditableSkills(container, skills, { onChange, statusElId } = {}) {
    if (!container) return;
    container.querySelectorAll(".skill-tag-remove").forEach((btn) => {
      btn.addEventListener("click", () => {
        const name = btn.dataset.skill;
        const next = skills.filter((s) => s !== name);
        skills.length = 0;
        skills.push(...next);
        container.innerHTML = renderEditableSkillsHtml(skills);
        bindEditableSkills(container, skills, { onChange, statusElId });
        onChange?.();
      });
    });
  }

  function scheduleAgentDetailSkillsSave(sessionId) {
    clearTimeout(agentDetailSkillsSaveTimer);
    agentDetailSkillsSaveTimer = setTimeout(async () => {
      const statusEl = $(`agent-detail-skills-status-${sessionId}`);
      if (!agentDetailSkills.length) {
        if (statusEl) {
          statusEl.textContent = "At least one skill is required.";
          statusEl.classList.remove("hidden");
        }
        const data = await window.api(`/agents/${sessionId}`);
        agentDetailSkills = filterUserSkills(data.skills || parseSkillsetString(data.skillset));
        renderAgentDetailSkills(sessionId);
        return;
      }
      try {
        const body = await window.api(`/agents/${sessionId}/skills`, {
          method: "PUT",
          body: JSON.stringify({ skills: agentDetailSkills }),
        });
        if (window.loadHome) await window.loadHome();
        personas = window.homePersonas || personas;
        agentDetailSkills = filterUserSkills(body.skills || agentDetailSkills);
        renderAgentDetailSkills(sessionId);
        if (statusEl) {
          const subs = (body.subagents || []).map((s) => s.skill).filter(Boolean);
          statusEl.textContent = subs.length
            ? `Framework updated — ${subs.length} subagent${subs.length === 1 ? "" : "s"}`
            : "Skills saved";
          statusEl.classList.remove("hidden");
          setTimeout(() => statusEl.classList.add("hidden"), 4000);
        }
      } catch (err) {
        if (statusEl) {
          statusEl.textContent = err.message || "Could not save skills";
          statusEl.classList.remove("hidden");
        }
        const data = await window.api(`/agents/${sessionId}`);
        agentDetailSkills = filterUserSkills(data.skills || parseSkillsetString(data.skillset));
        renderAgentDetailSkills(sessionId);
      }
    }, 500);
  }

  function renderAgentDetailSkills(sessionId) {
    const container = $(`agent-detail-skills-${sessionId}`);
    if (!container) return;
    container.innerHTML = renderEditableSkillsHtml(agentDetailSkills);
    bindEditableSkills(container, agentDetailSkills, {
      statusElId: `agent-detail-skills-status-${sessionId}`,
      onChange: () => scheduleAgentDetailSkillsSave(sessionId),
    });
    const addBtn = $(`agent-detail-skill-add-btn-${sessionId}`);
    const input = $(`agent-detail-skill-input-${sessionId}`);
    if (addBtn) addBtn.disabled = agentDetailSkills.length >= MAX_AGENT_SKILLS;
    if (input) input.disabled = agentDetailSkills.length >= MAX_AGENT_SKILLS;
  }

  function addAgentDetailSkill(sessionId) {
    const input = $(`agent-detail-skill-input-${sessionId}`);
    const statusEl = $(`agent-detail-skills-status-${sessionId}`);
    const value = input?.value?.trim();
    if (!value || PLATFORM_SKILL_KEYS.has(value.toLowerCase())) return;
    if (agentDetailSkills.length >= MAX_AGENT_SKILLS) {
      if (statusEl) {
        statusEl.textContent = `Maximum ${MAX_AGENT_SKILLS} skills per agent.`;
        statusEl.classList.remove("hidden");
      }
      return;
    }
    if (!agentDetailSkills.some((s) => s.toLowerCase() === value.toLowerCase())) {
      agentDetailSkills.push(value);
    }
    if (input) input.value = "";
    if (statusEl) statusEl.classList.add("hidden");
    renderAgentDetailSkills(sessionId);
    scheduleAgentDetailSkillsSave(sessionId);
  }

  function renderAgentDrawerSkills() {
    const el = $("collab-agent-drawer-skills");
    if (!el) return;
    if (!agentDrawerSkills.length) {
      el.innerHTML = '<p class="collab-list-empty">No skills yet — add one below.</p>';
      return;
    }
    el.innerHTML = agentDrawerSkills.map((skill) => `
      <span class="skill-tag skill-tag-removable">
        ${escapeHtml(skill)}
        <button type="button" class="skill-tag-remove" data-skill="${escapeHtml(skill)}" aria-label="Remove ${escapeHtml(skill)}">×</button>
      </span>`).join("");
    el.querySelectorAll(".skill-tag-remove").forEach((btn) => {
      btn.addEventListener("click", () => {
        const name = btn.dataset.skill;
        agentDrawerSkills = agentDrawerSkills.filter((s) => s !== name);
        renderAgentDrawerSkills();
        scheduleAgentSkillsSave();
      });
    });
  }

  function scheduleAgentSkillsSave() {
    if (!currentAgentId) return;
    clearTimeout(skillsSaveTimer);
    skillsSaveTimer = setTimeout(async () => {
      const statusEl = $("collab-agent-skills-status");
      if (!agentDrawerSkills.length) {
        if (statusEl) {
          statusEl.textContent = "At least one skill is required.";
          statusEl.classList.remove("hidden");
        }
        await loadAgentDrawerSkills();
        renderAgentDrawerSkills();
        return;
      }
      try {
        const body = await window.api(`/agents/${currentAgentId}/skills`, {
          method: "PUT",
          body: JSON.stringify({ skills: agentDrawerSkills }),
        });
        if (window.loadHome) await window.loadHome();
        personas = window.homePersonas || personas;
        if (statusEl) {
          const subs = (body.subagents || []).map((s) => s.skill).filter(Boolean);
          statusEl.textContent = subs.length
            ? `Framework updated — ${subs.length} subagent${subs.length === 1 ? "" : "s"}: ${subs.join(", ")}`
            : "Framework updated";
          statusEl.classList.remove("hidden");
          setTimeout(() => statusEl.classList.add("hidden"), 4000);
        }
      } catch (err) {
        if (statusEl) {
          statusEl.textContent = err.message || "Could not save skills";
          statusEl.classList.remove("hidden");
        }
        await loadAgentDrawerSkills();
        renderAgentDrawerSkills();
      }
    }, 500);
  }

  function addAgentDrawerSkill() {
    const input = $("collab-agent-skill-input");
    const statusEl = $("collab-agent-skills-status");
    const value = input?.value?.trim();
    if (!value || PLATFORM_SKILL_KEYS.has(value.toLowerCase())) return;
    if (agentDrawerSkills.length >= MAX_AGENT_SKILLS) {
      if (statusEl) {
        statusEl.textContent = `Maximum ${MAX_AGENT_SKILLS} skills per agent.`;
        statusEl.classList.remove("hidden");
      }
      return;
    }
    if (!agentDrawerSkills.some((s) => s.toLowerCase() === value.toLowerCase())) {
      agentDrawerSkills.push(value);
    }
    if (input) input.value = "";
    if (statusEl) statusEl.classList.add("hidden");
    renderAgentDrawerSkills();
    scheduleAgentSkillsSave();
  }

  async function renderAgentDrawer() {
    if (!$("collab-agent-drawer-skills")) return;

    await loadAgentDrawerSkills();
    renderAgentDrawerSkills();

    await loadAgentCommunicationStyle();

    if (currentThread?.id) {
      await loadThreadMemory(currentThread.id);
    } else if ($("collab-memory-topics")) {
      $("collab-memory-topics").innerHTML = '<p class="collab-memory-hint">Open a chat with this agent to see thread memory.</p>';
      if ($("collab-memory-status")) $("collab-memory-status").textContent = "";
    }

    await loadAgentDrawerFeedback();
  }

  function showProjectEmptyState(show) {
    $("collab-project-empty")?.classList.toggle("hidden", !show);
    $("collab-messages")?.classList.toggle("hidden", show);
    $("collab-composer")?.classList.toggle("hidden", show);
  }

  async function renderProjectPanel(project) {
    if ($("collab-project-column-name")) {
      $("collab-project-column-name").textContent = project.name || "Project";
    }
    const instr = $("collab-project-instructions");
    if (instr && document.activeElement !== instr) {
      instr.value = project.instructions || "";
    }

    const filesEl = $("collab-project-files");
    if (filesEl) {
      const files = project.context_files || [];
      filesEl.innerHTML = files.length
        ? files.map((f, i) => `
          <div class="collab-project-file-row">
            <span>📎 ${escapeHtml(f.filename)}</span>
            <button type="button" class="collab-file-remove" data-file-index="${i}" aria-label="Remove file">×</button>
          </div>`).join("")
        : '<p class="collab-list-empty">No files yet</p>';
      filesEl.querySelectorAll("[data-file-index]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          await window.api(`/projects/${project.id}/files/${btn.dataset.fileIndex}`, { method: "DELETE" });
          currentProject = await window.api(`/projects/${project.id}`);
          await renderProjectPanel(currentProject);
        });
      });
    }

    const agentsEl = $("collab-project-agents");
    if (agentsEl) {
      const plist = project.agents || [];
      agentsEl.innerHTML = plist.length
        ? plist.map((a) => {
          const color = agentColor(a.name);
          const active = currentProjectAgentId === a.session_id;
          return `
            <button type="button" class="collab-project-agent-row${active ? " active" : ""}" data-agent-session="${a.session_id}">
              <span class="workspace-agent-avatar xs" style="background:${color}">${agentInitials(a.name)}</span>
              <span>${escapeHtml(a.name)}</span>
            </button>`;
        }).join("")
        : '<p class="collab-list-empty">No agents assigned — add one below</p>';
      agentsEl.querySelectorAll("[data-agent-session]").forEach((btn) => {
        btn.addEventListener("click", () => {
          openProjectAgent(project.id, parseInt(btn.dataset.agentSession, 10));
        });
      });
    }
  }

  async function loadRecentFeedback(projectId, sessionId) {
    const el = $("collab-project-feedback-recent");
    if (!el) return;
    try {
      const data = await window.api(`/projects/${projectId}/agents/${sessionId}/feedback`);
      const items = data.feedback || [];
      if (!items.length) {
        el.innerHTML = "";
        return;
      }
      el.innerHTML = items.slice(0, 5).map((f) => `
        <div class="collab-feedback-item">
          <span class="badge">${escapeHtml(f.status)}</span>
          ${escapeHtml(f.content.slice(0, 80))}${f.content.length > 80 ? "…" : ""}
        </div>`).join("");
    } catch (_) {
      el.innerHTML = "";
    }
  }

  async function submitProjectFeedback() {
    const statusEl = $("collab-project-feedback-status");
    if (!currentProject || !currentProjectAgentId) {
      if (statusEl) {
        statusEl.textContent = "Select an agent from the project panel first.";
        statusEl.className = "collab-feedback-status filtered";
        statusEl.classList.remove("hidden");
      }
      return;
    }
    const content = $("collab-project-feedback-input")?.value?.trim();
    if (!content) return;
    try {
      const res = await window.api(
        `/projects/${currentProject.id}/agents/${currentProjectAgentId}/feedback`,
        {
          method: "POST",
          body: JSON.stringify({ content, thread_id: currentThread?.id }),
        },
      );
      if ($("collab-project-feedback-input")) $("collab-project-feedback-input").value = "";
      applyFeedbackSubmitStatus(statusEl, res);
      await loadRecentFeedback(currentProject.id, currentProjectAgentId);
    } catch (err) {
      if (statusEl) {
        statusEl.textContent = err.message || "Could not send feedback.";
        statusEl.className = "collab-feedback-status filtered";
        statusEl.classList.remove("hidden");
      }
    }
  }

  function scheduleProjectInstructionsSave() {
    if (!currentProject?.id) return;
    clearTimeout(projectInstructionsTimer);
    projectInstructionsTimer = setTimeout(async () => {
      const instructions = $("collab-project-instructions")?.value?.trim() || "";
      const status = $("collab-project-instructions-status");
      try {
        currentProject = await window.api(`/projects/${currentProject.id}`, {
          method: "PUT",
          body: JSON.stringify({ instructions }),
        });
        if (status) {
          status.textContent = "Saved";
          status.classList.remove("hidden");
          setTimeout(() => status.classList.add("hidden"), 1500);
        }
      } catch (err) {
        if (status) {
          status.textContent = err.message || "Save failed";
          status.classList.remove("hidden");
        }
      }
    }, 600);
  }

  async function openProjectAgent(projectId, sessionId) {
    await openProject(projectId, null, sessionId);
  }

  function hideAllPanels() {
    $("collab-welcome")?.classList.add("hidden");
    $("collab-thread-view")?.classList.add("hidden");
    $("collab-agents-roster")?.classList.add("hidden");
    $("collab-agent-detail")?.classList.add("hidden");
    $("collab-prebuilt-agents")?.classList.add("hidden");
  }

  function renderSidebar() {
    renderAgentsSidebar();
    renderProjects();
    renderDms();
  }

  function rosterAgents() {
    return agentDms.filter((a) => !a.hidden_from_roster);
  }

  function renderAgentsSidebar() {
    const el = $("collab-agents-list");
    if (!el) return;
    const roster = rosterAgents();
    if (!roster.length) {
      el.innerHTML = '<p class="collab-list-empty">No agents in roster</p>';
      return;
    }
    el.innerHTML = roster.map((a, index) => {
      const color = agentAvatarStyle(a.name, false, index);
      const active = currentMode === "agent-detail" && currentAgentId === a.session_id;
      return `
        <div class="collab-nav-row">
          <button type="button" class="collab-nav-item dm${active ? " active" : ""}" data-agent-id="${a.session_id}">
            <span class="${agentAvatarClass("xs")}" style="background:${color}">${agentInitials(a.name)}</span>
            <span class="collab-nav-label">
              <strong>${escapeHtml(a.name)}</strong>
              <span>${escapeHtml(a.job_title || a.field || "Agent")}</span>
            </span>
          </button>
          <button type="button" class="collab-nav-remove" data-remove-agent-id="${a.session_id}" title="Remove from agents" aria-label="Remove ${escapeHtml(a.name)} from agents">×</button>
        </div>`;
    }).join("");
    el.querySelectorAll("[data-agent-id]").forEach((btn) => {
      btn.addEventListener("click", () => showAgentDetail(parseInt(btn.dataset.agentId, 10)));
    });
    el.querySelectorAll("[data-remove-agent-id]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const sessionId = parseInt(btn.dataset.removeAgentId, 10);
        const agent = agentDms.find((a) => a.session_id === sessionId);
        if (!agent) return;
        window.openRemoveFromRosterModal?.({
          session_id: sessionId,
          name: agent.name,
        });
      });
    });
  }

  function navItemHtml({ id, label, sub, active, icon, dataAttrs }) {
    return `
      <button type="button" class="collab-nav-item${active ? " active" : ""}" ${dataAttrs}>
        ${icon || '<span class="collab-nav-hash">#</span>'}
        <span class="collab-nav-label">
          <strong>${escapeHtml(label)}</strong>
          ${sub ? `<span>${escapeHtml(sub)}</span>` : ""}
        </span>
      </button>`;
  }

  function syncDmThreadId(sessionId, threadId) {
    const dm = agentDms.find((a) => a.session_id === sessionId);
    if (dm) dm.thread_id = threadId;
    const agent = agents.find((a) => a.session_id === sessionId);
    if (agent) agent.thread_id = threadId;
    renderDms();
  }

  async function resolveThreadId(threadId, sessionId) {
    const parsed = parseInt(threadId, 10);
    if (parsed) return parsed;
    const sid = parseInt(sessionId, 10);
    if (!sid) return null;
    const dm = agentDms.find((a) => a.session_id === sid);
    if (dm?.thread_id) return dm.thread_id;
    if (currentAgentId === sid && currentThread?.id) return currentThread.id;
    try {
      const data = await window.api(`/chat/threads?agent_session_id=${sid}&thread_type=agent_dm`);
      const found = data.threads?.[0]?.id;
      if (found && dm) dm.thread_id = found;
      return found || null;
    } catch {
      return null;
    }
  }

  function chatLabelForThread(threadId, sessionId) {
    const sid = parseInt(sessionId, 10);
    if (sid) {
      const dm = agentDms.find((a) => a.session_id === sid);
      if (dm) return dm.name;
    }
    const dm = agentDms.find((a) => a.thread_id === threadId);
    if (dm) return dm.name;
    return "Chat";
  }

  function updateThreadChatMenu() {
    const wrap = $("collab-thread-chat-menu");
    if (!wrap) return;
    const show = !!currentThread?.id && (currentMode === "thread" || currentMode === "project");
    wrap.classList.toggle("hidden", !show);
  }

  function closeAllChatMenus() {
    document.querySelectorAll(".chat-menu .resume-menu-dropdown").forEach((el) => el.classList.add("hidden"));
  }

  function bindThreadChatMenu() {
    const wrap = $("collab-thread-chat-menu");
    if (!wrap || wrap.dataset.bound) return;
    wrap.dataset.bound = "1";
    $("collab-thread-menu-trigger")?.addEventListener("click", (e) => {
      e.stopPropagation();
      const dropdown = wrap.querySelector(".resume-menu-dropdown");
      const wasOpen = dropdown && !dropdown.classList.contains("hidden");
      closeAllChatMenus();
      if (!wasOpen && dropdown) dropdown.classList.remove("hidden");
    });
    $("collab-thread-export")?.addEventListener("click", (e) => {
      e.stopPropagation();
      exportChat(currentThread?.id, currentAgentId);
      closeAllChatMenus();
    });
    $("collab-thread-delete")?.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteChat(currentThread?.id, currentAgentId);
    });
  }

  async function exportChat(threadId, sessionId) {
    const id = await resolveThreadId(threadId, sessionId);
    if (!id) {
      alert("No chat history to export yet.");
      return;
    }
    const label = chatLabelForThread(id, sessionId);
    try {
      const res = await fetch(`/api/chat/threads/${id}/export?format=markdown`, { credentials: "same-origin" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || res.statusText);
      }
      const blob = await res.blob();
      const safe = (label || "chat").replace(/[^\w\s-]/g, "").trim().replace(/\s+/g, "_").slice(0, 40) || "chat";
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${safe}.md`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert(err.message || "Could not export chat");
    }
  }

  async function deleteChat(threadId, sessionId) {
    const id = await resolveThreadId(threadId, sessionId);
    if (!id) {
      alert("No chat to delete yet.");
      return;
    }
    const label = chatLabelForThread(id, sessionId);
    if (!confirm(`Delete chat with ${label || "this agent"}? Messages will be permanently removed.`)) return;
    try {
      await window.api(`/chat/threads/${id}`, { method: "DELETE" });
      closeAllChatMenus();
      const sid = parseInt(sessionId, 10);
      if (sid) {
        agentDms = agentDms.filter((a) => a.session_id !== sid);
        renderDms();
      }
      if (currentThread?.id === id) {
        currentThread = null;
        currentAgentId = null;
        showWelcome();
      }
      await loadSidebar();
    } catch (err) {
      alert(err.message || "Could not delete chat");
    }
  }

  function renderDms() {
    const el = $("collab-dm-list");
    if (!el) return;
    if (!agentDms.length) {
      el.innerHTML = '<p class="collab-list-empty">Create an agent to chat</p>';
      return;
    }
    el.innerHTML = agentDms.map((a, index) => {
      const deactivated = !!a.hidden_from_roster;
      const color = agentAvatarStyle(a.name, deactivated, index);
      const active = currentMode === "thread" && currentAgentId === a.session_id && !currentProject;
      return `
        <button type="button" class="collab-nav-item dm${active ? " active" : ""}${deactivated ? " deactivated" : ""}" data-session-id="${a.session_id}">
          <span class="${agentAvatarClass("xs", deactivated)}" style="background:${color}">${agentInitials(a.name)}</span>
          <span class="collab-nav-label">
            <strong>${escapeHtml(a.name)}</strong>
            <span>${escapeHtml(deactivated ? "Removed from agents" : (a.job_title || a.field || "Agent"))}</span>
          </span>
          <span class="workspace-agent-dot${deactivated ? " deactivated" : ""}"></span>
        </button>`;
    }).join("");
    el.querySelectorAll("[data-session-id]").forEach((btn) => {
      btn.addEventListener("click", () => openAgentDm(parseInt(btn.dataset.sessionId, 10)));
    });
  }

  function stopThreadPoll() {
    if (threadPollTimer) {
      clearTimeout(threadPollTimer);
      threadPollTimer = null;
    }
    pollingThreadId = null;
  }

  function thinkingStepIcon(status) {
    if (status === "done") return '<span class="thinking-step-icon done">✓</span>';
    if (status === "active") return '<span class="thinking-step-icon active"><span class="thinking-step-spinner"></span></span>';
    return '<span class="thinking-step-icon queued">○</span>';
  }

  function delegationStepsForDisplay(steps, { includePlan = false } = {}) {
    return (steps || []).filter((st) => includePlan || st.type !== "plan" || st.status === "active");
  }

  function summarizeThoughtLine(text) {
    const trimmed = (text || "").trim();
    if (!trimmed) return "";
    const sentence = trimmed.match(/^[^.!?\n]+[.!?]?/)?.[0]?.trim() || trimmed;
    if (sentence.length <= 96) return sentence;
    return `${sentence.slice(0, 93).trim()}…`;
  }

  function buildThoughtBlocks(source = {}) {
    const blocks = [];
    const seen = new Set();
    const pushBlock = (summary, body) => {
      const bodyText = (body || summary || "").trim();
      if (!bodyText || seen.has(bodyText)) return;
      seen.add(bodyText);
      blocks.push({
        summary: (summary || summarizeThoughtLine(bodyText)).trim(),
        body: bodyText,
      });
    };

    const managerPlan = (source.manager_plan || "").trim();
    if (managerPlan) {
      pushBlock(summarizeThoughtLine(managerPlan), managerPlan);
    }

    const hasStepDetails = delegationStepsForDisplay(source.steps || [], { includePlan: true })
      .some((st) => (st.detail || "").trim());

    (source.thoughts || []).filter(Boolean).forEach((line) => {
      const text = String(line).trim();
      if (!text || text === managerPlan) return;
      if (text.startsWith("── ")) return;
      if (text === "Delegation decisions:") return;
      if (hasStepDetails && /^Step \d+ → /.test(text)) return;
      if (hasStepDetails && text.startsWith("Not delegating to ")) return;
      pushBlock(summarizeThoughtLine(text), text);
    });

    delegationStepsForDisplay(source.steps || [], { includePlan: true }).forEach((st) => {
      const detail = (st.detail || "").trim();
      const label = (st.label || st.skill || "Step").trim();
      if (detail) {
        pushBlock(label, detail);
      } else if (label) {
        pushBlock(label, label);
      }
    });

    return blocks;
  }

  function renderThoughtBlocksHtml(blocks) {
    if (!blocks.length) {
      return `<p class="thought-block-empty">Thinking…</p>`;
    }
    return blocks.map((block) => {
      const showBody = block.body.length > block.summary.length + 16 && block.body !== block.summary;
      return `
        <article class="thought-block">
          <header class="thought-block-summary">
            <span>${escapeHtml(block.summary)}</span>
            <span class="thought-block-chevron" aria-hidden="true">›</span>
          </header>
          ${showBody ? `<p class="thought-block-body">${escapeHtml(block.body)}</p>` : ""}
        </article>`;
    }).join("");
  }

  function scrollThoughtBlocksToBottom(root, { force = false } = {}) {
    const scroller = root?.querySelector?.(".thought-blocks-scroll")
      || root?.closest?.(".thought-blocks-scroll")
      || root;
    if (!scroller) return;
    const atBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 28;
    if (force || atBottom) {
      scroller.scrollTop = scroller.scrollHeight;
    }
  }

  function renderDelegationStepsHtml(steps, { showActiveDetail = true } = {}) {
    const visible = delegationStepsForDisplay(steps);
    if (!visible.length) return "";
    return `<div class="thinking-claude-delegation">
        <span class="thinking-claude-delegation-label">Delegation</span>
        <ol class="thinking-claude-steps">${visible.map((st) => `
          <li class="thinking-claude-step status-${st.status || "queued"}">
            ${thinkingStepIcon(st.status)}
            <span class="thinking-claude-step-label">${escapeHtml(st.skill || st.label || "Step")}</span>
            ${showActiveDetail && st.status === "active" && st.detail
              ? `<span class="thinking-claude-step-detail">${escapeHtml(st.detail)}</span>`
              : ""}
          </li>`).join("")}</ol>
      </div>`;
  }

  function buildOptimisticProgress(content, agentName) {
    const preview = (content || "").trim();
    const short = preview.length > 120 ? `${preview.slice(0, 117)}…` : preview;
    const lower = preview.toLowerCase();
    const thoughts = [`Reading your message: «${short}»`];
    if (/\bwhat\b.*\bdate\b|\btoday'?s date\b|\bcurrent date\b/.test(lower)) {
      thoughts.push("I can answer this directly — no specialist delegation needed.");
      thoughts.push("Checking the current date and timezone.");
    } else if (/^(hi|hello|hey)\b/.test(lower)) {
      thoughts.push("I can answer this directly — no specialist delegation needed.");
      thoughts.push("Preparing a brief, friendly reply.");
    } else {
      thoughts.push(`${agentName || "Agent"} is reviewing your request…`);
    }
    return {
      mode: "simple",
      phase_label: thoughts[thoughts.length - 1],
      agent_name: agentName || "Agent",
      thoughts,
    };
  }

  function renderThinkingPanelHtml(progress) {
    const p = progress || {};
    const phaseLabel = escapeHtml(p.phase_label || "Thinking…");
    const blocks = buildThoughtBlocks(p);
    const blocksHtml = renderThoughtBlocksHtml(blocks);

    return `
      <div class="chat-msg chat-msg-assistant chat-thinking-panel" id="collab-thinking">
        <div class="thinking-claude card">
          <button type="button" class="thinking-claude-toggle" id="collab-thinking-toggle" aria-expanded="true">
            <span class="thinking-claude-spinner"></span>
            <span class="thinking-claude-title">Thinking</span>
            <span class="thinking-claude-phase">${phaseLabel}</span>
            <span class="thinking-claude-chevron">▾</span>
          </button>
          <div class="thinking-claude-body" id="collab-thinking-body">
            <div class="thought-blocks-scroll thinking-claude-log">${blocksHtml}</div>
          </div>
        </div>
      </div>`;
  }

  function bindThinkingPanel() {
    const toggle = $("collab-thinking-toggle");
    const body = $("collab-thinking-body");
    if (!toggle || !body || toggle.dataset.bound) return;
    toggle.dataset.bound = "1";
    toggle.addEventListener("click", () => {
      const collapsed = body.classList.toggle("hidden");
      toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
      toggle.closest(".thinking-claude")?.classList.toggle("collapsed", collapsed);
    });
  }

  function isComposerGenerating() {
    return sending || !!currentThread?.is_generating;
  }

  async function cancelActiveGeneration() {
    if (!currentThread?.id) return;
    const btn = $("collab-send-btn");
    if (btn) btn.classList.add("is-stopping");
    try {
      await window.api(`/chat/threads/${currentThread.id}/cancel`, { method: "POST" });
      sending = false;
      const fresh = await window.api(`/chat/threads/${currentThread.id}`);
      if (currentThread?.id === fresh.id) {
        applyLoadedThread(fresh);
      }
      await loadSidebar();
    } catch (err) {
      alert(err.message || "Could not stop generation");
    } finally {
      btn?.classList.remove("is-stopping");
      updateSendState();
    }
  }

  function showThinkingPanel(progress, { forceScroll = false } = {}) {
    const container = $("collab-messages");
    if (!container) return;
    const existing = container.querySelector("#collab-thinking");
    const wasCollapsed = existing?.querySelector(".thinking-claude")?.classList.contains("collapsed");
    const logEl = existing?.querySelector(".thought-blocks-scroll");
    const logScroll = logEl?.scrollTop ?? 0;
    const logAtBottom = logEl
      ? logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 28
      : true;

    if (existing) {
      existing.outerHTML = renderThinkingPanelHtml(progress);
    } else {
      container.insertAdjacentHTML("beforeend", renderThinkingPanelHtml(progress));
    }
    bindThinkingPanel();

    if (wasCollapsed) {
      const card = container.querySelector("#collab-thinking .thinking-claude");
      const body = $("collab-thinking-body");
      const toggle = $("collab-thinking-toggle");
      card?.classList.add("collapsed");
      body?.classList.add("hidden");
      toggle?.setAttribute("aria-expanded", "false");
    }

    const newLog = container.querySelector("#collab-thinking .thought-blocks-scroll");
    if (newLog) {
      newLog.scrollTop = logAtBottom || forceScroll ? newLog.scrollHeight : logScroll;
    }

    scrollToBottom({ force: forceScroll });
  }

  function removeThinkingPanel() {
    $("collab-thinking")?.remove();
  }

  function startThreadPoll(threadId, { immediate = false } = {}) {
    stopThreadPoll();
    pollingThreadId = threadId;

    const poll = async () => {
      if (pollingThreadId !== threadId || currentThread?.id !== threadId) return;
      try {
        const fresh = await window.api(`/chat/threads/${threadId}`);
        if (pollingThreadId !== threadId || currentThread?.id !== threadId) return;

        if (fresh.is_generating) {
          const prevSig = messagesSignature(currentThread?.messages);
          const nextSig = messagesSignature(fresh.messages);
          currentThread = fresh;
          if (prevSig !== nextSig) {
            preserveMessagesScroll(() => {
              renderMessages(fresh.messages || []);
              showThinkingPanel(fresh.generation_progress);
            });
          } else {
            showThinkingPanel(fresh.generation_progress);
          }
          threadPollTimer = setTimeout(poll, 300);
          return;
        }

        currentThread = fresh;
        sending = false;
        removeThinkingPanel();
        updateSendState();
        preserveMessagesScroll(() => {
          renderMessages(fresh.messages || []);
        });
        bindProgressCards($("collab-messages"));
        bindThoughtDropdowns($("collab-messages"));
        scrollToBottom();
        await loadSidebar();
        if (window.Billing?.load) {
          await window.Billing.load().catch(() => {});
        }
        const accountModal = $("account-modal");
        const accountBody = $("account-modal-body");
        if (
          accountModal
          && !accountModal.classList.contains("hidden")
          && accountBody
          && accountModalView !== "payment"
        ) {
          renderAccountOverview(accountBody);
        }
        stopThreadPoll();
      } catch {
        if (pollingThreadId === threadId) {
          threadPollTimer = setTimeout(poll, 1500);
        }
      }
    };

    if (immediate) {
      poll();
    } else {
      threadPollTimer = setTimeout(poll, 250);
    }
  }

  async function loadThreadMemory(threadId) {
    const topicsEl = $("collab-memory-topics");
    const statusEl = $("collab-memory-status");
    const summaryWrap = $("collab-memory-summary-wrap");
    const summaryEl = $("collab-memory-summary");
    if (!topicsEl || !threadId) return;
    try {
      const mem = await window.api(`/chat/threads/${threadId}/memory`);
      const running = mem.compaction_running || mem.compaction_status === "running";
      const msgCount = mem.eligible_message_count || 0;
      const hasTopics = (mem.topics || []).length > 0;
      const hasSummary = Boolean(mem.rolling_summary?.trim());

      if (statusEl) {
        if (running) {
          statusEl.textContent = "Updating memory…";
        } else if (hasTopics) {
          statusEl.textContent = `${mem.topics.length} topic${mem.topics.length === 1 ? "" : "s"}`;
        } else if (hasSummary) {
          statusEl.textContent = "Summary saved";
        } else if (msgCount > 0) {
          statusEl.textContent = `${msgCount} message${msgCount === 1 ? "" : "s"}`;
        } else {
          statusEl.textContent = "Empty thread";
        }
        statusEl.classList.toggle("is-running", running);
      }

      if (hasTopics) {
        topicsEl.innerHTML = mem.topics.map((t) => {
          const insights = (t.key_insights || []).slice(0, 3);
          const insightHtml = insights.length
            ? `<ul>${insights.map((i) => `<li>${escapeHtml(i)}</li>`).join("")}</ul>`
            : "";
          return `<div class="collab-memory-topic"><strong>${escapeHtml(t.title)}</strong><p>${escapeHtml(t.summary || "")}</p>${insightHtml}</div>`;
        }).join("");
      } else if (hasSummary) {
        topicsEl.innerHTML = `<div class="collab-memory-topic"><strong>Conversation summary</strong><p>${escapeHtml(mem.rolling_summary)}</p></div>`;
      } else if (msgCount > 0) {
        topicsEl.innerHTML = `<p class="collab-memory-hint">This chat has ${msgCount} message${msgCount === 1 ? "" : "s"}. Recent messages are used automatically when the agent replies. Summarized topics appear here after longer conversations are compacted.</p>`;
      } else {
        topicsEl.innerHTML = '<p class="collab-memory-hint">No messages in this thread yet. The agent will use new messages as you chat.</p>';
      }

      if (summaryWrap && summaryEl) {
        summaryWrap.classList.toggle("hidden", !hasSummary || !hasTopics);
        if (hasSummary && hasTopics) summaryEl.textContent = mem.rolling_summary;
      }
    } catch {
      if (topicsEl) topicsEl.innerHTML = '<p class="collab-memory-hint">Memory unavailable for this thread.</p>';
    }
  }

  function applyLoadedThread(thread) {
    currentThread = thread;
    showProjectEmptyState(false);
    stopThreadPoll();
    renderMessages(thread.messages || []);
    bindProgressCards($("collab-messages"));
    loadThreadMemory(thread.id);

    if (thread.is_generating) {
      sending = true;
      updateSendState();
      showThinkingPanel(thread.generation_progress);
      startThreadPoll(thread.id);
    } else {
      sending = false;
      removeThinkingPanel();
      updateSendState();
    }
    scrollToBottom({ force: true });
    updateThreadChatMenu();
    updateThreadHeaderActions();
  }

  function showWelcome() {
    if (currentMode === "welcome") {
      const hash = location.hash.replace(/^#\/?/, "") || "";
      if (hash === "home" || hash === "") return;
    }
    stopThreadPoll();
    sending = false;
    currentMode = "welcome";
    currentThread = null;
    currentProject = null;
    currentProjectAgentId = null;
    currentAgentId = null;
    hideAllPanels();
    setProjectColumnVisible(false);
    closeAllDrawers();
    document.querySelector(".collab-shell")?.classList.remove("project-open");
    $("collab-welcome")?.classList.remove("hidden");
    const g = $("collab-greeting");
    if (g) g.textContent = greeting();
    setHash("home");
    renderSidebar();
    updateThreadChatMenu();
  }

  function showThreadView() {
    hideAllPanels();
    $("collab-thread-view")?.classList.remove("hidden");
    showProjectEmptyState(false);
    if (currentMode !== "project") currentMode = "thread";
    renderSidebar();
    updateThreadChatMenu();
  }

  function showAgentsRoster() {
    stopThreadPoll();
    sending = false;
    currentMode = "agents-roster";
    currentThread = null;
    currentProject = null;
    currentProjectAgentId = null;
    currentAgentId = null;
    hideAllPanels();
    setProjectColumnVisible(false);
    closeAllDrawers();
    document.querySelector(".collab-shell")?.classList.remove("project-open");
    $("collab-agents-roster")?.classList.remove("hidden");
    setHash("agents");
    renderAgentRoster();
    renderSidebar();
  }

  const PREBUILT_RING_R = 20;
  const PREBUILT_RING_C = 2 * Math.PI * PREBUILT_RING_R;
  const prebuiltAddProgressFrames = new Map();

  async function loadPrebuiltCatalog(search = "") {
    const q = search.trim();
    const path = q ? `/agents/prebuilt?search=${encodeURIComponent(q)}` : "/agents/prebuilt";
    const data = await window.api(path);
    prebuiltAgents = data.agents || [];
    renderPrebuiltCatalog();
  }

  function prebuiltIconRingHtml() {
    return `
      <svg class="prebuilt-icon-ring" viewBox="0 0 44 44" aria-hidden="true">
        <circle class="prebuilt-icon-ring-track" cx="22" cy="22" r="${PREBUILT_RING_R}" fill="none"></circle>
        <circle class="prebuilt-icon-ring-progress" cx="22" cy="22" r="${PREBUILT_RING_R}" fill="none"></circle>
      </svg>`;
  }

  function setPrebuiltRingProgress(card, percent) {
    const ring = card?.querySelector(".prebuilt-icon-ring-progress");
    if (!ring) return;
    const clamped = Math.max(0, Math.min(100, percent));
    ring.style.strokeDashoffset = String(PREBUILT_RING_C * (1 - clamped / 100));
  }

  function stopPrebuiltAddProgress(card) {
    const frame = prebuiltAddProgressFrames.get(card);
    if (frame) cancelAnimationFrame(frame);
    prebuiltAddProgressFrames.delete(card);
  }

  function startPrebuiltAddProgress(card) {
    stopPrebuiltAddProgress(card);
    setPrebuiltRingProgress(card, 0);
    const start = performance.now();
    const duration = 48000;
    const maxPercent = 92;

    const tick = (now) => {
      if (!card?.classList.contains("prebuilt-card-adding")) return;
      const elapsed = now - start;
      const t = Math.min(1, elapsed / duration);
      const eased = 1 - Math.pow(1 - t, 2.2);
      setPrebuiltRingProgress(card, maxPercent * eased);
      if (t < 1) {
        prebuiltAddProgressFrames.set(card, requestAnimationFrame(tick));
      }
    };

    prebuiltAddProgressFrames.set(card, requestAnimationFrame(tick));
  }

  async function finishPrebuiltAddProgress(card) {
    stopPrebuiltAddProgress(card);
    setPrebuiltRingProgress(card, 100);
    await new Promise((resolve) => setTimeout(resolve, 400));
  }

  function buildPrebuiltCardHtml(agent) {
    const skillsHtml = (agent.skills || []).slice(0, 5).map((s) =>
      `<span class="skill-tag">${escapeHtml(s)}</span>`
    ).join("");
    const meta = [agent.job_title, agent.field, agent.industry].filter(Boolean).join(" · ");
    return `
      <article class="prebuilt-card card" data-prebuilt-id="${escapeHtml(agent.id)}">
        <div class="prebuilt-card-header">
          <div class="prebuilt-icon-wrap">
            ${prebuiltIconRingHtml()}
            <span class="prebuilt-card-icon">${agent.icon || "✦"}</span>
          </div>
          <div class="prebuilt-card-meta">
            <h3>${escapeHtml(agent.name)}</h3>
            <p class="prebuilt-tagline">${escapeHtml(agent.tagline || "")}</p>
            <p class="prebuilt-role">${escapeHtml(meta)}</p>
          </div>
        </div>
        <p class="prebuilt-description">${escapeHtml(agent.description || "")}</p>
        <div class="skill-tags prebuilt-skills">${skillsHtml}</div>
        <div class="prebuilt-card-actions">
          ${agent.added
            ? '<span class="prebuilt-added-badge">Added</span>'
            : `<button type="button" class="btn btn-primary btn-sm" data-add-prebuilt="${escapeHtml(agent.id)}">Add to workspace</button>`}
        </div>
      </article>`;
  }

  function renderPrebuiltCatalog() {
    const grid = $("collab-prebuilt-grid");
    const empty = $("collab-prebuilt-empty");
    if (!grid) return;

    if (!prebuiltAgents.length) {
      grid.innerHTML = "";
      empty?.classList.remove("hidden");
      return;
    }
    empty?.classList.add("hidden");
    grid.innerHTML = prebuiltAgents.map(buildPrebuiltCardHtml).join("");

    grid.querySelectorAll("[data-add-prebuilt]").forEach((btn) => {
      btn.addEventListener("click", () => addPrebuiltAgent(btn.dataset.addPrebuilt, btn));
    });
  }

  async function addPrebuiltAgent(templateId, btn) {
    if (!templateId || btn?.disabled) return;
    const card = btn?.closest(".prebuilt-card");
    const original = btn?.textContent;
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Adding…";
      btn.setAttribute("aria-busy", "true");
    }
    if (card) {
      card.classList.add("prebuilt-card-adding");
      card.setAttribute("aria-busy", "true");
      startPrebuiltAddProgress(card);
    }
    try {
      const result = await window.api(`/agents/prebuilt/${templateId}/add`, { method: "POST" });
      if (card) await finishPrebuiltAddProgress(card);
      await window.loadHome?.();
      await loadSidebar();
      await loadPrebuiltCatalog(prebuiltSearch);
      renderSidebar();
      if (result.session_id) {
        await showAgentDetail(result.session_id);
      }
    } catch (err) {
      if (card) {
        stopPrebuiltAddProgress(card);
        card.classList.remove("prebuilt-card-adding");
        card.removeAttribute("aria-busy");
        setPrebuiltRingProgress(card, 0);
      }
      if (btn) {
        btn.disabled = false;
        btn.textContent = original || "Add to workspace";
        btn.removeAttribute("aria-busy");
      }
      alert(err.message || "Could not add agent");
    }
  }

  async function showPrebuiltAgentsBrowse() {
    stopThreadPoll();
    sending = false;
    currentMode = "prebuilt-browse";
    currentThread = null;
    currentProject = null;
    currentAgentId = null;
    hideAllPanels();
    $("collab-prebuilt-agents")?.classList.remove("hidden");
    setHash("agents/browse");
    const searchInput = $("collab-prebuilt-search");
    if (searchInput && searchInput.value !== prebuiltSearch) {
      searchInput.value = prebuiltSearch;
    }
    await loadPrebuiltCatalog(prebuiltSearch);
    renderSidebar();
    searchInput?.focus();
  }

  function renderJobDescriptionHtml(jd) {
    if (!jd || typeof jd !== "object") return "";
    const responsibilities = Array.isArray(jd.responsibilities) ? jd.responsibilities : [];
    const hasContent = jd.title || jd.summary || responsibilities.length
      || Object.keys(jd).some((k) => !["title", "summary", "responsibilities"].includes(k) && jd[k]);
    if (!hasContent) return "";

    const title = jd.title
      ? `<p class="persona-jd-title">${escapeHtml(String(jd.title))}</p>`
      : "";
    const summary = jd.summary
      ? `<p class="persona-jd-summary">${escapeHtml(String(jd.summary))}</p>`
      : "";
    const respHtml = responsibilities.length
      ? `<ul class="persona-jd-list">${responsibilities.map((r) => `<li>${escapeHtml(String(r))}</li>`).join("")}</ul>`
      : "";

    const extraHtml = Object.entries(jd)
      .filter(([key, value]) => !["title", "summary", "responsibilities"].includes(key) && value)
      .map(([key, value]) => {
        const label = key.replace(/_/g, " ");
        if (Array.isArray(value)) {
          const items = value.map((item) => `<li>${escapeHtml(String(item))}</li>`).join("");
          return `<div class="persona-jd-extra"><h5 class="persona-jd-extra-label">${escapeHtml(label)}</h5><ul class="persona-jd-list">${items}</ul></div>`;
        }
        return `<div class="persona-jd-extra"><h5 class="persona-jd-extra-label">${escapeHtml(label)}</h5><p class="persona-jd-extra-text">${escapeHtml(String(value))}</p></div>`;
      })
      .join("");

    return `
      <div class="persona-section persona-jd-section">
        <h4>Job description</h4>
        <div class="persona-jd">${title}${summary}${respHtml}${extraHtml}</div>
      </div>`;
  }

  function personaStatusBadges(persona) {
    const trainingLabel = persona.status === "configured"
      ? "Personalized"
      : `${persona.training.completed}/${persona.training.total} tasks`;
    const statusBadge = persona.status === "completed"
      ? '<span class="persona-badge complete">Fully trained</span>'
      : persona.status === "configured"
        ? '<span class="persona-badge">Framework ready</span>'
        : '<span class="persona-badge">In training</span>';
    return { trainingLabel, statusBadge };
  }

  function buildPersonaCardHtml(persona, { expanded = false, showContext = false, workingInstructions = "", contextFiles = [] } = {}) {
    const { trainingLabel, statusBadge } = personaStatusBadges(persona);
    const displaySkills = filterUserSkills(persona.skills || []);
    const skillsSection = showContext ? `
          <div class="persona-section persona-skills-editable">
            <h4>Skills</h4>
            <p class="collab-drawer-hint">Up to ${MAX_AGENT_SKILLS} skills. Adding or removing skills rebuilds the agent framework.</p>
            <div id="agent-detail-skills-${persona.session_id}" class="skill-tags"></div>
            <div class="collab-agent-skill-add">
              <input type="text" id="agent-detail-skill-input-${persona.session_id}" class="collab-agent-skill-input" placeholder="Add a skill…" maxlength="80" aria-label="New skill">
              <button type="button" class="btn btn-secondary btn-sm" id="agent-detail-skill-add-btn-${persona.session_id}">Add</button>
            </div>
            <p id="agent-detail-skills-status-${persona.session_id}" class="collab-drawer-save-status hidden"></p>
          </div>`
      : `<div class="persona-section"><h4>Skills</h4><div class="skill-tags">${renderEditableSkillsHtml(displaySkills, { removable: false }) || '<span class="skill-tag">No skills listed</span>'}</div></div>`;
    const jdHtml = renderJobDescriptionHtml(persona.job_description);

    const contextSection = showContext ? `
      <div class="persona-section agent-context-section">
        <h4>Working context</h4>
        <p class="agent-context-hint">Instructions and files your agent uses in every conversation.</p>
        <label class="modal-label" for="agent-instructions-${persona.session_id}">Instructions</label>
        <textarea id="agent-instructions-${persona.session_id}" class="agent-instructions-input" rows="4" placeholder="Tone, goals, constraints, how you want this agent to work…"></textarea>
        <div class="agent-context-actions">
          <button type="button" class="btn btn-secondary btn-sm" data-save-instructions="${persona.session_id}">Save instructions</button>
          <button type="button" class="btn btn-secondary btn-sm" data-upload-context="${persona.session_id}">+ Add file</button>
        </div>
        <div class="agent-context-files" id="agent-context-files-${persona.session_id}">
          ${(contextFiles || []).map((f) => `<span class="collab-file-chip">📎 ${escapeHtml(f.filename)}</span>`).join("")
            || '<span class="collab-list-empty">No context files yet</span>'}
        </div>
      </div>` : "";

    return `
      <div class="persona-card${expanded ? " expanded" : ""}" data-session-id="${persona.session_id}">
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
            ${showContext ? "" : '<span class="persona-chevron">▾</span>'}
          </div>
        </div>
        <div class="persona-body">
          ${skillsSection}
          ${jdHtml}
          ${contextSection}
          <div class="persona-actions">
            ${persona.artifacts?.skill_md_id ? `<a class="btn btn-secondary" href="/api/studio/artifacts/${persona.artifacts.skill_md_id}/download">Download skills</a>` : ""}
            ${persona.artifacts?.framework_json_id ? `<a class="btn btn-secondary" href="/api/studio/artifacts/${persona.artifacts.framework_json_id}/download">Download framework</a>` : ""}
          </div>
        </div>
      </div>`;
  }

  function wirePersonaCard(card, persona) {
    card.querySelector(".persona-header")?.addEventListener("click", (e) => {
      if (e.target.closest(".persona-menu") || e.target.closest(".persona-chat-btn")) return;
      if (currentMode === "agents-roster") {
        showAgentDetail(persona.session_id);
        return;
      }
      card.classList.toggle("expanded");
    });
    card.querySelector(".persona-chat-btn")?.addEventListener("click", (e) => {
      e.stopPropagation();
      openAgentDm(persona.session_id);
    });
    window.attachPersonaMenu?.(card, persona);

    card.querySelector("[data-save-instructions]")?.addEventListener("click", async () => {
      const sid = persona.session_id;
      const text = $(`agent-instructions-${sid}`)?.value ?? "";
      await window.api(`/agents/${sid}/working-context`, {
        method: "PUT",
        body: JSON.stringify({ working_instructions: text }),
      });
      const btn = card.querySelector("[data-save-instructions]");
      if (btn) { btn.textContent = "Saved"; setTimeout(() => { btn.textContent = "Save instructions"; }, 1500); }
    });
    card.querySelector("[data-upload-context]")?.addEventListener("click", () => {
      currentAgentId = persona.session_id;
      $("collab-agent-context-file")?.click();
    });
  }

  function renderAgentRoster() {
    const grid = $("collab-agents-grid");
    const empty = $("collab-agents-empty");
    if (!grid) return;
    grid.innerHTML = "";
    if (!personas.length) {
      empty?.classList.remove("hidden");
      return;
    }
    empty?.classList.add("hidden");
    personas.forEach((persona) => {
      const wrap = document.createElement("div");
      wrap.innerHTML = buildPersonaCardHtml(persona);
      const card = wrap.firstElementChild;
      wirePersonaCard(card, persona);
      grid.appendChild(card);
    });
  }

  async function showAgentDetail(sessionId) {
    stopThreadPoll();
    sending = false;
    currentMode = "agent-detail";
    currentAgentId = sessionId;
    currentThread = null;
    currentProject = null;
    currentProjectAgentId = null;
    hideAllPanels();
    setProjectColumnVisible(false);
    $("collab-agent-detail")?.classList.remove("hidden");
    setHash(`agents/${sessionId}`);

    const persona = personas.find((p) => p.session_id === sessionId);
    if (!persona) return;

    let workingInstructions = "";
    let contextFiles = [];
    let personaForDetail = { ...persona, skills: filterUserSkills(persona.skills || []) };
    try {
      const data = await window.api(`/agents/${sessionId}`);
      workingInstructions = data.working_instructions || "";
      contextFiles = data.context_files || [];
      personaForDetail = {
        ...personaForDetail,
        skills: filterUserSkills(data.skills || parseSkillsetString(data.skillset)),
      };
      if (data.job_description) {
        personaForDetail = { ...personaForDetail, job_description: data.job_description };
        const idx = personas.findIndex((p) => p.session_id === sessionId);
        if (idx >= 0) personas[idx] = { ...personas[idx], job_description: data.job_description };
      }
    } catch (_) {}

    agentDetailSkillsSessionId = sessionId;
    agentDetailSkills = [...personaForDetail.skills];

    const container = $("collab-agent-detail-content");
    if (!container) return;
    container.innerHTML = `
      <div class="collab-agents-header">
        <button type="button" class="collab-back-btn" id="collab-back-agents">← All agents</button>
        <p class="page-eyebrow">Agent details</p>
        <h2>${escapeHtml(personaForDetail.name)}</h2>
      </div>
      ${buildPersonaCardHtml(personaForDetail, { expanded: true, showContext: true, workingInstructions, contextFiles })}
    `;
    const card = container.querySelector(".persona-card");
    if (card) wirePersonaCard(card, persona);
    renderAgentDetailSkills(sessionId);
    const detailSkillInput = $(`agent-detail-skill-input-${sessionId}`);
    const detailSkillAddBtn = $(`agent-detail-skill-add-btn-${sessionId}`);
    detailSkillAddBtn?.addEventListener("click", () => addAgentDetailSkill(sessionId));
    detailSkillInput?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        addAgentDetailSkill(sessionId);
      }
    });
    const instrEl = $(`agent-instructions-${sessionId}`);
    if (instrEl) instrEl.value = workingInstructions || "";
    $("collab-back-agents")?.addEventListener("click", showAgentsRoster);
    renderSidebar();
  }

  const navInFlight = new Map();

  function isViewingAgentDm(sessionId) {
    return (
      currentAgentId === sessionId
      && !!currentThread?.id
      && currentMode === "thread"
      && !currentProject
    );
  }

  function isViewingProjectAgent(projectId, agentSessionId) {
    return (
      currentMode === "project"
      && currentProject?.id === projectId
      && currentProjectAgentId === agentSessionId
      && !!currentThread?.id
    );
  }

  async function openAgentDm(sessionId) {
    const navKey = `agent:${sessionId}`;
    if (isViewingAgentDm(sessionId)) {
      showThreadView();
      return;
    }
    if (navInFlight.has(navKey)) {
      return navInFlight.get(navKey);
    }

    const task = (async () => {
      currentAgentId = sessionId;
      currentProject = null;
      currentProjectAgentId = null;
      currentMode = "thread";
      currentThread = null;
      updateThreadChatMenu();
      setProjectColumnVisible(false);
      closeAllDrawers();
      document.querySelector(".collab-shell")?.classList.remove("project-open");
      showThreadView();
      setHash(`chat/agent/${sessionId}`);

      const agent = agents.find((a) => a.session_id === sessionId);
      const dm = agentDms.find((a) => a.session_id === sessionId);
      renderThreadBreadcrumb({ agentName: agent?.name || "Agent" });
      updateThreadHeaderActions();

      $("collab-messages").innerHTML = '<div class="workspace-loading">Loading…</div>';

      let thread;
      if (dm?.thread_id) {
        thread = await window.api(`/chat/threads/${dm.thread_id}`);
      } else {
        thread = await window.api("/chat/threads", {
          method: "POST",
          body: JSON.stringify({ agent_session_id: sessionId, thread_type: "agent_dm" }),
        });
      }
      syncDmThreadId(sessionId, thread.id);
      applyLoadedThread(thread);
      await loadSidebar();
    })();

    navInFlight.set(navKey, task);
    try {
      await task;
    } finally {
      navInFlight.delete(navKey);
    }
  }

  async function openThread(threadId, type) {
    currentThread = null;
    updateThreadChatMenu();
    showThreadView();
    currentProject = null;
    closeAllDrawers();
    setHash(`chat/thread/${threadId}`);

    const thread = await window.api(`/chat/threads/${threadId}`);

    if (thread.thread_type === "group") {
      showWelcome();
      return;
    }

    currentThread = thread;
    currentAgentId = thread.agent_session_id;

    if (thread.thread_type === "project" || thread.thread_type === "project_agent") {
      await openProject(thread.project_id, thread, thread.agent_session_id);
      return;
    }

    setProjectColumnVisible(false);
    applyLoadedThread(thread);
  }

  async function openProject(projectId, existingThread, agentSessionId) {
    const project = await window.api(`/projects/${projectId}`);
    currentProject = project;

    const projectAgents = project.agents || [];
    if (!agentSessionId && projectAgents.length) {
      agentSessionId = projectAgents[0].session_id;
    }

    if (isViewingProjectAgent(projectId, agentSessionId)) {
      showThreadView();
      return;
    }

    const navKey = `project:${projectId}:${agentSessionId || "none"}`;
    if (navInFlight.has(navKey)) {
      return navInFlight.get(navKey);
    }

    const task = (async () => {
      currentMode = "project";
      currentProjectAgentId = agentSessionId || null;
      hideAllPanels();
      closeAllDrawers();
      document.querySelector(".collab-shell")?.classList.add("project-open");
      showThreadView();

      if (agentSessionId) {
        setHash(`project/${projectId}/agent/${agentSessionId}`);
      } else {
        setHash(`project/${projectId}`);
      }

      const agentInfo = projectAgents.find((a) => a.session_id === agentSessionId);
      renderThreadBreadcrumb({
        projectName: project.name,
        topic: agentInfo?.name || "Project workspace",
        agentName: agentInfo?.name,
      });

      await renderProjectPanel(project);

      if (agentSessionId) {
        showProjectEmptyState(false);
        let thread = existingThread;
        if (!thread) {
          thread = await window.api("/chat/threads", {
            method: "POST",
            body: JSON.stringify({
              thread_type: "project_agent",
              project_id: projectId,
              agent_session_id: agentSessionId,
            }),
          });
        }
        currentAgentId = agentSessionId;
        applyLoadedThread(thread);
        await loadRecentFeedback(projectId, agentSessionId);
      } else {
        currentThread = null;
        currentAgentId = null;
        stopThreadPoll();
        sending = false;
        showProjectEmptyState(true);
        if ($("collab-messages")) $("collab-messages").innerHTML = "";
      }
      renderSidebar();
      updateThreadChatMenu();
      updateThreadHeaderActions();
    })();

    navInFlight.set(navKey, task);
    try {
      await task;
    } finally {
      navInFlight.delete(navKey);
    }
  }

  const MSG_ACTION_ICONS = {
    copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="8.5" y="8.5" width="11" height="13" rx="1.5"/><path d="M7.5 15.5H6a1.5 1.5 0 0 1-1.5-1.5V5.5A1.5 1.5 0 0 1 6 4h8.5A1.5 1.5 0 0 1 16 5.5V7"/></svg>',
    thumbsUp: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7.5 11.5V19h-1A1.5 1.5 0 0 1 5 17.5v-5A1.5 1.5 0 0 1 6.5 11h1z"/><path d="M7.5 11.5 10 5.2c.3-.8 1.2-1.2 2-1 .8.2 1.3 1 1.3 1.8V9h5.2c1 0 1.7.9 1.5 1.9l-1.2 5.6c-.2.9-1 1.5-1.9 1.5H9.5"/></svg>',
    thumbsDown: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16.5 12.5V5h1A1.5 1.5 0 0 1 19 6.5v5a1.5 1.5 0 0 1-1.5 1.5h-1z"/><path d="M16.5 12.5 14 18.8c-.3.8-1.2 1.2-2 1-.8-.2-1.3-1-1.3-1.8V15H5.5c-1 0-1.7-.9-1.5-1.9l1.2-5.6c.2-.9 1-1.5 1.9-1.5H14.5"/></svg>',
    rerun: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 7.5A6.5 6.5 0 0 0 7.2 5.6L5.5 7.3"/><path d="M7 16.5A6.5 6.5 0 0 0 16.8 18.4l1.7-1.7"/><path d="M5.5 4.5v2.8h2.8"/><path d="M18.5 19.5v-2.8h-2.8"/></svg>',
  };

  function stripUserMention(content) {
    const text = (content || "").trim();
    const stripped = text.replace(/^@\S+\s+/, "").trim();
    return stripped || text;
  }

  function findPrecedingUserPrompt(messages, index) {
    for (let i = index - 1; i >= 0; i--) {
      if (messages[i]?.role === "user") {
        return stripUserMention(messages[i].content);
      }
    }
    return "";
  }

  function getMessageById(msgId) {
    return (currentThread?.messages || []).find((m) => String(m.id) === String(msgId));
  }

  function findUserPromptForMessage(msgId) {
    const messages = currentThread?.messages || [];
    const idx = messages.findIndex((m) => String(m.id) === String(msgId));
    if (idx < 0) return "";
    return findPrecedingUserPrompt(messages, idx);
  }

  function renderMessageActions(msg, userPrompt) {
    if (!msg.id || msg.role !== "assistant") return "";
    const rating = (msg.meta || {}).rating;
    const canRerun = !!userPrompt;
    return `
      <div class="chat-msg-actions" data-msg-id="${msg.id}">
        <button type="button" class="chat-msg-action-btn" data-action="copy" title="Copy" aria-label="Copy">
          ${MSG_ACTION_ICONS.copy}
        </button>
        <button type="button" class="chat-msg-action-btn${rating === "up" ? " active" : ""}" data-action="thumbs-up" title="Good response" aria-label="Good response">
          ${MSG_ACTION_ICONS.thumbsUp}
        </button>
        <button type="button" class="chat-msg-action-btn${rating === "down" ? " active" : ""}" data-action="thumbs-down" title="Poor response" aria-label="Poor response">
          ${MSG_ACTION_ICONS.thumbsDown}
        </button>
        <button type="button" class="chat-msg-action-btn" data-action="rerun" title="Rerun" aria-label="Rerun"${canRerun ? "" : " disabled"}>
          ${MSG_ACTION_ICONS.rerun}
        </button>
      </div>`;
  }

  function updateMessageRatingUI(bar, rating) {
    if (!bar) return;
    bar.querySelectorAll("[data-action='thumbs-up'], [data-action='thumbs-down']").forEach((btn) => {
      btn.classList.remove("active");
    });
    if (rating === "up") {
      bar.querySelector("[data-action='thumbs-up']")?.classList.add("active");
    } else if (rating === "down") {
      bar.querySelector("[data-action='thumbs-down']")?.classList.add("active");
    }
  }

  function bindMessageActions(root) {
    root?.querySelectorAll(".chat-msg-action-btn").forEach((btn) => {
      if (btn.dataset.bound) return;
      btn.dataset.bound = "1";
      btn.addEventListener("click", async () => {
        if (btn.disabled) return;
        const action = btn.dataset.action;
        const bar = btn.closest(".chat-msg-actions");
        const msgId = bar?.dataset.msgId;
        if (!msgId) return;

        if (action === "copy") {
          const msg = getMessageById(msgId);
          const text = msg?.content || "";
          if (!text) return;
          try {
            await navigator.clipboard.writeText(text);
            btn.classList.add("copied");
            const prevTitle = btn.title;
            btn.title = "Copied!";
            setTimeout(() => {
              btn.classList.remove("copied");
              btn.title = prevTitle;
            }, 1500);
          } catch {
            /* clipboard unavailable */
          }
          return;
        }

        if (action === "thumbs-up" || action === "thumbs-down") {
          const rating = action === "thumbs-up" ? "up" : "down";
          try {
            const res = await window.api(`/chat/messages/${msgId}/rating`, {
              method: "POST",
              body: JSON.stringify({ rating }),
            });
            updateMessageRatingUI(bar, res.rating);
            const msg = getMessageById(msgId);
            if (msg) {
              msg.meta = { ...(msg.meta || {}), rating: res.rating || undefined };
              if (!res.rating) delete msg.meta.rating;
            }
          } catch {
            /* rating failed silently */
          }
          return;
        }

        if (action === "rerun") {
          const prompt = findUserPromptForMessage(msgId);
          if (!prompt || sending) return;
          sendMessage(prompt);
        }
      });
    });
  }

  function renderMessages(messages) {
    const container = $("collab-messages");
    if (!container) return;
    if (!messages.length) {
      container.innerHTML = '<div class="workspace-empty-state"><p>Start the conversation below.</p></div>';
      return;
    }
    container.innerHTML = messages.map((msg, i) => {
      const userPrompt = msg.role === "assistant" ? findPrecedingUserPrompt(messages, i) : "";
      return renderMessage(msg, userPrompt);
    }).join("");
    bindPlanProposalActions(container);
    bindThoughtDropdowns(container);
    bindMessageActions(container);
    enhanceMarkdown(container);
  }

  function renderPlanProposalActions(msg) {
    const meta = msg.meta || {};
    if (meta.type !== "plan_proposal" || meta.dismissed) {
      return "";
    }
    const msgId = msg.id || "latest";
    const submittedRevision = (meta.revision_submitted || planRevisionSubmitted.get(String(msgId)) || "").trim();
    if (meta.confirmed) {
      return `
        <div class="plan-proposal-actions plan-proposal-confirmed" data-plan-msg="${msgId}">
          <button type="button" class="btn btn-secondary btn-sm plan-confirmed-btn" disabled>Confirmed to run</button>
        </div>`;
    }
    if (!currentThread?.pending_plan) {
      return "";
    }
    const revisionSubmittedHtml = submittedRevision
      ? `<p class="plan-revision-submitted">Revision submitted: ${escapeHtml(submittedRevision)}</p>`
      : "";
    const reviseFormHtml = submittedRevision
      ? ""
      : `
        <div class="plan-revise-form hidden" id="plan-revise-form-${msgId}">
          <textarea class="plan-revise-input" rows="3" placeholder="Tell the manager what to change — e.g. skip Report authoring, focus on SQL only…"></textarea>
          <button type="button" class="btn btn-primary btn-sm plan-revise-submit-btn" data-plan-msg="${msgId}">Submit revision</button>
        </div>`;
    return `
      <div class="plan-proposal-actions" data-plan-msg="${msgId}">
        <p class="plan-proposal-hint">This workflow uses more than half your specialists. Confirm to run it, or suggest changes.</p>
        <div class="plan-proposal-buttons">
          <button type="button" class="btn btn-primary btn-sm plan-confirm-btn" data-plan-msg="${msgId}">Confirm &amp; run</button>
          ${submittedRevision ? "" : `<button type="button" class="btn btn-secondary btn-sm plan-revise-toggle-btn" data-plan-msg="${msgId}">Revise plan</button>`}
          <button type="button" class="btn btn-ghost btn-sm plan-dismiss-btn" data-plan-msg="${msgId}">Dismiss</button>
        </div>
        ${revisionSubmittedHtml}
        ${reviseFormHtml}
      </div>`;
  }

  function formatThoughtDuration(sec) {
    const s = Math.max(1, Math.round(sec || 1));
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    const rem = s % 60;
    return rem ? `${m}m ${rem}s` : `${m}m`;
  }

  function renderThoughtDropdown(thought, msgId) {
    const blocks = buildThoughtBlocks(thought || {});
    if (!blocks.length) return "";
    const duration = formatThoughtDuration(thought.duration_sec);
    const blocksHtml = renderThoughtBlocksHtml(blocks);
    return `
      <div class="chat-thought collapsed" data-thought-msg="${msgId}">
        <button type="button" class="chat-thought-toggle" aria-expanded="false">
          <span class="chat-thought-label">Thought for ${duration}</span>
          <span class="chat-thought-chevron" aria-hidden="true">›</span>
        </button>
        <div class="chat-thought-body">
          <div class="chat-thought-chain thought-blocks-scroll">
            ${blocksHtml}
            <div class="chat-thought-step done">
              <span class="chat-thought-rail" aria-hidden="true">
                <span class="chat-thought-icon done">✓</span>
              </span>
              <span class="chat-thought-done-label">Done</span>
            </div>
          </div>
        </div>
      </div>`;
  }

  function bindThoughtDropdowns(root) {
    root?.querySelectorAll(".chat-thought-toggle").forEach((btn) => {
      if (btn.dataset.bound) return;
      btn.dataset.bound = "1";
      btn.addEventListener("click", () => {
        const wrap = btn.closest(".chat-thought");
        if (!wrap) return;
        const expanded = wrap.classList.toggle("collapsed") === false;
        btn.setAttribute("aria-expanded", expanded ? "true" : "false");
        if (expanded) {
          scrollThoughtBlocksToBottom(wrap.querySelector(".thought-blocks-scroll"), { force: true });
        }
      });
    });
  }

  function renderProgressCard(card, collapsed = true) {
    if (!card) return "";
    const total = card.total || (card.subtasks || []).length;
    const completed = card.completed ?? total;
    const summary = card.summary || `Team completed ${completed} subtasks`;
    const isProposal = card.status === "awaiting_confirmation";
    const isConfirmed = card.status === "confirmed";
    const subtasksHtml = (card.subtasks || []).map((st) => `
      <li class="progress-subtask status-${st.status || "queued"}">
        <span class="progress-status">${st.status === "done" ? "✓" : "…"}</span>
        <span class="progress-skill">${escapeHtml(st.skill || "")}</span>
        <span class="progress-label">${escapeHtml(st.label || "")}</span>
      </li>`).join("");
    const planHtml = card.manager_plan
      ? `<p class="progress-manager-plan">${escapeHtml(card.manager_plan)}</p>`
      : "";
    return `
      <div class="progress-card${collapsed && !isProposal && !isConfirmed ? " collapsed" : ""}${isProposal ? " plan-proposal-card" : ""}${isConfirmed ? " plan-confirmed-card" : ""}">
        <button type="button" class="progress-card-toggle">
          <span class="progress-card-icon">⚡</span>
          <span class="progress-card-summary">${escapeHtml(summary)}</span>
          <span class="progress-card-chevron">▾</span>
        </button>
        <div class="progress-card-bar"><div style="width:${total ? (completed / total) * 100 : 100}%"></div></div>
        <div class="progress-card-body">${planHtml}<ul class="progress-subtasks">${subtasksHtml}</ul></div>
      </div>`;
  }

  function renderArtifactCard(art) {
    return `
      <div class="artifact-card">
        <div class="artifact-icon docx">DOC</div>
        <div class="artifact-meta"><strong>${escapeHtml(art.title || art.filename || "File")}</strong></div>
        <a class="btn btn-primary btn-sm" href="/api/chat/artifacts/${art.id}/download">Download</a>
      </div>`;
  }

  function renderMessage(msg, userPrompt = "") {
    const meta = msg.meta || {};
    const isUser = msg.role === "user";
    const agentName = meta.agent_name || currentAgent()?.name || "Agent";
    const deactivated = currentMode === "thread" && !!agentDms.find((a) => a.session_id === currentAgentId)?.hidden_from_roster;
    const color = agentAvatarStyle(agentName, deactivated);
    if (isUser) {
      return `<div class="chat-msg chat-msg-user"><div class="chat-bubble chat-bubble-md">${formatMarkdown(msg.content)}</div></div>`;
    }
    const isPlanProposal = meta.type === "plan_proposal" && !meta.dismissed && !meta.confirmed;
    const progressHtml = meta.progress_card
      ? renderProgressCard(meta.progress_card, !isPlanProposal)
      : "";
    const thoughtHtml = meta.thought ? renderThoughtDropdown(meta.thought, msg.id || "latest") : "";
    const planActionsHtml = renderPlanProposalActions(msg);
    const artifactsHtml = (meta.artifacts || []).map(renderArtifactCard).join("");
    const actionsHtml = renderMessageActions(msg, userPrompt);
    return `
      <div class="chat-msg chat-msg-assistant${isPlanProposal ? " chat-msg-plan-proposal" : ""}">
        <span class="${agentAvatarClass("sm", deactivated)}" style="background:${color}">${agentInitials(agentName)}</span>
        <div class="chat-msg-body">
          <div class="chat-msg-header"><strong>${escapeHtml(agentName)}</strong>${isPlanProposal ? '<span class="plan-proposal-badge">Workflow proposal</span>' : ""}</div>
          ${progressHtml}
          ${thoughtHtml}
          <div class="chat-bubble chat-bubble-md">${formatMarkdown(msg.content)}</div>
          ${planActionsHtml}
          ${artifactsHtml ? `<div class="chat-artifacts">${artifactsHtml}</div>` : ""}
          ${actionsHtml}
        </div>
      </div>`;
  }

  function appendMessage(msg) {
    const container = $("collab-messages");
    container.querySelector(".workspace-empty-state")?.remove();
    container.insertAdjacentHTML("beforeend", renderMessage(msg));
    bindProgressCards(container);
    bindThoughtDropdowns(container);
    bindPlanProposalActions(container);
    bindMessageActions(container);
    enhanceMarkdown(container);
    scrollToBottom({ force: true });
  }

  async function confirmPlan() {
    if (!currentThread?.id || !currentThread.pending_plan) return;
    sending = true;
    updateSendState();
    showThinkingPanel({ phase_label: "Starting approved workflow…", agent_name: currentAgent()?.name }, { forceScroll: true });
    try {
      await window.api(`/chat/threads/${currentThread.id}/plan/confirm`, { method: "POST" });
      currentThread = { ...currentThread, pending_plan: null, is_generating: true };
      markPlanProposalConfirmed();
      startThreadPoll(currentThread.id);
    } catch (err) {
      alert(err.message || "Could not confirm plan");
      removeThinkingPanel();
      sending = false;
      updateSendState();
    }
  }

  async function revisePlan(comments, msgId) {
    if (!currentThread?.id || !currentThread.pending_plan) return;
    const key = String(msgId || "latest");
    planRevisionSubmitted.set(key, comments);
    const actions = document.querySelector(`.plan-proposal-actions[data-plan-msg="${key}"]`);
    if (actions) {
      actions.querySelector(".plan-revise-form")?.remove();
      actions.querySelector(".plan-revise-toggle-btn")?.remove();
      if (!actions.querySelector(".plan-revision-submitted")) {
        const note = document.createElement("p");
        note.className = "plan-revision-submitted";
        note.textContent = `Revision submitted: ${comments}`;
        actions.appendChild(note);
      }
    }
    sending = true;
    updateSendState();
    showThinkingPanel({ phase_label: "Revising workflow plan…", agent_name: currentAgent()?.name }, { forceScroll: true });
    try {
      await window.api(`/chat/threads/${currentThread.id}/plan/revise`, {
        method: "POST",
        body: JSON.stringify({ comments }),
      });
      currentThread = { ...currentThread, is_generating: true };
      startThreadPoll(currentThread.id);
    } catch (err) {
      alert(err.message || "Could not revise plan");
      removeThinkingPanel();
      sending = false;
      updateSendState();
    }
  }

  async function dismissPlan() {
    if (!currentThread?.id || !currentThread.pending_plan) return;
    try {
      await window.api(`/chat/threads/${currentThread.id}/plan/dismiss`, { method: "POST" });
      const fresh = await window.api(`/chat/threads/${currentThread.id}`);
      applyLoadedThread(fresh);
      await loadSidebar();
    } catch (err) {
      alert(err.message || "Could not dismiss plan");
    }
  }

  function bindPlanProposalActions(root) {
    root?.querySelectorAll(".plan-confirm-btn").forEach((btn) => {
      if (btn.dataset.bound) return;
      btn.dataset.bound = "1";
      btn.addEventListener("click", () => confirmPlan());
    });
    root?.querySelectorAll(".plan-revise-toggle-btn").forEach((btn) => {
      if (btn.dataset.bound) return;
      btn.dataset.bound = "1";
      btn.addEventListener("click", () => {
        const msgId = btn.dataset.planMsg;
        const form = $(`plan-revise-form-${msgId}`);
        form?.classList.toggle("hidden");
        form?.querySelector(".plan-revise-input")?.focus();
      });
    });
    root?.querySelectorAll(".plan-revise-submit-btn").forEach((btn) => {
      if (btn.dataset.bound) return;
      btn.dataset.bound = "1";
      btn.addEventListener("click", () => {
        const msgId = btn.dataset.planMsg;
        const input = document.querySelector(`#plan-revise-form-${msgId} .plan-revise-input`);
        const comments = (input?.value || "").trim();
        if (!comments) {
          alert("Please describe how you'd like the plan changed.");
          return;
        }
        revisePlan(comments, msgId);
      });
    });
    root?.querySelectorAll(".plan-dismiss-btn").forEach((btn) => {
      if (btn.dataset.bound) return;
      btn.dataset.bound = "1";
      btn.addEventListener("click", () => dismissPlan());
    });
  }

  function bindProgressCards(root) {
    root?.querySelectorAll(".progress-card-toggle").forEach((btn) => {
      if (btn.dataset.bound) return;
      btn.dataset.bound = "1";
      btn.addEventListener("click", () => btn.closest(".progress-card")?.classList.toggle("collapsed"));
    });
  }

  function messagesSignature(messages) {
    if (!messages?.length) return "0";
    const last = messages[messages.length - 1];
    return `${messages.length}:${last.id || ""}:${(last.content || "").length}`;
  }

  const SCROLL_PIN_THRESHOLD = 80;

  function isMessagesPinnedToBottom() {
    const el = $("collab-messages");
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight <= SCROLL_PIN_THRESHOLD;
  }

  function preserveMessagesScroll(updateFn) {
    const el = $("collab-messages");
    if (!el) {
      updateFn();
      return;
    }
    const pinned = isMessagesPinnedToBottom();
    const prevTop = el.scrollTop;
    updateFn();
    if (pinned) {
      el.scrollTop = el.scrollHeight;
    } else {
      el.scrollTop = prevTop;
    }
  }

  function scrollToBottom({ force = false } = {}) {
    const el = $("collab-messages");
    if (!el) return;
    if (force || isMessagesPinnedToBottom()) {
      el.scrollTop = el.scrollHeight;
    }
  }

  let mentionActiveIndex = 0;
  let mentionContext = null;

  function agentMentionList() {
    if (agentDms.length) return agentDms;
    return agents.map((a) => ({
      session_id: a.session_id,
      name: a.name,
      job_title: a.job_title,
      field: a.field,
    }));
  }

  function getMentionTrigger(input) {
    const pos = input.selectionStart ?? input.value.length;
    const text = input.value.slice(0, pos);
    const match = text.match(/@([^@\n]*)$/);
    if (!match) return null;
    return {
      query: match[1].toLowerCase(),
      startIndex: pos - match[0].length,
    };
  }

  function filterAgentsForMention(query) {
    const list = agentMentionList();
    if (!query) return list;
    return list.filter((a) => a.name.toLowerCase().includes(query));
  }

  function hideMentionMenu(menuEl) {
    menuEl?.classList.add("hidden");
    if (mentionContext?.menuEl === menuEl) mentionContext = null;
  }

  function hideAllMentionMenus() {
    hideMentionMenu($("collab-mention-menu"));
    hideMentionMenu($("collab-welcome-mention-menu"));
  }

  function selectMentionAgent(agent) {
    if (!mentionContext) return;
    const { input, startIndex, menuEl } = mentionContext;
    const pos = input.selectionStart ?? input.value.length;
    const before = input.value.slice(0, startIndex);
    const after = input.value.slice(pos);
    const insertion = `@${agent.name} `;
    input.value = before + insertion + after;
    const newPos = before.length + insertion.length;
    input.setSelectionRange(newPos, newPos);
    hideMentionMenu(menuEl);

    if (input.id === "collab-welcome-input") {
      updateWelcomeSendState();
    } else {
      currentAgentId = agent.session_id;
    }
    input.focus();
    if (input.id === "collab-welcome-input") updateWelcomeSendState();
    else updateSendState();
  }

  function renderMentionMenu(matches, menuEl) {
    menuEl.innerHTML = matches.map((a, i) => {
      const color = agentColor(a.name);
      const subtitle = a.job_title || a.field || "Agent";
      return `
        <button type="button" class="mention-item${i === mentionActiveIndex ? " active" : ""}" data-index="${i}" data-session-id="${a.session_id}">
          <span class="workspace-agent-avatar xs" style="background:${color}">${agentInitials(a.name)}</span>
          <span class="mention-item-text">
            <strong>${escapeHtml(a.name)}</strong>
            <span>${escapeHtml(subtitle)}</span>
          </span>
        </button>`;
    }).join("");

    menuEl.querySelectorAll(".mention-item").forEach((btn) => {
      btn.addEventListener("mousedown", (e) => e.preventDefault());
      btn.addEventListener("click", () => {
        const agent = matches[parseInt(btn.dataset.index, 10)];
        if (agent) selectMentionAgent(agent);
      });
    });
  }

  function showMentionMenu(input, menuEl) {
    const trigger = getMentionTrigger(input);
    if (!trigger) {
      hideMentionMenu(menuEl);
      return;
    }
    const matches = filterAgentsForMention(trigger.query);
    if (!matches.length) {
      hideMentionMenu(menuEl);
      return;
    }
    if (!mentionContext || mentionContext.menuEl !== menuEl) {
      mentionActiveIndex = 0;
    }
    mentionContext = { input, menuEl, startIndex: trigger.startIndex, matches };
    renderMentionMenu(matches, menuEl);
    menuEl.classList.remove("hidden");
  }

  function handleMentionInput(input, menuEl) {
    showMentionMenu(input, menuEl);
  }

  function handleMentionKeydown(e, input, menuEl) {
    if (menuEl?.classList.contains("hidden") || !mentionContext?.matches?.length) return false;

    const matches = mentionContext.matches;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      mentionActiveIndex = Math.min(mentionActiveIndex + 1, matches.length - 1);
      renderMentionMenu(matches, menuEl);
      return true;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      mentionActiveIndex = Math.max(mentionActiveIndex - 1, 0);
      renderMentionMenu(matches, menuEl);
      return true;
    }
    if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      selectMentionAgent(matches[mentionActiveIndex]);
      return true;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      hideMentionMenu(menuEl);
      return true;
    }
    return false;
  }

  function bindMentionInput(input, menuEl) {
    if (!input || !menuEl) return;
    input.addEventListener("input", () => handleMentionInput(input, menuEl));
    input.addEventListener("keydown", (e) => {
      if (handleMentionKeydown(e, input, menuEl)) return;
      if (e.key === "Enter" && !e.shiftKey && input.id === "collab-input") {
        e.preventDefault();
        handleComposerSend();
      }
    });
    input.addEventListener("blur", () => {
      setTimeout(() => hideMentionMenu(menuEl), 150);
    });
  }

  function updateWelcomeSendState() {
    const input = $("collab-welcome-input");
    const btn = $("collab-welcome-send");
    if (!input || !btn) return;
    btn.disabled = !input.value.trim() && !welcomePendingFile;
  }

  function updateSendState() {
    const input = $("collab-input");
    const btn = $("collab-send-btn");
    if (!input || !btn) return;
    const generating = isComposerGenerating();
    const awaitingPlan = !!currentThread?.pending_plan;
    const label = btn.querySelector(".workspace-send-label");
    if (awaitingPlan && !generating) {
      btn.classList.remove("is-stop", "is-stopping");
      btn.setAttribute("aria-label", "Confirm workflow plan first");
      if (label) label.textContent = "Send";
      btn.disabled = true;
      input.placeholder = "Confirm or revise the proposed workflow above…";
      return;
    }
    input.placeholder = "Message… (@ to mention an agent)";
    if (generating) {
      btn.classList.add("is-stop");
      btn.disabled = false;
      btn.setAttribute("aria-label", "Stop response");
      if (label) label.textContent = "";
    } else {
      btn.classList.remove("is-stop", "is-stopping");
      btn.setAttribute("aria-label", "Send message");
      if (label) label.textContent = "Send";
      btn.disabled = !input.value.trim() && !pendingFile;
    }
  }

  function handleComposerSend() {
    if (isComposerGenerating()) {
      cancelActiveGeneration();
      return;
    }
    sendMessage();
  }

  function showFileChip(file, welcome = false) {
    const chipId = welcome ? "collab-welcome-file-chip" : "collab-file-chip";
    if (welcome) welcomePendingFile = file;
    else pendingFile = file;
    const chip = $(chipId);
    if (!chip) return;
    chip.classList.remove("hidden");
    chip.innerHTML = `<span>📎 ${escapeHtml(file.name)}</span>
      <button type="button" class="workspace-file-remove">×</button>`;
    chip.querySelector(".workspace-file-remove")?.addEventListener("click", () => clearFile(welcome));
    updateSendState();
  }

  function clearFile(welcome = false) {
    if (welcome) welcomePendingFile = null;
    else pendingFile = null;
    const chip = $(welcome ? "collab-welcome-file-chip" : "collab-file-chip");
    chip?.classList.add("hidden");
    if (chip) chip.innerHTML = "";
    $("collab-file-input").value = "";
    updateSendState();
  }

  function resolveWelcomeAgentSession(content) {
    const list = agentMentionList();
    for (const a of list) {
      if (content.includes(`@${a.name}`)) {
        return a.session_id;
      }
    }
    if (list.length === 1) return list[0].session_id;
    return null;
  }

  async function sendMessage(textOverride, fromWelcome = false) {
    let input = fromWelcome ? $("collab-welcome-input") : $("collab-input");
    const content = (textOverride ?? input?.value ?? "").trim();
    const file = fromWelcome ? welcomePendingFile : pendingFile;

    if (!content && !file) return;

    if (!currentThread) {
      const sessionId = resolveWelcomeAgentSession(content);
      if (!sessionId) {
        if (!agentMentionList().length) {
          window.BackgroundWizard?.open({ mode: "new_agent", prefill: {} });
          return;
        }
        if (fromWelcome && $("collab-welcome-input")) {
          $("collab-welcome-input").focus();
          $("collab-welcome-input").placeholder = "Type @ to mention an agent…";
        }
        return;
      }
      await openAgentDm(sessionId);
      fromWelcome = false;
      input = $("collab-input");
    }

    if (sending || !currentThread) return;
    const threadId = currentThread.id;
    sending = true;
    updateSendState();

    hideAllMentionMenus();

    const agentName = currentAgent()?.name;

    try {
      let res;
      const activeFile = fromWelcome ? welcomePendingFile : pendingFile;
      if (activeFile) {
        const form = new FormData();
        form.append("content", content);
        form.append("file", activeFile);
        res = await window.api(`/chat/threads/${threadId}/messages`, { method: "POST", body: form });
        clearFile(fromWelcome);
      } else {
        res = await window.api(`/chat/threads/${threadId}/messages`, {
          method: "POST",
          body: JSON.stringify({ content, agent_session_id: currentAgentId }),
        });
      }

      if (content && !textOverride) {
        input.value = "";
        if (fromWelcome) updateWelcomeSendState();
        else updateSendState();
      }

      if (res?.accepted) {
        if (currentThread?.id === threadId) {
          const msgs = [...(currentThread.messages || [])];
          if (res.user_message) msgs.push(res.user_message);
          currentThread = { ...currentThread, messages: msgs, is_generating: true };
          renderMessages(msgs);
          showThinkingPanel(
            res.generation_progress || buildOptimisticProgress(content, agentName),
            { forceScroll: true },
          );
          updateSendState();
          startThreadPoll(threadId, { immediate: true });
        }
        return;
      }

      if (res?.cancelled) {
        if (currentThread?.id === threadId) {
          const fresh = await window.api(`/chat/threads/${threadId}`);
          applyLoadedThread(fresh);
        }
        await loadSidebar();
        return;
      }

      if (currentThread?.id === threadId) {
        const fresh = await window.api(`/chat/threads/${threadId}`);
        applyLoadedThread(fresh);
      }
      await loadSidebar();
    } catch (err) {
      const stillWaiting = /still responding/i.test(err.message || "");
      if (stillWaiting && currentThread?.id === threadId) {
        showThinkingPanel(currentThread.generation_progress);
        startThreadPoll(threadId);
        return;
      }

      if (currentThread?.id === threadId) {
        removeThinkingPanel();
        if (content && !textOverride && input) {
          input.value = content;
          if (fromWelcome) updateWelcomeSendState();
          else updateSendState();
        }
        alert(err.message || "Could not send message");
      }
      sending = false;
      if (currentThread?.id === threadId) updateSendState();
    } finally {
      if (currentThread?.id === threadId) {
        if (!currentThread.is_generating) {
          sending = false;
          updateSendState();
        }
      } else {
        sending = false;
      }
    }
  }

  function renderAgentPicks(containerId, multi = true) {
    const el = $(containerId);
    if (!el) return;
    if (!agents.length) {
      el.innerHTML = '<p class="collab-list-empty">Create agents first</p>';
      return;
    }
    const pickable = agents.filter((a) => !a.hidden_from_roster);
    if (!pickable.length) {
      el.innerHTML = '<p class="collab-list-empty">Create agents first</p>';
      return;
    }
    el.innerHTML = pickable.map((a) => {
      const c = agentAvatarStyle(a.name);
      return `<label class="agent-pick">
        <input type="${multi ? "checkbox" : "radio"}" name="agent-pick" value="${a.session_id}">
        <span class="workspace-agent-avatar xs" style="background:${c}">${agentInitials(a.name)}</span>
        ${escapeHtml(a.name)}
      </label>`;
    }).join("");
  }

  function closeProjectAgentMultiselect() {
    $("project-agent-multiselect")?.classList.remove("open");
    $("project-agent-multiselect-trigger")?.setAttribute("aria-expanded", "false");
    $("project-agent-multiselect-menu")?.classList.add("hidden");
  }

  function updateProjectAgentMultiselectChips() {
    const chipsEl = $("project-agent-chips");
    const wrap = $("project-agent-multiselect");
    const menu = $("project-agent-multiselect-menu");
    if (!chipsEl || !menu) return;

    const selected = [...menu.querySelectorAll("input:checked")].map((input) => {
      const id = parseInt(input.value, 10);
      const agent = agents.find((a) => a.session_id === id);
      return { id, name: agent?.name || "Agent" };
    });

    chipsEl.innerHTML = selected.map((a) => `
      <span class="project-agent-chip">${escapeHtml(a.name)}</span>`).join("");
    wrap?.classList.toggle("has-selection", selected.length > 0);
  }

  function renderProjectAgentMultiselect(selectedIds = []) {
    const menu = $("project-agent-multiselect-menu");
    if (!menu) return;

    const pickable = agents.filter((a) => !a.hidden_from_roster);
    if (!pickable.length) {
      menu.innerHTML = '<p class="project-agent-multiselect-empty">Create an agent first to add to this project.</p>';
      updateProjectAgentMultiselectChips();
      return;
    }

    const selected = new Set(selectedIds);
    menu.innerHTML = pickable.map((a) => {
      const c = agentAvatarStyle(a.name);
      const checked = selected.has(a.session_id) ? "checked" : "";
      const selectedClass = selected.has(a.session_id) ? " selected" : "";
      return `
        <label class="project-agent-multiselect-option${selectedClass}">
          <input type="checkbox" value="${a.session_id}" ${checked}>
          <span class="workspace-agent-avatar xs" style="background:${c}">${agentInitials(a.name)}</span>
          <span class="project-agent-option-name">${escapeHtml(a.name)}</span>
        </label>`;
    }).join("");

    menu.querySelectorAll("input").forEach((input) => {
      input.addEventListener("change", () => {
        input.closest(".project-agent-multiselect-option")
          ?.classList.toggle("selected", input.checked);
        updateProjectAgentMultiselectChips();
      });
    });
    updateProjectAgentMultiselectChips();
  }

  function toggleProjectAgentMultiselect() {
    const wrap = $("project-agent-multiselect");
    const menu = $("project-agent-multiselect-menu");
    const trigger = $("project-agent-multiselect-trigger");
    if (!wrap || !menu || !trigger) return;

    const open = !wrap.classList.contains("open");
    wrap.classList.toggle("open", open);
    menu.classList.toggle("hidden", !open);
    trigger.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function getProjectAgentSelections() {
    return [...document.querySelectorAll("#project-agent-multiselect-menu input:checked")]
      .map((input) => parseInt(input.value, 10));
  }

  function openProjectModal(editProject) {
    editingProjectId = editProject?.id || null;
    const isEdit = !!editingProjectId;
    $("project-modal-title").textContent = isEdit ? "Edit project" : "Create a project";
    $("project-modal-save").textContent = isEdit ? "Save changes" : "Create project";
    $("project-agent-picks-wrap")?.classList.toggle("hidden", isEdit);
    $("project-modal-delete")?.classList.toggle("hidden", !isEdit);
    $("project-name").value = editProject?.name || "";
    $("project-desc").value = editProject?.description || "";
    $("project-edit-id").value = editingProjectId || "";
    $("project-modal-error")?.classList.add("hidden");
    closeProjectAgentMultiselect();
    renderProjectAgentMultiselect(isEdit ? [] : (editProject?.agent_session_ids || []));
    $("project-modal")?.classList.remove("hidden");
    if (!isEdit) {
      setTimeout(() => $("project-name")?.focus(), 50);
    }
  }

  function closeProjectModal() {
    $("project-modal")?.classList.add("hidden");
    closeProjectAgentMultiselect();
    editingProjectId = null;
  }

  async function saveProject() {
    const name = $("project-name")?.value?.trim();
    if (!name) {
      $("project-modal-error").textContent = "Project name is required";
      $("project-modal-error").classList.remove("hidden");
      return;
    }
    const picks = getProjectAgentSelections();
    const payload = {
      name,
      description: $("project-desc")?.value?.trim(),
    };
    if (!editingProjectId) payload.agent_session_ids = picks;
    try {
      let project;
      if (editingProjectId) {
        project = await window.api(`/projects/${editingProjectId}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
      } else {
        project = await window.api("/projects", {
          method: "POST",
          body: JSON.stringify({ ...payload, agent_session_ids: picks }),
        });
      }
      closeProjectModal();
      await loadProjects();
      await openProject(project.id);
    } catch (err) {
      $("project-modal-error").textContent = err.message;
      $("project-modal-error").classList.remove("hidden");
    }
  }

  function openProjectAgentModal() {
    if (!currentProject) return;
    const assigned = new Set(currentProject.agent_session_ids || []);
    const el = $("project-add-agent-picks");
    if (!el) return;
    const available = agents.filter((a) => !assigned.has(a.session_id) && !a.hidden_from_roster);
    if (!available.length) {
      el.innerHTML = '<p class="collab-list-empty">All your agents are already in this project.</p>';
    } else {
      el.innerHTML = available.map((a) => {
        const c = agentAvatarStyle(a.name);
        return `<label class="agent-pick">
          <input type="radio" name="project-add-agent-pick" value="${a.session_id}">
          <span class="workspace-agent-avatar xs" style="background:${c}">${agentInitials(a.name)}</span>
          ${escapeHtml(a.name)}
        </label>`;
      }).join("");
    }
    $("project-agent-modal-error")?.classList.add("hidden");
    $("project-agent-modal")?.classList.remove("hidden");
  }

  function closeProjectAgentModal() {
    $("project-agent-modal")?.classList.add("hidden");
  }

  async function saveProjectAgent() {
    if (!currentProject) return;
    const pick = document.querySelector("#project-add-agent-picks input:checked");
    if (!pick) {
      $("project-agent-modal-error").textContent = "Select an agent";
      $("project-agent-modal-error").classList.remove("hidden");
      return;
    }
    const sessionId = parseInt(pick.value, 10);
    const ids = [...(currentProject.agent_session_ids || []), sessionId];
    try {
      currentProject = await window.api(`/projects/${currentProject.id}`, {
        method: "PUT",
        body: JSON.stringify({ agent_session_ids: ids }),
      });
      closeProjectAgentModal();
      await renderProjectPanel(currentProject);
      await openProjectAgent(currentProject.id, sessionId);
      await loadProjects();
    } catch (err) {
      $("project-agent-modal-error").textContent = err.message;
      $("project-agent-modal-error").classList.remove("hidden");
    }
  }

  async function deleteCurrentProject() {
    if (!currentProject?.id && !editingProjectId) return;
    const pid = editingProjectId || currentProject?.id;
    const name = currentProject?.name || "this project";
    if (!confirm(`Delete project "${name}"? This cannot be undone.`)) return;
    await window.api(`/projects/${pid}`, { method: "DELETE" });
    closeProjectModal();
    currentProject = null;
    await loadProjects();
    showWelcome();
  }

  function accountEmail() {
    const fromProfile = userProfile?.email?.trim();
    if (fromProfile) return fromProfile;
    const nav = $("user-email")?.textContent?.trim();
    if (nav) return nav;
    return "";
  }

  function accountDisplayName() {
    const first = userProfile?.first_name?.trim();
    const last = userProfile?.last_name?.trim();
    if (first || last) return [first, last].filter(Boolean).join(" ");
    const full = userProfile?.full_name?.trim();
    if (full) return full;
    const email = accountEmail();
    if (!email) return "Account";
    const local = email.split("@")[0] || email;
    return local
      .replace(/[._-]+/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase());
  }

  function accountFirstName() {
    const first = userProfile?.first_name?.trim();
    if (first) return first;
    const full = userProfile?.full_name?.trim();
    if (full) return full.split(/\s+/)[0] || "there";
    const email = accountEmail();
    if (!email) return "there";
    return accountDisplayName().split(" ")[0] || "there";
  }

  function accountInitial() {
    const first = userProfile?.first_name?.trim();
    const last = userProfile?.last_name?.trim();
    if (first && last) return (first[0] + last[0]).toUpperCase();
    if (first) return first[0].toUpperCase();
    const display = accountDisplayName();
    if (display && display !== "Account") return agentInitials(display);
    const email = accountEmail();
    if (!email) return "?";
    const local = email.split("@")[0] || email;
    return (local[0] || "?").toUpperCase();
  }

  let accountModalView = "overview";

  function accountBilling() {
    return window.Billing || null;
  }

  function formatAccountTokens(count) {
    return accountBilling()?.formatTokenCount?.(count) || String(count || 0);
  }

  function formatAccountTokenAllowance(plan) {
    return accountBilling()?.formatPlanTokenAllowance?.(plan) || "";
  }

  function formatAccountDate(iso) {
    return accountBilling()?.formatPlanDate?.(iso) || "—";
  }

  function renderAccountUsageSection(sub, { compact = false } = {}) {
    return accountBilling()?.renderUsageMeterHtml?.(sub, {
      compact,
      periodEnd: sub?.current_period_end || null,
    }) || "";
  }

  function closeAccountModal() {
    accountModalView = "overview";
    const modal = $("account-modal");
    const dialog = modal?.querySelector(".modal-dialog");
    dialog?.classList.remove("account-modal-wide");
    modal?.classList.add("hidden");
    modal?.setAttribute("aria-hidden", "true");
  }

  function syncAccountModalFooter(showLogout = false) {
    $("account-modal-logout")?.classList.toggle("hidden", !showLogout);
  }

  function bindAccountLogout() {
    const btn = $("account-modal-logout");
    if (!btn || btn.dataset.bound) return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", async () => {
      try {
        await window.api("/auth/logout", { method: "POST" });
        window.location.href = "/";
      } catch (err) {
        console.error(err);
      }
    });
  }

  function renderAccountPayment(body) {
    const billing = accountBilling();
    const sub = billing?.getSubscription?.();
    const plans = billing?.getConfig?.()?.plans || [];
    const hasAccess = Boolean(sub?.access_granted);

    const usageHtml = hasAccess ? (() => {
      const cancelNote = sub.cancel_at_period_end
        ? `<p class="account-muted account-cancel-note">Cancels on ${escapeHtml(formatAccountDate(sub.current_period_end))}</p>`
        : "";
      return `
        <section class="account-section account-section-compact">
          <p class="account-muted">Current — ${escapeHtml(billing.getCurrentPlanLabel())}</p>
          ${renderAccountUsageSection(sub, { compact: true })}
          ${cancelNote}
        </section>`;
    })() : "";

    body.innerHTML = `
      <div class="account-panel account-panel-payment">
        <button type="button" class="account-back-btn" id="account-payment-back">← Back</button>
        <section class="account-section account-section-flush">
          <p class="page-eyebrow">Subscription</p>
          <h4 class="account-plans-title">Choose your plan</h4>
          <p class="account-muted">Each plan includes a monthly API token allowance. Unused tokens do not roll over.</p>
        </section>
        <div id="account-payment-message"></div>
        <div id="account-payment-error"></div>
        ${usageHtml}
        <div class="account-plans-grid">
          ${plans.map((plan) => billing?.planCardHtml?.(plan) || "").join("")}
        </div>
        ${hasAccess ? `
        <section class="account-section account-section-compact">
          <div class="account-payment-actions">
            ${sub.cancel_at_period_end
              ? '<button type="button" class="btn btn-primary btn-sm" id="account-reactivate-btn">Reactivate subscription</button>'
              : '<button type="button" class="btn btn-secondary btn-sm" id="account-cancel-btn">Cancel at period end</button>'}
          </div>
        </section>` : ""}
      </div>`;

    body.querySelector("#account-payment-back")?.addEventListener("click", () => {
      accountModalView = "overview";
      openAccountModal();
    });

    billing?.bindPlanSelectButtons?.(body.querySelector(".account-plans-grid"), async (planId, btn) => {
      if (btn) btn.disabled = true;
      try {
        await billing.checkoutPlan(planId, {
          messageElId: "account-payment-message",
          errorElId: "account-payment-error",
          refreshPlansPage: false,
          onUpdated: async () => {
            await billing.load();
            if (!billing.getSubscription()?.access_granted) return;
            updateUserFooter();
            openAccountModal();
          },
        });
      } catch (_) {
        if (btn) btn.disabled = false;
      }
    });

    body.querySelector("#account-cancel-btn")?.addEventListener("click", async () => {
      try {
        await billing.cancel();
        await billing.load();
        renderAccountPayment(body);
        updateUserFooter();
      } catch (err) {
        const errEl = body.querySelector("#account-payment-error");
        if (errEl) errEl.innerHTML = `<div class="alert alert-error">${escapeHtml(err.message)}</div>`;
      }
    });

    body.querySelector("#account-reactivate-btn")?.addEventListener("click", async () => {
      try {
        await billing.reactivate();
        await billing.load();
        renderAccountPayment(body);
        updateUserFooter();
      } catch (err) {
        const errEl = body.querySelector("#account-payment-error");
        if (errEl) errEl.innerHTML = `<div class="alert alert-error">${escapeHtml(err.message)}</div>`;
      }
    });
  }

  function renderAccountOverview(body) {
    const email = accountEmail();
    const signedIn = !!email;
    const showLogout = !document.getElementById("logout-btn")?.classList.contains("hidden");
    const billing = accountBilling();
    const sub = billing?.getSubscription?.();
    const hasAccess = Boolean(sub?.access_granted);
    const planLabel = billing?.getCurrentPlanLabel?.() || "Free Plan";
    const nextPlan = billing?.getNextPlanTier?.();
    const firstName = userProfile?.first_name?.trim() || "";
    const lastName = userProfile?.last_name?.trim() || "";
    const displayName = [firstName, lastName].filter(Boolean).join(" ") || accountDisplayName();

    const nameSection = signedIn ? `
        <section class="account-section">
          <h4>Name</h4>
          <div class="account-name-view" id="account-name-view">
            <p class="account-value">${escapeHtml(displayName)}</p>
            <button type="button" class="btn btn-secondary btn-sm" id="account-edit-name">Edit</button>
          </div>
          <form class="account-name-edit hidden" id="account-name-form">
            <div class="account-name-fields">
              <input type="text" id="account-first-name" value="${escapeHtml(firstName)}" placeholder="First name" autocomplete="given-name" required>
              <input type="text" id="account-last-name" value="${escapeHtml(lastName)}" placeholder="Last name" autocomplete="family-name" required>
            </div>
            <div class="account-name-actions">
              <button type="submit" class="btn btn-primary btn-sm">Save</button>
              <button type="button" class="btn btn-secondary btn-sm" id="account-cancel-name">Cancel</button>
            </div>
          </form>
          <div id="account-name-error"></div>
        </section>` : "";

    let tokenSection = `
      <section class="account-section">
        <h4>Usage</h4>
        <div class="account-token-bar" aria-hidden="true">
          <div class="account-token-fill" style="width:0%"></div>
        </div>
        <p class="account-muted">Subscribe to a plan to unlock your workspace.</p>
      </section>`;

    if (hasAccess) {
      tokenSection = `
        <section class="account-section">
          <h4>Usage</h4>
          ${renderAccountUsageSection(sub)}
        </section>`;
    }

    let upgradeSection = "";
    if (nextPlan) {
      const buyLabel = hasAccess ? "Buy upgrade" : "Buy";
      upgradeSection = `
        <section class="account-section">
          <h4>${hasAccess ? "Upgrade" : "Plan"}</h4>
          <p class="account-value">${escapeHtml(nextPlan.name)} · ${escapeHtml(nextPlan.price_display)}/mo</p>
          <p class="account-muted">${escapeHtml(formatAccountTokenAllowance(nextPlan))} · ${escapeHtml(nextPlan.description)}</p>
          <div class="account-action-row">
            <button type="button" class="btn btn-primary btn-sm" id="account-buy-next">${escapeHtml(buyLabel)}</button>
            <button type="button" class="btn btn-secondary btn-sm" id="account-view-plans">View all plans</button>
          </div>
        </section>`;
    } else if (hasAccess) {
      upgradeSection = `
        <section class="account-section">
          <h4>Plan</h4>
          <p class="account-value">You're on our highest tier</p>
          <p class="account-muted">Manage billing or cancel your subscription.</p>
          <button type="button" class="btn btn-secondary btn-sm" id="account-view-plans">Manage subscription</button>
        </section>`;
    } else {
      upgradeSection = `
        <section class="account-section">
          <h4>Plan</h4>
          <p class="account-muted">Pick a monthly plan to unlock your workspace and API tokens.</p>
          <button type="button" class="btn btn-primary btn-sm" id="account-view-plans">Choose a plan</button>
        </section>`;
    }

    body.innerHTML = `
      <div class="account-panel">
        ${nameSection}
        <section class="account-section">
          <h4>Sign in</h4>
          <div class="account-login-row">
            <div class="account-login-main">
              <p class="account-value">${escapeHtml(email || "Not signed in")}</p>
              ${signedIn ? `<p class="account-current-plan">${escapeHtml(planLabel)}</p>` : ""}
            </div>
            ${signedIn ? '<span class="account-status-pill">Signed in</span>' : ""}
          </div>
          ${signedIn ? "" : '<button type="button" class="btn btn-primary btn-sm" id="account-modal-signin">Sign in</button>'}
        </section>
        ${tokenSection}
        ${upgradeSection}
        <div id="account-overview-message"></div>
        <div id="account-overview-error"></div>
      </div>`;

    syncAccountModalFooter(showLogout && signedIn);

    body.querySelector("#account-edit-name")?.addEventListener("click", () => {
      body.querySelector("#account-name-view")?.classList.add("hidden");
      body.querySelector("#account-name-form")?.classList.remove("hidden");
    });

    body.querySelector("#account-cancel-name")?.addEventListener("click", () => {
      body.querySelector("#account-name-form")?.classList.add("hidden");
      body.querySelector("#account-name-view")?.classList.remove("hidden");
      const errEl = body.querySelector("#account-name-error");
      if (errEl) errEl.innerHTML = "";
    });

    body.querySelector("#account-name-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const errEl = body.querySelector("#account-name-error");
      const first = body.querySelector("#account-first-name")?.value?.trim() || "";
      const last = body.querySelector("#account-last-name")?.value?.trim() || "";
      if (!first || !last) {
        if (errEl) errEl.innerHTML = `<div class="alert alert-error">First name and last name are required.</div>`;
        return;
      }
      const saveBtn = body.querySelector("#account-name-form button[type='submit']");
      if (saveBtn) saveBtn.disabled = true;
      try {
        await window.api("/profile", {
          method: "PUT",
          body: JSON.stringify({ first_name: first, last_name: last }),
        });
        userProfile = { ...(userProfile || {}), first_name: first, last_name: last, full_name: `${first} ${last}` };
        updateUserFooter();
        openAccountModal();
      } catch (err) {
        if (errEl) errEl.innerHTML = `<div class="alert alert-error">${escapeHtml(err.message)}</div>`;
      } finally {
        if (saveBtn) saveBtn.disabled = false;
      }
    });

    body.querySelector("#account-modal-signin")?.addEventListener("click", () => {
      closeAccountModal();
      window.showView?.("login");
    });

    body.querySelector("#account-view-plans")?.addEventListener("click", () => {
      accountModalView = "payment";
      openAccountModal();
    });

    body.querySelector("#account-buy-next")?.addEventListener("click", async () => {
      if (!nextPlan || !billing) return;
      const btn = body.querySelector("#account-buy-next");
      if (btn) btn.disabled = true;
      try {
        await billing.checkoutPlan(nextPlan.id, {
          messageElId: "account-overview-message",
          errorElId: "account-overview-error",
          refreshPlansPage: false,
          onUpdated: async () => {
            await billing.load();
            if (!billing.getSubscription()?.access_granted) return;
            updateUserFooter();
            openAccountModal();
          },
        });
      } catch (_) {
        if (btn) btn.disabled = false;
      }
    });
  }

  async function openAccountPlans() {
    accountModalView = "payment";
    await openAccountModal();
  }

  async function openAccountModal() {
    const body = $("account-modal-body");
    const modal = $("account-modal");
    const dialog = modal?.querySelector(".modal-dialog");
    if (!body || !modal) return;

    if (accountModalView === "payment") {
      dialog?.classList.add("account-modal-wide");
      $("account-modal-title").textContent = "Subscription";
    } else {
      dialog?.classList.remove("account-modal-wide");
      $("account-modal-title").textContent = "Account";
    }

    body.innerHTML = `<p class="account-muted" style="padding:0.5rem 0">Loading…</p>`;
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");

    try {
      if (window.Billing?.load) await window.Billing.load();
    } catch (err) {
      console.error("Failed to load billing:", err);
    }

    if (accountModalView === "payment") {
      renderAccountPayment(body);
      syncAccountModalFooter(false);
    } else {
      renderAccountOverview(body);
    }
  }

  function openProfileModal() {
    openAccountModal();
  }

  function updateUserFooter() {
    const displayName = accountDisplayName();
    const initial = accountInitial();
    const planLabel = window.Billing?.getCurrentPlanLabel?.() || "Free Plan";
    if ($("collab-user-name")) $("collab-user-name").textContent = displayName;
    if ($("collab-user-avatar")) $("collab-user-avatar").textContent = initial;
    if ($("collab-rail-account-avatar")) $("collab-rail-account-avatar").textContent = initial;
    if ($("collab-user-plan")) $("collab-user-plan").textContent = planLabel;
    $("collab-greeting") && ($("collab-greeting").textContent = greeting());
  }

  function markPlanProposalConfirmed() {
    const container = $("collab-messages");
    if (!container) return;
    container.querySelectorAll(".plan-proposal-actions:not(.plan-proposal-confirmed)").forEach((el) => {
      el.outerHTML = `
        <div class="plan-proposal-actions plan-proposal-confirmed">
          <button type="button" class="btn btn-secondary btn-sm plan-confirmed-btn" disabled>Confirmed to run</button>
        </div>`;
    });
    container.querySelectorAll(".progress-card.plan-proposal-card").forEach((card) => {
      card.classList.remove("plan-proposal-card");
      card.classList.add("plan-confirmed-card");
      const summary = card.querySelector(".progress-card-summary");
      if (summary) summary.textContent = "Confirmed to run";
    });
  }

  function initSidebarCollapse() {
    const sidebar = $("collab-sidebar");
    if (!sidebar) return;

    const stored = localStorage.getItem("collab-sidebar-collapsed");
    if (stored === "0") {
      sidebar.classList.remove("collapsed");
    } else {
      sidebar.classList.add("collapsed");
    }

    const expandSidebar = () => {
      sidebar.classList.remove("collapsed");
      localStorage.setItem("collab-sidebar-collapsed", "0");
    };

    const toggleSidebar = () => {
      sidebar.classList.toggle("collapsed");
      localStorage.setItem("collab-sidebar-collapsed", sidebar.classList.contains("collapsed") ? "1" : "0");
    };

    $("collab-sidebar-toggle")?.addEventListener("click", toggleSidebar);
    $("collab-sidebar-collapse")?.addEventListener("click", toggleSidebar);
    $("collab-rail-logo")?.addEventListener("click", () => window.goHome?.() || window.ChatWorkspace?.showWelcome?.());

    $("collab-rail-new-chat")?.addEventListener("click", () => {
      expandSidebar();
      showWelcome();
    });
    $("collab-rail-agents")?.addEventListener("click", () => {
      expandSidebar();
      showAgentsRoster();
    });
    $("collab-rail-projects")?.addEventListener("click", () => {
      expandSidebar();
      $("collab-section-projects")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    $("collab-rail-dms")?.addEventListener("click", () => {
      expandSidebar();
      $("collab-section-dms")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  function bindEvents() {
    $("collab-new-chat")?.addEventListener("click", showWelcome);
    $("collab-new-agent")?.addEventListener("click", () => window.BackgroundWizard?.open({ mode: "new_agent", prefill: {} }));
    $("collab-add-prebuilt")?.addEventListener("click", showPrebuiltAgentsBrowse);
    $("collab-agents-add-prebuilt")?.addEventListener("click", showPrebuiltAgentsBrowse);
    $("collab-prebuilt-back")?.addEventListener("click", showAgentsRoster);
    $("collab-agents-roster-btn")?.addEventListener("click", showAgentsRoster);
    const openNewAgent = () => window.BackgroundWizard?.open({ mode: "new_agent", prefill: {} });
    $("collab-roster-create")?.addEventListener("click", openNewAgent);
    $("collab-roster-add-prebuilt")?.addEventListener("click", showPrebuiltAgentsBrowse);
    $("collab-agents-create")?.addEventListener("click", openNewAgent);
    $("collab-prebuilt-search")?.addEventListener("input", (e) => {
      prebuiltSearch = e.target.value || "";
      clearTimeout(prebuiltSearchTimer);
      prebuiltSearchTimer = setTimeout(() => loadPrebuiltCatalog(prebuiltSearch), 200);
    });
    $("collab-new-project")?.addEventListener("click", () => openProjectModal());
    $("collab-project-search")?.addEventListener("input", (e) => {
      projectSearch = e.target.value || "";
      renderProjects();
    });

    $("project-modal-save")?.addEventListener("click", saveProject);
    $("project-modal-delete")?.addEventListener("click", deleteCurrentProject);
    $("project-modal-cancel")?.addEventListener("click", closeProjectModal);
    $("project-modal-close")?.addEventListener("click", closeProjectModal);
    $("project-modal-backdrop")?.addEventListener("click", closeProjectModal);

    $("project-agent-multiselect-trigger")?.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleProjectAgentMultiselect();
    });
    $("project-agent-browse-prebuilt")?.addEventListener("click", () => {
      closeProjectModal();
      showPrebuiltAgentsBrowse();
    });
    document.addEventListener("click", (e) => {
      if (!e.target.closest("#project-agent-multiselect")) {
        closeProjectAgentMultiselect();
      }
    });

    $("project-agent-modal-save")?.addEventListener("click", saveProjectAgent);
    $("project-agent-modal-cancel")?.addEventListener("click", closeProjectAgentModal);
    $("project-agent-modal-close")?.addEventListener("click", closeProjectAgentModal);
    $("project-agent-modal-backdrop")?.addEventListener("click", closeProjectAgentModal);
    $("project-add-agent-create")?.addEventListener("click", () => {
      closeProjectAgentModal();
      window.BackgroundWizard?.open({ mode: "new_agent", prefill: {} });
    });

    $("collab-account-btn")?.addEventListener("click", openAccountModal);
    $("collab-rail-account")?.addEventListener("click", openAccountModal);
    $("account-modal-close")?.addEventListener("click", closeAccountModal);
    $("account-modal-close-btn")?.addEventListener("click", closeAccountModal);
    $("account-modal-backdrop")?.addEventListener("click", closeAccountModal);
    bindAccountLogout();

    $("profile-modal-close")?.addEventListener("click", () => $("profile-modal")?.classList.add("hidden"));
    $("profile-modal-backdrop")?.addEventListener("click", () => $("profile-modal")?.classList.add("hidden"));
    $("profile-modal-edit")?.addEventListener("click", () => {
      $("profile-modal")?.classList.add("hidden");
      window.showHomeProfileEdit?.();
    });

    $("collab-send-btn")?.addEventListener("click", handleComposerSend);
    $("collab-welcome-send")?.addEventListener("click", () => sendMessage(null, true));
    $("collab-attach-btn")?.addEventListener("click", () => $("collab-file-input")?.click());
    $("collab-welcome-attach")?.addEventListener("click", () => $("collab-file-input")?.click());
    $("collab-file-input")?.addEventListener("change", (e) => {
      const f = e.target.files?.[0];
      if (f) showFileChip(f, currentMode === "welcome");
    });
    $("collab-project-file-input")?.addEventListener("change", async (e) => {
      const f = e.target.files?.[0];
      if (!f || !currentProject) return;
      const form = new FormData();
      form.append("file", f);
      try {
        currentProject = await window.api(`/projects/${currentProject.id}/files`, { method: "POST", body: form });
        await renderProjectPanel(currentProject);
      } catch (err) {
        alert(err.message || "Upload failed");
      }
      e.target.value = "";
    });
    $("collab-add-project-file")?.addEventListener("click", () => $("collab-project-file-input")?.click());
    $("collab-add-project-agent")?.addEventListener("click", openProjectAgentModal);
    $("collab-project-feedback-send")?.addEventListener("click", submitProjectFeedback);
    $("collab-project-instructions")?.addEventListener("input", scheduleProjectInstructionsSave);
    $("collab-project-drawer-toggle")?.addEventListener("click", toggleProjectDrawer);
    $("collab-project-drawer-close")?.addEventListener("click", closeProjectDrawer);
    $("collab-agent-drawer-toggle")?.addEventListener("click", toggleAgentDrawer);
    $("collab-agent-drawer-close")?.addEventListener("click", closeAgentDrawer);
    $("collab-agent-communication-style")?.addEventListener("change", scheduleCommunicationStyleSave);
    $("collab-agent-skill-add-btn")?.addEventListener("click", addAgentDrawerSkill);
    $("collab-agent-skill-input")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        addAgentDrawerSkill();
      }
    });
    $("collab-agent-feedback-send")?.addEventListener("click", submitAgentDrawerFeedback);
    $("collab-project-menu-btn")?.addEventListener("click", () => openProjectModal(currentProject));
    $("collab-project-chip-ask")?.addEventListener("click", () => {
      const first = currentProject?.agents?.[0];
      if (first) openProjectAgent(currentProject.id, first.session_id);
      else openProjectAgentModal();
    });
    $("collab-project-chip-task")?.addEventListener("click", () => {
      const first = currentProject?.agents?.[0];
      if (first) {
        openProjectAgent(currentProject.id, first.session_id).then(() => {
          if ($("collab-input")) {
            $("collab-input").value = "Help me with a task in this project: ";
            $("collab-input").focus();
            updateSendState();
          }
        });
      } else openProjectAgentModal();
    });
    $("collab-agent-context-file")?.addEventListener("change", async (e) => {
      const f = e.target.files?.[0];
      if (!f || !currentAgentId) return;
      const form = new FormData();
      form.append("file", f);
      await window.api(`/agents/${currentAgentId}/working-context/files`, { method: "POST", body: form });
      e.target.value = "";
      if (currentMode === "agent-detail") await showAgentDetail(currentAgentId);
    });

    bindMentionInput($("collab-welcome-input"), $("collab-welcome-mention-menu"));
    bindMentionInput($("collab-input"), $("collab-mention-menu"));

    document.addEventListener("click", closeAllChatMenus);
    bindThreadChatMenu();

    $("collab-welcome-input")?.addEventListener("input", () => {
      updateWelcomeSendState();
      const input = $("collab-welcome-input");
      input.style.height = "auto";
      input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
    });
    $("collab-welcome-input")?.addEventListener("keydown", (e) => {
      if (handleMentionKeydown(e, $("collab-welcome-input"), $("collab-welcome-mention-menu"))) return;
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage(null, true);
      }
    });

    $("collab-input")?.addEventListener("input", () => {
      updateSendState();
      const input = $("collab-input");
      input.style.height = "auto";
      input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
    });

    document.querySelectorAll(".collab-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        if (chip.dataset.starter) {
          $("collab-welcome-input").value = chip.dataset.starter;
          sendMessage(chip.dataset.starter, true);
        }
      });
    });

    document.querySelectorAll(".collab-section-toggle").forEach((btn) => {
      btn.addEventListener("click", () => {
        const section = btn.closest(".collab-section");
        section?.classList.toggle("collapsed");
      });
    });
  }

  async function refresh(homeData) {
    userProfile = homeData?.user || userProfile;
    personas = homeData?.personas || window.homePersonas || personas;
    updateUserFooter();
    await loadSidebar();
    const inActiveChat = currentMode === "thread" || currentMode === "project";
    if (
      currentAgentId
      && !inActiveChat
      && !agentDms.some((a) => a.session_id === currentAgentId)
    ) {
      showWelcome();
      return;
    }
    if (currentMode === "agent-detail" && currentAgentId) {
      const onRoster = rosterAgents().some((a) => a.session_id === currentAgentId);
      if (!onRoster) showWelcome();
      return;
    }
    if (currentMode === "agents-roster") renderAgentRoster();
    if (currentMode === "prebuilt-browse") await loadPrebuiltCatalog(prebuiltSearch);
    if (currentMode === "agent-detail" && currentAgentId) await showAgentDetail(currentAgentId);
  }

  async function open(sessionId) {
    window.showView("home");
    await loadSidebar();
    if (sessionId) await openAgentDm(sessionId);
    else if (window.navigateCollabHash) await window.navigateCollabHash();
    else showWelcome();
  }

  async function init() {
    bindEvents();
    initSidebarCollapse();
  }

  return {
    init, open, refresh, showWelcome, showAgentsRoster, showPrebuiltAgentsBrowse, showAgentDetail,
    renderJobDescriptionHtml,
    loadSidebar, loadProjects, openAgentDm, openThread, openProject, openProjectAgent, updateUserFooter,
    openAccountModal, openAccountPlans,
    shouldHandleHashChange, getCurrentMode: () => currentMode,
  };
})();

window.ChatWorkspace = ChatWorkspace;
window.renderJobDescriptionHtml = renderJobDescriptionHtml;
