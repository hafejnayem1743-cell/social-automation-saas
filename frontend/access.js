(function () {
  const role =
    sessionStorage.getItem("nbsa_access_role") ||
    localStorage.getItem("nbsa_access_role") ||
    "";

  window.NBSA_ACCESS_ROLE = role;
  window.NBSA_LOCK = function () {
    sessionStorage.removeItem("nbsa_access_role");
    sessionStorage.removeItem("nbsa_access_at");
    localStorage.removeItem("nbsa_access_role");
    localStorage.removeItem("nbsa_access_at");
    window.location.replace("./index.html");
  };

  const path = location.pathname.toLowerCase();

  if (/\/(login|register|forgot|reset)(\.html)?$/.test(path)) {
    window.location.replace("./index.html");
    return;
  }

  if (path.endsWith("/dashboard.html")) {
    if (!role) {
      window.location.replace("./index.html");
      return;
    }

    document.addEventListener("DOMContentLoaded", function () {
      const bar = document.createElement("div");
      bar.className = "locked-bar";
      bar.innerHTML =
        '<span>NBSA // ACCESS <b>' +
        role.toUpperCase() +
        '</b></span>' +
        '<button class="exit-btn" type="button">LOCK</button>';

      document.body.prepend(bar);
      bar.querySelector(".exit-btn").addEventListener("click", window.NBSA_LOCK);
    });
  }
})();
