import { Boom } from "@hapi/boom";
import makeWASocket, {
  Browsers,
  DisconnectReason,
  downloadMediaMessage,
  fetchLatestBaileysVersion,
  useMultiFileAuthState,
  type WAMessage,
} from "@whiskeysockets/baileys";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import pino from "pino";
import qrcode from "qrcode-terminal";
import { runRemoteAgent } from "./agent-runner.js";
import { config } from "./config.js";
import {
  cancelShutdown,
  closeApplication,
  controlAudio,
  controlMedia,
  findFiles,
  formatFileSize,
  getClipboardText,
  getSystemStatus,
  listDirectoryEntries,
  listOpenWindows,
  lockWorkstation,
  moveFileToRecycleBin,
  openAppOrUrl,
  resolveSafeFile,
  resolveShortcutDir,
  runPowerShellCommand,
  scheduleShutdown,
  sendShortcutKey,
  setClipboardText,
  sleepComputer,
  takeScreenshot,
  typeTextOnPc,
  type FileMatch,
} from "./pc-tools.js";
import {
  ApprovalManager,
  isAuthorizedChat,
  isDangerousAgentPrompt,
  normalizeJid,
} from "./security.js";

type WASocketInstance = ReturnType<typeof makeWASocket>;

const createSocket: typeof makeWASocket =
  typeof makeWASocket === "function"
    ? makeWASocket
    : (makeWASocket as unknown as { default: typeof makeWASocket }).default;

const approvals = new ApprovalManager(120_000);
const sentMessageIds = new Set<string>();
const processedMessageIds = new Set<string>();
let lastListedEntries: FileMatch[] = [];
let activeWorkspace = config.defaultAgentWorkspace;
let activeSocket: WASocketInstance | null = null;
let isConnected = false;
let ownPhoneJid = "";
let ownLid = "";
let loggedOutRetries = 0;
const bridgeLogPath = path.join(config.projectRoot, "bridge.log");

function logInfo(message: string): void {
  const line = `[${new Date().toISOString()}] ${message}`;
  console.log(message);
  try {
    fs.appendFileSync(bridgeLogPath, `${line}\n`, "utf-8");
  } catch {
    // ignore log file write failures
  }
}

function rememberId(set: Set<string>, id: string | null | undefined): void {
  if (!id) return;
  set.add(id);
  if (set.size > 1000) {
    const first = set.values().next().value;
    if (first) set.delete(first);
  }
}

function rememberSentId(id: string | null | undefined): void {
  rememberId(sentMessageIds, id);
}

function unwrapMessage(raw: WAMessage["message"]): WAMessage["message"] {
  let current = raw;
  for (let i = 0; i < 6 && current; i++) {
    if (current.deviceSentMessage?.message) {
      current = current.deviceSentMessage.message;
      continue;
    }
    if (current.ephemeralMessage?.message) {
      current = current.ephemeralMessage.message;
      continue;
    }
    if (current.viewOnceMessage?.message) {
      current = current.viewOnceMessage.message;
      continue;
    }
    if (current.viewOnceMessageV2?.message) {
      current = current.viewOnceMessageV2.message;
      continue;
    }
    if (current.documentWithCaptionMessage?.message) {
      current = current.documentWithCaptionMessage.message;
      continue;
    }
    break;
  }
  return current;
}

function extractText(msg: WAMessage): string {
  const m = unwrapMessage(msg.message);
  if (!m) return "";
  if (m.conversation) return m.conversation;
  if (m.extendedTextMessage?.text) return m.extendedTextMessage.text;
  if (m.imageMessage?.caption) return m.imageMessage.caption;
  if (m.documentMessage?.caption) return m.documentMessage.caption;
  return "";
}

function hasIncomingMedia(msg: WAMessage): boolean {
  const m = unwrapMessage(msg.message);
  return Boolean(m?.imageMessage || m?.documentMessage || m?.videoMessage || m?.audioMessage);
}

/**
 * Strips accidental outer brackets/quotes users type from help hints (e.g. "<temizlik>" -> "temizlik")
 */
