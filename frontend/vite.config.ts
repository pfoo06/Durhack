import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built output goes to frontend/dist, which the backend serves at / (SPEC §4.2).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
});
