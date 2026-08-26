import assert from "node:assert/strict";
import { browserExecutableVersion, resolveBrowserExecutable } from "./browser-executable.mjs";

const executable = (expected) => (candidate) => candidate === expected;

const explicit = resolveBrowserExecutable({
  env: { CHROME_PATH: "/custom/browser" },
  platform: "linux",
  isExecutable: executable("/custom/browser"),
  bundledCandidates: [{ path: "/bundled/chromium", source: "playwright:chromium" }],
  which: () => "/usr/bin/chromium",
});
assert.deepEqual(explicit, { path: "/custom/browser", source: "CHROME_PATH", platform: "linux" });

const bundled = resolveBrowserExecutable({
  env: {},
  platform: "linux",
  isExecutable: executable("/bundled/chromium"),
  bundledCandidates: [{ path: "/bundled/chromium", source: "playwright:chromium" }],
  which: () => "",
});
assert.equal(bundled.source, "playwright:chromium");

const linuxCommands = [];
const linux = resolveBrowserExecutable({
  env: {},
  platform: "linux",
  isExecutable: executable("/opt/bin/chromium-browser"),
  bundledCandidates: [],
  which: (command) => {
    linuxCommands.push(command);
    return command === "chromium-browser" ? "/opt/bin/chromium-browser" : "";
  },
});
assert.equal(linux.path, "/opt/bin/chromium-browser");
assert.deepEqual(linuxCommands, ["chromium-browser"]);

const mac = resolveBrowserExecutable({
  env: {},
  platform: "darwin",
  isExecutable: executable("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
  bundledCandidates: [],
  which: () => "",
});
assert.equal(mac.source, "darwin-standard-path");

const windows = resolveBrowserExecutable({
  env: {},
  platform: "win32",
  isExecutable: executable("C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"),
  bundledCandidates: [],
  which: () => "",
});
assert.equal(windows.source, "win32-standard-path");

assert.throws(
  () => resolveBrowserExecutable({ env: { CHROME_PATH: "/missing" }, platform: "linux", isExecutable: () => false }),
  /browser_executable_explicit_invalid.*CHROME_PATH/,
);
assert.throws(
  () => resolveBrowserExecutable({ env: {}, platform: "linux", isExecutable: () => false, bundledCandidates: [], which: () => "" }),
  /browser_executable_not_found.*chromium-browser.*pinned Playwright toolchain image/,
);
assert.equal(
  browserExecutableVersion("/browser", { run: () => ({ status: 0, stdout: "Chromium 140.0\n", stderr: "" }) }),
  "Chromium 140.0",
);

console.log("browser executable contract passed");
