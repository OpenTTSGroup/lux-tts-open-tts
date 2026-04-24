from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Any, Optional

import numpy as np

from app.config import Settings


log = logging.getLogger(__name__)


class TTSEngine:
    """Thin async wrapper around the upstream ``LuxTTS`` class.

    LuxTTS exposes a two-step zero-shot pipeline:
      1. ``encode_prompt(audio)`` — by default runs Whisper ASR on the
         reference audio and feeds its transcript into the tokenizer, then
         extracts Vocos features. When
         ``settings.luxtts_use_prompt_text`` is True (the default) we
         replicate ``process_audio()``'s feature extraction but substitute
         the externally supplied ``ref_text`` for Whisper's output, so the
         user-provided transcript actually participates in synthesis.
      2. ``generate_speech(text, encode_dict, ...)`` — flow-matching sampling +
         Vocos decode, returns a ``torch.Tensor`` shaped ``(1, samples)``.

    We cache step (1)'s output keyed by ``(abs(ref_audio), ref_mtime,
    duration, rms, ref_text_hash)`` to avoid re-running expensive feature
    extraction on every /speech call for the same voice.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._device = settings.resolved_device
        self._dtype_str = settings.luxtts_dtype
        self._sample_rate = settings.sample_rate

        model_path = self._resolve_model_path()

        # LuxTTS accepts "cuda" / "cpu" / "mps". We only pass "cuda" / "cpu"
        # (containers never get MPS).
        lux_device = "cuda" if self._device.startswith("cuda") else "cpu"

        from zipvoice.luxvoice import LuxTTS

        self._lux = LuxTTS(
            model_path=model_path,
            device=lux_device,
            threads=settings.luxtts_cpu_threads,
        )
        # Output sample rate is fixed for the process lifetime. Flip the
        # vocoder switch once so that subsequent generate_speech calls honour
        # the requested rate without overriding per-call (see luxvoice.py
        # generate_speech lines 52-55).
        self._lux.vocos.return_48k = not settings.luxtts_return_smooth

        # Cache key includes a hash of the reference text so that swapping
        # the .txt (or the multipart prompt_text on /clone) invalidates the
        # cached prompt_tokens. ref_text is empty string when
        # luxtts_use_prompt_text is False.
        self._prompt_cache: dict[
            tuple[str, float, float, float, str], dict
        ] = {}
        self._prompt_cache_order: list[
            tuple[str, float, float, float, str]
        ] = []
        self._prompt_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public attributes

    @property
    def device(self) -> str:
        return self._device

    @property
    def dtype_str(self) -> str:
        return self._dtype_str

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def model_id(self) -> str:
        return self._settings.luxtts_model

    @property
    def builtin_voices_list(self) -> list[str]:
        return []

    # ------------------------------------------------------------------
    # Model resolution

    def _resolve_model_path(self) -> Optional[str]:
        """Turn ``LUXTTS_MODEL`` into a concrete local directory.

        - Existing directory → use verbatim.
        - Default HF repo (``YatharthS/LuxTTS``) → return ``None`` so that
          LuxTTS' own ``__init__`` does the ``snapshot_download`` internally.
        - Any other string → treated as an HF repo id and downloaded here
          (LuxTTS' loaders concatenate the model path with ``tokens.txt``
          etc., so a bare repo id would not work past that point).
        """
        v = self._settings.luxtts_model
        if os.path.isdir(v):
            return v
        if v == "YatharthS/LuxTTS":
            return None
        from huggingface_hub import snapshot_download

        return snapshot_download(v)

    # ------------------------------------------------------------------
    # Prompt encoding

    def _encode_prompt_from_text(
        self,
        ref_audio: str,
        ref_text: str,
        duration: float,
        rms: float,
    ) -> dict:
        """Replicate ``process_audio()`` but skip Whisper, using ref_text.

        Mirrors ``engine/zipvoice/modeling_utils.py:47-62`` one-for-one
        except for the transcript source. Sample rates (24 kHz for Vocos,
        the 16 kHz branch is only used by Whisper and therefore dropped),
        the feat_scale=0.1 multiplier, and the ``rms_norm`` application
        match the upstream implementation so that downstream
        ``generate_speech`` sees identical feature magnitudes.
        """
        import librosa
        import torch
        from zipvoice.utils.infer import rms_norm

        lux_device = self._lux.device
        feat_scale = 0.1

        with torch.inference_mode():
            prompt_wav, _ = librosa.load(ref_audio, sr=24000, duration=duration)
            prompt_wav = torch.from_numpy(prompt_wav).unsqueeze(0)
            prompt_wav, prompt_rms = rms_norm(prompt_wav, rms)

            prompt_features = self._lux.feature_extractor.extract(
                prompt_wav, sampling_rate=24000
            ).to(lux_device)
            prompt_features = prompt_features.unsqueeze(0) * feat_scale
            prompt_features_lens = torch.tensor(
                [prompt_features.size(1)], device=lux_device
            )
            prompt_tokens = self._lux.tokenizer.texts_to_token_ids([ref_text])

        return {
            "prompt_tokens": prompt_tokens,
            "prompt_features_lens": prompt_features_lens,
            "prompt_features": prompt_features,
            "prompt_rms": prompt_rms,
        }

    def _encode_prompt_cached(
        self,
        ref_audio: str,
        ref_text: str,
        ref_mtime: Optional[float],
        duration: float,
        rms: float,
    ) -> dict:
        """Encode a prompt, caching by (path, mtime, duration, rms, text).

        Non-cached (``ref_mtime is None``) paths are the /clone one-shot
        uploads — the file is ephemeral so caching would just leak memory.
        """
        use_text = self._settings.luxtts_use_prompt_text

        def _encode() -> dict:
            if use_text:
                return self._encode_prompt_from_text(
                    ref_audio, ref_text, duration, rms
                )
            return self._lux.encode_prompt(
                ref_audio, duration=duration, rms=rms
            )

        if ref_mtime is None:
            return _encode()

        text_key = ref_text if use_text else ""
        key = (
            os.path.abspath(ref_audio),
            ref_mtime,
            float(duration),
            float(rms),
            text_key,
        )
        with self._prompt_lock:
            cached = self._prompt_cache.get(key)
            if cached is not None:
                try:
                    self._prompt_cache_order.remove(key)
                except ValueError:
                    pass
                self._prompt_cache_order.append(key)
                return cached

        encoded = _encode()

        with self._prompt_lock:
            self._prompt_cache[key] = encoded
            self._prompt_cache_order.append(key)
            while len(self._prompt_cache_order) > self._settings.luxtts_prompt_cache_size:
                old_key = self._prompt_cache_order.pop(0)
                self._prompt_cache.pop(old_key, None)

        return encoded

    # ------------------------------------------------------------------
    # Synthesis

    @staticmethod
    def _tensor_to_mono_float32(tensor: Any) -> np.ndarray:
        """LuxTTS returns a torch.Tensor shaped (1, N) or (N,). Normalize."""
        arr = tensor.squeeze().detach().cpu().numpy()
        return arr.astype(np.float32, copy=False).reshape(-1)

    async def synthesize_clone(
        self,
        text: str,
        *,
        ref_audio: str,
        ref_text: str,
        ref_mtime: Optional[float] = None,
        instructions: Optional[str] = None,
        speed: float = 1.0,
        num_steps: Optional[int] = None,
        guidance_scale: Optional[float] = None,
        t_shift: Optional[float] = None,
        duration: Optional[float] = None,
        **_: object,
    ) -> np.ndarray:
        s = self._settings
        ns = num_steps if num_steps is not None else s.luxtts_num_steps
        gs = guidance_scale if guidance_scale is not None else s.luxtts_guidance_scale
        ts = t_shift if t_shift is not None else s.luxtts_t_shift
        dur = duration if duration is not None else s.luxtts_prompt_duration
        return_smooth = s.luxtts_return_smooth

        def _run() -> np.ndarray:
            if instructions:
                log.warning(
                    "instructions ignored: LuxTTS has no instruct API"
                )
            encoded = self._encode_prompt_cached(
                ref_audio, ref_text, ref_mtime, dur, s.luxtts_prompt_rms
            )
            wav = self._lux.generate_speech(
                text,
                encoded,
                num_steps=ns,
                guidance_scale=gs,
                t_shift=ts,
                speed=speed,
                return_smooth=return_smooth,
            )
            return self._tensor_to_mono_float32(wav)

        return await asyncio.to_thread(_run)
