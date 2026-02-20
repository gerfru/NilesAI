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

/* --- Chat message helpers (flat layout) --- */

function createUserBubble(text) {
    const div = document.createElement("div");
    div.className = "mb-5";
    div.innerHTML =
        '<div class="flex items-baseline gap-2 mb-1">' +
        '<span class="text-xs font-semibold text-zinc-500 dark:text-zinc-400">Du</span>' +
        '<span class="text-[0.6rem] text-zinc-400 dark:text-zinc-500">' + formatTimestamp() + '</span>' +
        '</div>' +
        '<div class="whitespace-pre-wrap break-words px-4 py-3 rounded-xl bg-blue-50 dark:bg-blue-950 text-zinc-900 dark:text-zinc-100" data-user-content></div>';
    div.querySelector("[data-user-content]").textContent = text;
    return div;
}

function createAssistantBubble() {
    const div = document.createElement("div");
    div.className = "mb-5";
    div.innerHTML =
        '<div class="flex items-baseline gap-2 mb-1">' +
        '<span class="text-xs font-semibold text-zinc-500 dark:text-zinc-400">Niles</span>' +
        '<span class="text-[0.6rem] text-zinc-400 dark:text-zinc-500">' + formatTimestamp() + '</span>' +
        '</div>' +
        '<div class="whitespace-pre-wrap break-words text-zinc-900 dark:text-zinc-100 markdown"></div>';
    return div;
}

/* --- Chat streaming (SSE) --- */

let chatStreaming = false;
let chatAbortController = null;

async function handleChatSubmit(form) {
    if (chatStreaming) return;

    const input = form.querySelector("[name='message']");
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
    /* Reset auto-grow mirror */
    var mirror = input.parentNode && input.parentNode.querySelector("[data-autogrow-mirror]");
    if (mirror) mirror.textContent = "";
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

/* Calendar source add form -- show/hide auth fields based on type + populate hidden fields */
document.body.addEventListener("change", function(evt) {
    if (evt.target.id !== "cal-source-type") return;
    var authFields = document.getElementById("caldav-auth-fields");
    if (authFields) {
        if (evt.target.value === "caldav") {
            authFields.classList.remove("hidden");
        } else {
            authFields.classList.add("hidden");
        }
    }
});

document.body.addEventListener("click", function(evt) {
    if (!evt.target.hasAttribute("data-calendar-add")) return;
    /* Populate hidden form fields from visible inputs before htmx submit */
    var type = document.getElementById("cal-source-type");
    var name = document.getElementById("cal-source-name");
    var url = document.getElementById("cal-source-url");
    var user = document.getElementById("cal-source-user");
    var password = document.getElementById("cal-source-password");

    if (type) document.getElementById("cal-form-type").value = type.value;
    if (name) document.getElementById("cal-form-name").value = name.value;
    if (url) document.getElementById("cal-form-url").value = url.value;
    if (user) document.getElementById("cal-form-user").value = user.value;
    if (password) document.getElementById("cal-form-password").value = password.value;

    /* Validate URL is provided */
    if (!url || !url.value.trim()) {
        evt.preventDefault();
        return;
    }
});

/* Render markdown + convert timestamps in content loaded via htmx (history pagination) */
document.body.addEventListener("htmx:afterSettle", function() {
    convertTimestamps();
    renderAllMarkdown();
});

/* Textarea auto-grow: mirror content to invisible div (CSP-safe, no inline styles) */
document.body.addEventListener("input", function(evt) {
    if (!evt.target.hasAttribute("data-autogrow")) return;
    var mirror = evt.target.parentNode.querySelector("[data-autogrow-mirror]");
    if (mirror) mirror.textContent = evt.target.value + "\n";
});

/* Textarea: Enter sends, Shift+Enter inserts newline */
document.body.addEventListener("keydown", function(evt) {
    if (!evt.target.hasAttribute("data-autogrow")) return;
    if (evt.key === "Enter" && !evt.shiftKey) {
        evt.preventDefault();
        var form = evt.target.closest("form");
        if (form) form.requestSubmit();
    }
});
