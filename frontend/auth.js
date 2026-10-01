(function(){
  "use strict";

  const localHost =
    location.hostname==="127.0.0.1" ||
    location.hostname==="localhost";

  const API_BASE=(
    window.NBSA_API_BASE ||
    (localHost ? "http://127.0.0.1:8000/api" : "/api")
  ).replace(/\/$/,"");

  const $=id=>document.getElementById(id);

  function showMessage(message,type="error"){
    const box=$("message");
    if(!box)return;
    box.textContent=message;
    box.className="message show "+(
      type==="success" ? "success" : "error"
    );
  }

  function clearMessage(){
    const box=$("message");
    if(!box)return;
    box.textContent="";
    box.className="message";
  }

  async function api(path,options={}){
    let res;

    try{
      res=await fetch(
        API_BASE+path,
        Object.assign(
          {
            cache:"no-store",
            headers:{"Content-Type":"application/json"}
          },
          options
        )
      );
    }catch(_){
      throw new Error(
        localHost
          ? "The local NBSA server is offline. Start the backend first."
          : "The live NBSA API is not connected yet."
      );
    }

    const data=await res.json().catch(()=>({}));

    if(!res.ok){
      throw new Error(
        data.detail ||
        data.error ||
        data.message ||
        "Request failed."
      );
    }

    return data;
  }

  function setupPasswords(){
    document.querySelectorAll("[data-password-toggle]").forEach(btn=>{
      btn.addEventListener("click",()=>{
        const input=$(btn.dataset.passwordToggle);
        if(!input)return;

        const show=input.type==="password";
        input.type=show?"text":"password";
        btn.textContent=show?"Hide":"Show";
        input.focus();
      });
    });
  }

  async function checkApi(){
    const dot=$("apiDot");
    const text=$("apiText");
    if(!dot||!text)return;

    try{
      const healthUrl=API_BASE.endsWith("/api")
        ? API_BASE.slice(0,-4)+"/health"
        : API_BASE+"/health";

      const res=await fetch(healthUrl,{cache:"no-store"});

      if(res.ok){
        dot.className="apiDot online";
        text.textContent="API online";
      }else{
        dot.className="apiDot offline";
        text.textContent="API unavailable";
      }
    }catch(_){
      dot.className="apiDot offline";
      text.textContent=localHost
        ? "Local API offline"
        : "Live API not connected";
    }
  }

  function bindLogin(){
    const form=$("loginForm");
    if(!form)return;

    form.addEventListener("submit",async e=>{
      e.preventDefault();
      clearMessage();

      const email=$("email")?.value.trim()||"";
      const password=$("password")?.value||"";

      if(!email){
        showMessage("Enter your email.");
        $("email")?.focus();
        return;
      }

      if(!password){
        showMessage("Enter your password.");
        $("password")?.focus();
        return;
      }

      const btn=$("submitBtn");
      if(btn){
        btn.disabled=true;
        btn.textContent="Signing in...";
      }

      try{
        const data=await api("/auth/login",{
          method:"POST",
          body:JSON.stringify({email,password})
        });

        const token=data.token||data.access_token;
        if(!token){
          throw new Error("Login response did not contain a session token.");
        }

        localStorage.setItem("nbsa_token",token);
        showMessage(
          "Signed in successfully. Opening your workspace...",
          "success"
        );

        setTimeout(()=>{
          location.replace("./dashboard.html");
        },300);
      }catch(err){
        showMessage(err.message);
      }finally{
        if(btn){
          btn.disabled=false;
          btn.textContent="Sign in";
        }
      }
    });
  }

  function bindRegister(){
    const form=$("registerForm");
    if(!form)return;

    form.addEventListener("submit",async e=>{
      e.preventDefault();
      clearMessage();

      const email=$("email")?.value.trim()||"";
      const password=$("password")?.value||"";
      const confirm=$("confirmPassword")?.value||"";

      if(!email){
        showMessage("Enter your email.");
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
      if(btn){
        btn.disabled=true;
        btn.textContent="Creating account...";
      }

      try{
        await api("/auth/register",{
          method:"POST",
          body:JSON.stringify({email,password})
        });

        showMessage(
          "Your account was created. Redirecting to sign in...",
          "success"
        );

        setTimeout(()=>location.replace("./login.html"),700);
      }catch(err){
        showMessage(err.message);
      }finally{
        if(btn){
          btn.disabled=false;
          btn.textContent="Create account";
        }
      }
    });
  }

  function bindForgot(){
    const form=$("forgotForm");
    if(!form)return;

    form.addEventListener("submit",async e=>{
      e.preventDefault();
      clearMessage();

      const email=$("email")?.value.trim()||"";
      if(!email){
        showMessage("Enter your account email.");
        return;
      }

      const btn=$("submitBtn");
      if(btn){
        btn.disabled=true;
        btn.textContent="Creating reset link...";
      }

      try{
        const data=await api("/auth/forgot-password",{
          method:"POST",
          body:JSON.stringify({email})
        });

        if(data.reset_link){
          showMessage(
            "Reset link created. Opening secure reset page...",
            "success"
          );
          setTimeout(
            ()=>location.replace(data.reset_link),
            500
          );
        }else{
          showMessage(
            data.message||
            "If the account exists, reset instructions were created.",
            "success"
          );
        }
      }catch(err){
        showMessage(err.message);
      }finally{
        if(btn){
          btn.disabled=false;
          btn.textContent="Send reset link";
        }
      }
    });
  }

  function bindReset(){
    const form=$("resetForm");
    if(!form)return;

    const token=
      new URLSearchParams(location.search).get("token");

    if(token&&$("token")){
      $("token").value=token;
    }

    form.addEventListener("submit",async e=>{
      e.preventDefault();
      clearMessage();

      const resetToken=$("token")?.value.trim()||"";
      const password=$("password")?.value||"";
      const confirm=$("confirmPassword")?.value||"";

      if(!resetToken){
        showMessage("Enter your reset token.");
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
      if(btn){
        btn.disabled=true;
        btn.textContent="Resetting password...";
      }

      try{
        await api("/auth/reset-password",{
          method:"POST",
          body:JSON.stringify({
            token:resetToken,
            password
          })
        });

        localStorage.removeItem("nbsa_token");

        showMessage(
          "Password reset successfully. Returning to sign in...",
          "success"
        );

        setTimeout(()=>location.replace("./login.html"),800);
      }catch(err){
        showMessage(err.message);
      }finally{
        if(btn){
          btn.disabled=false;
          btn.textContent="Reset password";
        }
      }
    });
  }

  setupPasswords();
  bindLogin();
  bindRegister();
  bindForgot();
  bindReset();
  checkApi();
})();
