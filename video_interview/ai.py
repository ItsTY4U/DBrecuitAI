"""
DBRecruitAI - Multimodal Video Interview Evaluation Engine
Handles video file processing, Gemini Files API upload, objective question evaluation,
and executive session synthesis.
"""

import os
import json
import logging
import re
import tempfile
import time
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
        logger.warning("Initial Video Interview GenAI client setup deferred: %s", _init_err)


def get_genai_client() -> Optional[genai.Client]:
    """
    Returns an initialized Google GenAI client or None if API key is unconfigured.
    """
    global client
    if client is None and getattr(settings, "GEMINI_API_KEY", None):
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return client


def _clean_json_text(raw_text: str) -> str:
    """
    Extracts JSON content inside markdown code blocks or strips outer formatting fences.
    """
    text = raw_text.strip()
    if "```" in text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1).strip()
    return text


def _call_gemini_with_retry_and_fallback(
    ai_client: genai.Client,
    contents: list,
    system_instruction: str = "",
    response_mime_type: str = "application/json",
    temperature: float = 0.2,
    max_output_tokens: int = 1500,
) -> str:
    """
    Calls Gemini API with exponential backoff retry and automatic model fallback
    to reliably handle 503 UNAVAILABLE (high demand), 429 RESOURCE_EXHAUSTED,
    and temporary connection spikes.
    """
    primary_model = getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash")
    fast_model = getattr(settings, "GEMINI_FAST_MODEL", "gemini-2.5-flash-lite")

    models_to_try = [primary_model]
    if fast_model and fast_model not in models_to_try:
        models_to_try.append(fast_model)
    for fallback in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
        if fallback not in models_to_try:
            models_to_try.append(fallback)

    last_error = None
    config_args = {
        "response_mime_type": response_mime_type,
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
    }
    if system_instruction:
        config_args["system_instruction"] = system_instruction

    for model_name in models_to_try:
        for attempt in range(3):
            try:
                response = ai_client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(**config_args),
                )
                if response and response.text:
                    return response.text
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                is_transient = (
                    "503" in err_str
                    or "unavailable" in err_str
                    or "high demand" in err_str
                    or "429" in err_str
                    or "resource_exhausted" in err_str
                    or "deadline" in err_str
                    or "timeout" in err_str
                )
                if is_transient and attempt < 2:
                    wait_time = (2 ** attempt) * 1.5
                    logger.warning(
                        "Gemini call to %s failed (%s). Retrying in %.1fs (attempt %d/3)...",
                        model_name, e, wait_time, attempt + 1
                    )
                    time.sleep(wait_time)
                else:
                    logger.warning(
                        "Gemini model %s call failed: %s. Moving to next candidate model if available.",
                        model_name, e
                    )
                    break

    raise last_error or RuntimeError("Gemini API call failed after retries and fallback models.")


def analyze_single_response(response: Any, job_title: str, job_department: str) -> Dict[str, Any]:
    """
    Evaluates an individual question video recording using Gemini 2.5 Flash.
    Returns dict with keys: score (50-100), transcript, feedback, strengths, improvements.
    """
    if response.skipped or not response.video_clip:
        return {
            "score": 50,
            "transcript": "[Candidate skipped this question]",
            "feedback": "The candidate chose to skip this question. No answer was provided.",
            "strengths": [],
            "improvements": ["Did not attempt the question"],
        }

    ai_client = get_genai_client()
    if not ai_client:
        return {
            "score": 75,
            "transcript": "Recorded response submitted (Gemini API key not configured for transcription).",
            "feedback": "Video response recorded successfully. Manual HR review recommended.",
            "strengths": ["Completed video submission"],
            "improvements": ["Pending manual evaluation"],
        }

    temp_file_path = None
    uploaded_file = None

    try:
        # Read the video clip or stream from remote storage backend (S3/Cloudflare R2)
        file_to_upload = None
        try:
            path = response.video_clip.path
            if os.path.exists(path):
                file_to_upload = path
        except (NotImplementedError, AttributeError, ValueError):
            pass

        if not file_to_upload:
            suffix = os.path.splitext(response.video_clip.name or "")[-1] or ".webm"
            temp_fd, temp_file_path = tempfile.mkstemp(suffix=suffix)
            with os.fdopen(temp_fd, "wb") as f:
                try:
                    response.video_clip.open("rb")
                    for chunk in response.video_clip.chunks():
                        f.write(chunk)
                finally:
                    response.video_clip.close()
            file_to_upload = temp_file_path

        # Upload to Gemini Files API
        uploaded_file = ai_client.files.upload(file=file_to_upload)

        # Wait for file processing to reach ACTIVE state
        for _ in range(30):
            if uploaded_file.state.name == "ACTIVE":
                break
            if uploaded_file.state.name == "FAILED":
                raise RuntimeError(f"Gemini file processing failed: {getattr(uploaded_file, 'error', 'Unknown error')}")
            time.sleep(2)
            uploaded_file = ai_client.files.get(name=uploaded_file.name)

        system_instruction = (
            "You are an expert AI Video Interview Evaluator and Senior HR Talent Specialist. "
            "Evaluate applicant video answers for prompt relevance, structured thinking "
            "(e.g. STAR method for behavioral inquiries), articulation, clarity, and professionalism."
        )

        prompt = f"""
Evaluate the applicant's recorded video answer for this question.

ROLE SPECIFICATION:
Position: {job_title} ({job_department})
Question Category: {response.get_question_type_display()}
Question Prompt: "{response.question_text}"

EVALUATION CRITERIA:
1. Relevance and depth of content in relation to the question.
2. Speech clarity, professionalism, articulation, and confidence.
3. Structured thinking (e.g. STAR method: Situation, Task, Action, Result for behavioral inquiries).

SCORING MANDATE:
- The score MUST be an integer between 50 and 100 inclusive.
- 50 to 64: Below expectations, off-topic, or lacking substance.
- 65 to 79: Solid, satisfactory answer with basic competence demonstrated.
- 80 to 89: Strong, well-articulated answer with relevant examples.
- 90 to 100: Exceptional, articulate, compelling answer with measurable impact described.

RETURN FORMAT:
Return strictly a valid JSON object matching:
{{
    "score": 85,
    "transcript": "Spoken transcript or clear verbatim summary of what the applicant said...",
    "feedback": "2-3 constructive sentences evaluating their answer.",
    "strengths": ["Key delivery or content strength"],
    "improvements": ["Actionable improvement recommendation"]
}}
"""

        raw_text = _clean_json_text(
            _call_gemini_with_retry_and_fallback(
                ai_client=ai_client,
                contents=[uploaded_file, prompt],
                system_instruction=system_instruction,
                response_mime_type="application/json",
                temperature=0.2,
                max_output_tokens=1500,
            )
        )
        data = json.loads(raw_text)

        # Clamp score between 50 and 100
        score = int(data.get("score", 75))
        score = max(50, min(100, score))

        return {
            "score": score,
            "transcript": data.get("transcript", "Transcription unavailable."),
            "feedback": data.get("feedback", "No feedback provided."),
            "strengths": data.get("strengths", []),
            "improvements": data.get("improvements", []),
        }

    except Exception as e:
        logger.error("Error analyzing video response Q%s: %s", response.question_number, e)
        err_str = str(e)
        if "503" in err_str or "unavailable" in err_str.lower() or "high demand" in err_str.lower():
            friendly_feedback = "Automated analysis experienced a temporary delay from the AI provider due to high demand. Video is ready for HR playback."
        else:
            friendly_feedback = "Automated analysis was delayed. Video is ready for HR playback."
        return {
            "score": 70,
            "transcript": "Video recording captured successfully.",
            "feedback": friendly_feedback,
            "strengths": ["Completed recorded response"],
            "improvements": ["Review video manually"],
        }
    finally:
        # Clean up temporary file
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError:
                pass
        # Clean up Gemini uploaded file
        if uploaded_file:
            try:
                ai_client.files.delete(name=uploaded_file.name)
            except Exception:
                pass


