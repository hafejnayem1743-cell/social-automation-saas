(function(){
  const role =
    sessionStorage.getItem("nbsa_access_role") ||
    localStorage.getItem("nbsa_access_role") ||
    "";

  const allowed = role === "admin" || role === "user";
  const path = location.pathname.toLowerCase();

  window.NBSA_ACCESS_ROLE = role;

  window.NBSA_LOCK = function(){
    sessionStorage.clear();
    localStorage.removeItem("nbsa_access_role");
    localStorage.removeItem("nbsa_access");
    location.replace("./index.html?v=" + Date.now());
  };

  if (/\/(login|register|forgot|reset)(\.html)?$/i.test(path)) {
    location.replace("./index.html?v=" + Date.now());
    return;
  }

  if (path.endsWith("/dashboard.html") && !allowed) {
    location.replace("./index.html?v=" + Date.now());
    return;
  }

  if (path.endsWith("/dashboard.html") && allowed) {
    document.addEventListener("DOMContentLoaded",function(){
      const bar=document.createElement("div");
      bar.className="nbsa-access-bar";
      bar.style.cssText=
        "position:fixed;top:8px;right:8px;z-index:99999;padding:8px 10px;"+
        "border:1px solid rgba(0,255,100,.3);border-radius:8px;"+
        "background:rgba(0,10,5,.9);color:#75c88f;font:10px monospace;"+
        "letter-spacing:.08em";
      bar.innerHTML="ACCESS: "+role.toUpperCase()+
        ' <button id="nbsaLock" style="margin-left:8px;background:transparent;color:#74c991;border:1px solid rgba(0,255,100,.25);border-radius:5px;padding:4px 7px">LOCK</button>';
      document.body.appendChild(bar);
      document.getElementById("nbsaLock").onclick=window.NBSA_LOCK;
    });
  }
})();
