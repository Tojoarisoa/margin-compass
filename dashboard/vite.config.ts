import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Served from the lake's site/ prefix through CloudFront; /publish/* and /api/* are other behaviors on the same distribution.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 900 },
});
