"""
DBRecruitAI - Text-to-Speech Engine via ElevenLabs
Converts interview question texts into natural voice speech with disk caching
to minimize character quota usage and ensure fast responses.
"""

import hashlib
import logging
import os
import tempfile
from typing import Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(tempfile.gettempdir(), "dbrecruitai_tts_cache")
os.makedirs(CACHE_DIR, exist_ok=True)


def get_tts_cache_path(voice_id: str, text: str) -> str:
    """Generate deterministic file path for caching TTS audio."""
    key = f"{voice_id}_{text.strip()}"
    filename = hashlib.sha256(key.encode("utf-8")).hexdigest() + ".mp3"
    return os.path.join(CACHE_DIR, filename)


def generate_question_speech(text: str, voice_id: Optional[str] = None) -> Optional[bytes]:
    """
    Synthesizes speech audio for an interview question using ElevenLabs.
    Returns audio/mpeg bytes if successful, or None if failed/unconfigured.
    """
    if not text or not text.strip():
        return None

    api_key = getattr(settings, "ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        logger.info("ElevenLabs API key is not configured; TTS audio generation skipped.")
        return None

    voice = (voice_id or getattr(settings, "ELEVENLABS_VOICE_ID", "cgSgspJ2msm6clMCkdW9")).strip()
    if not voice:
        voice = "cgSgspJ2msm6clMCkdW9"

    cache_path = get_tts_cache_path(voice, text)
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "rb") as f:
                cached_bytes = f.read()
                if len(cached_bytes) > 0:
                    logger.debug("Serving cached TTS audio for question.")
                    return cached_bytes
        except Exception as e:
            logger.warning("Failed reading TTS cache file: %s", e)

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text.strip(),
        "model_id": "eleven_turbo_v2_5",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
        },
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        if response.status_code == 200 and response.content:
            audio_bytes = response.content
            # Save to cache
            try:
                with open(cache_path, "wb") as f:
                    f.write(audio_bytes)
            except Exception as e:
                logger.warning("Failed writing TTS audio to cache: %s", e)
            return audio_bytes
        else:
            logger.warning(
                "ElevenLabs TTS failed: status %s, response: %s",
                response.status_code,
                response.text[:200],
            )
            return None
    except Exception as exc:
        logger.error("ElevenLabs TTS request encountered error: %s", exc)
        return None
