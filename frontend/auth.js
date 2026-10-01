const API="http://127.0.0.1:8000";

const $=(s,r=document)=>r.querySelector(s);

async function api(path,opt={}){
  const headers={...(opt.headers||{})};
  if(opt.body)headers["Content-Type"]="application/json";
  const r=await fetch(API+path,{...opt,headers});
  const text=await r.text();
  let d={};
  try{d=text?JSON.parse(text):{}}catch{d={detail:text||"Invalid response"}}
  if(!r.ok)throw new Error(d.detail||d.message||`HTTP ${r.status}`);
  return d;
}

function show(id,msg){
  const x=$("#"+id);if(x)x.textContent=msg;
}

function togglePassword(id,btn){
  const x=$("#"+id);
  if(!x)return;
  x.type=x.type==="password"?"text":"password";
  btn.textContent=x.type==="password"?"Show":"Hide";
}

function authShell(title,sub,form,links){
 return `<div class="auth-shell"><div class="auth-card">
 <div class="brand">
   <div class="mark">NB</div>
   <div class="brand-text"><strong>NBSA</strong><span>SOCIAL AUTOMATION</span></div>
 </div>
 <h1>${title}</h1><p class="sub">${sub}</p>
 ${form}${links}
 </div></div>`;
}

const passwordField=(name,id,label)=>`
<div class="field"><label>${label}</label>
 <div class="input-wrap">
  <input id="${id}" name="${name}" type="password" required>
  <button type="button" class="show" onclick="togglePassword('${id}',this)">Show</button>
 </div>
</div>`;

function loginPage(){
 document.body.innerHTML=authShell(
 "Welcome back",
 "Sign in to your NBSA workspace.",
 `<form id="loginForm">
    <div class="field"><label>Email</label><input name="email" type="email" required autocomplete="email" placeholder="you@example.com"></div>
    ${passwordField("password","loginPassword","Password")}
    <button class="main-btn">Sign in</button>
    <p id="error" class="error"></p>
  </form>
  <div class="links">
    <a href="/forgot.html">Forgot password?</a>
    <a href="/register.html">Create account</a>
  </div>`,
 ""
 );

 $("#loginForm").addEventListener("submit",async e=>{
  e.preventDefault();show("error","");
  try{
   const f=new FormData(e.target);
   const d=await api("/api/auth/login",{
    method:"POST",
    body:JSON.stringify({email:f.get("email"),password:f.get("password")})
   });
   localStorage.setItem("nbsa_token",d.token);
   location.href="/dashboard.html";
  }catch(x){show("error",x.message)}
 });
}

function registerPage(){
 document.body.innerHTML=authShell(
 "Create your workspace",
 "Start your social automation workspace.",
 `<form id="registerForm">
    <div class="field"><label>Email</label><input name="email" type="email" required autocomplete="email" placeholder="you@example.com"></div>
    ${passwordField("password","registerPassword","Password")}
    ${passwordField("confirm","confirmPassword","Confirm password")}
    <div class="notice">Use at least 8 characters. Your password is stored as a hash on the server.</div>
    <button class="main-btn">Create account</button>
    <p id="error" class="error"></p>
  </form>
  <div class="links">
    <a href="/login.html">Already have an account?</a>
  </div>`,
 ""
 );

 $("#registerForm").addEventListener("submit",async e=>{
  e.preventDefault();show("error","");
  const f=new FormData(e.target);
  if(f.get("password")!==f.get("confirm")){
   show("error","Passwords do not match.");return;
  }
  try{
   await api("/api/auth/register",{
    method:"POST",
    body:JSON.stringify({email:f.get("email"),password:f.get("password")})
   });
   location.href="/login.html?registered=1";
  }catch(x){show("error",x.message)}
 });
}

function forgotPage(){
 document.body.innerHTML=authShell(
 "Forgot your password?",
 "Enter your account email and generate a secure reset link.",
 `<form id="forgotForm">
    <div class="field"><label>Email</label><input name="email" type="email" required autocomplete="email" placeholder="you@example.com"></div>
    <button class="main-btn">Generate reset link</button>
    <p id="message" class="success"></p>
    <p id="error" class="error"></p>
  </form>
  <div class="links"><a href="/login.html">Back to login</a><a href="/register.html">Create account</a></div>`,
 ""
 );

 $("#forgotForm").addEventListener("submit",async e=>{
  e.preventDefault();show("error","");show("message","");
  try{
   const f=new FormData(e.target);
   const d=await api("/api/auth/forgot-password",{
    method:"POST",body:JSON.stringify({email:f.get("email")})
   });
   show("message",d.message||"Reset request processed.");

   if(d.reset_link){
    $("#message").insertAdjacentHTML("afterend",
      `<div class="notice"><b>Free-first local reset link</b><br>
      <span class="reset-link">${d.reset_link}</span><br><br>
      <button type="button" class="secondary" id="openReset">Open reset page</button></div>`
    );
    $("#openReset").onclick=()=>location.href=d.reset_link;
   }
  }catch(x){show("error",x.message)}
 });
}

function resetPage(){
 const token=new URLSearchParams(location.search).get("token")||"";

 document.body.innerHTML=authShell(
 "Set a new password",
 "Choose a new password for your NBSA account.",
 `<form id="resetForm">
    <div class="notice">${token?"Reset token detected. It expires in 30 minutes and can be used once.":"Reset token is missing."}</div>
    ${passwordField("password","newPassword","New password")}
    ${passwordField("confirm","newConfirm","Confirm password")}
    <button class="main-btn" ${token?"":"disabled"}>Reset password</button>
    <p id="message" class="success"></p>
    <p id="error" class="error"></p>
  </form>
  <div class="links"><a href="/login.html">Back to login</a></div>`,
 ""
 );

 $("#resetForm").addEventListener("submit",async e=>{
  e.preventDefault();show("error","");show("message","");
  if(!token){show("error","Invalid or missing reset token.");return}
  const f=new FormData(e.target);
  if(f.get("password")!==f.get("confirm")){
   show("error","Passwords do not match.");return;
  }
  try{
   const d=await api("/api/auth/reset-password",{
    method:"POST",
    body:JSON.stringify({token,password:f.get("password")})
   });
   show("message",d.message||"Password reset successful.");
   setTimeout(()=>location.href="/login.html?reset=1",900);
  }catch(x){show("error",x.message)}
 });
}

window.togglePassword=togglePassword;

const page=location.pathname.split("/").pop();
if(page==="register.html")registerPage();
else if(page==="forgot.html")forgotPage();
else if(page==="reset.html")resetPage();
else{
 loginPage();
 const q=new URLSearchParams(location.search);
 if(q.get("registered"))show("error","Account created. Please sign in.");
 if(q.get("reset"))show("error","Password changed. Please sign in.");
}
