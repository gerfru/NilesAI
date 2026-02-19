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

    /* Hide thinking indicator */
    if (evt.detail.elt.id === "chat-form") {
        var indicator = document.getElementById("thinking-indicator");
        if (indicator) indicator.style.display = "none";
    }
});
