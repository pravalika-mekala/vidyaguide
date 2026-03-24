let recognition = null;
let isListening = false;
let voiceOutputEnabled = true;
let selectedVoice = null;
let chatHistory = [];
let chatThreads = [];
let activeThreadId = "";

const CHAT_TOPICS = [
  "Review my resume for backend developer roles.",
  "Give me a 7-day interview preparation plan for Python and SQL.",
  "Help me answer Tell me about yourself for a fresher software role.",
  "Suggest projects I can build to improve my placement chances.",
  "Rewrite my resume bullets to sound more impactful.",
];

function selectBestVoice() {
  if (!("speechSynthesis" in window)) return null;
  const voices = window.speechSynthesis.getVoices() || [];
  if (!voices.length) return null;

  const preferredNames = [
    "Google US English",
    "Microsoft Aria",
    "Microsoft Jenny",
    "Samantha",
    "Karen",
    "Daniel",
  ];

  const byName = voices.find((voice) => preferredNames.some((name) => (voice.name || "").toLowerCase().includes(name.toLowerCase())));
  if (byName) return byName;

  const english = voices.find((voice) => String(voice.lang || "").toLowerCase().startsWith("en"));
  return english || voices[0] || null;
}

function readJsonSeed(id, fallback) {
  const seed = document.getElementById(id);
  if (!seed) {
    return fallback;
  }
  try {
    return JSON.parse(seed.textContent || JSON.stringify(fallback));
  } catch (_err) {
    return fallback;
  }
}

function readHistoryFromPage() {
  const data = readJsonSeed("chatHistorySeed", []);
  return Array.isArray(data) ? data : [];
}

function readThreadsFromPage() {
  const data = readJsonSeed("chatThreadsSeed", []);
  return Array.isArray(data) ? data : [];
}

function readActiveThreadFromPage() {
  return String(readJsonSeed("activeThreadSeed", "") || "");
}

function formatAgo(ts) {
  const n = Number(ts || 0);
  if (!n) return "";
  const diff = Math.max(0, Math.floor(Date.now() / 1000) - n);
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function getFilteredThreads() {
  const search = document.getElementById("chatSearch");
  const query = String(search?.value || "").trim().toLowerCase();
  if (!query) {
    return chatThreads;
  }

  return chatThreads.filter((thread) => {
    const title = String(thread.title || "").toLowerCase();
    const preview = String(thread.preview || "").toLowerCase();
    return title.includes(query) || preview.includes(query);
  });
}

function renderThreads() {
  const list = document.getElementById("chatThreadList");
  if (!list) return;

  list.innerHTML = "";
  const visibleThreads = getFilteredThreads();
  if (!visibleThreads.length) {
    const empty = document.createElement("div");
    empty.className = "chat-thread-empty";
    empty.textContent = chatThreads.length ? "No chats match your search." : "No previous conversations yet.";
    list.appendChild(empty);
    return;
  }

  visibleThreads.forEach((thread) => {
    const isActive = thread.id === activeThreadId;
    const wrap = document.createElement("div");
    wrap.className = "chat-thread-row";

    const button = document.createElement("button");
    button.type = "button";
    button.className = `chat-thread ${isActive ? "active" : ""}`;

    const title = document.createElement("div");
    title.className = "chat-thread-title";
    title.textContent = thread.title || "Untitled chat";

    const meta = document.createElement("div");
    meta.className = "chat-thread-meta";
    const preview = (thread.preview || "").trim();
    const ago = formatAgo(thread.updated_at);
    meta.textContent = preview ? `${preview}${ago ? ` | ${ago}` : ""}` : (ago || "Recent");
    meta.textContent = preview ? `${preview}${ago ? ` • ${ago}` : ""}` : (isActive ? "Active now" : (ago || ""));

    meta.textContent = preview ? `${preview}${ago ? ` | ${ago}` : ""}` : (ago || "Recent");
    button.appendChild(title);
    button.appendChild(meta);
    button.addEventListener("click", () => switchThread(thread.id));

    const del = document.createElement("button");
    del.type = "button";
    del.className = "chat-thread-del";
    del.title = "Delete chat";
    del.textContent = "x";
    del.textContent = "×";
    del.textContent = "x";
    del.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      deleteThread(thread.id);
    });

    wrap.appendChild(button);
    wrap.appendChild(del);
    list.appendChild(wrap);
  });
}

function renderTopicList() {
  const list = document.getElementById("chatTopicList");
  const input = document.getElementById("message");
  if (!list || !input) {
    return;
  }

  list.innerHTML = "";
  CHAT_TOPICS.forEach((topic) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "chat-topic-chip";
    button.textContent = topic;
    button.addEventListener("click", () => {
      input.value = topic;
      resizeComposer(input);
      input.focus();
      list.querySelectorAll(".chat-topic-chip").forEach((chip) => chip.classList.remove("active"));
      button.classList.add("active");
    });
    list.appendChild(button);
  });
}

