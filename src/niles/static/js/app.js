/* Scroll chat to bottom (throttled via rAF to avoid layout thrashing) */
let _scrollPending = false;
function scrollChat() {
    if (_scrollPending) return;
    _scrollPending = true;
    requestAnimationFrame(function() {
        const el = document.getElementById("chat-messages");
        if (el) el.scrollTop = el.scrollHeight;
        _scrollPending = false;
    });
}

/* Read a cookie value by name */
function getCookie(name) {
    const match = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
    return match ? decodeURIComponent(match[2]) : "";
}

/* --- Dark Mode (Tailwind: class="dark" on <html>) --- */

function applyTheme(theme) {
    if (theme === "dark") {
        document.documentElement.classList.add("dark");
    } else {
        document.documentElement.classList.remove("dark");
    }
    localStorage.setItem("niles_theme", theme);
}

function toggleTheme() {
    const isDark = document.documentElement.classList.contains("dark");
    applyTheme(isDark ? "light" : "dark");
}

/* Theme is applied early in theme.js (loaded in <head>) to prevent FOUC */

/* --- Markdown rendering --- */

function renderMarkdown(el) {
    if (!el || el.dataset.rendered) return;
    const raw = el.textContent;
    if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
        el.innerHTML = DOMPurify.sanitize(marked.parse(raw));
    }
    el.dataset.rendered = "1";
}

function renderAllMarkdown() {
    document.querySelectorAll(".markdown:not([data-rendered])").forEach(renderMarkdown);
}

/* --- Timestamp helpers --- */

function formatLocalTime(d) {
    const dd = String(d.getDate()).padStart(2, "0");
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const hh = String(d.getHours()).padStart(2, "0");
    const min = String(d.getMinutes()).padStart(2, "0");
    return dd + "." + mm + ". " + hh + ":" + min;
}

function formatTimestamp() {
    return formatLocalTime(new Date());
}

function formatISOToLocal(isoStr) {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    return formatLocalTime(d);
}

function convertTimestamps() {
    document.querySelectorAll("[data-iso]:not([data-converted])").forEach(function(el) {
        el.textContent = formatISOToLocal(el.dataset.iso);
        el.dataset.converted = "1";
    });
}

/* --- Chat bubble helpers --- */

function createUserBubble(text) {
    const div = document.createElement("div");
    div.className = "flex flex-col mb-3 items-end";
    div.innerHTML =
        '<span class="text-[0.65rem] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-0.5 px-1">Du</span>' +
        '<div class="max-w-[75%] px-4 py-3 rounded-2xl whitespace-pre-wrap break-words bg-blue-600 text-white"></div>' +
        '<span class="text-[0.6rem] text-gray-400 dark:text-gray-500 mt-0.5 px-1">' + formatTimestamp() + '</span>';
    div.querySelector(".bg-blue-600").textContent = text;
    return div;
}

function createAssistantBubble() {
    const div = document.createElement("div");
    div.className = "flex flex-col mb-3 items-start";
    div.innerHTML =
        '<span class="text-[0.65rem] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-0.5 px-1">Niles</span>' +
        '<div class="max-w-[75%] px-4 py-3 rounded-2xl whitespace-pre-wrap break-words bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100 markdown"></div>' +
        '<span class="text-[0.6rem] text-gray-400 dark:text-gray-500 mt-0.5 px-1">' + formatTimestamp() + '</span>';
    return div;
}

/* --- Chat streaming (SSE) --- */

let chatStreaming = false;
let chatAbortController = null;

