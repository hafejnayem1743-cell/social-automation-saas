(() => {
  const token = localStorage.getItem("nbsa_token");
  if (!token) return;
  window.NBSA_AUTH_TOKEN = token;
})();
