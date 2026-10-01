(() => {
  const token = localStorage.getItem("nbsa_token");
  if (!token) {
    location.replace("./index.html?auth=required");
    return;
  }

  window.NBSA_AUTH_TOKEN = token;

  window.NBSA_CLEAR_AUTH = () => {
    localStorage.removeItem("nbsa_token");
    location.replace("./index.html?auth=expired");
  };
})();
