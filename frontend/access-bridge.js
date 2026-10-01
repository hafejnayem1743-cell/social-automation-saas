(function(){
  const role =
    sessionStorage.getItem("nbsa_access_role") ||
    localStorage.getItem("nbsa_access_role") ||
    "";

  if (location.pathname.toLowerCase().endsWith("/dashboard.html")) {
    if (role !== "admin" && role !== "user") {
      location.replace("./index.html?locked=1");
      return;
    }
  }

  window.NBSA_ACCESS_ROLE = role;
  window.NBSA_SHARED_MODE = true;

  /* Keep the old dashboard alive without its old server-login requirement. */
  const realFetch = window.fetch.bind(window);

  window.fetch = async function(input, init) {
    let url = "";
    try {
      url = typeof input === "string" ? input : input.url;
    } catch (_) {}

    const isApi = url.includes("/api/");
    const isMe = /\/api\/me(?:\?|$)/.test(url);

    if (isMe && (role === "admin" || role === "user")) {
      const body = {
        ok: true,
        authenticated: true,
        id: role === "admin" ? "admin" : "public-user",
        user_id: role === "admin" ? "admin" : "public-user",
        email: role === "admin" ? "admin@nbsa.local" : "user@nbsa.local",
        role: role,
        tenant_id: role === "admin" ? "admin" : "public",
        is_active: true
      };

      return new Response(JSON.stringify(body), {
        status: 200,
        headers: {"Content-Type":"application/json"}
      });
    }

    const response = await realFetch(input, init);

    /* Do not let the old frontend kick the user back to login on API 401. */
    if (isApi && response.status === 401) {
      const text = await response.text();
      return new Response(
        text || JSON.stringify({
          ok:false,
          authenticated:false,
          error:"Shared password mode"
        }),
        {
          status: 200,
          headers: {"Content-Type":"application/json"}
        }
      );
    }

    return response;
  };

  document.addEventListener("DOMContentLoaded", function(){
    if (!role) return;

    const badge = document.createElement("div");
    badge.textContent = "NBSA // " + role.toUpperCase();

    badge.style.cssText =
      "position:fixed;top:8px;right:8px;z-index:2147483647;" +
      "padding:8px 12px;border:1px solid rgba(0,255,100,.35);" +
      "border-radius:8px;background:rgba(0,8,4,.94);" +
      "color:#65ff9a;font:700 10px monospace;letter-spacing:.1em;" +
      "box-shadow:0 0 18px rgba(0,255,100,.12)";

    document.body.appendChild(badge);
  });
})();
