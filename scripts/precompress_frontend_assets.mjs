import { readdir, readFile, stat, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { brotliCompressSync, constants, gzipSync } from "node:zlib";

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

function shouldCompress(path, size) {
  const extension = path.slice(path.lastIndexOf(".")).toLowerCase();
  return size >= minimumBytes && compressibleExtensions.has(extension) && !path.endsWith(".br") && !path.endsWith(".gz");
}

const files = await walk(root);
let compressedCount = 0;
for (const path of files) {
  const details = await stat(path);
  if (!shouldCompress(path, details.size)) continue;
  const source = await readFile(path);
  const brotli = brotliCompressSync(source, {
    params: { [constants.BROTLI_PARAM_QUALITY]: 11 },
  });
  const gzip = gzipSync(source, { level: 9 });
  if (brotli.length < source.length) await writeFile(`${path}.br`, brotli);
  if (gzip.length < source.length) await writeFile(`${path}.gz`, gzip);
  compressedCount += 1;
}
console.log(`Precompressed ${compressedCount} frontend assets in ${root}`);
