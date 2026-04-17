// AI Agent — enhanced SPA with markdown, toasts, export, keyboard shortcuts.

const state = {
  sessionId: null,
  cost: 0,
  currentAssistantEl: null,
  toolCards: {},
  allSessions: [],
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

// ---------- markdown setup -------------------------------------------------
if (typeof marked !== "undefined") {
  marked.setOptions({
    breaks: true,
    gfm: true,
    highlight: function (code, lang) {
      if (typeof hljs !== "undefined" && lang && hljs.getLanguage(lang)) {
        try { return hljs.highlight(code, { language: lang }).value; } catch {}
      }
      return code;
    },
  });
}

function renderMarkdown(text) {
  if (typeof marked !== "undefined" && text) {
    try { return marked.parse(text); } catch { return escapeHtml(text); }
  }
  return escapeHtml(text || "");
}

// ---------- initial load ---------------------------------------------------
async function boot() {
  await Promise.all([loadConfig(), loadTools(), loadSessions(), loadAudit()]);
  setInterval(loadAudit, 8000);
  setupKeyboardShortcuts();
  setupPanelTabs();
  setupMobileSidebar();
  setupSessionSearch();
}

async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    const cfg = await res.json();
    $$(".status-dot").forEach((el) => {
      const key = el.dataset.key;
      if (cfg[key]) el.classList.add("ok");
      else el.classList.remove("ok");
    });
    $("#status-model").textContent = cfg.default_model;
    $("#status-transport").textContent = cfg.mcp_transport;
    $("#header-model").textContent = cfg.default_model;
  } catch (e) { console.error("config:", e); }
}

async function loadTools() {
  const list = $("#tools-list");
  list.innerHTML = '<li class="text-ink-400 text-xs px-1">Loading…</li>';
  try {
    const res = await fetch("/api/tools");
    if (!res.ok) throw new Error(await res.text());
    const tools = await res.json();
    if (!tools.length) {
      list.innerHTML = '<li class="text-ink-400 text-xs px-1">No tools.</li>';
      return;
    }
    list.innerHTML = "";
    const icons = {
      list_files: "📁", search_drive: "🔍", read_document: "📄",
      save_file: "💾", create_folder: "📂", get_metadata: "ℹ️",
      move_file: "➡️", rename_file: "✏️", delete_file: "🗑️",
    };
    tools.forEach((t) => {
      const li = document.createElement("li");
      li.className = "tool-item";
      const icon = icons[t.name] || "🔧";
      li.innerHTML = `<div class="name">${icon} ${t.name}</div><div class="desc">${escapeHtml(t.description)}</div>`;
      list.appendChild(li);
    });
  } catch (e) {
    list.innerHTML = `<li class="text-ink-400 text-xs px-1">Unavailable</li>`;
  }
}

async function loadSessions() {
  try {
    const res = await fetch("/api/sessions");
    state.allSessions = await res.json();
    renderSessions(state.allSessions);
  } catch (e) { console.error("sessions:", e); }
}

function renderSessions(sessions) {
  const list = $("#session-list");
  list.innerHTML = "";
  if (!sessions.length) {
    list.innerHTML = '<li class="text-ink-500 text-xs px-3 py-2">No sessions yet</li>';
    return;
  }
  sessions.forEach((s) => {
    const li = document.createElement("li");
    li.className = "session-item" + (s.id === state.sessionId ? " active" : "");
    li.dataset.id = s.id;
    li.innerHTML = `
      <svg class="h-3.5 w-3.5 text-ink-400 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
      <span class="title" title="${escapeHtml(s.title)}">${escapeHtml(s.title)}</span>
      <span class="text-[10px] text-ink-500 shrink-0">${s.message_count}</span>
      <button class="delete" title="delete session">
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>
      </button>`;
    li.addEventListener("click", async (ev) => {
      if (ev.target.closest(".delete")) {
        await fetch(`/api/sessions/${s.id}`, { method: "DELETE" });
        if (state.sessionId === s.id) resetConversation();
        await loadSessions();
        showToast("Session deleted", "info");
        return;
      }
      await openSession(s.id);
      closeMobileSidebar();
    });
    list.appendChild(li);
  });
}

