import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

// The build is one self-contained index.html (scripts, styles and fonts inlined), copied into
// the Python package so `arachne dashboard` can serve it with no static-file handling.
export default defineConfig({
  plugins: [react(), tailwindcss(), viteSingleFile()],
  build: { assetsInlineLimit: 100_000_000, cssCodeSplit: false },
  server: { proxy: { "/api": "http://127.0.0.1:7777" } },
});
