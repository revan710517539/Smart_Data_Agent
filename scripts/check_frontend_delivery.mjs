import assert from "node:assert/strict";
import { readdir, readFile, stat } from "node:fs/promises";
import { join, resolve } from "node:path";
import { brotliDecompressSync, gunzipSync } from "node:zlib";

const root = resolve(process.argv[2] || "dist");
const compressibleExtensions = new Set([".css", ".html", ".js", ".json", ".mjs", ".svg"]);
const minimumBytes = 512;

async function walk(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  return (await Promise.all(entries.map(async (entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return walk(path);
    return [path];
  }))).flat();
}

const indexHtml = await readFile(join(root, "index.html"), "utf8");
assert.doesNotMatch(indexHtml, /modulepreload[^>]+(?:charts|pdfExport)/i, "large optional chunks must not preload from index.html");

let checked = 0;
for (const path of await walk(root)) {
  const details = await stat(path);
  const extension = path.slice(path.lastIndexOf(".")).toLowerCase();
  if (details.size < minimumBytes || !compressibleExtensions.has(extension)) continue;
  const source = await readFile(path);
  const brotli = await readFile(`${path}.br`);
  const gzip = await readFile(`${path}.gz`);
  assert.deepEqual(brotliDecompressSync(brotli), source, `${path}.br must decode to the original asset`);
  assert.deepEqual(gunzipSync(gzip), source, `${path}.gz must decode to the original asset`);
  checked += 1;
}
assert.ok(checked > 0, "expected at least one precompressed frontend asset");
console.log(`Verified deferred optional chunks and ${checked} compressed frontend assets`);