async function openSession(id) {
  state.sessionId = id;
  state.cost = 0;
  state.currentAssistantEl = null;
  state.toolCards = {};
  const chat = $("#chat");
  chat.innerHTML = '<div class="text-center text-ink-400 text-xs py-6 animate-fade-in">Loading session…</div>';
  try {
    const res = await fetch(`/api/sessions/${id}/transcript`);
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    chat.innerHTML = "";
    $("#header-title").textContent = data.title;
    state.cost = data.total_cost_usd;
    data.transcript.forEach(replayEvent);
    await loadSessions();
  } catch (e) {
    chat.innerHTML = `<div class="text-red-400 text-sm animate-fade-in">Failed to load session: ${escapeHtml(String(e))}</div>`;
  }
}

function resetConversation() {
  state.sessionId = null;
  state.cost = 0;
  state.currentAssistantEl = null;
  state.toolCards = {};
  $("#chat").innerHTML = "";
  $("#header-title").textContent = "New conversation";
}

async function loadAudit() {
  try {
    const res = await fetch("/api/audit?limit=20");
    if (!res.ok) return;
    const entries = await res.json();
    const list = $("#audit-list");
    list.innerHTML = "";
    if (!entries.length) {
      list.innerHTML = '<li class="text-ink-400 text-[11px] px-1">No calls yet.</li>';
      return;
    }
    entries.slice().reverse().forEach((e) => {
      const li = document.createElement("li");
      li.className = "audit-item " + e.status;
      li.innerHTML = `
        <div><span class="tool">${escapeHtml(e.tool)}</span>
             <span class="text-ink-500">&middot;</span>
             <span class="${e.status === 'ok' ? 'text-green-400' : 'text-red-400'}">${escapeHtml(e.status)}</span>
             <span class="text-ink-500">&middot;</span>
             <span class="text-ink-300">${e.duration_ms}ms</span></div>
        <div class="ts">${e.ts}</div>
        ${e.error ? `<div class="text-red-400 text-[11px] mt-0.5">${escapeHtml(e.error)}</div>` : ""}`;
      list.appendChild(li);
    });
  } catch (e) { /* silent */ }
}

// ---------- chat streaming -------------------------------------------------
async function sendPrompt(prompt) {
  if (!prompt.trim()) return;
  hideEmptyState();
  addUserBubble(prompt);
  state.currentAssistantEl = null;
  state.toolCards = {};

  setSending(true);
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, session_id: state.sessionId }),
    });
    if (!res.ok || !res.body) {
      const err = await res.text();
      addAssistantBubble(`Error: ${err}`);
      showToast("Failed to send message", "error");
      return;
    }
    await consumeSSE(res.body);
  } catch (e) {
    addAssistantBubble(`Network error: ${e.message}`);
    showToast("Network error", "error");
  } finally {
    setSending(false);
    await loadSessions();
    await loadAudit();
  }
}

async function consumeSSE(stream) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let currentEvent = "message";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      currentEvent = "message";
      let dataLine = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) currentEvent = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLine += line.slice(5).trim();
      }
      if (!dataLine) continue;
      try {
        const payload = JSON.parse(dataLine);
        handleEvent(currentEvent, payload);
      } catch (e) {
        console.error("bad SSE chunk", dataLine);
      }
    }
  }
}

