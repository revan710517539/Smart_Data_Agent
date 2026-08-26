import { constants, accessSync } from "node:fs";
import { createRequire } from "node:module";
import { execFileSync, spawnSync } from "node:child_process";

const require = createRequire(import.meta.url);

const PLATFORM_CANDIDATES = {
  darwin: ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
  linux: [
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
  ],
  win32: [
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files\\Chromium\\Application\\chrome.exe",
  ],
};

const COMMAND_CANDIDATES = {
  darwin: ["google-chrome", "chromium"],
  linux: ["chromium-browser", "chromium", "google-chrome", "google-chrome-stable"],
  win32: ["chrome.exe", "chromium.exe"],
};

export function resolveBrowserExecutable(options = {}) {
  const env = options.env || process.env;
  const platform = options.platform || process.platform;
  const isExecutable = options.isExecutable || defaultIsExecutable;
  const which = options.which || ((command) => defaultWhich(command, platform));
  const bundled = options.bundledCandidates || resolveBundledCandidates();
  const explicit = String(env.CHROME_PATH || "").trim();
  if (explicit) {
    if (!isExecutable(explicit)) {
      throw new Error(`browser_executable_explicit_invalid path=${explicit}; set CHROME_PATH to an executable Chrome/Chromium binary`);
    }
    return { path: explicit, source: "CHROME_PATH", platform };
  }

  const checked = [];
  for (const candidate of bundled) {
    const path = String(candidate.path || "").trim();
    if (!path) continue;
    checked.push(path);
    if (isExecutable(path)) return { path, source: String(candidate.source || "bundled"), platform };
  }
  for (const path of PLATFORM_CANDIDATES[platform] || []) {
    checked.push(path);
    if (isExecutable(path)) return { path, source: `${platform}-standard-path`, platform };
  }
  for (const command of COMMAND_CANDIDATES[platform] || []) {
    const path = String(which(command) || "").trim();
    checked.push(path || `PATH:${command}`);
    if (path && isExecutable(path)) return { path, source: `${platform}-PATH:${command}`, platform };
  }
  throw new Error(
    `browser_executable_not_found platform=${platform}; checked=${checked.join(",") || "none"}; `
    + "set CHROME_PATH or run the release gate in the pinned Playwright toolchain image",
  );
}

export function browserExecutableVersion(executable, options = {}) {
  const run = options.run || ((path) => spawnSync(path, ["--version"], { encoding: "utf8", timeout: 10_000 }));
  const result = run(executable);
  if (Number(result?.status) !== 0) {
    throw new Error(`browser_version_probe_failed path=${executable} status=${String(result?.status)} error=${String(result?.stderr || "").trim()}`);
  }
  const version = String(result.stdout || result.stderr || "").trim();
  if (!version) throw new Error(`browser_version_probe_empty path=${executable}`);
  return version;
}

function resolveBundledCandidates() {
  const candidates = [];
  for (const packageName of ["playwright", "playwright-core"]) {
    try {
      const module = require(packageName);
      const path = module?.chromium?.executablePath?.();
      if (path) candidates.push({ path, source: `${packageName}:chromium` });
    } catch {
      // Optional release-toolchain dependency.
    }
  }
  try {
    const puppeteer = require("puppeteer");
    const path = puppeteer?.executablePath?.();
    if (path) candidates.push({ path, source: "puppeteer:chromium" });
  } catch {
    // Optional release-toolchain dependency.
  }
  return candidates;
}

function defaultIsExecutable(path) {
  try {
    accessSync(path, constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

function defaultWhich(command, platform) {
  try {
    return execFileSync(platform === "win32" ? "where" : "which", [command], { encoding: "utf8" })
      .split(/\r?\n/, 1)[0]
      .trim();
  } catch {
    return "";
  }
}
