(() => {
  const token = localStorage.getItem("nbsa_token");

  if (!token) {
    location.replace("./index.html?auth=required");
    return;
  }

  window.NBSA_AUTH_TOKEN = token;
})();
