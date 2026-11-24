import dotenv from "dotenv";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// dist/config.js -> wp-pc-pilot/
export const PROJECT_ROOT = path.resolve(__dirname, "..");

dotenv.config({ path: path.join(PROJECT_ROOT, ".env") });

function parseList(raw: string | undefined): string[] {
  if (!raw) return [];
  return raw
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export const config = {
  projectRoot: PROJECT_ROOT,
  allowedPhone: (process.env.ALLOWED_PHONE ?? "").replace(/\D/g, ""),
  bridgeApiPort: Number.parseInt(process.env.BRIDGE_API_PORT ?? "3847", 10) || 3847,
  bridgeApiToken: process.env.BRIDGE_API_TOKEN ?? "wp-pc-pilot-local-token",
  agentBackend: (process.env.AGENT_BACKEND ?? "auto").toLowerCase() as
    | "auto"
    | "antigravity"
    | "gemini",
  defaultAgentWorkspace:
    process.env.AGENT_WORKSPACE && process.env.AGENT_WORKSPACE.trim().length > 0
      ? path.resolve(process.env.AGENT_WORKSPACE.trim())
      : PROJECT_ROOT,
  geminiApiKey: process.env.GEMINI_API_KEY ?? "",
  geminiModel: process.env.GEMINI_MODEL ?? "gemini-2.5-flash",
  extraSearchDirs: parseList(process.env.SEARCH_DIRS),
  screenshotDir: path.resolve(
    PROJECT_ROOT,
    process.env.SCREENSHOT_DIR && process.env.SCREENSHOT_DIR.trim().length > 0
      ? process.env.SCREENSHOT_DIR.trim()
      : "captures"
  ),
  authDir: path.join(PROJECT_ROOT, "auth_info"),
};

export function resolvePythonExecutable(): string {
  if (process.env.PYTHON_EXECUTABLE && fs.existsSync(process.env.PYTHON_EXECUTABLE)) {
    return process.env.PYTHON_EXECUTABLE;
  }

  const localVenvWin = path.join(
    process.env.LOCALAPPDATA ?? os.homedir(),
    "wp-pc-pilot-venv",
    "Scripts",
    "python.exe"
  );
  if (fs.existsSync(localVenvWin)) return localVenvWin;

  const venvWin = path.join(PROJECT_ROOT, "agent", ".venv", "Scripts", "python.exe");
  if (fs.existsSync(venvWin)) return venvWin;

  const venvUnix = path.join(PROJECT_ROOT, "agent", ".venv", "bin", "python");
  if (fs.existsSync(venvUnix)) return venvUnix;

  return "python";
}
