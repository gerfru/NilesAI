/* Scroll chat to bottom */
function scrollChat() {
    var el = document.getElementById("chat-messages");
    if (el) el.scrollTop = el.scrollHeight;
}

/* Auto-scroll on page load */
document.addEventListener("DOMContentLoaded", scrollChat);

/* Loading indicator via aria-busy on submit buttons */
document.body.addEventListener("htmx:beforeRequest", function(evt) {
    var btn = evt.detail.elt.querySelector("button[type='submit']");
    if (btn) btn.setAttribute("aria-busy", "true");
});

document.body.addEventListener("htmx:afterRequest", function(evt) {
    var btn = evt.detail.elt.querySelector("button[type='submit']");
    if (btn) btn.removeAttribute("aria-busy");
});
