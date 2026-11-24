import { spawn } from "node:child_process";
import path from "node:path";
import { config, resolvePythonExecutable } from "./config.js";

export interface AgentRunResult {
  ok: boolean;
  backend: string;
  response: string;
  toolCalls: string[];
  error?: string;
}

export async function runRemoteAgent(
  prompt: string,
  workspace: string,
  timeoutMs = 180_000
): Promise<AgentRunResult> {
  const pythonBin = resolvePythonExecutable();
  const workerPath = path.join(config.projectRoot, "agent", "agy_worker.py");

  return new Promise((resolve) => {
    const child = spawn(pythonBin, [workerPath], {
      cwd: workspace,
      env: {
        ...process.env,
        PYTHONIOENCODING: "utf-8",
        AGENT_BACKEND: config.agentBackend,
        GEMINI_API_KEY: config.geminiApiKey,
        GEMINI_MODEL: config.geminiModel,
      },
      windowsHide: true,
    });

    let stdout = "";
    let stderr = "";
    let settled = false;

    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        child.kill();
        resolve({
          ok: false,
          backend: config.agentBackend,
          response: "",
          toolCalls: [],
          error: `Ajan zaman aşımına uğradı (${Math.round(timeoutMs / 1000)} sn).`,
        });
      }
    }, timeoutMs);

    child.stdout.on("data", (chunk: Buffer) => {
      stdout += chunk.toString("utf-8");
    });

    child.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString("utf-8");
    });

    child.on("error", (err) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        resolve({
          ok: false,
          backend: config.agentBackend,
          response: "",
          toolCalls: [],
          error: `Python worker başlatılamadı: ${err.message}`,
        });
      }
    });

    child.on("close", () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);

      // Parse the last non-empty JSON line from stdout
      const lines = stdout
        .split(/\r?\n/)
        .map((l) => l.trim())
        .filter(Boolean);
      const lastLine = lines[lines.length - 1] ?? "";

      try {
        const parsed = JSON.parse(lastLine) as AgentRunResult;
        resolve({
          ok: Boolean(parsed.ok),
          backend: parsed.backend ?? config.agentBackend,
          response: parsed.response ?? "",
          toolCalls: Array.isArray(parsed.toolCalls) ? parsed.toolCalls : [],
          error: parsed.error,
        });
      } catch {
        resolve({
          ok: false,
          backend: config.agentBackend,
          response: stdout.trim(),
          toolCalls: [],
          error:
            stderr.trim() ||
            stdout.trim() ||
            "Ajan çıktısı JSON olarak okunamadı.",
        });
      }
    });

    const payload = JSON.stringify({
      prompt,
      workspace,
      backend: config.agentBackend,
    });

    child.stdin.write(payload, "utf-8");
    child.stdin.end();
  });
}
