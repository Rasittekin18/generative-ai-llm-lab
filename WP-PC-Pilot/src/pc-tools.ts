import { execFile } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { config } from "./config.js";

const execFileAsync = promisify(execFile);

export interface FileMatch {
  name: string;
  fullPath: string;
  sizeBytes: number;
  modifiedAt: string;
  isDir?: boolean;
}

export interface ScreenshotResult {
  filePath: string;
  width: number;
  height: number;
}

export interface ResolvedFile {
  fullPath: string;
  fileName: string;
  sizeBytes: number;
  mimeType: string;
  isImage: boolean;
}

const SKIP_DIRS = new Set([
  "node_modules",
  ".git",
  ".venv",
  "venv",
  "__pycache__",
  ".next",
  "dist",
  "build",
  "$recycle.bin",
  "system volume information",
]);

function escapePsSingleQuotes(value: string): string {
  return value.replace(/'/g, "''");
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const parts: string[] = [];
  if (days > 0) parts.push(`${days}g`);
  if (hours > 0) parts.push(`${hours}s`);
  parts.push(`${mins}dk`);
  return parts.join(" ");
}

function guessMimeType(filePath: string): { mimeType: string; isImage: boolean } {
  const ext = path.extname(filePath).toLowerCase();
  const map: Record<string, string> = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".json": "application/json",
    ".csv": "text/csv",
    ".zip": "application/zip",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
  };
  const mimeType = map[ext] ?? "application/octet-stream";
  const isImage = [".png", ".jpg", ".jpeg", ".webp"].includes(ext);
  return { mimeType, isImage };
}

export async function runPowerShellRaw(
  script: string,
  timeoutMs = 30_000,
  cwd?: string
): Promise<{ stdout: string; stderr: string }> {
  const wrapped = `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $OutputEncoding = [System.Text.Encoding]::UTF8; ${script}`;
  const { stdout, stderr } = await execFileAsync(
    "powershell.exe",
    ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", wrapped],
    {
      timeout: timeoutMs,
      maxBuffer: 4 * 1024 * 1024,
      cwd,
      windowsHide: true,
    }
  );
  return { stdout: stdout.trim(), stderr: stderr.trim() };
}

