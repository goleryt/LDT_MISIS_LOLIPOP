import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  timeout: 30000,
  use: { baseURL: process.env.BASE_URL ?? "http://127.0.0.1:8080", headless: true,
    screenshot: "only-on-failure", trace: "retain-on-failure" },
  projects: [
    { name: "chrome", use: { channel: "chrome" } },
    ...(process.env.YANDEX_BROWSER_PATH ? [{ name: "yandex", use: { launchOptions: { executablePath: process.env.YANDEX_BROWSER_PATH } } }] : []),
  ],
  reporter: [["list"], ["json", { outputFile: "test-results/browser-results.json" }]],
});
