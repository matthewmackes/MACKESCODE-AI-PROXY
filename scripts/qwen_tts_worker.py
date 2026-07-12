#!/usr/bin/env python3
"""JSON-lines worker for optional Qwen3-TTS VoiceDesign synthesis."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _dtype(torch_module: Any, raw: str) -> Any:
    value = (raw or "").strip().lower()
    if value in {"", "auto", "none"}:
        return None
    mapping = {
        "bfloat16": getattr(torch_module, "bfloat16", None),
        "bf16": getattr(torch_module, "bfloat16", None),
        "float16": getattr(torch_module, "float16", None),
        "fp16": getattr(torch_module, "float16", None),
        "float32": getattr(torch_module, "float32", None),
        "fp32": getattr(torch_module, "float32", None),
    }
    return mapping.get(value)


def _load_model() -> Any:
    from qwen_tts import Qwen3TTSModel  # type: ignore
    import torch  # type: ignore

    kwargs: dict[str, Any] = {}
    device = os.environ.get("MATTS_QWEN_TTS_DEVICE", "auto").strip()
    dtype = _dtype(torch, os.environ.get("MATTS_QWEN_TTS_DTYPE", "bfloat16"))
    attn = os.environ.get("MATTS_QWEN_TTS_ATTN", "").strip()
    if device:
        kwargs["device_map"] = device
    if dtype is not None:
        kwargs["dtype"] = dtype
    if attn:
        kwargs["attn_implementation"] = attn
    return Qwen3TTSModel.from_pretrained(
        os.environ.get("MATTS_QWEN_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"),
        **kwargs,
    )


def _write_wav(result: Any, output_path: Path) -> int:
    if hasattr(result, "save"):
        result.save(str(output_path))
        return int(getattr(result, "sampling_rate", 0) or getattr(result, "sample_rate", 0) or 0)
    if isinstance(result, dict):
        if isinstance(result.get("path"), str):
            source = Path(result["path"])
            if source != output_path:
                output_path.write_bytes(source.read_bytes())
            return int(result.get("sample_rate") or result.get("sampling_rate") or 0)
        audio = result.get("audio") or result.get("waveform") or result.get("samples")
        sample_rate = int(result.get("sample_rate") or result.get("sampling_rate") or 24000)
    elif isinstance(result, tuple) and len(result) >= 2:
        audio, sample_rate = result[0], int(result[1] or 24000)
    else:
        audio = getattr(result, "audio", None) or getattr(result, "waveform", None) or getattr(result, "samples", None)
        sample_rate = int(getattr(result, "sample_rate", 0) or getattr(result, "sampling_rate", 0) or 24000)
    if audio is None:
        raise RuntimeError("Qwen3-TTS returned an unsupported audio payload")
    import soundfile as sf  # type: ignore
    sf.write(str(output_path), audio, sample_rate)
    return sample_rate


def _handle(model: Any, request: dict[str, Any]) -> dict[str, Any]:
    output_path = Path(str(request.get("output_path") or "")).expanduser()
    if not output_path:
        raise RuntimeError("output_path is required")
    result = model.generate_voice_design(
        str(request.get("text") or ""),
        str(request.get("language") or "Auto"),
        str(request.get("instruct") or ""),
    )
    sample_rate = _write_wav(result, output_path)
    return {
        "ok": True,
        "id": request.get("id"),
        "path": str(output_path),
        "sample_rate": sample_rate,
        "engine": "qwen3_voice_design",
    }


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=True), flush=True)


def main() -> int:
    try:
        model = _load_model()
    except Exception as exc:
        _emit({"ok": False, "error": "failed to load Qwen3-TTS: %s" % exc})
        return 1
    for line in sys.stdin:
        try:
            request = json.loads(line)
            _emit(_handle(model, request if isinstance(request, dict) else {}))
        except Exception as exc:
            _emit({"ok": False, "error": str(exc)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