export async function getSystemStatus(): Promise<string> {
  const totalMem = os.totalmem();
  const freeMem = os.freemem();
  const usedMem = totalMem - freeMem;
  const memPct = ((usedMem / totalMem) * 100).toFixed(1);

  const psScript = `
    $cpu = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
    $disks = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {
      [PSCustomObject]@{
        drive = $_.DeviceID
        freeGB = [math]::Round($_.FreeSpace / 1GB, 1)
        totalGB = [math]::Round($_.Size / 1GB, 1)
      }
    }
    $battery = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue | Select-Object -First 1 EstimatedChargeRemaining, BatteryStatus
    $top = Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 5 | ForEach-Object {
      [PSCustomObject]@{
        name = $_.ProcessName
        ramMB = [math]::Round($_.WorkingSet64 / 1MB, 0)
      }
    }
    [PSCustomObject]@{
      cpu = $cpu
      disks = @($disks)
      battery = $battery
      top = @($top)
    } | ConvertTo-Json -Depth 4 -Compress
  `;

  let cpuText = "Bilinmiyor";
  let diskLines = "";
  let batteryLine = "";
  let topLines = "";

  try {
    const { stdout } = await runPowerShellRaw(psScript, 15_000);
    const data = JSON.parse(stdout) as {
      cpu?: number | null;
      disks?: Array<{ drive: string; freeGB: number; totalGB: number }>;
      battery?: { EstimatedChargeRemaining?: number; BatteryStatus?: number } | null;
      top?: Array<{ name: string; ramMB: number }>;
    };

    if (typeof data.cpu === "number") {
      cpuText = `%${Math.round(data.cpu)}`;
    }
    if (Array.isArray(data.disks) && data.disks.length > 0) {
      diskLines = data.disks
        .map((d) => `  • ${d.drive} ${d.freeGB} GB boş / ${d.totalGB} GB`)
        .join("\n");
    }
    if (data.battery && typeof data.battery.EstimatedChargeRemaining === "number") {
      const charging = data.battery.BatteryStatus === 2 ? " (Şarjda)" : "";
      batteryLine = `\n🔋 *Pil:* %${data.battery.EstimatedChargeRemaining}${charging}`;
    }
    if (Array.isArray(data.top) && data.top.length > 0) {
      topLines = data.top.map((p, i) => `  ${i + 1}. ${p.name} (${p.ramMB} MB)`).join("\n");
    }
  } catch {
    // Fallback to Node os data
  }

  return [
    `💻 *PC Durum Raporu (${os.hostname()})*`,
    `⏱️ *Açık Kalma:* ${formatUptime(os.uptime())}`,
    `🧠 *CPU Kullanımı:* ${cpuText}`,
    `📊 *RAM:* ${formatBytes(usedMem)} / ${formatBytes(totalMem)} (%${memPct})${batteryLine}`,
    diskLines ? `💾 *Diskler:*\n${diskLines}` : "",
    topLines ? `🔥 *En Çok RAM Kullananlar:*\n${topLines}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

export async function takeScreenshot(outputDir = config.screenshotDir): Promise<ScreenshotResult> {
  fs.mkdirSync(outputDir, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const filePath = path.join(outputDir, `screen_${stamp}.png`);
  const escapedPath = escapePsSingleQuotes(filePath);

  const psScript = `
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
    if ($bounds.Width -le 0 -or $bounds.Height -le 0) {
      $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    }
    $bitmap = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
    $bitmap.Save('${escapedPath}', [System.Drawing.Imaging.ImageFormat]::Png)
    $graphics.Dispose()
    $bitmap.Dispose()
    "$($bounds.Width)x$($bounds.Height)"
  `;

  const { stdout } = await runPowerShellRaw(psScript, 15_000);
  if (!fs.existsSync(filePath)) {
    throw new Error("Ekran görüntüsü oluşturulamadı.");
  }

  const [wStr, hStr] = stdout.split("x");
  return {
    filePath,
    width: Number.parseInt(wStr ?? "0", 10) || 0,
    height: Number.parseInt(hStr ?? "0", 10) || 0,
  };
}

export function resolveShortcutDir(alias: string): string | null {
  const home = os.homedir();
  const key = alias.trim().toLowerCase();

  const pickFirst = (paths: string[]): string | null => {
    for (const p of paths) {
      if (fs.existsSync(p)) return path.resolve(p);
    }
    return null;
  };

  if (["masaüstü", "masaustu", "desktop"].includes(key)) {
    return pickFirst([
      path.join(home, "OneDrive", "Masaüstü"),
      path.join(home, "Desktop"),
      path.join(home, "OneDrive", "Desktop"),
    ]);
  }
  if (["indirilenler", "downloads", "indir"].includes(key)) {
    return pickFirst([path.join(home, "Downloads")]);
  }
  if (["belgeler", "documents", "dokumanlar"].includes(key)) {
    return pickFirst([
      path.join(home, "OneDrive", "Belgeler"),
      path.join(home, "Documents"),
    ]);
  }
  if (["ev", "home", "kullanici"].includes(key)) {
    return path.resolve(home);
  }
  return null;
}

export function getDefaultSearchDirs(): string[] {
  const home = os.homedir();
  const candidates = [
    path.join(home, "OneDrive", "Masaüstü"),
    path.join(home, "Desktop"),
    path.join(home, "OneDrive", "Desktop"),
    path.join(home, "Downloads"),
    path.join(home, "OneDrive", "Belgeler"),
    path.join(home, "Documents"),
    ...config.extraSearchDirs,
  ];
  const unique = new Set<string>();
  for (const dir of candidates) {
    const resolved = path.resolve(dir);
    if (fs.existsSync(resolved)) {
      unique.add(resolved);
    }
  }
  return Array.from(unique);
}

export function listDirectoryEntries(dirPath: string, maxItems = 25): FileMatch[] {
  const resolved = path.resolve(dirPath);
  if (!fs.existsSync(resolved) || !fs.statSync(resolved).isDirectory()) {
    throw new Error(`Klasör bulunamadı: ${resolved}`);
  }
  const entries = fs.readdirSync(resolved, { withFileTypes: true });
  const results: FileMatch[] = [];

  for (const entry of entries) {
    if (entry.name.startsWith(".")) continue;
    const fullPath = path.join(resolved, entry.name);
    try {
      const stat = fs.statSync(fullPath);
      results.push({
        name: entry.name,
        fullPath,
        sizeBytes: entry.isDirectory() ? 0 : stat.size,
        modifiedAt: stat.mtime.toISOString(),
        isDir: entry.isDirectory(),
      });
    } catch {
      // ignore inaccessible entries
    }
  }

  results.sort((a, b) => {
    if (Boolean(a.isDir) !== Boolean(b.isDir)) return a.isDir ? -1 : 1;
    return a.name.localeCompare(b.name, "tr");
  });

  return results.slice(0, maxItems);
}

export function findFiles(
  query: string,
  customDirs?: string[],
  maxResults = 15,
  maxDepth = 4
): FileMatch[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [];

  const roots =
    customDirs && customDirs.length > 0
      ? customDirs.map((d) => path.resolve(d)).filter((d) => fs.existsSync(d))
      : getDefaultSearchDirs();

  const matches: FileMatch[] = [];
  const visited = new Set<string>();

  function walk(dir: string, depth: number): void {
    if (depth > maxDepth || matches.length >= maxResults) return;
    const norm = dir.toLowerCase();
    if (visited.has(norm)) return;
    visited.add(norm);

    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }

    for (const entry of entries) {
      if (matches.length >= maxResults) return;
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (!SKIP_DIRS.has(entry.name.toLowerCase())) {
          walk(fullPath, depth + 1);
        }
      } else if (entry.isFile()) {
        if (entry.name.toLowerCase().includes(needle)) {
          try {
            const stat = fs.statSync(fullPath);
            matches.push({
              name: entry.name,
              fullPath,
              sizeBytes: stat.size,
              modifiedAt: stat.mtime.toISOString(),
              isDir: false,
            });
          } catch {
            // ignore unreadable files
          }
        }
      }
    }
  }

  for (const root of roots) {
    walk(root, 0);
  }

  matches.sort((a, b) => b.modifiedAt.localeCompare(a.modifiedAt));
  return matches.slice(0, maxResults);
}

export function resolveSafeFile(filePath: string, maxSizeBytes = 50 * 1024 * 1024): ResolvedFile {
  const resolved = path.resolve(filePath);
  if (!fs.existsSync(resolved)) {
    throw new Error(`Dosya bulunamadı: ${resolved}`);
  }
  const stat = fs.statSync(resolved);
  if (!stat.isFile()) {
    throw new Error(`Bu bir dosya değil (klasör olabilir): ${resolved}`);
  }
  if (stat.size > maxSizeBytes) {
    throw new Error(
      `Dosya boyutu çok büyük (${formatBytes(stat.size)}). WhatsApp gönderim limiti: ${formatBytes(maxSizeBytes)}.`
    );
  }
  const { mimeType, isImage } = guessMimeType(resolved);
  return {
    fullPath: resolved,
    fileName: path.basename(resolved),
    sizeBytes: stat.size,
    mimeType,
    isImage,
  };
}

export async function openAppOrUrl(target: string): Promise<string> {
  const cleaned = target.trim();
  const key = cleaned.toLowerCase();

  const shortcuts: Record<string, string> = {
    chrome: "chrome.exe",
    edge: "msedge.exe",
    notepad: "notepad.exe",
    notdefteri: "notepad.exe",
    hesap: "calc.exe",
    "hesap makinesi": "calc.exe",
    calc: "calc.exe",
    gorev: "taskmgr.exe",
    "görev yöneticisi": "taskmgr.exe",
    explorer: "explorer.exe",
    dosya: "explorer.exe",
    spotify: "spotify:",
    vscode: "code",
    code: "code",
    cmd: "cmd.exe",
    powershell: "powershell.exe",
    ayarlar: "ms-settings:",
    youtube: "https://www.youtube.com",
    google: "https://www.google.com",
    github: "https://github.com",
    whatsapp: "https://web.whatsapp.com",
  };

  let launchTarget = shortcuts[key] ?? cleaned;
  if (
    !shortcuts[key] &&
    !launchTarget.includes("://") &&
    !launchTarget.includes("\\") &&
    /^[a-z0-9-]+(\.[a-z0-9-]+)+(\/.*)?$/i.test(launchTarget)
  ) {
    launchTarget = `https://${launchTarget}`;
  }

  const escaped = escapePsSingleQuotes(launchTarget);
  await runPowerShellRaw(`Start-Process '${escaped}'`, 10_000);
  return `🚀 Açıldı: *${launchTarget}*`;
}

