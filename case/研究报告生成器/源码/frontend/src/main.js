import { createApp } from "vue";
import App from "./App.vue";
import "./styles/global.css";

window.__RESEARCH_APP_BOOTED__ = true;

try {
  createApp(App).mount("#app");
} catch (error) {
  console.error("Vue mount failed", error);
  const mount = document.querySelector("#app");
  if (mount) {
    mount.innerHTML = `
      <main style="font-family: system-ui; padding: 32px; color: #202523">
        <h1>前端加载失败</h1>
        <p>请查看浏览器控制台或重新运行 npm run build。</p>
      </main>
    `;
  }
}
