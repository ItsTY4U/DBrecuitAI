import os
import json
import tempfile
import time
from django.conf import settings
from google import genai
from google.genai import types

client = None
if getattr(settings, "GEMINI_API_KEY", None):
    client = genai.Client(api_key=settings.GEMINI_API_KEY)


def get_genai_client():
    global client
    if client is None and getattr(settings, "GEMINI_API_KEY", None):
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return client


def analyze_single_response(response, job_title, job_department):
    """
    Evaluates a single question video response using Gemini 2.5 Flash.
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
        # Fallback if API key is not configured
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
        # Read the video clip
        file_to_upload = None
        try:
            path = response.video_clip.path
            if os.path.exists(path):
                file_to_upload = path
        except (NotImplementedError, AttributeError, ValueError):
            pass

        if not file_to_upload:
            # S3/R2 or remote storage backend: download to a temporary file
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

        # Wait for file processing if necessary
        for _ in range(30):
            if uploaded_file.state.name == "ACTIVE":
                break
            if uploaded_file.state.name == "FAILED":
                raise RuntimeError(f"Gemini file processing failed: {getattr(uploaded_file, 'error', 'Unknown error')}")
            time.sleep(2)
            uploaded_file = ai_client.files.get(name=uploaded_file.name)

        prompt = f"""
        You are an expert AI Video Interview Evaluator and Senior HR Talent Specialist.
        Evaluate the applicant's video answer for this question.

        Job Role: {job_title} ({job_department})
        Question Type: {response.get_question_type_display()}
        Question: "{response.question_text}"

        Criteria to evaluate:
        1. Relevance and depth of content in relation to the question.
        2. Speech clarity, professionalism, articulation, and confidence.
        3. Structured thinking (e.g. STAR method for behavioral inquiries).

        SCORING MANDATE:
        - The score MUST be an integer between 50 and 100 inclusive.
        - 50 to 64: Below expectations or off-topic.
        - 65 to 79: Solid, satisfactory answer.
        - 80 to 89: Strong, well-articulated answer.
        - 90 to 100: Exceptional, articulate, and compelling answer.

        Return ONLY a JSON object formatted strictly as:
        {{
            "score": 85,
            "transcript": "Spoken transcript or clear verbatim summary of what the applicant said...",
            "feedback": "2-3 constructive sentences evaluating their answer.",
            "strengths": ["strength 1", "strength 2"],
            "improvements": ["improvement 1"]
        }}
        """

        gemini_response = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[uploaded_file, prompt],
        )

        raw_text = gemini_response.text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.replace("```json", "").replace("```", "").strip()

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
        print(f"Error analyzing video response Q{response.question_number}: {e}")
        return {
            "score": 70,
            "transcript": "Video recording captured successfully.",
            "feedback": f"Automated analysis experienced a temporary delay ({str(e)}). Video is ready for HR playback.",
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


def analyze_interview_session(session):
    """
    Analyzes all 5 question responses in an InterviewSession, scores them,
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

    # Calculate final score (average of 5 questions, 50 to 100)
    final_score = round(total_score / analyzed_count) if analyzed_count > 0 else 50
    final_score = max(50, min(100, final_score))
    session.final_score = final_score

    # Generate overall summary and feedback with Gemini
    ai_client = get_genai_client()
    overall_summary = ""
    overall_feedback = ""

    if ai_client:
        try:
            summary_prompt = f"""
            You are the Head of Talent Acquisition evaluating an applicant's complete 5-question AI video interview.
            
            Applicant: {session.application.first_name} {session.application.last_name}
            Position: {job_title} ({job_department})
            Final Average Score: {final_score}/100

            Individual Questions and Evaluated Scores:
            """ + "\n".join([
                f"- Q{r.question_number} ({r.question_text}): Score {r.score}/100. Feedback: {r.feedback}"
                for r in responses
            ]) + """

            Provide an executive synthesis in JSON:
            {
                "overall_summary": "A concise executive paragraph highlighting communication proficiency, key themes, and overall fit.",
                "overall_feedback": "Actionable HR recommendations for subsequent live interviews or next screening steps."
            }
            """

            sum_resp = ai_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=summary_prompt
            )
            raw = sum_resp.text.strip()
            if raw.startswith("```"):
                raw = raw.replace("```json", "").replace("```", "").strip()
            sum_data = json.loads(raw)
            overall_summary = sum_data.get("overall_summary", "")
            overall_feedback = sum_data.get("overall_feedback", "")
        except Exception as e:
            print(f"Error generating overall interview summary: {e}")
            overall_summary = f"Candidate completed the 5-question video interview with an average score of {final_score}%."
            overall_feedback = "Candidate's individual answers and video clips are available for HR review below."
    else:
        overall_summary = f"Candidate completed the 5-question video interview with an overall score of {final_score}%."
        overall_feedback = "Detailed video recordings are available below for HR assessment."

    session.overall_summary = overall_summary
    session.overall_feedback = overall_feedback
    session.ai_analyzed = True
    session.save()