export async function listOpenWindows(): Promise<string> {
  const psScript = `
    Get-Process | Where-Object { $_.MainWindowTitle -and $_.MainWindowTitle.Trim() -ne '' } |
      Select-Object -First 20 ProcessName, MainWindowTitle |
      ConvertTo-Json -Compress
  `;
  const { stdout } = await runPowerShellRaw(psScript, 10_000);
  if (!stdout) return "ℹ️ Şu anda açık pencere bulunamadı.";
  const raw = JSON.parse(stdout);
  const items: Array<{ ProcessName: string; MainWindowTitle: string }> = Array.isArray(raw)
    ? raw
    : [raw];

  const lines = items.map(
    (w, i) => `${i + 1}. *${w.ProcessName}* — ${w.MainWindowTitle.slice(0, 70)}`
  );
  return `🪟 *Açık Pencereler (${items.length}):*\n${lines.join("\n")}`;
}

export async function closeApplication(processName: string): Promise<string> {
  const clean = processName.trim().replace(/\.exe$/i, "");
  const escaped = escapePsSingleQuotes(clean);
  const { stdout } = await runPowerShellRaw(
    `$procs = Get-Process -Name '${escaped}' -ErrorAction SilentlyContinue; if (-not $procs) { 'NOT_FOUND' } else { $procs | Stop-Process -Force; "CLOSED:$($procs.Count)" }`,
    10_000
  );
  if (stdout === "NOT_FOUND") {
    return `ℹ️ "${clean}" adında çalışan bir uygulama bulunamadı.`;
  }
  const count = stdout.split(":")[1] ?? "1";
  return `✅ *${clean}* kapatıldı (${count} işlem).`;
}

