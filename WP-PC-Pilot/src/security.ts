import crypto from "node:crypto";

export interface PendingApproval {
  code: string;
  description: string;
  createdAt: number;
  expiresAt: number;
  execute: () => Promise<string>;
}

/**
 * Strips WhatsApp multi-device suffix (e.g. "905551234567:12@s.whatsapp.net" -> "905551234567@s.whatsapp.net")
 */
export function normalizeJid(jid: string | null | undefined): string {
  if (!jid) return "";
  const [userPart, domainPart] = jid.split("@");
  if (!domainPart) return jid.toLowerCase();
  const baseUser = userPart.split(":")[0];
  return `${baseUser}@${domainPart}`.toLowerCase();
}

export interface SenderAuthInput {
  remoteJid: string | null | undefined;
  fromMe: boolean;
  ownPhoneJid: string | null | undefined;
  ownLid: string | null | undefined;
  allowedPhone: string;
}

/**
 * Only allows messages from your own WhatsApp Self-Chat ("Kendime Mesaj")
 * or an explicitly whitelisted personal phone JID (never groups or other chats).
 */
export function isAuthorizedChat(input: SenderAuthInput): boolean {
  const normRemote = normalizeJid(input.remoteJid);
  if (!normRemote) return false;
  if (normRemote.endsWith("@g.us") || normRemote.endsWith("@broadcast") || normRemote === "status@broadcast") {
    return false;
  }

  const normOwnPhone = normalizeJid(input.ownPhoneJid);
  const normOwnLid = normalizeJid(input.ownLid);

  const isOwnSelfChat =
    input.fromMe &&
    ((normOwnPhone.length > 0 && normRemote === normOwnPhone) ||
      (normOwnLid.length > 0 && normRemote === normOwnLid));

  if (input.allowedPhone.length > 0) {
    const allowedJid = `${input.allowedPhone}@s.whatsapp.net`.toLowerCase();
    return normRemote === allowedJid || isOwnSelfChat;
  }

  return isOwnSelfChat;
}

const DANGEROUS_AGENT_PATTERNS: RegExp[] = [
  /\bshutdown\b/i,
  /\brestart-computer\b/i,
  /\bstop-computer\b/i,
  /\bformat\s+[a-z]:/i,
  /\brm\s+-rf\b/i,
  /\bremove-item\b.*-recurse/i,
  /\bdel\s+\/[fsq]/i,
  /\brd\s+\/s/i,
  /\breg\s+delete\b/i,
  /\btaskkill\b/i,
  /\bstop-process\b/i,
  /\bdiskpart\b/i,
  /bilgisayar[ıi]\s+kapat/i,
  /t[üu]m\s+dosyalar[ıi]\s+sil/i,
];

export function isDangerousAgentPrompt(prompt: string): boolean {
  return DANGEROUS_AGENT_PATTERNS.some((pattern) => pattern.test(prompt));
}

export class ApprovalManager {
  private readonly pending = new Map<string, PendingApproval>();
  private readonly ttlMs: number;

  constructor(ttlMs = 120_000) {
    this.ttlMs = ttlMs;
  }

  private pruneExpired(now = Date.now()): void {
    for (const [code, item] of this.pending.entries()) {
      if (item.expiresAt <= now) {
        this.pending.delete(code);
      }
    }
  }

  create(description: string, execute: () => Promise<string>): PendingApproval {
    this.pruneExpired();
    let code = "";
    for (let attempt = 0; attempt < 20; attempt++) {
      const candidate = String(crypto.randomInt(1000, 10000));
      if (!this.pending.has(candidate)) {
        code = candidate;
        break;
      }
    }
    if (!code) {
      code = String(crypto.randomInt(10000, 99999));
    }

    const now = Date.now();
    const record: PendingApproval = {
      code,
      description,
      createdAt: now,
      expiresAt: now + this.ttlMs,
      execute,
    };
    this.pending.set(code, record);
    return record;
  }

  consume(code: string): PendingApproval | null {
    this.pruneExpired();
    const cleaned = code.trim();
    const record = this.pending.get(cleaned);
    if (!record) return null;
    this.pending.delete(cleaned);
    return record;
  }

  cancelAll(): number {
    const count = this.pending.size;
    this.pending.clear();
    return count;
  }

  listPending(): Array<{ code: string; description: string; remainingSec: number }> {
    const now = Date.now();
    this.pruneExpired(now);
    return Array.from(this.pending.values()).map((item) => ({
      code: item.code,
      description: item.description,
      remainingSec: Math.max(0, Math.ceil((item.expiresAt - now) / 1000)),
    }));
  }
}