function cleanArg(raw: string): string {
  let s = raw.trim();
  if ((s.startsWith("<") && s.endsWith(">")) || (s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) {
    s = s.slice(1, -1).trim();
  }
  return s;
}

/**
 * Normalizes phone-friendly inputs:
 *   "! pc durum" -> cmd="durum", arg=""
 *   "ekran"      -> cmd="ekran", arg=""
 *   "!agy <selam>" -> cmd="agy", arg="selam"
 */
export function parseCommandInput(rawText: string): {
  cmd: string;
  arg: string;
  explicitBang: boolean;
} | null {
  const trimmed = rawText.trim();
  if (!trimmed) return null;

  const explicitBang = trimmed.startsWith("!");
  const withoutBang = explicitBang ? trimmed.slice(1).trim() : trimmed;
  if (!withoutBang) return null;

  // Strip optional leading "pc " prefix ("pc durum" -> "durum")
  let normalized = withoutBang;
  if (/^pc(\s+|$)/i.test(normalized)) {
    normalized = normalized.slice(2).trim();
    if (!normalized) {
      return { cmd: "yardim", arg: "", explicitBang };
    }
  }

  const spaceIdx = normalized.search(/\s/);
  const head = (spaceIdx === -1 ? normalized : normalized.slice(0, spaceIdx)).toLowerCase();
  const tail = spaceIdx === -1 ? "" : cleanArg(normalized.slice(spaceIdx + 1));

  // Normalize Turkish characters on the command keyword only
  const asciiHead = head
    .replace(/ı/g, "i")
    .replace(/ğ/g, "g")
    .replace(/ü/g, "u")
    .replace(/ş/g, "s")
    .replace(/ö/g, "o")
    .replace(/ç/g, "c");

  const KNOWN_COMMANDS = new Set([
    "yardim",
    "help",
    "menu",
    "?",
    "durum",
    "ekran",
    "ss",
    "bul",
    "at",
    "gonder",
    "klasor",
    "ls",
    "gir",
    "cd",
    "geri",
    "..",
    "ac",
    "pencereler",
    "kapat-uyg",
    "pano",
    "kopyala",
    "ses",
    "medya",
    "sonraki",
    "onceki",
    "yaz",
    "yaz-enter",
    "tus",
    "kilitle",
    "uyut",
    "kapat",
    "yenidenbaslat",
    "iptal",
    "calistir",
    "sil",
    "onay",
    "kaydet",
    "ai",
    "agy",
    "agy-klasor",
  ]);

  if (!KNOWN_COMMANDS.has(asciiHead)) {
    if (explicitBang) {
      return { cmd: asciiHead, arg: tail, explicitBang: true };
    }
    return null;
  }

  return { cmd: asciiHead, arg: tail, explicitBang };
}

async function sendText(jid: string, text: string): Promise<void> {
  if (!activeSocket || !isConnected) {
    throw new Error("WhatsApp bağlantısı aktif değil.");
  }
  const sent = await activeSocket.sendMessage(jid, { text });
  rememberSentId(sent?.key?.id);
}

async function sendFileToJid(jid: string, filePath: string, caption?: string): Promise<void> {
  if (!activeSocket || !isConnected) {
    throw new Error("WhatsApp bağlantısı aktif değil.");
  }
  const file = resolveSafeFile(filePath);
  const buffer = fs.readFileSync(file.fullPath);

  if (file.isImage) {
    const sent = await activeSocket.sendMessage(jid, {
      image: buffer,
      caption: caption ?? file.fileName,
      mimetype: file.mimeType,
    });
    rememberSentId(sent?.key?.id);
  } else {
    const sent = await activeSocket.sendMessage(jid, {
      document: buffer,
      fileName: file.fileName,
      mimetype: file.mimeType,
      caption,
    });
    rememberSentId(sent?.key?.id);
  }
}

async function saveIncomingMedia(msg: WAMessage, targetHint: string): Promise<string> {
  const m = unwrapMessage(msg.message);
  if (!m) throw new Error("Medya içeriği bulunamadı.");

  const targetDir =
    (targetHint ? resolveShortcutDir(targetHint) : null) ||
    resolveShortcutDir("indirilenler") ||
    path.join(os.homedir(), "Downloads");

  fs.mkdirSync(targetDir, { recursive: true });

  let fileName = `whatsapp_${Date.now()}`;
  if (m.documentMessage?.fileName) {
    fileName = m.documentMessage.fileName;
  } else if (m.imageMessage) {
    fileName = `wp_foto_${Date.now()}.jpg`;
  } else if (m.videoMessage) {
    fileName = `wp_video_${Date.now()}.mp4`;
  } else if (m.audioMessage) {
    fileName = `wp_ses_${Date.now()}.ogg`;
  }

  // Strip invalid Windows filename characters
  fileName = fileName.replace(/[<>:"/\\|?*]/g, "_");
  const destPath = path.join(targetDir, fileName);

  const buffer = (await downloadMediaMessage(
    msg,
    "buffer",
    {},
    {
      logger: pino({ level: "silent" }),
      reuploadRequest: activeSocket!.updateMediaMessage,
    }
  )) as Buffer;

  fs.writeFileSync(destPath, buffer);
  return `✅ Dosya PC'ye kaydedildi (${formatFileSize(buffer.length)}):\n\`${destPath}\``;
}

function formatDirectoryList(dir: string, entries: FileMatch[]): string {
  if (entries.length === 0) {
    return `📁 *${dir}*\n_(Klasör boş)_`;
  }
  const lines = entries.map((item, i) => {
    const icon = item.isDir ? "📁" : "📄";
    const meta = item.isDir ? "" : ` (${formatFileSize(item.sizeBytes)})`;
    return `${i + 1}. ${icon} *${item.name}*${meta}`;
  });
  return [
    `📁 *${dir}*`,
    "",
    ...lines,
    "",
    "💡 Klasöre girmek için: `gir 1` | Dosya indirmek için: `at 2` | Üst klasör: `geri`",
  ].join("\n");
}

function helpMessage(): string {
  return [
    "📱 *WP-PC Pilot — Hızlı Kumanda Rehberi*",
    "_(Ünlem veya `< >` kullanmana gerek yok, direkt yazabilirsin!)_",
    "",
    "🖥️ *Ekran & Sistem*",
    "• `ekran` (veya `ss`) — Ekran görüntüsü al",
    "• `durum` — CPU, RAM, disk, pil raporu",
    "• `pencereler` — Açık pencereleri listele",
    "• `aç chrome` / `aç youtube.com` — Uygulama veya site aç",
    "• `kilitle` — PC ekranını anında kilitle",
    "",
    "📂 *Dosya & Klasör Gezgini*",
    "• `klasör` — Aktif klasördeki dosyaları listele",
    "• `gir masaüstü` / `gir 1` / `geri` — Klasörler arası gez",
    "• `bul fatura` — PC'de dosya ara",
    "• `at 1` veya `at fatura` — Dosyayı cebine gönder",
    "• _(Fotoğraf/PDF atıp açıklamasına `kaydet` yaz → PC'ye kaydeder)_",
    "",
    "📋 *Pano, Ses, Medya & Klavye*",
    "• `pano` — PC'de kopyalananı (Ctrl+C) sana atar",
    "• `kopyala merhaba` — Metni PC panosuna kopyalar",
    "• `ses 50` / `ses kapat` / `ses arttır` / `ses azalt`",
    "• `medya` (oynat/duraklat) | `sonraki` | `önceki`",
    "• `yaz selam` / `yaz-enter selam` — Aktif pencereye yaz",
    "• `tuş enter` / `tuş alt+tab` / `tuş win+d` / `tuş esc`",
    "",
    "🔐 *2 Adımlı Onaylı Kritik Komutlar*",
    "• `calistir <komut>` — PowerShell çalıştır",
    "• `kapat-uyg chrome` — Uygulamayı zorla kapat",
    "• `sil 1` — Dosyayı Geri Dönüşüm Kutusu'na taşı",
    "• `uyut` | `kapat 5` | `yenidenbaslat 5` | `iptal`",
    "• `onay 4829` — Bekleyen kritik işlemi onayla",
    "",
    "🧠 *Yapay Zeka Ajanı*",
    "• `ai <görev>` (veya `agy <görev>`) — Aktif klasörde AI çalıştır",
    "",
    `📁 *Aktif Klasör:* \`${activeWorkspace}\``,
  ].join("\n");
}

function resolveFromListOrPath(arg: string): { path: string; isDir: boolean } | null {
  if (/^\d+$/.test(arg)) {
    const idx = Number.parseInt(arg, 10) - 1;
    if (idx >= 0 && idx < lastListedEntries.length) {
      return {
        path: lastListedEntries[idx].fullPath,
        isDir: Boolean(lastListedEntries[idx].isDir),
      };
    }
    return null;
  }
  const direct = path.resolve(activeWorkspace, arg);
  if (fs.existsSync(direct)) {
    return { path: direct, isDir: fs.statSync(direct).isDirectory() };
  }
  if (fs.existsSync(arg)) {
    return { path: path.resolve(arg), isDir: fs.statSync(arg).isDirectory() };
  }
  return null;
}

async function handleCommand(jid: string, msg: WAMessage, rawText: string): Promise<void> {
  const parsed = parseCommandInput(rawText);
  if (!parsed) return;

  const { cmd, arg } = parsed;

  switch (cmd) {
    case "yardim":
    case "help":
    case "menu":
    case "?": {
      await sendText(jid, helpMessage());
      return;
    }

    case "kaydet": {
      if (!hasIncomingMedia(msg)) {
        await sendText(
          jid,
          "ℹ️ PC'ye kaydetmek için bir fotoğraf veya belge seçip açıklama (caption) kısmına `kaydet` yazarak gönder."
        );
        return;
      }
      const savedMsg = await saveIncomingMedia(msg, arg);
      await sendText(jid, savedMsg);
      return;
    }

    case "durum": {
      await sendText(jid, await getSystemStatus());
      return;
    }

    case "ekran":
    case "ss": {
      const shot = await takeScreenshot();
      await sendFileToJid(
        jid,
        shot.filePath,
        `🖥️ Ekran (${shot.width}x${shot.height}) — ${new Date().toLocaleTimeString("tr-TR")}`
      );
      return;
    }

    case "klasor":
    case "ls": {
      const targetDir = arg
        ? resolveShortcutDir(arg) ?? path.resolve(activeWorkspace, arg)
        : activeWorkspace;
      const entries = listDirectoryEntries(targetDir);
      lastListedEntries = entries;
      await sendText(jid, formatDirectoryList(targetDir, entries));
      return;
    }

    case "gir":
    case "cd":
    case "agy-klasor": {
      if (!arg) {
        await sendText(
          jid,
          `📁 *Aktif Klasör:* \`${activeWorkspace}\`\nİçeriği görmek için \`klasör\` yaz.`
        );
        return;
      }
      const shortcut = resolveShortcutDir(arg);
      let nextDir: string | null = shortcut;

      if (!nextDir) {
        const hit = resolveFromListOrPath(arg);
        if (hit && hit.isDir) {
          nextDir = hit.path;
        }
      }

      if (!nextDir || !fs.existsSync(nextDir) || !fs.statSync(nextDir).isDirectory()) {
        await sendText(
          jid,
          `❌ Klasör bulunamadı: \`${arg}\`\nKısayollar: \`gir masaüstü\`, \`gir indirilenler\`, \`gir belgeler\`, \`gir 1\``
        );
        return;
      }

      activeWorkspace = path.resolve(nextDir);
      const entries = listDirectoryEntries(activeWorkspace);
      lastListedEntries = entries;
      await sendText(jid, formatDirectoryList(activeWorkspace, entries));
      return;
    }

    case "geri":
    case "..": {
      const parent = path.dirname(activeWorkspace);
      activeWorkspace = parent;
      const entries = listDirectoryEntries(activeWorkspace);
      lastListedEntries = entries;
      await sendText(jid, formatDirectoryList(activeWorkspace, entries));
      return;
    }

    case "bul": {
      if (!arg) {
        await sendText(jid, "ℹ️ Kullanım: `bul fatura`");
        return;
      }
      const matches = findFiles(arg, [activeWorkspace, ...getSearchRootsDedup()]);
      lastListedEntries = matches;
      if (matches.length === 0) {
        await sendText(jid, `🔍 "${arg}" için dosya bulunamadı.`);
        return;
      }
      const lines = matches.map(
        (f, i) => `${i + 1}. 📄 *${f.name}* (${formatFileSize(f.sizeBytes)})\n   \`${f.fullPath}\``
      );
      await sendText(
        jid,
        `🔎 *"${arg}" Sonuçları (${matches.length}):*\n\n${lines.join("\n\n")}\n\n📎 İndirmek için: \`at 1\``
      );
      return;
    }

    case "at":
    case "gonder": {
      if (!arg) {
        await sendText(jid, "ℹ️ Kullanım: `at 1` veya `at dosya_adi`");
        return;
      }
      const resolved = resolveFromListOrPath(arg);
      if (resolved && !resolved.isDir) {
        await sendFileToJid(jid, resolved.path, `📎 ${path.basename(resolved.path)}`);
        return;
      }
      if (resolved && resolved.isDir) {
        await sendText(jid, `ℹ️ Bu bir klasör. İçine girmek için \`gir ${arg}\` yaz.`);
        return;
      }

      // Auto-search by name when user types e.g. "at temizlik"
      const matches = findFiles(arg, [activeWorkspace, ...getSearchRootsDedup()], 10);
      lastListedEntries = matches;
      if (matches.length === 0) {
        await sendText(jid, `🔍 "${arg}" adında bir dosya bulunamadı.`);
        return;
      }
      if (matches.length === 1) {
        await sendFileToJid(jid, matches[0].fullPath, `📎 ${matches[0].name}`);
        return;
      }
      const lines = matches.map(
        (f, i) => `${i + 1}. 📄 *${f.name}* (${formatFileSize(f.sizeBytes)})\n   \`${f.fullPath}\``
      );
      await sendText(
        jid,
        `🔎 *"${arg}" için ${matches.length} dosya bulundu:*\n\n${lines.join("\n\n")}\n\nHangisini göndereyim? Örn: \`at 1\``
      );
      return;
    }

    case "ac": {
      if (!arg) {
        await sendText(jid, "ℹ️ Kullanım: `aç chrome`, `aç youtube.com`, `aç spotify`, `aç notepad`");
        return;
      }
      const msgOut = await openAppOrUrl(arg);
      await sendText(jid, msgOut);
      return;
    }

    case "pencereler": {
      await sendText(jid, await listOpenWindows());
      return;
    }

    case "kapat-uyg": {
      if (!arg) {
        await sendText(jid, "ℹ️ Kullanım: `kapat-uyg chrome`");
        return;
      }
      const pending = approvals.create(`Uygulama kapat: ${arg}`, () => closeApplication(arg));
      await sendText(
        jid,
        `⚠️ *Uygulama Kapatma Onayı*\nUygulama: *${arg}*\n\nOnaylamak için yaz: *onay ${pending.code}*`
      );
      return;
    }

    case "pano": {
      await sendText(jid, await getClipboardText());
      return;
    }

    case "kopyala": {
      if (!arg) {
        await sendText(jid, "ℹ️ Kullanım: `kopyala kopyalanacak metin`");
        return;
      }
      await sendText(jid, await setClipboardText(arg));
      return;
    }

    case "ses": {
      await sendText(jid, await controlAudio(arg || "kapat"));
      return;
    }

    case "medya": {
      await sendText(jid, await controlMedia("toggle"));
      return;
    }

    case "sonraki": {
      await sendText(jid, await controlMedia("next"));
      return;
    }

    case "onceki": {
      await sendText(jid, await controlMedia("prev"));
      return;
    }

    case "yaz":
    case "yaz-enter": {
      if (!arg) {
        await sendText(jid, `ℹ️ Kullanım: \`${cmd} yazılacak metin\``);
        return;
      }
      await sendText(jid, await typeTextOnPc(arg, cmd === "yaz-enter"));
      return;
    }

    case "tus": {
      if (!arg) {
        await sendText(
          jid,
          "ℹ️ Kullanım: `tuş enter`, `tuş esc`, `tuş alt+tab`, `tuş win+d`, `tuş ctrl+s`, `tuş f5`"
        );
        return;
      }
      await sendText(jid, await sendShortcutKey(arg));
      return;
    }

    case "kilitle": {
      await sendText(jid, await lockWorkstation());
      return;
    }

    case "uyut": {
      const pending = approvals.create("Bilgisayarı uyku moduna al", () => sleepComputer());
      await sendText(
        jid,
        `⚠️ *Uyku Modu Onayı*\nOnaylamak için yaz: *onay ${pending.code}*`
      );
      return;
    }

    case "iptal": {
      const msgOut = await cancelShutdown();
      const cleared = approvals.cancelAll();
      await sendText(
        jid,
        `${msgOut}${cleared > 0 ? `\n🧹 ${cleared} adet bekleyen onay iptal edildi.` : ""}`
      );
      return;
    }

    case "kapat":
    case "yenidenbaslat": {
      const restart = cmd === "yenidenbaslat";
      const mins = arg ? Number.parseInt(arg, 10) : 1;
      if (Number.isNaN(mins) || mins < 0) {
        await sendText(jid, `ℹ️ Kullanım: \`${cmd} 5\` (5 dakika sonra)`);
        return;
      }
      const label = restart ? `${mins} dk sonra PC yeniden başlatma` : `${mins} dk sonra PC kapatma`;
      const pending = approvals.create(label, () => scheduleShutdown(mins, restart));
      await sendText(
        jid,
        `⚠️ *Kritik İşlem Onayı*\nİşlem: *${label}*\n\nOnaylamak için yaz: *onay ${pending.code}*`
      );
      return;
    }

    case "calistir": {
      if (!arg) {
        await sendText(jid, "ℹ️ Kullanım: `calistir <PowerShell komutu>`");
        return;
      }
      const pending = approvals.create(`PowerShell: ${arg.slice(0, 100)}`, () =>
        runPowerShellCommand(arg, activeWorkspace)
      );
      await sendText(
        jid,
        `⚠️ *Komut Çalıştırma Onayı*\n\`\`\`${arg}\`\`\`\n📁 \`${activeWorkspace}\`\n\nOnaylamak için yaz: *onay ${pending.code}*`
      );
      return;
    }

    case "sil": {
      if (!arg) {
        await sendText(jid, "ℹ️ Kullanım: `sil 1` veya `sil dosya_yolu`");
        return;
      }
      const hit = resolveFromListOrPath(arg);
      if (!hit || hit.isDir) {
        await sendText(jid, `❌ Silinecek dosya bulunamadı: \`${arg}\``);
        return;
      }
      const pending = approvals.create(`Geri Dönüşüm'e taşı: ${hit.path}`, () =>
        moveFileToRecycleBin(hit.path)
      );
      await sendText(
        jid,
        `⚠️ *Dosya Silme Onayı*\nGeri Dönüşüm Kutusu'na taşınacak:\n\`${hit.path}\`\n\nOnaylamak için yaz: *onay ${pending.code}*`
      );
      return;
    }

    case "onay": {
      if (!arg) {
        const list = approvals.listPending();
        if (list.length === 0) {
          await sendText(jid, "ℹ️ Onay bekleyen kritik bir işlem yok.");
        } else {
          const lines = list.map((p) => `• Kod \`${p.code}\` (${p.remainingSec}sn): ${p.description}`);
          await sendText(jid, `⏳ *Onay Bekleyen İşlemler:*\n${lines.join("\n")}`);
        }
        return;
      }
      const pending = approvals.consume(arg);
      if (!pending) {
        await sendText(jid, "❌ Geçersiz veya süresi dolmuş onay kodu.");
        return;
      }
      await sendText(jid, `⏳ Onaylandı, çalıştırılıyor:\n_${pending.description}_`);
      const output = await pending.execute();
      await sendText(jid, output);
      return;
    }

    case "ai":
    case "agy": {
      if (!arg) {
        await sendText(jid, "ℹ️ Kullanım: `ai Bu klasördeki dosyaları özetle`");
        return;
      }
      const executeAgent = async (): Promise<string> => {
        const result = await runRemoteAgent(arg, activeWorkspace);
        if (!result.ok) {
          return `❌ *AI Ajanı Hatası:*\n${result.error ?? "Bilinmeyen hata"}`;
        }
        const toolsText =
          result.toolCalls.length > 0
            ? `\n\n🛠️ *Araçlar:* ${result.toolCalls.slice(0, 10).join(", ")}`
            : "";
        const body =
          result.response.length > 3400
            ? `${result.response.slice(0, 3400)}\n\n... (kısaltıldı)`
            : result.response;
        return `🧠 *AI Yanıtı [${result.backend}]*\n📁 \`${path.basename(activeWorkspace)}\`\n\n${body}${toolsText}`;
      };

      if (isDangerousAgentPrompt(arg)) {
        const pending = approvals.create(`AI Kritik İstek: ${arg.slice(0, 120)}`, executeAgent);
        await sendText(
          jid,
          `⚠️ *Kritik AI İsteği Algılandı!*\nGörev: _${arg.slice(0, 180)}_\n\nOnaylamak için yaz: *onay ${pending.code}*`
        );
        return;
      }

      await sendText(jid, `🧠 AI çalışıyor...\n📁 \`${path.basename(activeWorkspace)}\``);
      await sendText(jid, await executeAgent());
      return;
    }

    default: {
      if (parsed.explicitBang) {
        await sendText(jid, `❓ Bilinmeyen komut: \`${cmd}\`\nKomut listesi için \`yardım\` yaz.`);
      }
    }
  }
}

function getSearchRootsDedup(): string[] {
  const roots = [
    resolveShortcutDir("masaüstü"),
    resolveShortcutDir("indirilenler"),
    resolveShortcutDir("belgeler"),
    ...config.extraSearchDirs,
  ].filter((x): x is string => Boolean(x));
  return Array.from(new Set(roots));
}

function readJsonBody(req: http.IncomingMessage): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    let raw = "";
    req.on("data", (chunk) => {
      raw += chunk.toString("utf-8");
      if (raw.length > 2 * 1024 * 1024) {
        reject(new Error("İstek gövdesi çok büyük."));
      }
    });
    req.on("end", () => {
      try {
        resolve(raw ? (JSON.parse(raw) as Record<string, unknown>) : {});
      } catch {
        reject(new Error("Geçersiz JSON gövdesi."));
      }
    });
    req.on("error", reject);
  });
}

