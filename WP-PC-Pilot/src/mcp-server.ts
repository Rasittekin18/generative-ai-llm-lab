import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { config } from "./config.js";
import {
  findFiles,
  formatFileSize,
  getSystemStatus,
  resolveSafeFile,
  takeScreenshot,
} from "./pc-tools.js";

const server = new McpServer({
  name: "wp-pc-pilot",
  version: "1.0.0",
});

async function callBridgeApi(
  endpoint: string,
  method: "GET" | "POST",
  body?: Record<string, unknown>
): Promise<Record<string, unknown>> {
  const url = `http://127.0.0.1:${config.bridgeApiPort}${endpoint}`;
  const res = await fetch(url, {
    method,
    headers: {
      Authorization: `Bearer ${config.bridgeApiToken}`,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  const data = (await res.json()) as Record<string, unknown>;
  if (!res.ok || data.ok === false) {
    throw new Error(String(data.error ?? `Bridge API hatası (HTTP ${res.status})`));
  }
  return data;
}

server.tool(
  "pc_system_status",
  "Bilgisayarın anlık CPU, RAM, disk, pil ve en çok kaynak kullanan işlem durumunu getirir.",
  {},
  async () => {
    const report = await getSystemStatus();
    return {
      content: [{ type: "text", text: report }],
    };
  }
);

server.tool(
  "pc_take_screenshot",
  "Windows masaüstünün anlık ekran görüntüsünü PNG olarak kaydeder ve dosya yolunu döner.",
  {},
  async () => {
    const shot = await takeScreenshot();
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify(
            {
              filePath: shot.filePath,
              width: shot.width,
              height: shot.height,
            },
            null,
            2
          ),
        },
      ],
    };
  }
);

server.tool(
  "pc_find_files",
  "Masaüstü, Belgeler, İndirilenler veya belirtilen klasörde dosya adı arar.",
  {
    query: z.string().min(1).describe("Aranacak dosya adı veya parçası"),
    directory: z
      .string()
      .optional()
      .describe("Opsiyonel özel arama klasörü (tam yol)"),
    maxResults: z
      .number()
      .int()
      .min(1)
      .max(30)
      .default(10)
      .describe("Dönecek maksimum sonuç sayısı"),
  },
  async ({ query, directory, maxResults }) => {
    const matches = findFiles(
      query,
      directory ? [directory] : undefined,
      maxResults
    );
    if (matches.length === 0) {
      return {
        content: [{ type: "text", text: `"${query}" için eşleşen dosya bulunamadı.` }],
      };
    }
    const formatted = matches
      .map(
        (m, i) =>
          `${i + 1}. ${m.name} (${formatFileSize(m.sizeBytes)}) — ${m.fullPath}`
      )
      .join("\n");
    return {
      content: [{ type: "text", text: formatted }],
    };
  }
);

server.tool(
  "wp_bridge_status",
  "Yerel WhatsApp köprüsünün çalışıp çalışmadığını ve bağlantı durumunu kontrol eder.",
  {},
  async () => {
    try {
      const data = await callBridgeApi("/health", "GET");
      return {
        content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
      };
    } catch (err) {
      return {
        content: [
          {
            type: "text",
            text: `WhatsApp köprüsüne ulaşılamadı (${(err as Error).message}). Önce "npm run start:bridge" çalışıyor olmalı.`,
          },
        ],
        isError: true,
      };
    }
  }
);

server.tool(
  "wp_send_message",
  "Aktif WhatsApp köprüsü üzerinden kendine (veya belirtilen numaraya) WhatsApp mesajı gönderir.",
  {
    text: z.string().min(1).describe("Gönderilecek WhatsApp mesaj metni"),
    phone: z
      .string()
      .optional()
      .describe(
        "Opsiyonel hedef telefon numarası (ülke koduyla, örn: 905551234567). Boş bırakılırsa kendi sohbetine gönderir."
      ),
  },
  async ({ text, phone }) => {
    const data = await callBridgeApi("/send-message", "POST", { text, phone });
    return {
      content: [
        {
          type: "text",
          text: `✅ WhatsApp mesajı gönderildi → ${String(data.to)}`,
        },
      ],
    };
  }
);

server.tool(
  "wp_send_file",
  "Bilgisayardaki bir dosyayı veya ekran görüntüsünü WhatsApp üzerinden gönderir.",
  {
    filePath: z.string().min(1).describe("Gönderilecek dosyanın tam yolu"),
    caption: z.string().optional().describe("Dosya ile birlikte gönderilecek açıklama"),
    phone: z
      .string()
      .optional()
      .describe("Opsiyonel hedef telefon numarası. Boşsa kendi sohbetine gönderir."),
  },
  async ({ filePath, caption, phone }) => {
    const resolved = resolveSafeFile(filePath);
    const data = await callBridgeApi("/send-file", "POST", {
      filePath: resolved.fullPath,
      caption,
      phone,
    });
    return {
      content: [
        {
          type: "text",
          text: `✅ Dosya WhatsApp ile gönderildi: ${resolved.fileName} → ${String(data.to)}`,
        },
      ],
    };
  }
);

async function start(): Promise<void> {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("wp-pc-pilot MCP sunucusu stdio üzerinden hazır.");
}

void start();
