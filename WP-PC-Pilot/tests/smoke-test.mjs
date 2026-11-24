import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT = path.resolve(__dirname, "..");

async function testSecurity() {
  const { ApprovalManager, isAuthorizedChat, isDangerousAgentPrompt, normalizeJid } = await import(
    "../dist/security.js"
  );

  assert.equal(normalizeJid("905551234567:12@s.whatsapp.net"), "905551234567@s.whatsapp.net");
  assert.equal(normalizeJid("123456789:5@lid"), "123456789@lid");

  // Own self-chat allowed
  assert.equal(
    isAuthorizedChat({
      remoteJid: "905551234567@s.whatsapp.net",
      fromMe: true,
      ownPhoneJid: "905551234567:4@s.whatsapp.net",
      ownLid: "99999:1@lid",
      allowedPhone: "",
    }),
    true
  );

  // Own LID self-chat allowed
  assert.equal(
    isAuthorizedChat({
      remoteJid: "99999@lid",
      fromMe: true,
      ownPhoneJid: "905551234567:4@s.whatsapp.net",
      ownLid: "99999:1@lid",
      allowedPhone: "",
    }),
    true
  );

  // Friend chat rejected even when fromMe=true
  assert.equal(
    isAuthorizedChat({
      remoteJid: "905559999999@s.whatsapp.net",
      fromMe: true,
      ownPhoneJid: "905551234567:4@s.whatsapp.net",
      ownLid: "99999:1@lid",
      allowedPhone: "",
    }),
    false
  );

  // Group chat always rejected
  assert.equal(
    isAuthorizedChat({
      remoteJid: "120363000000000@g.us",
      fromMe: true,
      ownPhoneJid: "905551234567:4@s.whatsapp.net",
      ownLid: "99999:1@lid",
      allowedPhone: "905551234567",
    }),
    false
  );

  // Dangerous prompt detector
  assert.equal(isDangerousAgentPrompt("bilgisayarı kapat hemen"), true);
  assert.equal(isDangerousAgentPrompt("README dosyasını özetle"), false);

  // 2-step approval manager (one-time code)
  const mgr = new ApprovalManager(60_000);
  const pending = mgr.create("Test işlem", async () => "tamam");
  assert.match(pending.code, /^\d{4}$/);
  const consumed = mgr.consume(pending.code);
  assert.ok(consumed);
  assert.equal(await consumed.execute(), "tamam");
  assert.equal(mgr.consume(pending.code), null); // cannot reuse

  console.log("✅ 1/4 Security & 2-Step Approval testleri geçti.");

  const { parseCommandInput } = await import("../dist/bridge.js");
  assert.deepEqual(parseCommandInput("! pc durum"), { cmd: "durum", arg: "", explicitBang: true });
  assert.deepEqual(parseCommandInput("! pc at <temizlik>"), { cmd: "at", arg: "temizlik", explicitBang: true });
  assert.deepEqual(parseCommandInput("ekran"), { cmd: "ekran", arg: "", explicitBang: false });
  assert.deepEqual(parseCommandInput("aç chrome"), { cmd: "ac", arg: "chrome", explicitBang: false });
  assert.deepEqual(parseCommandInput("ai <merhaba>"), { cmd: "ai", arg: "merhaba", explicitBang: false });
  assert.equal(parseCommandInput("akşam ekmek almayı unutma"), null);
  console.log("✅ 1.5/4 Esnek komut ayrıştırıcı (! boşluk, <>, ünlemsiz) testleri geçti.");
}

async function testPcTools() {
  const { findFiles, getSystemStatus, takeScreenshot } = await import("../dist/pc-tools.js");

  const status = await getSystemStatus();
  assert.ok(status.includes("PC Durum Raporu"), "System status rapor başlığı eksik");

  const files = findFiles("package.json", [ROOT], 5, 2);
  assert.ok(files.some((f) => f.name === "package.json"), "findFiles package.json bulamadı");

  const shot = await takeScreenshot(path.join(ROOT, "captures", "test"));
  assert.ok(fs.existsSync(shot.filePath), "Screenshot dosyası oluşturulamadı");
  const size = fs.statSync(shot.filePath).size;
  assert.ok(size > 1000, `Screenshot çok küçük (${size} bytes)`);
  fs.rmSync(shot.filePath, { force: true });

  console.log(`✅ 2/4 PC Tools testleri geçti (Screenshot ${shot.width}x${shot.height}, ${size} bytes).`);
}

async function testPythonWorker() {
  const { resolvePythonExecutable } = await import("../dist/config.js");
  const py = resolvePythonExecutable();
  const worker = path.join(ROOT, "agent", "agy_worker.py");

  const output = await new Promise((resolve, reject) => {
    const child = spawn(py, [worker], { windowsHide: true });
    let out = "";
    let err = "";
    child.stdout.on("data", (d) => (out += d.toString("utf-8")));
    child.stderr.on("data", (d) => (err += d.toString("utf-8")));
    child.on("close", (code) => {
      if (code !== 0) reject(new Error(err || `exit ${code}`));
      else resolve(out.trim());
    });
    child.stdin.write(JSON.stringify({ dryRun: true }));
    child.stdin.end();
  });

  const parsed = JSON.parse(String(output));
  assert.equal(parsed.ok, true);
  console.log(`✅ 3/4 Python Worker dry-run geçti: ${parsed.response}`);
}

async function testMcpServer() {
  const mcpPath = path.join(ROOT, "dist", "mcp-server.js");

  const tools = await new Promise((resolve, reject) => {
    const child = spawn("node", [mcpPath], { windowsHide: true });
    let buffer = "";
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("MCP server yanıt zaman aşımı"));
    }, 10_000);

    child.stdout.on("data", (chunk) => {
      buffer += chunk.toString("utf-8");
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.trim()) continue;
        const msg = JSON.parse(line);
        if (msg.id === 1) {
          child.stdin.write(
            JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }) + "\n"
          );
          child.stdin.write(
            JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} }) + "\n"
          );
        } else if (msg.id === 2) {
          clearTimeout(timer);
          child.kill();
          resolve(msg.result.tools.map((t) => t.name));
        }
      }
    });

    child.stdin.write(
      JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "initialize",
        params: {
          protocolVersion: "2024-11-05",
          capabilities: {},
          clientInfo: { name: "smoke-test", version: "1.0.0" },
        },
      }) + "\n"
    );
  });

  for (const expected of [
    "pc_system_status",
    "pc_take_screenshot",
    "pc_find_files",
    "wp_bridge_status",
    "wp_send_message",
    "wp_send_file",
  ]) {
    assert.ok(tools.includes(expected), `MCP tool eksik: ${expected}`);
  }

  console.log(`✅ 4/4 MCP Server stdio testi geçti (${tools.length} tool: ${tools.join(", ")}).`);
}

await testSecurity();
await testPcTools();
await testPythonWorker();
await testMcpServer();
console.log("\n🎉 TÜM TESTLER BAŞARILI!");