export async function getClipboardText(): Promise<string> {
  const { stdout } = await runPowerShellRaw("Get-Clipboard -Raw", 8_000);
  if (!stdout) return "📋 PC panosu şu anda boş (veya metin değil).";
  if (stdout.length > 3500) {
    return `📋 *PC Panosu:*\n\n${stdout.slice(0, 3500)}\n\n... (kısaltıldı)`;
  }
  return `📋 *PC Panosu:*\n\n${stdout}`;
}

export async function setClipboardText(text: string): Promise<string> {
  const escaped = escapePsSingleQuotes(text);
  await runPowerShellRaw(`Set-Clipboard -Value '${escaped}'`, 8_000);
  return `📋 Metin PC panosuna (Ctrl+C) kopyalandı! (${text.length} karakter)`;
}

const KEYBD_CSHARP = `
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class WinKeys {
  [DllImport("user32.dll")]
  public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
  public static void Tap(byte vk) {
    keybd_event(vk, 0, 0, UIntPtr.Zero);
    keybd_event(vk, 0, 2, UIntPtr.Zero);
  }
}
"@ -ErrorAction SilentlyContinue
`;

export async function controlAudio(action: string): Promise<string> {
  const key = action.trim().toLowerCase();

  if (["kapat", "sustur", "mute", "aç", "ac", "sessiz"].includes(key)) {
    await runPowerShellRaw(`${KEYBD_CSHARP}; [WinKeys]::Tap(0xAD)`, 10_000);
    return "🔇 Ses açma/kapama (mute) değiştirildi.";
  }

  if (["arttir", "arttır", "yukselt", "yükselt", "+"].includes(key)) {
    await runPowerShellRaw(`${KEYBD_CSHARP}; 1..5 | ForEach-Object { [WinKeys]::Tap(0xAF) }`, 10_000);
    return "🔊 Ses yükseltildi (+%10).";
  }

  if (["azalt", "kis", "kıs", "-"].includes(key)) {
    await runPowerShellRaw(`${KEYBD_CSHARP}; 1..5 | ForEach-Object { [WinKeys]::Tap(0xAE) }`, 10_000);
    return "🔉 Ses azaltıldı (-%10).";
  }

  const pct = Number.parseInt(key, 10);
  if (!Number.isNaN(pct) && pct >= 0 && pct <= 100) {
    const steps = Math.round(pct / 2);
    await runPowerShellRaw(
      `${KEYBD_CSHARP}; 1..50 | ForEach-Object { [WinKeys]::Tap(0xAE) }; if (${steps} -gt 0) { 1..${steps} | ForEach-Object { [WinKeys]::Tap(0xAF) } }`,
      12_000
    );
    return `🔊 Ses yaklaşık *%${pct}* seviyesine ayarlandı.`;
  }

  return "ℹ️ Kullanım: `ses 50`, `ses kapat`, `ses arttır`, `ses azalt`";
}

