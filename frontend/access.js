(() => {
  const ADMIN_HASH = "751fd3e87272d6e5084765a6d74a0178f6fffeb757b6f556f134ebb4b88f7149";
  const USER_HASH  = "a8c1b8aeede055d196481569fd2b8321789bbf620cc1cae644ec161ab24fbf05";
  const KEY = "nbsa_access_role";

  const sha256 = async (value) => {
    const data = new TextEncoder().encode(value);
    const digest = await crypto.subtle.digest("SHA-256", data);
    return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2,"0")).join("");
  };

  const setRole = role => {
    sessionStorage.setItem(KEY, role);
    sessionStorage.setItem("nbsa_access_at", new Date().toISOString());
    window.NBSA_ACCESS_ROLE = role;
  };

  const getRole = () => sessionStorage.getItem(KEY) || "";

  const clearRole = () => {
    sessionStorage.removeItem(KEY);
    sessionStorage.removeItem("nbsa_access_at");
    sessionStorage.removeItem("nbsa_token");
    sessionStorage.removeItem("token");
  };

  const lock = () => {
    clearRole();
    location.href = "./index.html";
  };

  window.NBSA_ACCESS_ROLE = getRole();
  window.NBSA_LOCK = lock;

  const path = location.pathname.toLowerCase();

  if (/\/(login|register|forgot|reset)(\.html)?$/.test(path)) {
    location.replace("./index.html");
    return;
  }

  if (path.endsWith("/dashboard.html")) {
    if (!getRole()) {
      location.replace("./index.html");
      return;
    }
    document.documentElement.dataset.nbsaRole = getRole();

    const bar = document.createElement("div");
    bar.className = "locked-bar";
    bar.innerHTML = `<span>NBSA // ACCESS <b>${getRole().toUpperCase()}</b></span><button class="exit-btn" type="button">LOCK</button>`;
    document.addEventListener("DOMContentLoaded", () => {
      document.body.prepend(bar);
      bar.querySelector(".exit-btn").addEventListener("click", lock);
      window.NBSA_ACCESS_ROLE = getRole();
    });
    return;
  }

  if (!path.endsWith("/index.html") && !path.endsWith("/")) return;

  const ready = () => {
    const form = document.getElementById("accessForm");
    const input = document.getElementById("accessPassword");
    const show = document.getElementById("showPassword");
    const msg = document.getElementById("accessMessage");

    if (!form || !input || !msg) return;

    if (show) {
      show.addEventListener("click", () => {
        const visible = input.type === "text";
        input.type = visible ? "password" : "text";
        show.textContent = visible ? "SHOW" : "HIDE";
      });
    }

    form.addEventListener("submit", async e => {
      e.preventDefault();
      const password = input.value;
      msg.className = "message";
      msg.textContent = "";
      if (!password) {
        msg.className = "message error";
        msg.textContent = "PASSWORD REQUIRED";
        return;
      }

      const button = form.querySelector("button[type=submit]");
      if (button) button.disabled = true;

      try {
        const hash = await sha256(password);
        let role = "";
        if (hash === ADMIN_HASH) role = "admin";
        else if (hash === USER_HASH) role = "user";

        if (!role) {
          msg.className = "message error";
          msg.textContent = "ACCESS DENIED // INVALID PASSWORD";
          input.select();
          return;
        }

        setRole(role);
        msg.className = "message ok";
        msg.textContent = `ACCESS GRANTED // ${role.toUpperCase()}`;
        setTimeout(() => location.href = "./dashboard.html", 250);
      } catch {
        msg.className = "message error";
        msg.textContent = "ACCESS SYSTEM ERROR";
      } finally {
        if (button) button.disabled = false;
      }
    });
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready);
  else ready();

  // Lightweight matrix rain
  const bootMatrix = () => {
    const canvas = document.getElementById("matrix");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const chars = "01ABCDEFGHIJKLMNOPQRSTUVWXYZ#$%&<>[]{}";
    let drops = [];
    const resize = () => {
      const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
      canvas.width = innerWidth * dpr;
      canvas.height = innerHeight * dpr;
      canvas.style.width = innerWidth + "px";
      canvas.style.height = innerHeight + "px";
      ctx.setTransform(dpr,0,0,dpr,0,0);
      drops = Array.from({length:Math.ceil(innerWidth/14)}, () => Math.random()*-60);
    };
    const draw = () => {
      ctx.fillStyle = "rgba(0,4,2,.11)";
      ctx.fillRect(0,0,innerWidth,innerHeight);
      ctx.font = "12px monospace";
      ctx.fillStyle = "#00ff73";
      for(let i=0;i<drops.length;i++){
        const x = i*14;
        const y = drops[i]*14;
        ctx.fillText(chars[Math.floor(Math.random()*chars.length)],x,y);
        if(y>innerHeight && Math.random()>.975) drops[i]=0;
        drops[i]+=0.55;
      }
      requestAnimationFrame(draw);
    };
    addEventListener("resize", resize);
    resize();
    draw();
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bootMatrix);
  else bootMatrix();
})();
