/* Scroll chat to bottom (throttled via rAF to avoid layout thrashing) */
var _scrollPending = false;
function scrollChat() {
    if (_scrollPending) return;
    _scrollPending = true;
    requestAnimationFrame(function() {
        var el = document.getElementById("chat-messages");
        if (el) el.scrollTop = el.scrollHeight;
        _scrollPending = false;
    });
}

/* Read a cookie value by name */
function getCookie(name) {
    var match = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
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
    var isDark = document.documentElement.classList.contains("dark");
    applyTheme(isDark ? "light" : "dark");
}

/* Theme is applied early in theme.js (loaded in <head>) to prevent FOUC */

/* --- Markdown rendering --- */

function renderMarkdown(el) {
    if (!el || el.dataset.rendered) return;
    var raw = el.textContent;
    if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
        el.innerHTML = DOMPurify.sanitize(marked.parse(raw));
    }
    el.dataset.rendered = "1";
}

function renderAllMarkdown() {
    var els = document.querySelectorAll(".markdown:not([data-rendered])");
    els.forEach(renderMarkdown);
}

/* --- Timestamp helper --- */

function formatTimestamp() {
    var now = new Date();
    var dd = String(now.getDate()).padStart(2, "0");
    var mm = String(now.getMonth() + 1).padStart(2, "0");
    var hh = String(now.getHours()).padStart(2, "0");
    var min = String(now.getMinutes()).padStart(2, "0");
    return dd + "." + mm + ". " + hh + ":" + min;
}

/* --- Chat bubble helpers --- */

function createUserBubble(text) {
    var div = document.createElement("div");
    div.className = "flex flex-col mb-3 items-end";
    div.innerHTML =
        '<span class="text-[0.65rem] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-0.5 px-1">Du</span>' +
        '<div class="max-w-[75%] px-4 py-3 rounded-2xl whitespace-pre-wrap break-words bg-blue-600 text-white"></div>' +
        '<span class="text-[0.6rem] text-gray-400 dark:text-gray-500 mt-0.5 px-1">' + formatTimestamp() + '</span>';
    div.querySelector(".bg-blue-600").textContent = text;
    return div;
}

function createAssistantBubble() {
    var div = document.createElement("div");
    div.className = "flex flex-col mb-3 items-start";
    div.innerHTML =
        '<span class="text-[0.65rem] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-0.5 px-1">Niles</span>' +
        '<div class="max-w-[75%] px-4 py-3 rounded-2xl whitespace-pre-wrap break-words bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100 markdown"></div>' +
        '<span class="text-[0.6rem] text-gray-400 dark:text-gray-500 mt-0.5 px-1">' + formatTimestamp() + '</span>';
    return div;
}

/* --- Chat streaming (SSE) --- */

var chatStreaming = false;
var chatAbortController = null;