export async function controlMedia(action: "toggle" | "next" | "prev"): Promise<string> {
  const vkMap = {
    toggle: { vk: "0xB3", label: "⏯️ Medya oynat/duraklat gönderildi." },
    next: { vk: "0xB0", label: "⏭️ Sonraki parça/video gönderildi." },
    prev: { vk: "0xB1", label: "⏮️ Önceki parça/video gönderildi." },
  } as const;
  const item = vkMap[action];
  await runPowerShellRaw(`${KEYBD_CSHARP}; [WinKeys]::Tap(${item.vk})`, 10_000);
  return item.label;
}

export async function typeTextOnPc(text: string, pressEnter = false): Promise<string> {
  const escaped = escapePsSingleQuotes(text);
  const enterCmd = pressEnter
    ? "Start-Sleep -Milliseconds 120; [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')"
    : "";
  const psScript = `
    Add-Type -AssemblyName System.Windows.Forms
    Set-Clipboard -Value '${escaped}'
    Start-Sleep -Milliseconds 100
    [System.Windows.Forms.SendKeys]::SendWait('^v')
    ${enterCmd}
  `;
  await runPowerShellRaw(psScript, 10_000);
  return `⌨️ Aktif pencereye yazıldı${pressEnter ? " ve Enter'a basıldı" : ""}.`;
}