function resolveTargetJid(phone?: string): string {
  if (phone && phone.trim().length > 0) {
    const digits = phone.replace(/\D/g, "");
    if (!digits) throw new Error("Geçersiz telefon numarası.");
    return `${digits}@s.whatsapp.net`;
  }
  if (config.allowedPhone) {
    return `${config.allowedPhone}@s.whatsapp.net`;
  }
  if (ownPhoneJid) {
    return normalizeJid(ownPhoneJid);
  }
  throw new Error("Hedef JID belirlenemedi (WhatsApp bağlı değil).");
}

function startLocalApiServer(): http.Server {
  const server = http.createServer(async (req, res) => {
    res.setHeader("Content-Type", "application/json; charset=utf-8");

    const authHeader = req.headers.authorization ?? "";
    const expected = `Bearer ${config.bridgeApiToken}`;
    if (authHeader !== expected) {
      res.writeHead(401);
      res.end(JSON.stringify({ ok: false, error: "Yetkisiz yerel API isteği." }));
      return;
    }

    try {
      if (req.method === "GET" && req.url === "/health") {
        res.writeHead(200);
        res.end(
          JSON.stringify({
            ok: true,
            connected: isConnected,
            ownJid: normalizeJid(ownPhoneJid),
            activeWorkspace,
          })
        );
        return;
      }

      if (req.method === "POST" && req.url === "/send-message") {
        const body = await readJsonBody(req);
        const text = String(body.text ?? "").trim();
        const phone = typeof body.phone === "string" ? body.phone : undefined;
        if (!text) {
          res.writeHead(400);
          res.end(JSON.stringify({ ok: false, error: "text alanı zorunludur." }));
          return;
        }
        const jid = resolveTargetJid(phone);
        await sendText(jid, text);
        res.writeHead(200);
        res.end(JSON.stringify({ ok: true, to: jid }));
        return;
      }

      if (req.method === "POST" && req.url === "/send-file") {
        const body = await readJsonBody(req);
        const filePath = String(body.filePath ?? "").trim();
        const caption = typeof body.caption === "string" ? body.caption : undefined;
        const phone = typeof body.phone === "string" ? body.phone : undefined;
        if (!filePath) {
          res.writeHead(400);
          res.end(JSON.stringify({ ok: false, error: "filePath alanı zorunludur." }));
          return;
        }
        const jid = resolveTargetJid(phone);
        await sendFileToJid(jid, filePath, caption);
        res.writeHead(200);
        res.end(JSON.stringify({ ok: true, to: jid, filePath }));
        return;
      }

      res.writeHead(404);
      res.end(JSON.stringify({ ok: false, error: "Bilinmeyen endpoint." }));
    } catch (err) {
      res.writeHead(500);
      res.end(JSON.stringify({ ok: false, error: (err as Error).message }));
    }
  });

  server.listen(config.bridgeApiPort, "127.0.0.1", () => {
    logInfo(`🔌 Yerel MCP-WhatsApp API hazır: http://127.0.0.1:${config.bridgeApiPort}`);
  });

  return server;
}

