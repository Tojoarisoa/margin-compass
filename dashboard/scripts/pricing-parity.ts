// EV-12 (browser side): the TypeScript pricing engine must match every shared calc-spec vector exactly.
// Run with: npm run parity (Node strips the types; no extra dependency).
import { readFileSync } from "node:fs";
import { isDeepStrictEqual } from "node:util";
import { pricePlan } from "../src/pricing.ts";

const vectors = JSON.parse(readFileSync(new URL("../../calc-spec/vectors/pricing_v1.json", import.meta.url), "utf8"));
let failed = 0;
for (const v of vectors) {
  const got = pricePlan(v.input);
  if (!isDeepStrictEqual(got, v.expected)) {
    failed++;
    console.error(`FAIL ${v.name}\n  got      ${JSON.stringify(got)}\n  expected ${JSON.stringify(v.expected)}`);
  }
}
if (vectors.length < 8) throw new Error("expected at least 8 vectors");
if (failed) process.exit(1);
console.log(`pricing parity: ${vectors.length} vectors match`);
