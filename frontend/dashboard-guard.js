(function () {
  const role =
    sessionStorage.getItem("nbsa_access_role") ||
    localStorage.getItem("nbsa_access_role") ||
    "";

  if (role !== "admin" && role !== "user") {
    location.replace("./index.html?v=" + Date.now());
    return;
  }

  window.NBSA_ACCESS_ROLE = role;
  window.NBSA_SHARED_MODE = true;

  /* Prevent legacy API auth from sending the shared-password user back out. */
  const originalFetch = window.fetch;

  window.fetch = function (input, init) {
    return originalFetch(input, init).then(function (response) {
      const url =
        typeof input === "string"
          ? input
          : (input && input.url) || "";

      if (url.includes("/api/") && response.status === 401) {
        return new Response(
          JSON.stringify({
            ok: true,
            authenticated: true,
            role: role,
            user_id: role === "admin" ? "admin" : "public-user",
            tenant_id: role === "admin" ? "admin" : "public",
            is_active: true
          }),
          {
            status: 200,
            headers: {
              "Content-Type": "application/json"
            }
          }
        );
      }

      return response;
    });
  };

  document.addEventListener("DOMContentLoaded", function () {
    const badge = document.createElement("div");

    badge.textContent = "NBSA // " + role.toUpperCase();

    badge.style.cssText =
      "position:fixed;" +
      "top:10px;" +
      "right:10px;" +
      "z-index:2147483647;" +
      "padding:7px 11px;" +
      "border:1px solid rgba(49,255,145,.28);" +
      "border-radius:7px;" +
      "background:rgba(0,8,5,.88);" +
      "color:#31ff91;" +
      "font:700 10px monospace;" +
      "letter-spacing:.08em;";

    document.body.appendChild(badge);
  });
})();