async function connectWhatsApp(): Promise<void> {
  fs.mkdirSync(config.authDir, { recursive: true });
  const { state, saveCreds } = await useMultiFileAuthState(config.authDir);
  const { version } = await fetchLatestBaileysVersion();

  const sock = createSocket({
    version,
    auth: state,
    logger: pino({ level: "silent" }),
    printQRInTerminal: false,
    browser: Browsers.windows("Desktop"),
    syncFullHistory: false,
  });

  activeSocket = sock;
  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      console.log("\n📱 WhatsApp → Bağlı Cihazlar → Cihaz Bağla ile bu QR kodu okut:\n");
      qrcode.generate(qr, { small: true });
    }

    if (connection === "open") {
      isConnected = true;
      loggedOutRetries = 0;
      ownPhoneJid = sock.user?.id || state.creds.me?.id || "";
      ownLid =
        (sock.user as { lid?: string } | undefined)?.lid ||
        (state.creds.me as { lid?: string } | undefined)?.lid ||
        "";
      logInfo(
        `✅ WhatsApp bağlantısı kuruldu! Hesap: ${normalizeJid(ownPhoneJid)} | LID: ${normalizeJid(ownLid)}`
      );
      logInfo("ℹ️  WhatsApp'ta KENDİ SOHBETİNE 'yardım' yazarak başlayabilirsin.");
    }

    if (connection === "close") {
      isConnected = false;
      const statusCode = (lastDisconnect?.error as Boom | undefined)?.output?.statusCode;
      if (statusCode === DisconnectReason.loggedOut) {
        loggedOutRetries += 1;
        if (loggedOutRetries <= 3) {
          logInfo(
            "⚠️ Oturum geçersiz (401). Eski auth_info temizleniyor ve yeni QR kodu hazırlanıyor..."
          );
          try {
            fs.rmSync(config.authDir, { recursive: true, force: true });
          } catch {
            // ignore cleanup error
          }
          setTimeout(() => {
            void connectWhatsApp();
          }, 2000);
        } else {
          logInfo("❌ 3 kez 401 hatası alındı. Lütfen bağlantıyı kontrol edip tekrar başlat.");
        }
        return;
      }

      const delayMs = statusCode === DisconnectReason.restartRequired ? 1000 : 5000;
      logInfo(
        `⚠️ WhatsApp bağlantısı yenileniyor (kod: ${statusCode ?? "bilinmiyor"}). ${
          delayMs / 1000
        } sn içinde yeniden bağlanılıyor...`
      );
      setTimeout(() => {
        void connectWhatsApp();
      }, delayMs);
    }
  });

  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    const nowSec = Math.floor(Date.now() / 1000);

    for (const msg of messages) {
      const msgId = msg.key.id;
      if (msgId && (sentMessageIds.has(msgId) || processedMessageIds.has(msgId))) continue;

      const rawTs = Number(msg.messageTimestamp ?? 0);
      if (type !== "notify") {
        if (!rawTs || Math.abs(nowSec - rawTs) > 30) continue;
      }

      const remoteJid = msg.key.remoteJid;
      const fromMe = Boolean(msg.key.fromMe);
      const text = extractText(msg).trim();
      if (!text) continue;

      const parsed = parseCommandInput(text);
      if (!parsed) continue;

      const authorized = isAuthorizedChat({
        remoteJid,
        fromMe,
        ownPhoneJid,
        ownLid,
        allowedPhone: config.allowedPhone,
      });

      if (!authorized) {
        continue;
      }

      rememberId(processedMessageIds, msgId);
      logInfo(`📩 Komut [${parsed.cmd}${parsed.arg ? ` ${parsed.arg}` : ""}]: ${text}`);
      try {
        await handleCommand(remoteJid!, msg, text);
      } catch (err) {
        logInfo(`❌ Komut işleme hatası: ${(err as Error).message}`);
        try {
          await sendText(remoteJid!, `❌ Hata: ${(err as Error).message}`);
        } catch {
          // ignore secondary send failure
        }
      }
    }
  });
}

process.on("uncaughtException", (err) => {
  logInfo(`🔥 Yakalanmayan hata: ${err.stack ?? err.message}`);
});

process.on("unhandledRejection", (reason) => {
  logInfo(`🔥 Yakalanmayan Promise reddi: ${String(reason)}`);
});

async function main(): Promise<void> {
  logInfo("🚀 WP-PC Pilot v2 başlatılıyor...");
  logInfo(`📁 Varsayılan Ajan Klasörü: ${activeWorkspace}`);
  logInfo(`🧠 AI Ajan Arka Ucu: ${config.agentBackend}`);
  startLocalApiServer();
  await connectWhatsApp();
}

// Only start server when executed directly (allows importing parseCommandInput in unit tests)
const isDirectRun = process.argv[1] && path.resolve(process.argv[1]).endsWith("bridge.js");
if (isDirectRun) {
  void main();
}