def analyze_interview_session(session: Any) -> None:
    """
    Analyzes all question responses in an InterviewSession, scores them,
    calculates the final overall score, and writes feedback back to the database.
    """
    job = session.application.job
    job_title = job.title
    job_department = job.department

    responses = list(session.responses.all().order_by("question_number"))
    if not responses:
        return

    total_score = 0
    analyzed_count = 0

    for resp in responses:
        eval_result = analyze_single_response(resp, job_title, job_department)
        resp.score = eval_result["score"]
        resp.transcript = eval_result["transcript"]
        resp.feedback = eval_result["feedback"]
        resp.strengths = "\n".join(eval_result.get("strengths", []))
        resp.improvements = "\n".join(eval_result.get("improvements", []))
        resp.save()

        total_score += resp.score
        analyzed_count += 1

    # Calculate final score (average of questions, 50 to 100)
    final_score = round(total_score / analyzed_count) if analyzed_count > 0 else 50
    final_score = max(50, min(100, final_score))
    session.final_score = final_score

    ai_client = get_genai_client()
    overall_summary = ""
    overall_feedback = ""

    if ai_client:
        try:
            questions_summary = "\n".join([
                f"- Q{r.question_number} ({r.question_text}): Score {r.score}/100. Feedback: {r.feedback}"
                for r in responses
            ])

            summary_prompt = f"""
You are the Head of Talent Acquisition evaluating an applicant's complete AI video interview.

Applicant: {session.application.first_name} {session.application.last_name}
Position: {job_title} ({job_department})
Final Average Score: {final_score}/100

Individual Questions and Evaluated Scores:
{questions_summary}

Provide an executive synthesis in JSON conforming strictly to:
{{
    "overall_summary": "A concise executive paragraph highlighting communication proficiency, key themes, and overall fit.",
    "overall_feedback": "Actionable HR recommendations for subsequent live interviews or next screening steps."
}}
"""

            raw = _clean_json_text(
                _call_gemini_with_retry_and_fallback(
                    ai_client=ai_client,
                    contents=summary_prompt,
                    response_mime_type="application/json",
                    temperature=0.2,
                    max_output_tokens=1000,
                )
            )
            sum_data = json.loads(raw)
            overall_summary = sum_data.get("overall_summary", "")
            overall_feedback = sum_data.get("overall_feedback", "")
        except Exception as e:
            logger.error("Error generating overall interview summary: %s", e)
            overall_summary = f"Candidate completed the video interview with an average score of {final_score}%."
            overall_feedback = "Candidate's individual answers and video clips are available for HR review below."
    else:
        overall_summary = f"Candidate completed the video interview with an overall score of {final_score}%."
        overall_feedback = "Detailed video recordings are available below for HR assessment."

    session.overall_summary = overall_summary
    session.overall_feedback = overall_feedback
    session.ai_analyzed = True
    session.save()
