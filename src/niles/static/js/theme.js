/* Apply saved dark mode immediately to prevent flash of white */
var t = localStorage.getItem("niles_theme");
if (t === "dark") document.documentElement.classList.add("dark");