function escapeHtml(text) {
  return String(text || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function inlineMarkdown(text) {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function markdownToHtml(text) {
  const source = String(text || "").replace(/\r\n/g, "\n");
  const lines = source.split("\n");
  const html = [];
  let inList = false;
  let inCode = false;
  let codeBuffer = [];

  function flushList() {
    if (inList) {
      html.push("</ul>");
      inList = false;
    }
  }

  function flushCode() {
    if (inCode) {
      html.push(`<pre><code>${escapeHtml(codeBuffer.join("\n"))}</code></pre>`);
      inCode = false;
      codeBuffer = [];
    }
  }

  lines.forEach((line) => {
    if (line.trim().startsWith("```")) {
      if (inCode) {
        flushCode();
      } else {
        flushList();
        inCode = true;
      }
      return;
    }

    if (inCode) {
      codeBuffer.push(line);
      return;
    }

    const trimmed = line.trim();
    if (!trimmed) {
      flushList();
      return;
    }

    if (/^[-*]\s+/.test(trimmed)) {
      if (!inList) {
        html.push("<ul>");
        inList = true;
      }
      html.push(`<li>${inlineMarkdown(trimmed.replace(/^[-*]\s+/, ""))}</li>`);
      return;
    }

    flushList();
    html.push(`<p>${inlineMarkdown(trimmed)}</p>`);
  });

  flushList();
  flushCode();
  return html.join("");
}

function createCopyButton(text) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "chat-copy-btn";
  button.textContent = "Copy";
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(String(text || ""));
      button.textContent = "Copied";
      window.setTimeout(() => {
        button.textContent = "Copy";
      }, 1200);
    } catch (_err) {
      button.textContent = "Failed";
      window.setTimeout(() => {
        button.textContent = "Copy";
      }, 1200);
    }
  });
  return button;
}

function scrollChatToBottom(chat) {
  if (!chat) return;
  chat.scrollTop = chat.scrollHeight;
}

function buildMessageBubble(text, roleClass, options = {}) {
  const { includeActions = true } = options;
  const line = document.createElement("div");
  line.className = `chat-msg ${roleClass}`;

  const bubble = document.createElement("div");
  bubble.className = "chat-bubble";

  const body = document.createElement("div");
  body.className = "chat-markdown";
  body.innerHTML = markdownToHtml(text);
  bubble.appendChild(body);

  if (roleClass === "chat-ai" && includeActions) {
    const actions = document.createElement("div");
    actions.className = "chat-message-actions";
    actions.appendChild(createCopyButton(text));
    bubble.appendChild(actions);
  }

  line.appendChild(bubble);
  return { line, body, bubble };
}

function renderHistory(chat) {
  if (!chat) {
    return;
  }
  const suggestions = document.getElementById("chatTopicList");

  chat.innerHTML = "";
  if (!chatHistory.length) {
    if (suggestions) {
      suggestions.style.display = "flex";
    }
    const empty = document.createElement("div");
    empty.className = "chat-empty";
    empty.textContent = "Start a conversation. Ask for resume help, interview prep, project guidance, or a study plan.";
    chat.appendChild(empty);
    return;
  }

  if (suggestions) {
    suggestions.style.display = "none";
  }

  chatHistory.forEach((item) => {
    const message = buildMessageBubble(item.content || "", item.role === "user" ? "chat-user" : "chat-ai");
    chat.appendChild(message.line);
  });
  scrollChatToBottom(chat);
}

async function streamAssistantMessage(chat, text) {
  const message = buildMessageBubble("", "chat-ai", { includeActions: false });
  chat.appendChild(message.line);
  scrollChatToBottom(chat);

  const fullText = String(text || "");
  let current = "";
  const chunks = fullText.split(/(\s+)/).filter((part) => part.length);

  for (const chunk of chunks) {
    current += chunk;
    message.body.innerHTML = markdownToHtml(current);
    scrollChatToBottom(chat);
    await new Promise((resolve) => window.setTimeout(resolve, /\s/.test(chunk) ? 0 : 18));
  }

  const actions = document.createElement("div");
  actions.className = "chat-message-actions";
  actions.appendChild(createCopyButton(fullText));
  if (!message.bubble.querySelector(".chat-message-actions")) {
    message.bubble.appendChild(actions);
  }
}

function appendTyping(chat) {
  removeTyping(chat);
  const line = document.createElement("div");
  line.className = "chat-msg chat-ai";
  line.id = "chatTyping";

  const bubble = document.createElement("div");
  bubble.className = "chat-bubble";
  bubble.innerHTML = '<div class="chat-typing"><span></span><span></span><span></span></div>';

  line.appendChild(bubble);
  chat.appendChild(line);
  scrollChatToBottom(chat);
}

