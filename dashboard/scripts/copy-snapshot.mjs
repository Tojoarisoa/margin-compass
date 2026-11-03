// Local development: serve the locally published PG-1 snapshot at /publish/latest/pg1.json.
import { copyFileSync, existsSync, mkdirSync } from "node:fs";

const src = new URL("../../data/local/publish/latest/pg1.json", import.meta.url);
const dest = new URL("../public/publish/latest/", import.meta.url);
if (!existsSync(src)) {
  console.error("No local snapshot. Run the pipeline first: cd pipelines && uv run mc-pipeline run");
  process.exit(1);
}
mkdirSync(dest, { recursive: true });
copyFileSync(src, new URL("pg1.json", dest));
console.log("copied data/local/publish/latest/pg1.json -> public/publish/latest/pg1.json");