function handleEvent(type, payload) {
  switch (type) {
    case "session":
      state.sessionId = payload.id;
      $("#header-title").textContent = payload.title || "Conversation";
      break;
    case "user":
      break;
    case "llm_start":
      ensureAssistantBubble(true);
      break;
    case "assistant":
      if (payload.text) setAssistantContent(payload.text);
      break;
    case "tool_call": {
      const card = addToolCard(payload);
      state.toolCards[payload.id] = card;
      state.currentAssistantEl = null;
      break;
    }
    case "tool_result": {
      const card = state.toolCards[payload.id];
      if (card) updateToolCard(card, payload);
      break;
    }
    case "step":
      break;
    case "final":
      if (payload.text) setAssistantContent(payload.text);
      if (payload.stopped_reason && payload.stopped_reason !== "completed") {
        addNote(`Stopped: ${payload.stopped_reason}`);
      }
      break;
    case "error":
      addNote(`Error: ${payload.message}`, true);
      showToast(payload.message, "error");
      break;
    case "done":
      break;
  }
}

function replayEvent(payload) {
  switch (payload.type) {
    case "user": addUserBubble(payload.text); break;
    case "assistant":
      if (payload.text) {
        ensureAssistantBubble();
        setAssistantContent(payload.text);
        state.currentAssistantEl = null;
      }
      break;
    case "tool_call": {
      const card = addToolCard(payload);
      state.toolCards[payload.id] = card;
      break;
    }
    case "tool_result": {
      const card = state.toolCards[payload.id];
      if (card) updateToolCard(card, payload);
      break;
    }
    case "final":
      if (payload.text) {
        ensureAssistantBubble();
        setAssistantContent(payload.text);
        state.currentAssistantEl = null;
      }
      break;
  }
}

// ---------- DOM helpers ----------------------------------------------------
function addUserBubble(text) {
  const row = document.createElement("div");
  row.className = "msg-row msg-row-user";
  const avatar = document.createElement("div");
  avatar.className = "msg-avatar avatar-user";
  avatar.textContent = "U";
  const bubble = document.createElement("div");
  bubble.className = "msg msg-user";
  bubble.textContent = text;
  addCopyButton(bubble, text);
  row.appendChild(bubble);
  row.appendChild(avatar);
  $("#chat").appendChild(row);
  scrollChat();
}

function ensureAssistantBubble(showTyping = false) {
  if (!state.currentAssistantEl) {
    const row = document.createElement("div");
    row.className = "msg-row msg-row-assistant";
    const avatar = document.createElement("div");
    avatar.className = "msg-avatar avatar-assistant";
    avatar.innerHTML = '<svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2 3 7v10l9 5 9-5V7l-9-5Z"/></svg>';
    const bubble = document.createElement("div");
    bubble.className = "msg msg-assistant";
    if (showTyping) {
      bubble.innerHTML = '<span class="typing"><span></span><span></span><span></span></span>';
    }
    row.appendChild(avatar);
    row.appendChild(bubble);
    $("#chat").appendChild(row);
    state.currentAssistantEl = bubble;
    scrollChat();
  }
  return state.currentAssistantEl;
}

function setAssistantContent(text) {
  const el = ensureAssistantBubble();
  el.innerHTML = renderMarkdown(text);
  addCopyButton(el, text);
  // Re-highlight code blocks
  if (typeof hljs !== "undefined") {
    el.querySelectorAll("pre code").forEach((block) => {
      try { hljs.highlightElement(block); } catch {}
    });
  }
  scrollChat();
}

function addAssistantBubble(text) {
  state.currentAssistantEl = null;
  const el = ensureAssistantBubble();
  el.innerHTML = renderMarkdown(text);
  state.currentAssistantEl = null;
}

function addCopyButton(el, rawText) {
  el.style.position = "relative";
  const btn = document.createElement("button");
  btn.className = "msg-copy";
  btn.textContent = "copy";
  btn.onclick = (e) => {
    e.stopPropagation();
    navigator.clipboard.writeText(rawText).then(() => {
      btn.textContent = "copied!";
      setTimeout(() => { btn.textContent = "copy"; }, 1500);
    });
  };
  el.appendChild(btn);
}

