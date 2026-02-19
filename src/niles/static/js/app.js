/* Scroll chat to bottom */
function scrollChat() {
    var el = document.getElementById("chat-messages");
    if (el) el.scrollTop = el.scrollHeight;
}

/* Read a cookie value by name */
function getCookie(name) {
    var match = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
    return match ? decodeURIComponent(match[2]) : "";
}

/* Auto-scroll on page load */
document.addEventListener("DOMContentLoaded", scrollChat);

/* CSRF: include token header on every htmx request (#2) */
document.body.addEventListener("htmx:configRequest", function(evt) {
    var token = getCookie("niles_csrf");
    if (token) {
        evt.detail.headers["X-CSRF-Token"] = token;
    }
});

/* Thinking indicator (#15) + loading aria-busy on submit buttons */
document.body.addEventListener("htmx:beforeRequest", function(evt) {
    var btn = evt.detail.elt.querySelector("button[type='submit']");
    if (btn) btn.setAttribute("aria-busy", "true");

    /* Show thinking indicator for chat form */
    if (evt.detail.elt.id === "chat-form") {
        var indicator = document.getElementById("thinking-indicator");
        if (indicator) indicator.style.display = "block";
        scrollChat();
    }
});

/* Feature flag toggles -- update hidden value and submit form (CSP-safe, no eval) */
document.body.addEventListener("change", function(evt) {
    if (!evt.target.hasAttribute("data-flag-toggle")) return;
    var form = evt.target.closest("form");
    var hidden = form.querySelector("input[type='hidden']");
    hidden.value = evt.target.checked ? "true" : "false";
    htmx.trigger(form, "submit");
});

document.body.addEventListener("htmx:afterRequest", function(evt) {
    var btn = evt.detail.elt.querySelector("button[type='submit']");
    if (btn) btn.removeAttribute("aria-busy");

    /* Hide thinking indicator */
    if (evt.detail.elt.id === "chat-form") {
        var indicator = document.getElementById("thinking-indicator");
        if (indicator) indicator.style.display = "none";
    }
});
