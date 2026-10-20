"""
DBRecruitAI - Multimodal Candidate Interview Audio Analysis Engine
Handles processing of live interview recordings using Google GenAI / Gemini,
extracting transcription summaries, spoken communication clarity, key highlights,
and talent recommendations.
"""

import os
import json
import logging
import re
from typing import Any, Dict, Optional
from django.conf import settings
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

client: Optional[genai.Client] = None
if getattr(settings, "GEMINI_API_KEY", None):
    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
    except Exception as _init_err:
        logger.warning("Candidate Evaluation GenAI client setup deferred: %s", _init_err)


def get_genai_client() -> Optional[genai.Client]:
    """Returns an initialized Google GenAI client or None if API key is unconfigured."""
    global client
    if client is None and getattr(settings, "GEMINI_API_KEY", None):
        try:
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
        except Exception as err:
            logger.warning("Failed to initialize GenAI client: %s", err)
            client = None
    return client


def _clean_json_text(raw_text: str) -> str:
    """Extracts JSON content inside markdown code blocks or strips fences."""
    text = raw_text.strip()
    if "```" in text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1).strip()
        return re.sub(r"^```json\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    return text


def analyze_interview_audio(
    audio_path: str,
    candidate_name: str,
    job_title: str,
    interviewer_notes: str = ""
) -> Dict[str, Any]:
    """
    Analyzes an interview audio recording file using Gemini.
    Returns a dictionary with:
      - transcript: Spoken audio transcript or summarized transcript
      - summary: Executive summary of interview responses
      - score: Communication and engagement score (0-100)
      - key_points: List of key talking points/strengths
      - red_flags: List of potential concerns or inconsistencies
      - recommendation: Suggested recommendation (Strong Hire / Hire / Hold / No Hire)
    """
    if not audio_path or not os.path.exists(audio_path):
        return {
            "transcript": "No audio file provided or file not found.",
            "summary": "Audio analysis was not run because no audio recording was provided.",
            "score": 0,
            "key_points": [],
            "red_flags": [],
            "recommendation": "Hold",
        }

    ai_client = get_genai_client()
    if not ai_client:
        return {
            "transcript": "Audio recording uploaded successfully (Gemini API key not configured for live transcription).",
            "summary": "The interview audio file was securely saved. Configure GEMINI_API_KEY for automated transcription and AI insights.",
            "score": 75,
            "key_points": ["Audio recorded and saved for manual review"],
            "red_flags": [],
            "recommendation": "Hire",
        }

    # Determine MIME type based on file extension
    ext = os.path.splitext(audio_path)[1].lower()
    mime_map = {
        ".mp3": "audio/mp3",
        ".wav": "audio/wav",
        ".m4a": "audio/m4a",
        ".aac": "audio/aac",
        ".ogg": "audio/ogg",
        ".webm": "audio/webm",
    }
    mime_type = mime_map.get(ext, "audio/mp3")

    uploaded_file = None
    try:
        logger.info("Uploading audio %s to Gemini for candidate %s...", audio_path, candidate_name)
        uploaded_file = ai_client.files.upload(
            file=audio_path,
            config=types.UploadFileConfig(mime_type=mime_type)
        )

        prompt = (
            f"You are a Senior Talent Partner and expert Technical Interview Evaluator. "
            f"Analyze the attached interview audio recording of applicant '{candidate_name}' for the position of '{job_title}'.\n"
            f"Interviewer notes taken during the session: '{interviewer_notes or 'None provided'}'.\n\n"
            "Produce an objective evaluation in STRICT JSON format with EXACTLY these keys:\n"
            "{\n"
            '  "transcript": "Detailed summary and transcription of the primary discussion and candidate answers",\n'
            '  "summary": "Executive summary of candidate performance, communication clarity, and articulation",\n'
            '  "score": <integer from 0 to 100 representing spoken clarity, technical articulation, and engagement>,\n'
            '  "key_points": ["Key strength or highlight 1", "Key strength or highlight 2"],\n'
            '  "red_flags": ["Potential concern, hesitation, or red flag if any, else empty list"],\n'
            '  "recommendation": "One of: Strong Hire, Hire, Hold, No Hire"\n'
            "}\n"
            "Respond ONLY with valid JSON. Do not prepend markdown explanation outside the JSON."
        )

        eval_model = getattr(settings, "GEMINI_MODEL", "gemini-3.6-flash")
        response = ai_client.models.generate_content(
            model=eval_model,
            contents=[uploaded_file, prompt],
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=1500,
            ),
        )

        cleaned = _clean_json_text(response.text)
        data = json.loads(cleaned)
        return {
            "transcript": str(data.get("transcript", "")),
            "summary": str(data.get("summary", "")),
            "score": int(data.get("score", 75)),
            "key_points": list(data.get("key_points", [])),
            "red_flags": list(data.get("red_flags", [])),
            "recommendation": str(data.get("recommendation", "Hire")),
        }

    except Exception as err:
        logger.error("Error analyzing interview audio for %s: %s", candidate_name, err)
        return {
            "transcript": "Interview audio recorded. Automated AI transcription encountered a temporary error.",
            "summary": f"Audio file saved. Gemini analysis note: {str(err)}",
            "score": 70,
            "key_points": ["Audio file saved on server"],
            "red_flags": [],
            "recommendation": "Hold",
        }
    finally:
        if uploaded_file and hasattr(uploaded_file, "name"):
            try:
                ai_client.files.delete(name=uploaded_file.name)
            except Exception as del_err:
                logger.warning("Could not delete temporary Gemini audio file %s: %s", uploaded_file.name, del_err)
