from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    # --- Engine (LUXTTS_* prefix) -------------------------------------------
    luxtts_model: str = Field(
        default="YatharthS/LuxTTS",
        description=(
            "HuggingFace repo id or local directory holding LuxTTS weights. "
            "A local directory is used verbatim; anything else is resolved "
            "via huggingface_hub.snapshot_download (LuxTTS only supports HF)."
        ),
    )
    luxtts_device: Literal["auto", "cuda", "cpu"] = "auto"
    luxtts_cuda_index: int = Field(default=0, ge=0)
    luxtts_dtype: Literal["float32"] = Field(
        default="float32",
        description="LuxTTS only supports fp32; field exists for spec parity.",
    )
    luxtts_cpu_threads: int = Field(
        default=4,
        ge=1,
        description="ONNX Runtime thread count when running on CPU.",
    )
    luxtts_num_steps: int = Field(default=4, ge=1, le=64)
    luxtts_guidance_scale: float = Field(default=3.0, ge=0.0, le=10.0)
    luxtts_t_shift: float = Field(default=0.5, ge=0.0, le=1.0)
    luxtts_prompt_duration: float = Field(default=5.0, ge=0.5, le=30.0)
    luxtts_prompt_rms: float = Field(default=0.001, ge=0.0, le=1.0)
    luxtts_return_smooth: bool = Field(
        default=False,
        description="False → 48 kHz output, True → 24 kHz output. Fixed for process lifetime.",
    )
    luxtts_use_prompt_text: bool = Field(
        default=True,
        description=(
            "True → use the supplied prompt_text (<id>.txt on /speech, form field "
            "on /clone) as the reference transcript, bypassing Whisper. "
            "False → let LuxTTS' bundled Whisper re-transcribe the prompt audio "
            "(the upstream default)."
        ),
    )
    luxtts_prompt_cache_size: int = Field(default=16, ge=1)

    # --- Service-level (no prefix) ------------------------------------------
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "info"
    voices_dir: str = "/voices"
    max_input_chars: int = Field(default=8000, ge=1)
    default_response_format: Literal[
        "mp3", "opus", "aac", "flac", "wav", "pcm"
    ] = "mp3"
    max_concurrency: int = Field(default=1, ge=1)
    max_queue_size: int = Field(default=0, ge=0)
    queue_timeout: float = Field(default=0.0, ge=0.0)
    max_audio_bytes: int = Field(default=20 * 1024 * 1024, ge=1)
    cors_enabled: bool = False

    @property
    def voices_path(self) -> Path:
        return Path(self.voices_dir)

    @property
    def resolved_device(self) -> str:
        if self.luxtts_device == "cpu":
            return "cpu"
        if self.luxtts_device == "cuda":
            return f"cuda:{self.luxtts_cuda_index}"
        # auto
        import torch

        if torch.cuda.is_available():
            return f"cuda:{self.luxtts_cuda_index}"
        return "cpu"

    @property
    def sample_rate(self) -> int:
        return 24000 if self.luxtts_return_smooth else 48000


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
