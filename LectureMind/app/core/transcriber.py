"""Faster-Whisper tabanlı zaman damgalı ses transkripsiyon modülü."""

from pathlib import Path
from typing import Any, Callable

import ctranslate2
from faster_whisper import WhisperModel


ProgressCallback = Callable[[int, str], None]


class LectureTranscriber:
    """CUDA (GTX 1650) ve CPU arasında otomatik geçiş yapan Whisper motoru."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str, str], WhisperModel] = {}

    def _resolve_device_candidates(self, preferred: str) -> list[tuple[str, str]]:
        if preferred == "cpu":
            return [("cpu", "int8")]
        has_cuda = False
        try:
            has_cuda = ctranslate2.get_cuda_device_count() > 0
        except Exception:
            has_cuda = False

        if preferred == "cuda" or (preferred == "auto" and has_cuda):
            return [("cuda", "int8_float16"), ("cuda", "float16"), ("cpu", "int8")]
        return [("cpu", "int8")]

    def _load_model(self, model_size: str, device: str, compute_type: str) -> WhisperModel:
        key = (model_size, device, compute_type)
        if key not in self._cache:
            self._cache[key] = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
            )
        return self._cache[key]

    def transcribe(
        self,
        audio_path: Path,
        model_size: str = "small",
        device_pref: str = "auto",
        language: str | None = None,
        duration_sec: float = 0.0,
        on_progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        """Ses dosyasını zaman damgalı segmentlere çevirir."""
        candidates = self._resolve_device_candidates(device_pref)
        last_error: Exception | None = None

        for device, compute_type in candidates:
            try:
                if on_progress:
                    on_progress(22, f"Whisper ({model_size}, {device}) yükleniyor...")
                model = self._load_model(model_size, device, compute_type)

                lang_arg = language if language and language != "auto" else None
                segments_iter, info = model.transcribe(
                    str(audio_path),
                    language=lang_arg,
                    beam_size=5,
                    vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 500},
                )

                total_dur = duration_sec or float(getattr(info, "duration", 0.0) or 0.0)
                segments: list[dict[str, Any]] = []
                last_pct = 25

                for seg in segments_iter:
                    text = seg.text.strip()
                    if not text:
                        continue
                    segments.append(
                        {
                            "start": round(float(seg.start), 2),
                            "end": round(float(seg.end), 2),
                            "text": text,
                        }
                    )
                    if on_progress and total_dur > 0:
                        pct = min(68, 25 + int((seg.end / total_dur) * 43))
                        if pct >= last_pct + 4:
                            last_pct = pct
                            on_progress(
                                pct,
                                f"Transkripsiyon sürüyor ({int(seg.end)}s / {int(total_dur)}s)...",
                            )

                return {
                    "language": getattr(info, "language", lang_arg or "unknown"),
                    "duration": total_dur,
                    "device_used": f"{device}:{compute_type}",
                    "segments": segments,
                }
            except Exception as exc:
                last_error = exc
                self._cache.pop((model_size, device, compute_type), None)
                continue

        raise RuntimeError(f"Transkripsiyon başarısız oldu: {last_error}")