function addToolCard(payload) {
  const icons = {
    list_files: "📁", search_drive: "🔍", read_document: "📄",
    save_file: "💾", create_folder: "📂", get_metadata: "ℹ️",
    move_file: "➡️", rename_file: "✏️", delete_file: "🗑️",
  };
  const icon = icons[payload.name] || "🔧";
  const card = document.createElement("div");
  card.className = "tool-card";
  card.innerHTML = `
    <div class="tool-card-header">
      <span style="font-size:0.9rem">${icon}</span>
      <span class="tool-name">${escapeHtml(payload.name)}</span>
      <span class="tool-status running">running…</span>
    </div>
    <div class="tool-card-body">
      <span class="label">args</span>
      <pre>${escapeHtml(JSON.stringify(payload.arguments, null, 2))}</pre>
    </div>`;
  card.querySelector(".tool-card-header").addEventListener("click", () => {
    const body = card.querySelector(".tool-card-body");
    body.hidden = !body.hidden;
  });
  $("#chat").appendChild(card);
  scrollChat();
  return card;
}

function updateToolCard(card, payload) {
  const status = card.querySelector(".tool-status");
  if (payload.error) {
    status.textContent = "error";
    status.className = "tool-status denied";
  } else {
    status.textContent = "ok";
    status.className = "tool-status ok";
  }
  const body = card.querySelector(".tool-card-body");
  body.appendChild(Object.assign(document.createElement("span"), { className: "label", textContent: "result" }));
  const resultPre = document.createElement("pre");
  resultPre.textContent = prettyMaybeJson(payload.content);
  body.appendChild(resultPre);
  scrollChat();
}

function addNote(text, isError = false) {
  const el = document.createElement("div");
  el.className = "text-xs text-center py-1 animate-fade-in " + (isError ? "text-red-400" : "text-ink-400");
  el.textContent = text;
  $("#chat").appendChild(el);
  scrollChat();
}

function setSending(sending) {
  const btn = $("#send");
  btn.disabled = sending;
  btn.classList.toggle("thinking", sending);
  $("#prompt").disabled = sending;
}

function hideEmptyState() {
  const el = $("#empty-state");
  if (el) el.remove();
}

function scrollChat() {
  const chat = $("#chat");
  chat.scrollTo({ top: chat.scrollHeight, behavior: "smooth" });
}

// ---------- toast system ---------------------------------------------------
function showToast(message, type = "info") {
  const container = $("#toast-container");
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  const icons = { success: "✓", error: "✕", info: "ℹ" };
  toast.innerHTML = `<span style="font-weight:bold;font-size:1rem">${icons[type] || "ℹ"}</span><span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add("removing");
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// ---------- export ---------------------------------------------------------
function exportConversation() {
  const chat = $("#chat");
  if (!chat || !chat.children.length) {
    showToast("No conversation to export", "info");
    return;
  }
  // Build plain text from transcript
  let text = `AI Agent — Conversation Export\n${"=".repeat(40)}\n\n`;
  chat.querySelectorAll(".msg-row, .tool-card, .msg").forEach((el) => {
    if (el.classList.contains("msg-row-user")) {
      const msg = el.querySelector(".msg-user");
      if (msg) text += `USER:\n${msg.textContent.replace("copy", "").trim()}\n\n`;
    } else if (el.classList.contains("msg-row-assistant")) {
      const msg = el.querySelector(".msg-assistant");
      if (msg) text += `ASSISTANT:\n${msg.textContent.replace("copy", "").trim()}\n\n`;
    } else if (el.classList.contains("tool-card")) {
      const name = el.querySelector(".tool-name")?.textContent || "";
      const status = el.querySelector(".tool-status")?.textContent || "";
      text += `[TOOL: ${name} → ${status}]\n\n`;
    }
  });

  const blob = new Blob([text], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `ai-agent-conversation-${new Date().toISOString().slice(0, 10)}.txt`;
  a.click();
  URL.revokeObjectURL(url);
  showToast("Conversation exported", "success");
}

// ---------- keyboard shortcuts ---------------------------------------------
function setupKeyboardShortcuts() {
  document.addEventListener("keydown", (e) => {
    // Ctrl+N — new session
    if (e.ctrlKey && e.key === "n") {
      e.preventDefault();
      $("#new-session").click();
    }
    // Ctrl+E — export
    if (e.ctrlKey && e.key === "e") {
      e.preventDefault();
      exportConversation();
    }
    // Ctrl+/ — shortcuts modal
    if (e.ctrlKey && e.key === "/") {
      e.preventDefault();
      toggleShortcuts();
    }
    // Escape — close modal
    if (e.key === "Escape") {
      const modal = $("#shortcuts-modal");
      if (!modal.classList.contains("hidden")) {
        modal.classList.add("hidden");
      }
      closeMobileSidebar();
    }
  });
}

function toggleShortcuts() {
  const modal = $("#shortcuts-modal");
  modal.classList.toggle("hidden");
}

// ---------- panel tabs -----------------------------------------------------
function setupPanelTabs() {
  $$(".panel-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      $$(".panel-tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      $$(".panel-tab-content").forEach((c) => c.classList.add("hidden"));
      const target = $(`#tab-${tab.dataset.tab}`);
      if (target) target.classList.remove("hidden");
    });
  });
}