export async function sendShortcutKey(shortcut: string): Promise<string> {
  const key = shortcut.trim().toLowerCase().replace(/\s+/g, "");
  const map: Record<string, string> = {
    enter: "{ENTER}",
    esc: "{ESC}",
    tab: "{TAB}",
    bosluk: " ",
    boşluk: " ",
    space: " ",
    sil: "{BACKSPACE}",
    "alt+tab": "%{TAB}",
    "ctrl+s": "^s",
    "ctrl+c": "^c",
    "ctrl+v": "^v",
    "ctrl+z": "^z",
    "ctrl+w": "^w",
    "ctrl+a": "^a",
    f5: "{F5}",
    f11: "{F11}",
    yukari: "{UP}",
    yukarı: "{UP}",
    asagi: "{DOWN}",
    aşağı: "{DOWN}",
    sol: "{LEFT}",
    sag: "{RIGHT}",
    sağ: "{RIGHT}",
  };

  if (key === "win+d" || key === "masaustu" || key === "masaüstü") {
    await runPowerShellRaw("(New-Object -ComObject Shell.Application).ToggleDesktop()", 8_000);
    return "🖥️ Masaüstü gösterildi/gizlendi (`Win+D`).";
  }

  const sendKeysToken = map[key];
  if (!sendKeysToken) {
    throw new Error(
      `Desteklenmeyen tuş: "${shortcut}". Örnekler: enter, esc, boşluk, alt+tab, win+d, ctrl+s, ctrl+w, f5, yukarı, aşağı`
    );
  }

  await runPowerShellRaw(
    `Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait('${sendKeysToken}')`,
    8_000
  );
  return `⌨️ Tuş gönderildi: *${shortcut}*`;
}

export async function lockWorkstation(): Promise<string> {
  await execFileAsync("rundll32.exe", ["user32.dll,LockWorkStation"], { windowsHide: true });
  return "🔒 Bilgisayar ekranı kilitlendi.";
}

export async function sleepComputer(): Promise<string> {
  await runPowerShellRaw(
    "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Application]::SetSuspendState('Suspend', $false, $false)",
    10_000
  );
  return "😴 Bilgisayar uyku moduna alınıyor...";
}

export async function runPowerShellCommand(command: string, cwd?: string): Promise<string> {
  const { stdout, stderr } = await runPowerShellRaw(command, 45_000, cwd);
  const combined = [stdout, stderr ? `[STDERR]\n${stderr}` : ""].filter(Boolean).join("\n\n");
  if (!combined) return "✅ Komut çıktı üretmeden başarıyla tamamlandı.";
  if (combined.length > 3500) {
    return `${combined.slice(0, 3500)}\n\n... (çıktı uzun olduğu için kısaltıldı)`;
  }
  return combined;
}

export async function scheduleShutdown(minutes: number, restart = false): Promise<string> {
  const safeMin = Math.max(0, Math.min(1440, Math.round(minutes)));
  const seconds = safeMin * 60;
  const flag = restart ? "/r" : "/s";
  await execFileAsync("shutdown", [flag, "/t", String(seconds)], { windowsHide: true });
  const action = restart ? "yeniden başlatma" : "kapatma";
  return `✅ Bilgisayar ${safeMin} dakika sonra ${action} için zamanlandı.\nİptal etmek için: \`iptal\``;
}

export async function cancelShutdown(): Promise<string> {
  try {
    await execFileAsync("shutdown", ["/a"], { windowsHide: true });
    return "✅ Zamanlanmış kapatma/yeniden başlatma iptal edildi.";
  } catch {
    return "ℹ️ Şu anda aktif bir kapatma zamanlaması yok.";
  }
}

export async function moveFileToRecycleBin(filePath: string): Promise<string> {
  const resolved = path.resolve(filePath);
  if (!fs.existsSync(resolved)) {
    throw new Error(`Dosya bulunamadı: ${resolved}`);
  }
  const escaped = escapePsSingleQuotes(resolved);
  const psScript = `
    Add-Type -AssemblyName Microsoft.VisualBasic
    [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile('${escaped}', 'OnlyErrorDialogs', 'SendToRecycleBin')
  `;
  await runPowerShellRaw(psScript, 15_000);
  return `🗑️ Dosya Geri Dönüşüm Kutusu'na taşındı:\n${resolved}`;
}

export function formatFileSize(bytes: number): string {
  return formatBytes(bytes);
}
