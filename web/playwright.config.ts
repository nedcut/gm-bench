import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  // Run files concurrently while preserving test order within each file.
  workers: 2,
  reporter: [["list"], ["junit", { outputFile: "test-results/junit.xml" }]],
  use: {
    baseURL: "http://127.0.0.1:5178",
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {},
    trace: "retain-on-failure",
  },
  webServer: { command: "bun run build && bun run preview --host 127.0.0.1 --port 5178", url: "http://127.0.0.1:5178/replays/", reuseExistingServer: false },
});
