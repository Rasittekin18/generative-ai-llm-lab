"""LLM ve VLM sağlayıcı soyutlama katmanı (Ollama yerel + Gemini/OpenAI opsiyonel)."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

import httpx

from config import Settings


VISION_NAME_HINTS = (
    "vl",
    "vision",
    "llava",
    "minicpm-v",
    "moondream",
    "bakllava",
    "pixtral",
    "gemma3",
    "llama3.2-vision",
    "granite3.2-vision",
)


class ProviderError(RuntimeError):
    """Sağlayıcı iletişim veya yanıt hatası."""


class VisionModelUnavailableError(ProviderError):
    """Görsel okuyabilen (VLM) bir model aktif olmadığında fırlatılır."""


def strip_thinking_tags(text: str) -> str:
    """Qwen3 gibi modellerin <think>...</think> bloklarını temizler."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()


def extract_json_object(text: str) -> dict[str, Any]:
    """Model çıktısından güvenli biçimde JSON nesnesi ayrıştırır."""
    cleaned = strip_thinking_tags(text)
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        candidate = cleaned[start : end + 1]
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError as exc:
            raise ProviderError(f"JSON ayrıştırma hatası: {exc}") from exc

    raise ProviderError(f"Model yanıtında geçerli JSON bulunamadı: {cleaned[:250]}")


