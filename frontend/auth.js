(function(){
  "use strict";

  const host=location.hostname;
  const local=host==="127.0.0.1"||host==="localhost";

  // Local development uses the Python API.
  // Production is same-origin /api so it can later sit behind a public API proxy.
  const API_BASE=(window.NBSA_API_BASE||(
    local ? "http://127.0.0.1:8000/api" : "/api"
  )).replace(/\/$/,"");

  function $(id){return document.getElementById(id)}

  function showMessage(message,type="error"){
    const box=$("message");
    if(!box)return;
    box.textContent=message;
    box.className="message show "+(type==="success"?"success":"error");
  }

  function clearMessage(){
    const box=$("message");
    if(!box)return;
    box.textContent="";
    box.className="message";
  }

  async function api(path,options){
    let res;

    try{
      res=await fetch(API_BASE+path,Object.assign({
        headers:{"Content-Type":"application/json"}
      },options||{}));
    }catch(_){
      throw new Error(
        local
          ? "Local backend is offline. Start the NBSA backend and try again."
          : "NBSA API is not connected to this live website yet."
      );
    }

    const data=await res.json().catch(()=>({}));

    if(!res.ok){
      throw new Error(
        data.detail||
        data.error||
        data.message||
        "Request failed"
      );
    }

    return data;
  }

  function setupPasswords(){
    document.querySelectorAll("[data-password-toggle]").forEach(btn=>{
      btn.addEventListener("click",()=>{
        const id=btn.getAttribute("data-password-toggle");
        const input=$(id);
        if(!input)return;

        const isPassword=input.type==="password";
        input.type=isPassword?"text":"password";
        btn.textContent=isPassword?"Hide":"Show";
      });
    });
  }

  async function checkApi(){
    const dot=$("apiDot");
    const text=$("apiText");
    if(!dot||!text)return;

    try{
      let base=API_BASE;
      let url;

      if(base.endsWith("/api")){
        url=base.slice(0,-4)+"/health";
      }else{
        url=base+"/health";
      }

      const res=await fetch(url,{cache:"no-store"});

      if(res.ok){
        dot.className="apiDot online";
        text.textContent="API online";
      }else{
        dot.className="apiDot offline";
        text.textContent="API unavailable";
      }
    }catch(_){
      dot.className="apiDot offline";
      text.textContent=local
        ?"Local API offline"
        :"Live API not connected";
    }
  }

  function go(path){
    location.href=path;
  }

  async function login(){
    const form=$("loginForm");
    if(!form)return;

    form.addEventListener("submit",async e=>{
      e.preventDefault();
      clearMessage();

      const email=$("email").value.trim();
      const password=$("password").value;

      if(!email||!password){
        showMessage("Enter your email and password.");
        return;
      }

      const btn=$("submitBtn");
      btn.disabled=true;
      btn.textContent="Signing in...";

      try{
        const data=await api("/auth/login",{
          method:"POST",
          body:JSON.stringify({email,password})
        });

        const token=data.token||data.access_token;

        if(!token){
          throw new Error("Login succeeded but no session token was returned.");
        }

        localStorage.setItem("nbsa_token",token);
        showMessage("Login successful. Opening dashboard...","success");

        setTimeout(()=>go("./dashboard.html"),250);
      }catch(err){
        showMessage(err.message);
      }finally{
        btn.disabled=false;
        btn.textContent="Sign in";
      }
    });
  }

  async function register(){
    const form=$("registerForm");
    if(!form)return;

    form.addEventListener("submit",async e=>{
      e.preventDefault();
      clearMessage();

      const email=$("email").value.trim();
      const password=$("password").value;
      const confirm=$("confirmPassword").value;

      if(!email||!password||!confirm){
        showMessage("Complete all required fields.");
        return;
      }

      if(password.length<8){
        showMessage("Password must be at least 8 characters.");
        return;
      }

      if(password!==confirm){
        showMessage("Passwords do not match.");
        return;
      }

      const btn=$("submitBtn");
      btn.disabled=true;
      btn.textContent="Creating account...";

      try{
        await api("/auth/register",{
          method:"POST",
          body:JSON.stringify({email,password})
        });

        showMessage(
          "Account created successfully. Redirecting to sign in...",
          "success"
        );

        setTimeout(()=>go("./login.html"),600);
      }catch(err){
        showMessage(err.message);
      }finally{
        btn.disabled=false;
        btn.textContent="Create account";
      }
    });
  }

  async function forgot(){
    const form=$("forgotForm");
    if(!form)return;

    form.addEventListener("submit",async e=>{
      e.preventDefault();
      clearMessage();

      const email=$("email").value.trim();

      if(!email){
        showMessage("Enter your account email.");
        return;
      }

      const btn=$("submitBtn");
      btn.disabled=true;
      btn.textContent="Sending...";

      try{
        const data=await api("/auth/forgot-password",{
          method:"POST",
          body:JSON.stringify({email})
        });

        showMessage(
          data.reset_link
            ? "Reset link created. Opening reset page..."
            : (data.message||"If the account exists, reset instructions were created."),
          "success"
        );

        if(data.reset_link){
          setTimeout(()=>go(data.reset_link),500);
        }
      }catch(err){
        showMessage(err.message);
      }finally{
        btn.disabled=false;
        btn.textContent="Send reset link";
      }
    });
  }

  async function reset(){
    const form=$("resetForm");
    if(!form)return;

    const urlToken=new URLSearchParams(location.search).get("token");
    if(urlToken&&$("token"))$("token").value=urlToken;

    form.addEventListener("submit",async e=>{
      e.preventDefault();
      clearMessage();

      const token=$("token").value.trim();
      const password=$("password").value;
      const confirm=$("confirmPassword").value;

      if(!token||!password||!confirm){
        showMessage("Complete all required fields.");
        return;
      }

      if(password.length<8){
        showMessage("Password must be at least 8 characters.");
        return;
      }

      if(password!==confirm){
        showMessage("Passwords do not match.");
        return;
      }

      const btn=$("submitBtn");
      btn.disabled=true;
      btn.textContent="Resetting...";

      try{
        await api("/auth/reset-password",{
          method:"POST",
          body:JSON.stringify({token,password})
        });

        localStorage.removeItem("nbsa_token");

        showMessage(
          "Password reset successful. Redirecting to sign in...",
          "success"
        );

        setTimeout(()=>go("./login.html"),700);
      }catch(err){
        showMessage(err.message);
      }finally{
        btn.disabled=false;
        btn.textContent="Reset password";
      }
    });
  }

  setupPasswords();
  login();
  register();
  forgot();
  reset();
  checkApi();
})();
