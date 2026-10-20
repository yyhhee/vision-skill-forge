import { defineConfig } from "@playwright/test";
import { testOrigin } from "./tests/testOrigin";
const qaRoot = process.env.VSF_QA_DIR ?? "qa/editor-flow/test-run";
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  workers: 2,
  retries: 0,
  reporter: [
    ["list"],
    ["json", { outputFile: `${qaRoot}/functional-results.json` }],
    ["html", { outputFolder: `${qaRoot}/playwright-report`, open: "never" }],
  ],
  outputDir: `${qaRoot}/test-artifacts`,
  use: {
    baseURL: testOrigin,
    viewport: { width: 1513, height: 1040 },
    deviceScaleFactor: 1,
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    colorScheme: "light",
    reducedMotion: "reduce",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: process.env.VSF_CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.VSF_CHROMIUM_EXECUTABLE }
      : {},
  },
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${new URL(testOrigin).port || "80"} --strictPort`,
    url: testOrigin,
    reuseExistingServer: process.env.VSF_REQUIRE_OWN_SERVER !== "1",
    timeout: 30000,
  },
  projects: [{ name: "isolated-chromium", use: { browserName: "chromium" } }],
});