async function handleChatSubmit(form) {
    if (chatStreaming) return;

    const input = form.querySelector("input[name='message']");
    const message = input.value.trim();
    if (!message) return;

    const messagesEl = document.getElementById("chat-messages");
    const indicator = document.getElementById("thinking-indicator");
    const submitBtn = form.querySelector("button[type='submit']");

    /* Remove empty state */
    const empty = messagesEl.querySelector(".chat-empty");
    if (empty) empty.remove();

    /* Show user bubble immediately */
    messagesEl.appendChild(createUserBubble(message));
    input.value = "";
    scrollChat();

    /* Show thinking indicator + disable button */
    chatStreaming = true;
    chatAbortController = new AbortController();
    if (indicator) indicator.classList.remove("hidden");
    if (submitBtn) submitBtn.disabled = true;
    scrollChat();

    try {
        const response = await fetch("/ui/api/chat/stream", {
            method: "POST",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded",
                "X-CSRF-Token": getCookie("niles_csrf"),
            },
            body: "message=" + encodeURIComponent(message),
            signal: chatAbortController.signal,
        });

        if (!response.ok) {
            throw new Error("HTTP " + response.status);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let bubble = null;
        let content = null;
        let rawText = "";

        /* Iterative stream reader (no recursive Promise chain) */
        while (true) {
            const { done, value } = await reader.read();
            if (done) {
                if (content) renderMarkdown(content);
                break;
            }

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop(); /* Keep incomplete line in buffer */

            for (let i = 0; i < lines.length; i++) {
                const line = lines[i];
                if (!line.startsWith("data: ")) continue;
                try {
                    const item = JSON.parse(line.slice(6));
                    if (item.type === "chunk") {
                        /* Create bubble on first chunk (not earlier) */
                        if (!bubble) {
                            if (indicator) indicator.classList.add("hidden");
                            bubble = createAssistantBubble();
                            messagesEl.appendChild(bubble);
                            content = bubble.querySelector(".markdown");
                        }
                        rawText += item.text;
                        content.textContent = rawText;
                        scrollChat();
                    }
                    if (item.type === "status") {
                        /* Keep thinking indicator visible during tool calls */
                        if (!bubble && indicator) {
                            indicator.classList.remove("hidden");
                        }
                    }
                    if (item.type === "done") {
                        if (indicator) indicator.classList.add("hidden");
                        if (content) renderMarkdown(content);
                    }
                } catch (e) { /* ignore parse errors */ }
            }
        }
    } catch (err) {
        if (err.name === "AbortError") return; /* User cancelled */
        if (indicator) indicator.classList.add("hidden");
        const errBubble = createAssistantBubble();
        messagesEl.appendChild(errBubble);
        errBubble.querySelector(".markdown").textContent = "Entschuldigung, ein Fehler ist aufgetreten.";
    } finally {
        chatStreaming = false;
        chatAbortController = null;
        if (submitBtn) submitBtn.disabled = false;
        scrollChat();
    }
}

/* --- Init --- */

document.addEventListener("DOMContentLoaded", function() {
    scrollChat();
    convertTimestamps();
    renderAllMarkdown();

    /* Chat form: custom submit handler (not htmx) */
    const chatForm = document.getElementById("chat-form");
    if (chatForm) {
        chatForm.addEventListener("submit", function(e) {
            e.preventDefault();
            handleChatSubmit(chatForm);
        });
    }
});

/* Dark mode toggle button (CSP-safe, event delegation) */
document.body.addEventListener("click", function(evt) {
    if (evt.target.hasAttribute("data-theme-toggle")) {
        toggleTheme();
    }
});

/* CSRF: include token header on every htmx request (#2) */
document.body.addEventListener("htmx:configRequest", function(evt) {
    const token = getCookie("niles_csrf");
    if (token) {
        evt.detail.headers["X-CSRF-Token"] = token;
    }
});

/* Thinking indicator + loading aria-busy on submit buttons (non-chat htmx) */
document.body.addEventListener("htmx:beforeRequest", function(evt) {
    const btn = evt.detail.elt.querySelector("button[type='submit']");
    if (btn) btn.setAttribute("aria-busy", "true");
});

/* Feature flag toggles -- update hidden value and submit form (CSP-safe, no eval) */
document.body.addEventListener("change", function(evt) {
    if (!evt.target.hasAttribute("data-flag-toggle")) return;
    const form = evt.target.closest("form");
    const hidden = form.querySelector("input[type='hidden']");
    hidden.value = evt.target.checked ? "true" : "false";
    htmx.trigger(form, "submit");
});

/* Calendar save -- collect checked values into hidden field before submit (CSP-safe) */
document.body.addEventListener("click", function(evt) {
    if (!evt.target.hasAttribute("data-calendar-save")) return;
    const form = evt.target.closest("form");
    const boxes = form.querySelectorAll("input[name=cal]:checked");
    if (boxes.length === 0) {
        evt.preventDefault();
        return;
    }
    const vals = Array.from(boxes).map(function(b) { return b.value; });
    form.querySelector("#cal-value").value = vals.join(",");
});

/* Calendar checkboxes -- disable save button when nothing is checked */
document.body.addEventListener("change", function(evt) {
    if (evt.target.name !== "cal") return;
    const form = evt.target.closest("form");
    const btn = form.querySelector("[data-calendar-save]");
    const checked = form.querySelectorAll("input[name=cal]:checked").length;
    btn.disabled = checked === 0;
});

document.body.addEventListener("htmx:afterRequest", function(evt) {
    const btn = evt.detail.elt.querySelector("button[type='submit']");
    if (btn) btn.removeAttribute("aria-busy");
});

/* Render markdown + convert timestamps in content loaded via htmx (history pagination) */
document.body.addEventListener("htmx:afterSettle", function() {
    convertTimestamps();
    renderAllMarkdown();
});
