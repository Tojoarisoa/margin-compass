// EV-12 (browser side): the TypeScript pricing engine and lever replay must match every shared calc-spec vector exactly.
// Run with: npm run parity (Node strips the types; no extra dependency).
import { readFileSync } from "node:fs";
import { isDeepStrictEqual } from "node:util";
import { pricePlan } from "../src/pricing.ts";
import { replayLever } from "../src/levers.ts";

let failed = 0;
function check(file: string, fn: (input: never) => unknown, minimum: number): void {
  const vectors = JSON.parse(readFileSync(new URL(`../../calc-spec/vectors/${file}`, import.meta.url), "utf8"));
  for (const v of vectors) {
    const got = fn(v.input);
    if (!isDeepStrictEqual(got, v.expected)) {
      failed++;
      console.error(`FAIL ${file} ${v.name}\n  got      ${JSON.stringify(got)}\n  expected ${JSON.stringify(v.expected)}`);
    }
  }
  if (vectors.length < minimum) throw new Error(`${file}: expected at least ${minimum} vectors`);
  console.log(`${file}: ${vectors.length} vectors checked`);
}
check("pricing_v1.json", pricePlan as (i: never) => unknown, 8);
check("levers_v1.json", replayLever as (i: never) => unknown, 8);
if (failed) process.exit(1);
console.log("parity: all vectors match");
