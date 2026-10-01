import { defineConfig } from "vite";

export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        index: "index.html",
        login: "login.html",
        register: "register.html",
        forgot: "forgot.html",
        reset: "reset.html",
        dashboard: "dashboard.html"
      }
    }
  }
});
