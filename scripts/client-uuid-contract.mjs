import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { createClientUuid } from "../src/app/utils/clientUuid.ts";

assert.equal(
  createClientUuid({
    randomUUID: () => "11111111-1111-4111-8111-111111111111",
    getRandomValues: (values) => values,
  }),
  "11111111-1111-4111-8111-111111111111",
);

const insecureHttpCrypto = {
  getRandomValues(values) {
    values.fill(0);
    return values;
  },
};
assert.equal(createClientUuid(insecureHttpCrypto), "00000000-0000-4000-8000-000000000000");
assert.match(createClientUuid(null), /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);

const sourceRoot = new URL("../src/app", import.meta.url).pathname;
const directCallViolations = [];
const visit = (directory) => {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) visit(path);
    if (!entry.isFile() || !/\.(ts|tsx)$/.test(entry.name) || entry.name === "clientUuid.ts") continue;
    if (/\bcrypto(?:Api)?\.randomUUID\s*\(/.test(readFileSync(path, "utf8"))) {
      directCallViolations.push(relative(sourceRoot, path));
    }
  }
};
visit(sourceRoot);
assert.deepEqual(directCallViolations, []);

console.log("客户端 UUID 兼容契约通过（randomUUID / insecure HTTP / legacy fallback）");