function handleChatSubmit(form) {
    if (chatStreaming) return;

    var input = form.querySelector("input[name='message']");
    var message = input.value.trim();
    if (!message) return;

    var messages = document.getElementById("chat-messages");
    var indicator = document.getElementById("thinking-indicator");
    var submitBtn = form.querySelector("button[type='submit']");

    /* Remove empty state */
    var empty = messages.querySelector(".chat-empty");
    if (empty) empty.remove();

    /* Show user bubble immediately */
    messages.appendChild(createUserBubble(message));
    input.value = "";
    scrollChat();

    /* Show thinking indicator + disable button */
    chatStreaming = true;
    chatAbortController = new AbortController();
    if (indicator) indicator.classList.remove("hidden");
    if (submitBtn) submitBtn.disabled = true;
    scrollChat();

    /* Start SSE stream */
    fetch("/ui/api/chat/stream", {
        method: "POST",
        headers: {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-CSRF-Token": getCookie("niles_csrf"),
        },
        body: "message=" + encodeURIComponent(message),
        signal: chatAbortController.signal,
    }).then(function(response) {
        if (!response.ok) {
            throw new Error("HTTP " + response.status);
        }

        /* Hide thinking indicator, create assistant bubble */
        if (indicator) indicator.classList.add("hidden");
        var bubble = createAssistantBubble();
        messages.appendChild(bubble);
        var content = bubble.querySelector(".markdown");
        var rawText = "";

        var reader = response.body.getReader();
        var decoder = new TextDecoder();
        var buffer = "";

        function processStream() {
            return reader.read().then(function(result) {
                if (result.done) {
                    /* Render final markdown */
                    if (rawText) {
                        content.textContent = rawText;
                        renderMarkdown(content);
                    }
                    chatStreaming = false;
                    chatAbortController = null;
                    if (submitBtn) submitBtn.disabled = false;
                    scrollChat();
                    return;
                }

                buffer += decoder.decode(result.value, { stream: true });
                var lines = buffer.split("\n");
                buffer = lines.pop(); /* Keep incomplete line in buffer */

                for (var i = 0; i < lines.length; i++) {
                    var line = lines[i];
                    if (!line.startsWith("data: ")) continue;
                    try {
                        var item = JSON.parse(line.slice(6));
                        if (item.type === "chunk") {
                            rawText += item.text;
                            content.textContent = rawText;
                            scrollChat();
                        }
                        if (item.type === "status") {
                            if (indicator) {
                                indicator.querySelector("div > div").textContent = item.text;
                                indicator.classList.remove("hidden");
                            }
                        }
                        if (item.type === "done") {
                            content.textContent = rawText;
                            renderMarkdown(content);
                        }
                    } catch (e) { /* ignore parse errors */ }
                }

                return processStream();
            });
        }

        return processStream();
    }).catch(function(err) {
        if (err.name === "AbortError") return; /* User cancelled */
        if (indicator) indicator.classList.add("hidden");
        var bubble = createAssistantBubble();
        messages.appendChild(bubble);
        bubble.querySelector(".markdown").textContent = "Entschuldigung, ein Fehler ist aufgetreten.";
        chatStreaming = false;
        chatAbortController = null;
        if (submitBtn) submitBtn.disabled = false;
        scrollChat();
    });
}

/* --- Init --- */

document.addEventListener("DOMContentLoaded", function() {
    scrollChat();
    renderAllMarkdown();

    /* Chat form: custom submit handler (not htmx) */
    var chatForm = document.getElementById("chat-form");
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
    var token = getCookie("niles_csrf");
    if (token) {
        evt.detail.headers["X-CSRF-Token"] = token;
    }
});

/* Thinking indicator + loading aria-busy on submit buttons (non-chat htmx) */
document.body.addEventListener("htmx:beforeRequest", function(evt) {
    var btn = evt.detail.elt.querySelector("button[type='submit']");
    if (btn) btn.setAttribute("aria-busy", "true");
});

/* Feature flag toggles -- update hidden value and submit form (CSP-safe, no eval) */
document.body.addEventListener("change", function(evt) {
    if (!evt.target.hasAttribute("data-flag-toggle")) return;
    var form = evt.target.closest("form");
    var hidden = form.querySelector("input[type='hidden']");
    hidden.value = evt.target.checked ? "true" : "false";
    htmx.trigger(form, "submit");
});

/* Calendar save -- collect checked values into hidden field before submit (CSP-safe) */
document.body.addEventListener("click", function(evt) {
    if (!evt.target.hasAttribute("data-calendar-save")) return;
    var form = evt.target.closest("form");
    var boxes = form.querySelectorAll("input[name=cal]:checked");
    if (boxes.length === 0) {
        evt.preventDefault();
        return;
    }
    var vals = Array.from(boxes).map(function(b) { return b.value; });
    form.querySelector("#cal-value").value = vals.join(",");
});

/* Calendar checkboxes -- disable save button when nothing is checked */
document.body.addEventListener("change", function(evt) {
    if (evt.target.name !== "cal") return;
    var form = evt.target.closest("form");
    var btn = form.querySelector("[data-calendar-save]");
    var checked = form.querySelectorAll("input[name=cal]:checked").length;
    btn.disabled = checked === 0;
});

document.body.addEventListener("htmx:afterRequest", function(evt) {
    var btn = evt.detail.elt.querySelector("button[type='submit']");
    if (btn) btn.removeAttribute("aria-busy");
});

/* Render markdown in content loaded via htmx (history pagination) */
document.body.addEventListener("htmx:afterSettle", function() {
    renderAllMarkdown();
});
