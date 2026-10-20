import { defineConfig } from "@playwright/test";
const baseURL=process.env.BASE_URL ?? "http://127.0.0.1:8080";
const allowLocalTestCertificate=process.env.ALLOW_SELF_SIGNED_TLS==="true"
  && ["127.0.0.1","localhost","[::1]"].includes(new URL(baseURL).hostname);
export default defineConfig({
  testDir: "./e2e",
  timeout: 30000,
  use: { baseURL, headless: true, ignoreHTTPSErrors:allowLocalTestCertificate,
    screenshot: "only-on-failure", trace: "retain-on-failure" },
  projects: [
    { name: "chrome", use: { channel: "chrome" } },
    ...(process.env.YANDEX_BROWSER_PATH ? [{ name: "yandex", use: { launchOptions: { executablePath: process.env.YANDEX_BROWSER_PATH } } }] : []),
  ],
  reporter: [["list"], ["json", { outputFile: "test-results/browser-results.json" }]],
});