function removeTyping(chat) {
  const existing = document.getElementById("chatTyping");
  if (existing && chat.contains(existing)) {
    chat.removeChild(existing);
  }
}

async function switchThread(threadId) {
  const chat = document.getElementById("chatbox");
  const id = String(threadId || "").trim();
  if (!id || id === activeThreadId) return;

  try {
    const res = await fetch("/chat/thread/switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thread_id: id }),
    });
    const data = await res.json();
    if (data && data.ok) {
      activeThreadId = id;
      chatHistory = Array.isArray(data.history) ? data.history : [];
      renderHistory(chat);
      renderThreads();
    }
  } catch (_err) {
    // ignore
  }
}

async function deleteThread(threadId) {
  const id = String(threadId || "").trim();
  if (!id) return;
  try {
    const res = await fetch("/chat/thread/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thread_id: id }),
    });
    const data = await res.json();
    if (data && data.ok) {
      if (Array.isArray(data.threads)) {
        const byId = new Map(chatThreads.map((thread) => [thread.id, thread]));
        chatThreads = data.threads.map((thread) => ({ ...byId.get(thread.id), ...thread }));
      } else {
        chatThreads = chatThreads.filter((thread) => thread.id !== id);
      }
      activeThreadId = String(data.active_thread_id || activeThreadId);
      renderThreads();
      if (activeThreadId) {
        await switchThread(activeThreadId);
      } else {
        chatHistory = [];
        renderHistory(document.getElementById("chatbox"));
      }
    }
  } catch (_err) {
    // ignore
  }
}

async function createNewThread() {
  const chat = document.getElementById("chatbox");
  try {
    const res = await fetch("/chat/thread/new", { method: "POST" });
    const data = await res.json();
    if (data && data.ok && data.thread && data.thread.id) {
      activeThreadId = data.thread.id;
      chatHistory = [];
      chatThreads = [{ ...data.thread, preview: "" }, ...chatThreads.filter((thread) => thread.id !== data.thread.id)].slice(0, 30);
      renderThreads();
      renderHistory(chat);
      return;
    }
  } catch (_err) {
    // ignore
  }
  chatHistory = [];
  renderHistory(chat);
}

function updateActiveThreadMeta(message) {
  const idx = chatThreads.findIndex((thread) => thread.id === activeThreadId);
  if (idx < 0) return;

  const title = (chatThreads[idx].title || "").trim();
  if (!title || title === "New chat" || title === "Current chat" || title === "Untitled chat") {
    const normalized = message.replace(/\s+/g, " ").trim();
    chatThreads[idx].title = normalized.length > 44 ? `${normalized.slice(0, 44)}...` : normalized;
  }
  chatThreads[idx].updated_at = Math.floor(Date.now() / 1000);
  chatThreads[idx].preview = message.slice(0, 90);
  const active = chatThreads.splice(idx, 1)[0];
  chatThreads.unshift(active);
  renderThreads();
}

async function sendMessage() {
  const input = document.getElementById("message");
  const chat = document.getElementById("chatbox");
  const sendBtn = document.getElementById("sendBtn");

  if (!input || !chat || !sendBtn) {
    return;
  }

  const msg = input.value.trim();
  if (!msg) {
    return;
  }

  input.value = "";
  resizeComposer(input);
  input.focus();
  sendBtn.disabled = true;

  chatHistory.push({ role: "user", content: msg });
  renderHistory(chat);
  appendTyping(chat);
  updateActiveThreadMeta(msg);

  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: msg }),
    });
    const data = await res.json();
    removeTyping(chat);

    const reply = String(data.reply || "No response");
    if (Array.isArray(data.history)) {
      chatHistory = data.history;
      if (chatHistory.length) {
        const historyWithoutLast = chatHistory.slice(0, -1);
        chat.innerHTML = "";
        historyWithoutLast.forEach((item) => {
          const message = buildMessageBubble(item.content || "", item.role === "user" ? "chat-user" : "chat-ai");
          chat.appendChild(message.line);
        });
        await streamAssistantMessage(chat, reply);
      } else {
        renderHistory(chat);
      }
    } else {
      chatHistory.push({ role: "assistant", content: reply });
      await streamAssistantMessage(chat, reply);
    }

    speakText(reply);
  } catch (_err) {
    removeTyping(chat);
    const fallback = "Service is currently unavailable. Please retry.";
    chatHistory.push({ role: "assistant", content: fallback });
    renderHistory(chat);
    speakText(fallback);
  } finally {
    sendBtn.disabled = false;
  }
}

async function clearConversation() {
  await createNewThread();
}

