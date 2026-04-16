// Minimal SPA that talks to the FastAPI backend over fetch + SSE.

const state = {
  sessionId: null,
  cost: 0,
  currentAssistantEl: null,   // the currently-streaming assistant bubble
  toolCards: {},              // id -> DOM element for pending tool calls
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

// ---------- initial load ----------------------------------------------------
async function boot() {
  await Promise.all([loadConfig(), loadTools(), loadSessions(), loadAudit()]);
  setInterval(loadAudit, 6000);
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
    tools.forEach((t) => {
      const li = document.createElement("li");
      li.className = "tool-item";
      li.innerHTML = `<div class="name">${t.name}</div><div class="desc">${escapeHtml(t.description)}</div>`;
      list.appendChild(li);
    });
  } catch (e) {
    list.innerHTML = `<li class="text-ink-400 text-xs px-1">Unavailable (${escapeHtml(String(e))}).</li>`;
  }
}

async function loadSessions() {
  try {
    const res = await fetch("/api/sessions");
    const sessions = await res.json();
    renderSessions(sessions);
  } catch (e) { console.error("sessions:", e); }
}

function renderSessions(sessions) {
  const list = $("#session-list");
  list.innerHTML = "";
  sessions.forEach((s) => {
    const li = document.createElement("li");
    li.className = "session-item" + (s.id === state.sessionId ? " active" : "");
    li.dataset.id = s.id;
    li.innerHTML = `
      <svg class="h-3.5 w-3.5 text-ink-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
      <span class="title" title="${escapeHtml(s.title)}">${escapeHtml(s.title)}</span>
      <button class="delete" title="delete session">
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>
      </button>`;
    li.addEventListener("click", async (ev) => {
      if (ev.target.closest(".delete")) {
        await fetch(`/api/sessions/${s.id}`, { method: "DELETE" });
        if (state.sessionId === s.id) resetConversation();
        await loadSessions();
        return;
      }
      await openSession(s.id);
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
  chat.innerHTML = '<div class="text-center text-ink-400 text-xs py-6">Loading session…</div>';
  try {
    const res = await fetch(`/api/sessions/${id}/transcript`);
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    chat.innerHTML = "";
    $("#header-title").textContent = data.title;
    $("#cost-display").textContent = fmtCost(data.total_cost_usd);
    state.cost = data.total_cost_usd;
    data.transcript.forEach(replayEvent);
    await loadSessions();
  } catch (e) {
    chat.innerHTML = `<div class="text-red-400 text-sm">Failed to load session: ${escapeHtml(String(e))}</div>`;
  }
}

function resetConversation() {
  state.sessionId = null;
  state.cost = 0;
  state.currentAssistantEl = null;
  state.toolCards = {};
  $("#chat").innerHTML = "";
  $("#header-title").textContent = "New conversation";
  $("#cost-display").textContent = "$0.0000";
}

async function loadAudit() {
  try {
    const res = await fetch("/api/audit?limit=15");
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
             <span class="text-ink-400">·</span>
             <span class="${e.status === 'ok' ? 'text-green-400' : 'text-red-400'}">${escapeHtml(e.status)}</span>
             <span class="text-ink-400">·</span>
             <span class="text-ink-300">${e.duration_ms}ms</span></div>
        <div class="ts">${e.ts}</div>
        ${e.error ? `<div class="text-red-400 text-[11px]">${escapeHtml(e.error)}</div>` : ""}
      `;
      list.appendChild(li);
    });
  } catch (e) { /* silent */ }
}

// ---------- chat streaming --------------------------------------------------
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
      body: JSON.stringify({
        prompt,
        session_id: state.sessionId,
      }),
    });
    if (!res.ok || !res.body) {
      const err = await res.text();
      addAssistantBubble(`Error: ${err}`);
      return;
    }
    await consumeSSE(res.body);
  } catch (e) {
    addAssistantBubble(`Network error: ${e.message}`);
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
      break; // already displayed
    case "llm_start":
      ensureAssistantBubble(true);
      break;
    case "assistant":
      if (payload.text) setAssistantText(payload.text);
      break;
    case "tool_call": {
      const card = addToolCard(payload);
      state.toolCards[payload.id] = card;
      state.currentAssistantEl = null; // next assistant event starts fresh
      break;
    }
    case "tool_result": {
      const card = state.toolCards[payload.id];
      if (card) updateToolCard(card, payload);
      break;
    }
    case "step":
      if (payload.trace && typeof payload.trace.cost_usd === "number") {
        state.cost += payload.trace.cost_usd;
        $("#cost-display").textContent = fmtCost(state.cost);
      }
      break;
    case "final":
      if (payload.text) setAssistantText(payload.text);
      if (typeof payload.total_cost_usd === "number") {
        state.cost = payload.total_cost_usd;
        $("#cost-display").textContent = fmtCost(state.cost);
      }
      if (payload.stopped_reason && payload.stopped_reason !== "completed") {
        addNote(`Stopped: ${payload.stopped_reason}`);
      }
      break;
    case "error":
      addNote(`Error: ${payload.message}`, true);
      break;
    case "done":
      break;
  }
}

function replayEvent(payload) {
  // Re-render an event loaded from transcript (server state restored).
  switch (payload.type) {
    case "user": addUserBubble(payload.text); break;
    case "assistant":
      if (payload.text) {
        ensureAssistantBubble();
        setAssistantText(payload.text);
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
        setAssistantText(payload.text);
        state.currentAssistantEl = null;
      }
      break;
  }
}

// ---------- DOM helpers -----------------------------------------------------
function addUserBubble(text) {
  const el = document.createElement("div");
  el.className = "msg msg-user";
  el.textContent = text;
  $("#chat").appendChild(el);
  scrollChat();
}

function ensureAssistantBubble(showTyping = false) {
  if (!state.currentAssistantEl) {
    const el = document.createElement("div");
    el.className = "msg msg-assistant";
    if (showTyping) {
      el.innerHTML = '<span class="typing"><span></span><span></span><span></span></span>';
    }
    $("#chat").appendChild(el);
    state.currentAssistantEl = el;
    scrollChat();
  }
  return state.currentAssistantEl;
}

function setAssistantText(text) {
  const el = ensureAssistantBubble();
  el.textContent = text;
  scrollChat();
}

function addAssistantBubble(text) {
  state.currentAssistantEl = null;
  const el = ensureAssistantBubble();
  el.textContent = text;
  state.currentAssistantEl = null;
}

function addToolCard(payload) {
  const card = document.createElement("div");
  card.className = "tool-card";
  card.innerHTML = `
    <div class="tool-card-header">
      <svg class="h-3.5 w-3.5 text-brand" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M14.7 6.3a4 4 0 0 1 5 5L17 14l3 3-3 3-3-3-2.7 2.7a4 4 0 0 1-5-5L7 12l-3-3 3-3 3 3 1.7-1.7Z"/>
      </svg>
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
  const resultPre = document.createElement("pre");
  resultPre.textContent = prettyMaybeJson(payload.content);
  body.appendChild(Object.assign(document.createElement("span"), { className: "label", textContent: "result" }));
  body.appendChild(resultPre);
  scrollChat();
}

function addNote(text, isError = false) {
  const el = document.createElement("div");
  el.className = "text-xs text-center " + (isError ? "text-red-400" : "text-ink-400");
  el.textContent = text;
  $("#chat").appendChild(el);
  scrollChat();
}

function setSending(sending) {
  $("#send").disabled = sending;
  $("#prompt").disabled = sending;
}

function hideEmptyState() {
  const el = $("#empty-state");
  if (el) el.remove();
}

function scrollChat() {
  const chat = $("#chat");
  chat.scrollTop = chat.scrollHeight;
}

function fmtCost(v) {
  const n = Number(v) || 0;
  return "$" + n.toFixed(4);
}

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
    try { return JSON.stringify(JSON.parse(t), null, 2); } catch { /* ignore */ }
  }
  return s;
}

// ---------- events ----------------------------------------------------------
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
    }
  });

  $("#refresh-audit").addEventListener("click", loadAudit);

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

function autoResize() {
  const ta = $("#prompt");
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight, 240) + "px";
}
