"""
WP-PC Pilot — Uzaktan AI Ajanı Çalıştırıcı (Antigravity Python SDK + Gemini Fallback)

Stdin'den JSON alır:
  { "prompt": "...", "workspace": "C:\\...", "backend": "auto|antigravity|gemini", "dryRun": false }
Stdout'a tek satır JSON döner:
  { "ok": true, "backend": "antigravity|gemini", "response": "...", "toolCalls": [...], "error": null }
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# .env dosyasını wp-pc-pilot kökünden yükle
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

SYSTEM_PROMPT_TR = (
    "Sen kullanıcının Windows bilgisayarında WhatsApp üzerinden uzaktan tetiklenen "
    "kıdemli bir yazılım ve bilgisayar asistanısın. Yanıtlarını Türkçe, net, öz ve "
    "WhatsApp'tan okunması kolay olacak şekilde yaz. Çalışma klasörü içindeki "
    "dosyaları okuyabilir, düzenleyebilir ve geliştirme komutlarını çalıştırabilirsin. "
    "Yaptığın önemli dosya değişikliklerini veya komut sonuçlarını kısaca maddeleyerek bildir."
)


async def run_antigravity(prompt: str, workspace: str) -> dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY eksik. Ücretsiz anahtar için https://aistudio.google.com/apikey "
            "adresinden anahtar alıp wp-pc-pilot/.env dosyasına GEMINI_API_KEY=... olarak ekle."
        )

    from google.antigravity import Agent, CapabilitiesConfig, LocalAgentConfig
    from google.antigravity.hooks import policy

    os.chdir(workspace)
    tool_calls: list[str] = []
    chunks: list[str] = []

    config = LocalAgentConfig(
        system_instructions=f"{SYSTEM_PROMPT_TR}\nAktif çalışma klasörü: {workspace}",
        capabilities=CapabilitiesConfig(),
        policies=[policy.allow_all()],
        workspaces=[workspace],
        api_key=api_key,
    )

    async with Agent(config) as agent:
        response = await agent.chat(prompt)

        async def collect_text() -> None:
            async for token in response:
                chunks.append(str(token))

        async def collect_tools() -> None:
            if hasattr(response, "tool_calls"):
                async for call in response.tool_calls:
                    name = getattr(call, "name", str(call))
                    tool_calls.append(str(name))

        await asyncio.gather(collect_text(), collect_tools())

    text = "".join(chunks).strip()
    return {
        "ok": True,
        "backend": "antigravity",
        "response": text or "Görev tamamlandı (metin çıktısı boş).",
        "toolCalls": tool_calls,
    }


def _safe_resolve_in_workspace(workspace: Path, relative_path: str) -> Path:
    target = (workspace / relative_path).resolve()
    ws_resolved = workspace.resolve()
    if target != ws_resolved and ws_resolved not in target.parents:
        raise ValueError(f"Güvenlik engeli: Yol çalışma klasörü dışına çıkamaz ({relative_path})")
    return target


def run_gemini(prompt: str, workspace: str) -> dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY tanımlı değil. Ücretsiz anahtar için Google AI Studio'dan "
            "(https://aistudio.google.com/apikey) alıp .env dosyasına ekle."
        )

    from google import genai
    from google.genai import types

    ws_path = Path(workspace).resolve()
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    tool_calls: list[str] = []

    def list_workspace_files(subdir: str = ".") -> str:
        """Çalışma klasöründeki dosya ve alt klasörleri listeler."""
        tool_calls.append(f"list_workspace_files({subdir})")
        target = _safe_resolve_in_workspace(ws_path, subdir)
        if not target.exists():
            return f"Klasör bulunamadı: {subdir}"
        items = []
        for entry in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:80]:
            prefix = "[DIR] " if entry.is_dir() else "[FILE]"
            items.append(f"{prefix} {entry.name}")
        return "\n".join(items) if items else "(boş klasör)"

    def read_workspace_file(relative_path: str) -> str:
        """Çalışma klasörü içindeki bir metin dosyasını okur."""
        tool_calls.append(f"read_workspace_file({relative_path})")
        target = _safe_resolve_in_workspace(ws_path, relative_path)
        if not target.is_file():
            return f"Dosya bulunamadı: {relative_path}"
        content = target.read_text(encoding="utf-8", errors="replace")
        return content[:12000]

    def write_workspace_file(relative_path: str, content: str) -> str:
        """Çalışma klasörü içine yeni dosya yazar veya mevcut dosyayı günceller."""
        tool_calls.append(f"write_workspace_file({relative_path})")
        target = _safe_resolve_in_workspace(ws_path, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Kaydedildi: {target}"

    def run_workspace_command(command: str) -> str:
        """Çalışma klasörü içinde güvenli bir PowerShell geliştirme komutu çalıştırır."""
        tool_calls.append(f"run_workspace_command({command[:40]})")
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=str(ws_path),
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        out = (proc.stdout or "") + ("\n[STDERR]\n" + proc.stderr if proc.stderr else "")
        return (out.strip() or "(çıktı yok)")[:6000]

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=f"{SYSTEM_PROMPT_TR}\nAktif çalışma klasörü: {ws_path}",
            tools=[
                list_workspace_files,
                read_workspace_file,
                write_workspace_file,
                run_workspace_command,
            ],
        ),
    )

    return {
        "ok": True,
        "backend": f"gemini ({model_name})",
        "response": (response.text or "Görev tamamlandı.").strip(),
        "toolCalls": tool_calls,
    }


def check_backends() -> dict[str, Any]:
    agy_installed = False
    gemini_installed = False
    try:
        import google.antigravity  # noqa: F401
        agy_installed = True
    except Exception:
        agy_installed = False

    try:
        import google.genai  # noqa: F401
        gemini_installed = True
    except Exception:
        gemini_installed = False

    return {
        "ok": True,
        "backend": "diagnostics",
        "response": json.dumps(
            {
                "antigravityInstalled": agy_installed,
                "geminiInstalled": gemini_installed,
                "geminiKeyConfigured": bool(os.getenv("GEMINI_API_KEY", "").strip()),
            },
            ensure_ascii=False,
        ),
        "toolCalls": [],
    }


async def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"ok": False, "backend": "none", "response": "", "toolCalls": [], "error": "Boş girdi."}))
        return

    req = json.loads(raw)
    if req.get("dryRun"):
        print(json.dumps(check_backends(), ensure_ascii=False))
        return

    prompt = str(req.get("prompt", "")).strip()
    workspace = str(req.get("workspace", str(PROJECT_ROOT))).strip() or str(PROJECT_ROOT)
    backend = str(req.get("backend", os.getenv("AGENT_BACKEND", "auto"))).lower()

    if not prompt:
        print(json.dumps({"ok": False, "backend": backend, "response": "", "toolCalls": [], "error": "Prompt boş."}))
        return

    if backend == "antigravity":
        try:
            res = await run_antigravity(prompt, workspace)
        except Exception as exc:
            res = {
                "ok": False,
                "backend": "antigravity",
                "response": "",
                "toolCalls": [],
                "error": f"Antigravity SDK hatası: {exc}",
            }
        print(json.dumps(res, ensure_ascii=False))
        return

    if backend == "gemini":
        try:
            res = run_gemini(prompt, workspace)
        except Exception as exc:
            res = {
                "ok": False,
                "backend": "gemini",
                "response": "",
                "toolCalls": [],
                "error": f"Gemini API hatası: {exc}",
            }
        print(json.dumps(res, ensure_ascii=False))
        return

    # backend == "auto": önce Antigravity SDK dene, başarısız olursa Gemini API'ye düş
    agy_error = ""
    try:
        res = await run_antigravity(prompt, workspace)
        print(json.dumps(res, ensure_ascii=False))
        return
    except Exception as exc:
        agy_error = str(exc)

    if os.getenv("GEMINI_API_KEY", "").strip():
        try:
            res = run_gemini(prompt, workspace)
            res["response"] = f"_(Antigravity SDK yerine Gemini kullanıldı)_\n\n{res['response']}"
            print(json.dumps(res, ensure_ascii=False))
            return
        except Exception as g_exc:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "backend": "auto",
                        "response": "",
                        "toolCalls": [],
                        "error": f"Antigravity hatası: {agy_error} | Gemini hatası: {g_exc}",
                    },
                    ensure_ascii=False,
                )
            )
            return

    print(
        json.dumps(
            {
                "ok": False,
                "backend": "auto",
                "response": "",
                "toolCalls": [],
                "error": (
                    f"Antigravity SDK çalıştırılamadı ({agy_error}) ve .env dosyasında "
                    "fallback için GEMINI_API_KEY tanımlı değil."
                ),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