function resizeComposer(textarea) {
  if (!textarea) return;
  textarea.style.height = "0px";
  textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
}

function initVoiceFeatures() {
  const micBtn = document.getElementById("micBtn");
  const micInlineBtn = document.getElementById("micInlineBtn");
  const voiceToggleBtn = document.getElementById("voiceToggleBtn");
  const voiceStatus = document.getElementById("voiceStatus");
  const input = document.getElementById("message");

  if (!micBtn || !micInlineBtn || !voiceToggleBtn || !voiceStatus || !input) {
    return;
  }

  function setMicLabels(label) {
    micBtn.textContent = label;
    micInlineBtn.textContent = label;
  }

  function toggleMic() {
    if (!recognition) return;
    if (isListening) {
      recognition.stop();
    } else {
      voiceStatus.textContent = "Mic requesting permission";
      recognition.start();
    }
  }

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (SpeechRecognition) {
    recognition = new SpeechRecognition();
    recognition.lang = "en-US";
    recognition.interimResults = true;
    recognition.continuous = true;

    recognition.onstart = () => {
      isListening = true;
      setMicLabels("Listening");
      voiceStatus.textContent = "Mic listening";
    };

    recognition.onresult = (event) => {
      let transcript = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        transcript += event.results[i][0].transcript;
      }
      input.value = transcript.trim();
      resizeComposer(input);
    };

    recognition.onerror = (event) => {
      isListening = false;
      setMicLabels("Mic");
      voiceStatus.textContent = "Mic error";
    };

    recognition.onend = () => {
      isListening = false;
      setMicLabels("Mic");
      if (!voiceStatus.textContent.startsWith("Mic error")) {
        voiceStatus.textContent = "Mic idle";
      }
    };

    micBtn.addEventListener("click", toggleMic);
    micInlineBtn.addEventListener("click", toggleMic);
  } else {
    micBtn.disabled = true;
    micInlineBtn.disabled = true;
    setMicLabels("Mic off");
    voiceStatus.textContent = "Mic not supported";
  }

  voiceToggleBtn.addEventListener("click", () => {
    voiceOutputEnabled = !voiceOutputEnabled;
    voiceToggleBtn.textContent = `Voice: ${voiceOutputEnabled ? "ON" : "OFF"}`;
    if (!voiceOutputEnabled && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
  });

  if ("speechSynthesis" in window) {
    selectedVoice = selectBestVoice();
    window.speechSynthesis.onvoiceschanged = () => {
      selectedVoice = selectBestVoice();
    };
  }
}

function speakText(text) {
  if (!voiceOutputEnabled || !("speechSynthesis" in window)) {
    return;
  }

  const spoken = String(text || "").trim();
  if (!spoken) {
    return;
  }

  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(spoken);
  utterance.lang = "en-US";
  utterance.rate = 0.97;
  utterance.pitch = 1.03;
  if (selectedVoice) {
    utterance.voice = selectedVoice;
    if (selectedVoice.lang) {
      utterance.lang = selectedVoice.lang;
    }
  }
  window.speechSynthesis.speak(utterance);
}

function bindPromptButtons(input) {
  document.querySelectorAll(".chat-topic-chip").forEach((button) => {
    button.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        button.click();
      }
    });
  });

  if (input) {
    input.addEventListener("input", () => resizeComposer(input));
  }
}

function initChatPage() {
  const chat = document.getElementById("chatbox");
  if (!chat || chat.__vgInitialized) {
    return;
  }
  chat.__vgInitialized = true;

  const input = document.getElementById("message");
  const sendBtn = document.getElementById("sendBtn");
  const newChatBtn = document.getElementById("newChatBtn");
  const composerAddBtn = document.getElementById("composerAddBtn");
  const search = document.getElementById("chatSearch");
  if (!input || !chat) {
    return;
  }

  chatHistory = readHistoryFromPage();
  chatThreads = readThreadsFromPage();
  activeThreadId = readActiveThreadFromPage();

  renderTopicList();
  renderThreads();
  renderHistory(chat);
  resizeComposer(input);
  bindPromptButtons(input);

  if (sendBtn) {
    sendBtn.onclick = sendMessage;
  }

  if (newChatBtn) {
    newChatBtn.onclick = clearConversation;
  }

  if (composerAddBtn) {
    composerAddBtn.onclick = clearConversation;
  }

  if (search) {
    search.oninput = renderThreads;
  }

  input.onkeydown = (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  };

  initVoiceFeatures();
}

if (!window.__vgChatInitBound) {
  document.addEventListener("DOMContentLoaded", initChatPage);
  document.addEventListener("page:loaded", initChatPage);
  window.__vgChatInitBound = true;
}

// Always attempt initialization when script runs (e.g. after SPA swap)
initChatPage();