class LLMRouter:
    """Yerel Ollama ve opsiyonel bulut API sağlayıcılarını tek arayüzde toplar."""

    def __init__(self, settings: Settings):
        self.settings = settings

    # ------------------------------------------------------------------
    # Ollama Sağlık & Model Keşfi
    # ------------------------------------------------------------------
    def check_ollama_health(self) -> dict[str, Any]:
        """Ollama sunucusunun durumunu ve yüklü modelleri döndürür."""
        base = self.settings.ollama_base_url.rstrip("/")
        model_names: list[str] = []
        vision_models: list[str] = []

        try:
            with httpx.Client(timeout=10.0, trust_env=False) as client:
                resp = client.get(f"{base}/api/tags")
                resp.raise_for_status()
                data = resp.json()

                models_raw = data.get("models", [])
                for item in models_raw:
                    name = item.get("name", "")
                    if not name:
                        continue
                    model_names.append(name)
                    is_vision = any(hint in name.lower() for hint in VISION_NAME_HINTS)
                    if not is_vision:
                        try:
                            show_resp = client.post(f"{base}/api/show", json={"model": name})
                            if show_resp.status_code == 200:
                                caps = show_resp.json().get("capabilities", [])
                                if isinstance(caps, list) and "vision" in caps:
                                    is_vision = True
                        except Exception:
                            pass
                    if is_vision:
                        vision_models.append(name)
        except Exception as exc:
            return {
                "running": False,
                "error": str(exc),
                "models": [],
                "vision_models": [],
                "recommended_llm": self.settings.ollama_llm_model,
            }

        recommended_llm = self._pick_best_ollama_llm(model_names)
        return {
            "running": True,
            "error": None,
            "models": model_names,
            "vision_models": vision_models,
            "recommended_llm": recommended_llm,
        }

    def _pick_best_ollama_llm(self, installed: list[str]) -> str:
        """Yüklü modeller arasından yapılandırılan veya en iyi alternatifi seçer."""
        configured = self.settings.ollama_llm_model
        if configured in installed:
            return configured
        for preferred in ("qwen3:4b", "qwen2.5:3b", "qwen2.5:7b", "llama3.2:3b", "gemma3:4b"):
            if preferred in installed:
                return preferred
        return installed[0] if installed else configured

    def _pick_ollama_vlm(self, health: dict[str, Any]) -> Optional[str]:
        vision_models = health.get("vision_models", [])
        if self.settings.ollama_vlm_model in vision_models:
            return self.settings.ollama_vlm_model
        return vision_models[0] if vision_models else None

    # ------------------------------------------------------------------
    # Metin LLM Çağrıları
    # ------------------------------------------------------------------
    def chat(
        self,
        messages: list[dict[str, str]],
        json_mode: bool = False,
        temperature: float = 0.1,
    ) -> tuple[str, str]:
        """(yanıt_metni, kullanılan_model) döndürür."""
        provider = self.settings.llm_provider.lower()
        if provider == "gemini":
            if not self.settings.gemini_api_key:
                raise ProviderError("Gemini API anahtarı tanımlı değil. Lütfen Model Ayarları'ndan ekleyin.")
            return self._gemini_chat(messages, json_mode=json_mode, temperature=temperature)
        if provider == "openai":
            if not self.settings.openai_api_key:
                raise ProviderError("OpenAI / Uyumlu API anahtarı tanımlı değil. Lütfen Model Ayarları'ndan ekleyin.")
            return self._openai_chat(messages, json_mode=json_mode, temperature=temperature)
        return self._ollama_chat(messages, json_mode=json_mode, temperature=temperature)

    def chat_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.05,
    ) -> tuple[dict[str, Any], str]:
        """JSON nesnesi döndüren LLM çağrısı yapar (bozuk JSON'da 1 kez düzeltme dener)."""
        text, model_used = self.chat(messages, json_mode=True, temperature=temperature)
        try:
            return extract_json_object(text), model_used
        except ProviderError:
            retry_msgs = messages + [
                {"role": "assistant", "content": text},
                {
                    "role": "user",
                    "content": "Lütfen yanıtını açıklama eklemeden YALNIZCA geçerli bir JSON nesnesi olarak ver.",
                },
            ]
            text2, model_used = self.chat(retry_msgs, json_mode=True, temperature=0.0)
            return extract_json_object(text2), model_used

    def _ollama_chat(
        self,
        messages: list[dict[str, Any]],
        json_mode: bool = False,
        temperature: float = 0.1,
        model_override: Optional[str] = None,
    ) -> tuple[str, str]:
        base = self.settings.ollama_base_url.rstrip("/")
        model = model_override
        if not model:
            health = self.check_ollama_health()
            if not health["running"]:
                raise ProviderError(
                    "Ollama sunucusuna bağlanılamadı (127.0.0.1:11434). Lütfen Ollama'yı başlatın."
                )
            model = health["recommended_llm"]

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if json_mode:
            payload["format"] = "json"
        if "qwen3" in model.lower():
            payload["think"] = False

        try:
            with httpx.Client(timeout=float(self.settings.ollama_timeout_sec), trust_env=False) as client:
                resp = client.post(f"{base}/api/chat", json=payload)
                if resp.status_code == 400 and "think" in payload:
                    payload.pop("think", None)
                    resp = client.post(f"{base}/api/chat", json=payload)
                resp.raise_for_status()
                content = resp.json().get("message", {}).get("content", "")
                return strip_thinking_tags(content), f"ollama/{model}"
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama API hatası ({model}): {exc}") from exc

    # ------------------------------------------------------------------
    # Görsel Dil Modeli (VLM) Çağrıları
    # ------------------------------------------------------------------
    def chat_vision_json(
        self,
        system_prompt: str,
        user_prompt: str,
        images_b64: list[str],
        mime_type: str = "image/png",
    ) -> tuple[dict[str, Any], str]:
        """Görsellerden yapılandırılmış JSON çıkarır."""
        vp = self.settings.vlm_provider.lower()

        if vp in ("auto", "ollama"):
            health = self.check_ollama_health()
            if health["running"]:
                vlm_model = self._pick_ollama_vlm(health)
                if vlm_model:
                    messages: list[dict[str, Any]] = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt, "images": images_b64},
                    ]
                    text, used = self._ollama_chat(
                        messages,
                        json_mode=True,
                        temperature=0.05,
                        model_override=vlm_model,
                    )
                    try:
                        return extract_json_object(text), used
                    except ProviderError:
                        retry_msgs = messages + [
                            {"role": "assistant", "content": text},
                            {
                                "role": "user",
                                "content": "Lütfen yanıtını açıklama eklemeden YALNIZCA geçerli bir JSON nesnesi olarak ver.",
                            },
                        ]
                        text2, used = self._ollama_chat(
                            retry_msgs,
                            json_mode=True,
                            temperature=0.0,
                            model_override=vlm_model,
                        )
                        return extract_json_object(text2), used
            if vp == "ollama":
                raise VisionModelUnavailableError(
                    f"Ollama üzerinde görsel model bulunamadı. 'ollama pull {self.settings.ollama_vlm_model}' çalıştırın."
                )

        if vp in ("auto", "gemini"):
            if self.settings.gemini_api_key:
                return self._gemini_vision_json(system_prompt, user_prompt, images_b64, mime_type)
            if vp == "gemini":
                raise VisionModelUnavailableError("Gemini API anahtarı tanımlı değil. Lütfen Model Ayarları'ndan ekleyin.")

        if vp in ("auto", "openai"):
            if self.settings.openai_api_key:
                return self._openai_vision_json(system_prompt, user_prompt, images_b64, mime_type)
            if vp == "openai":
                raise VisionModelUnavailableError("OpenAI API anahtarı tanımlı değil. Lütfen Model Ayarları'ndan ekleyin.")

        raise VisionModelUnavailableError(
            f"Görsel okuyabilen VLM modeli hazır değil. Yerelde 'ollama pull {self.settings.ollama_vlm_model}' "
            "komutunu çalıştırabilir veya Ayarlar bölümünden Gemini / OpenAI API anahtarı ekleyebilirsiniz."
        )

    # ------------------------------------------------------------------
    # Opsiyonel Bulut Sağlayıcılar (Gemini / OpenAI-uyumlu)
    # ------------------------------------------------------------------
    def _gemini_chat(
        self,
        messages: list[dict[str, str]],
        json_mode: bool = False,
        temperature: float = 0.1,
    ) -> tuple[str, str]:
        try:
            import google.generativeai as genai

            genai.configure(api_key=self.settings.gemini_api_key)
            system_parts = [m["content"] for m in messages if m["role"] == "system"]
            prompt_parts = [f"{m['role'].upper()}: {m['content']}" for m in messages if m["role"] != "system"]
            model = genai.GenerativeModel(
                model_name=self.settings.gemini_model,
                system_instruction="\n".join(system_parts) if system_parts else None,
            )
            gen_cfg: dict[str, Any] = {"temperature": temperature}
            if json_mode:
                gen_cfg["response_mime_type"] = "application/json"
            resp = model.generate_content("\n\n".join(prompt_parts), generation_config=gen_cfg)
            return (resp.text or "").strip(), f"gemini/{self.settings.gemini_model}"
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Gemini API hatası ({self.settings.gemini_model}): {exc}") from exc

    def _gemini_vision_json(
        self,
        system_prompt: str,
        user_prompt: str,
        images_b64: list[str],
        mime_type: str,
    ) -> tuple[dict[str, Any], str]:
        try:
            import base64
            import google.generativeai as genai

            genai.configure(api_key=self.settings.gemini_api_key)
            model = genai.GenerativeModel(
                model_name=self.settings.gemini_model,
                system_instruction=system_prompt,
            )
            parts: list[Any] = [user_prompt]
            for b64 in images_b64:
                parts.append({"mime_type": mime_type, "data": base64.b64decode(b64)})
            resp = model.generate_content(
                parts,
                generation_config={"temperature": 0.05, "response_mime_type": "application/json"},
            )
            return extract_json_object(resp.text or ""), f"gemini/{self.settings.gemini_model}"
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Gemini Vision API hatası ({self.settings.gemini_model}): {exc}") from exc

    def _openai_chat(
        self,
        messages: list[dict[str, str]],
        json_mode: bool = False,
        temperature: float = 0.1,
    ) -> tuple[str, str]:
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=self.settings.openai_api_key,
                base_url=self.settings.openai_base_url,
            )
            kwargs: dict[str, Any] = {
                "model": self.settings.openai_model,
                "messages": messages,
                "temperature": temperature,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            resp = client.chat.completions.create(**kwargs)
            content = resp.choices[0].message.content or ""
            return content.strip(), f"openai/{self.settings.openai_model}"
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"OpenAI API hatası ({self.settings.openai_model}): {exc}") from exc

    def _openai_vision_json(
        self,
        system_prompt: str,
        user_prompt: str,
        images_b64: list[str],
        mime_type: str,
    ) -> tuple[dict[str, Any], str]:
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=self.settings.openai_api_key,
                base_url=self.settings.openai_base_url,
            )
            content_parts: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
            for b64 in images_b64:
                content_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                    }
                )
            resp = client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content_parts},
                ],
                temperature=0.05,
                response_format={"type": "json_object"},
            )
            text = resp.choices[0].message.content or ""
            return extract_json_object(text), f"openai/{self.settings.openai_model}"
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"OpenAI Vision API hatası ({self.settings.openai_model}): {exc}") from exc