// ---------- mobile sidebar -------------------------------------------------
function setupMobileSidebar() {
  const menuBtn = $("#mobile-menu");
  if (menuBtn) {
    menuBtn.addEventListener("click", toggleMobileSidebar);
  }
}

function toggleMobileSidebar() {
  const sidebar = $("#sidebar");
  sidebar.classList.toggle("open");
  // Add/remove overlay
  let overlay = $(".sidebar-overlay");
  if (sidebar.classList.contains("open")) {
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.className = "sidebar-overlay";
      overlay.addEventListener("click", closeMobileSidebar);
      sidebar.parentElement.appendChild(overlay);
    }
  } else {
    closeMobileSidebar();
  }
}

function closeMobileSidebar() {
  const sidebar = $("#sidebar");
  sidebar.classList.remove("open");
  const overlay = $(".sidebar-overlay");
  if (overlay) overlay.remove();
}

// ---------- session search -------------------------------------------------
function setupSessionSearch() {
  const input = $("#session-search");
  if (input) {
    input.addEventListener("input", () => {
      const q = input.value.toLowerCase().trim();
      if (!q) {
        renderSessions(state.allSessions);
        return;
      }
      const filtered = state.allSessions.filter((s) =>
        s.title.toLowerCase().includes(q)
      );
      renderSessions(filtered);
    });
  }
}

// ---------- utilities ------------------------------------------------------
function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function prettyMaybeJson(s) {
  if (typeof s !== "string") return String(s);
  const t = s.trim();
  if (t.startsWith("{") || t.startsWith("[")) {
    try { return JSON.stringify(JSON.parse(t), null, 2); } catch {}
  }
  return s;
}

function autoResize() {
  const ta = $("#prompt");
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight, 240) + "px";
}

// ---------- events ---------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  boot();

  $("#composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const prompt = $("#prompt").value;
    if (!prompt.trim()) return;
    $("#prompt").value = "";
    autoResize();
    sendPrompt(prompt);
  });

  $("#prompt").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      $("#composer").requestSubmit();
    }
  });
  $("#prompt").addEventListener("input", autoResize);

  $("#new-session").addEventListener("click", async () => {
    const res = await fetch("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    if (res.ok) {
      const s = await res.json();
      await openSession(s.id);
      showToast("New session created", "success");
      closeMobileSidebar();
    }
  });

  $("#refresh-audit").addEventListener("click", () => {
    loadAudit();
    showToast("Audit refreshed", "info");
  });

  $$(".suggestion").forEach((btn) => {
    btn.addEventListener("click", () => {
      $("#prompt").value = btn.dataset.prompt;
      autoResize();
      $("#composer").requestSubmit();
    });
  });

  $("#toggle-panel")?.addEventListener("click", () => {
    $("#right-panel")?.classList.toggle("hidden");
    $("#right-panel")?.classList.toggle("lg:flex");
  });
});
