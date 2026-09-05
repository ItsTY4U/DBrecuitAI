from google import genai
from django.conf import settings
import pdfplumber
import json
import re

client = None

if settings.GEMINI_API_KEY:
    client = genai.Client(api_key=settings.GEMINI_API_KEY)

def extract_resume_text(pdf_path):
    text = ""
    
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            
            if page_text:
                text += page_text + "\n"
                
    return text

def analyze_resume(resume_text, job):
    if client is None:
        raise Exception("Gemini API key is missing.")

    general_requirements = job.requirements.strip()

    key_qualifications = "\n".join(
        f"- {r.text}"
        for r in job.requirements_list.all()
    )

    prompt = f"""
    You are an Expert HR recruiter assistant for a recruitment
    decision-support system operating in the Philippine job market.

    Evaluate the applicant for the following job using the
    4-criteria rubric below.

    RUBRIC (score each criterion 50-100)

    1. Qualifications (Licenses & Certifications)
       90-100 Exceptional: exceeds requirements, holds premium/advanced
       localized certs beyond the JD baseline.
       75-89 Proficient: meets all mandatory local credentials in the JD
       (e.g., LTO, TESDA NC II, PRC, or specific software certs).
       60-74 Developing: credentials missing/incomplete/expired, but a
       partial or pending application exists.
       50-59 Unsatisfactory: completely lacks the mandatory,
       non-negotiable legal or technical licenses required for the role.

    2. Experience (Tenure & Environment)
       90-100 Exceptional: years exceed the JD requirement, strong
       employment stability, minimal job-hopping.
       75-89 Proficient: meets the required years; past environments
       directly match the target workflow.
       60-74 Developing: shorter tenure than requested, or experience in
       an unrelated industry with low transferable context.
       50-59 Unsatisfactory: no relevant experience, unexplained gaps,
       or high job-hopping frequency.

    3. Skills (Hard, Soft, & Tools)
       90-100 Exceptional: high density (>80%) of core technical tools,
       localized terminology, and operational keywords from the JD.
       75-89 Proficient: solid baseline (60-79%) of primary hard skills
       and essential soft skills.
       60-74 Developing: weak keyword alignment (<60%); relies on
       generic text without naming specific tools/methods.
       50-59 Unsatisfactory: zero relevant skills or tool proficiencies
       matched.

    4. Education (Academic Baseline)
       90-100 Exceptional: exceeds minimum requirement.
       75-89 Proficient: exactly matches the minimum required education
       for the Philippine context (e.g., K-12, Vocational, Degree).
       60-74 Developing: below the requested level, but has significant
       equivalent practical field experience.
       50-59 Unsatisfactory: does not meet the baseline educational
       requirement.

    Do not assume the applicant has a qualification unless there is
    evidence of it in the resume.

    JOB INFORMATION

    Job Title:
    {job.title}

    Department:
    {job.department}

    Description:
    {job.description}

    Requirements:
    {general_requirements}

    HR Key Qualifications:
    {key_qualifications}

    APPLICANT RESUME:
    {resume_text}

    TASK

    1. Score the applicant 50-100 on each of the four rubric criteria.

    2. Decide how much each criterion should count toward this specific
       job's final score, as a weight from 10 to 40 (inclusive), with
       all four weights summing to exactly 100. Base the weights on
       what actually matters most for this job — e.g., a role that
       legally requires a license should weight Qualifications higher;
       a hands-on technical role should weight Skills higher; a role
       with flexible entry requirements should weight Education lower.

    3. For each of the four weights, give a short one-sentence reason
       tied to this specific job.

    Return ONLY valid JSON. Use EXACTLY this structure:

    {{
        "first_name": "",
        "middle_initial": "",
        "last_name": "",
        "email": "",
        "phone": "",

        "score": 0,

        "recommendation": "",

        "match_level": "",

        "summary": "",

        "matched_qualifications": [
            ""
        ],

        "missing_qualifications": [
            ""
        ],

        "strengths": [
            ""
        ],

        "weaknesses": [
            ""
        ],

        "skills_match": 0,
        "experience_match": 0,
        "education_match": 0,
        "qualification_match": 0,

        "criteria_weights": {{
            "qualification_weight": 0,
            "experience_weight": 0,
            "skills_weight": 0,
            "education_weight": 0
        }},

        "weight_reasoning": {{
            "qualification": "",
            "experience": "",
            "skills": "",
            "education": ""
        }}
    }}

    RULES

    1. "score" must be an integer from 50 to 100 (you may leave this at 0;
       the backend recalculates it).

    2. "skills_match", "experience_match", "education_match", and
       "qualification_match" must each be an integer from 50 to 100,
       following the rubric bands above.

    3. "criteria_weights" values must each be an integer between 10 and
       40 inclusive, and the four values must sum to exactly 100.

    4. "match_level" must be one of:
    - "Exceptional"
    - "Proficient"
    - "Developing"
    - "Unsatisfactory"

    5. "recommendation" must be one of:
    - "Qualified"
    - "Potentially Qualified"
    - "Not Qualified"

    6. "matched_qualifications" must contain qualifications that are
       supported by evidence in the applicant's resume.

    7. "missing_qualifications" must contain important job
       qualifications that are required or preferred but are not
       supported by the resume.

    8. Do not invent skills, experience, education, certifications, or
       qualifications. If there is no evidence for a qualification, do
       not assume the applicant has it.

    9. Keep the summary concise but explain the main reason for the
       applicant's score.

    10. Keep strengths, weaknesses, and weight_reasoning entries concise
        (one sentence each).

    11. Return valid JSON parseable by Python's json.loads(). Do not
        include Markdown, ```json fences, or any text before/after the
        JSON.

    12. Do not determine the final overall score, match_level, or
        recommendation yourself — the backend recalculates these.
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    text = response.text.strip()

    text = re.sub(r"^```json\s*```$", "", text, flags=re.IGNORECASE).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        print("Gemini returned invalid JSON:")
        print(text)
        raise Exception("Gemini returned invalid JSON")

    # ---- Step 0: pull and clamp the four raw criterion scores ----
    skills_match = _clamp(data.get("skills_match", 0), 0, 100)
    experience_match = _clamp(data.get("experience_match", 0), 0, 100)
    education_match = _clamp(data.get("education_match", 0), 0, 100)
    qualification_match = _clamp(data.get("qualification_match", 0), 0, 100)

    data["skills_match"] = skills_match
    data["experience_match"] = experience_match
    data["education_match"] = education_match
    data["qualification_match"] = qualification_match

    # ---- Pull and normalize the AI-generated weights ----
    raw_weights = data.get("criteria_weights", {}) or {}
    weights = _normalize_weights(
        qualification=raw_weights.get("qualification_weight", 25),
        experience=raw_weights.get("experience_weight", 25),
        skills=raw_weights.get("skills_weight", 25),
        education=raw_weights.get("education_weight", 25),
    )
    data["criteria_weights"] = weights

    # ---- Step 1: Knockout Layer (Safety Check) ----
    # If qualifications_score < 60, hard-fail regardless of the weighted
    # average — the candidate lacks a mandatory, non-negotiable license
    # or credential.
    if qualification_match < 60:
        data["hard_fail"] = True
        data["hard_fail_reason"] = (
            "Qualifications score is below 60 — candidate lacks a "
            "mandatory, non-negotiable license or credential required "
            "for this role."
        )
        data["score"] = qualification_match
        data["recommendation"] = "Not Qualified"
        data["match_level"] = _match_level(qualification_match)
        return data

    data["hard_fail"] = False
    data["hard_fail_reason"] = None

    # ---- Step 2: Average Scoring Layer, using the job-specific weights ----
    final_score = (
        qualification_match * (weights["qualification_weight"] / 100)
        + experience_match * (weights["experience_weight"] / 100)
        + skills_match * (weights["skills_weight"] / 100)
        + education_match * (weights["education_weight"] / 100)
    )
    final_score = round(final_score, 1)
    data["score"] = final_score

    # ---- Recommendation per the rubric's decision matrix ----
    if final_score >= 85.0:
        data["recommendation"] = "Qualified"
    elif final_score >= 70.0:
        data["recommendation"] = "Potentially Qualified"
    else:
        data["recommendation"] = "Not Qualified"

    # ---- match_level mirrors the rubric's per-criterion bands ----
    data["match_level"] = _match_level(final_score)

    return data


def _clamp(value, low, high):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = low
    return max(low, min(value, high))


def _match_level(score):
    if score >= 90:
        return "Exceptional"
    if score >= 75:
        return "Proficient"
    if score >= 60:
        return "Developing"
    return "Unsatisfactory"


def _normalize_weights(qualification, experience, skills, education):
    """
    Clamp each AI-supplied weight to [10, 40], then proportionally scale
    so the four weights sum to exactly 100 while staying as close to the
    clamped values (and the 10-40 bounds) as possible.
    """
    raw = {
        "qualification_weight": _clamp(qualification, 10, 40),
        "experience_weight": _clamp(experience, 10, 40),
        "skills_weight": _clamp(skills, 10, 40),
        "education_weight": _clamp(education, 10, 40),
    }

    total = sum(raw.values())
    if total == 100:
        return raw

    # Scale proportionally, then re-clamp so no weight drifts outside
    # [10, 40] after scaling.
    scaled = {k: v * 100 / total for k, v in raw.items()}
    scaled = {k: _clamp(round(v), 10, 40) for k, v in scaled.items()}

    # Fix any rounding drift by nudging the largest weight.
    drift = 100 - sum(scaled.values())
    if drift != 0:
        biggest_key = max(scaled, key=scaled.get)
        scaled[biggest_key] = _clamp(scaled[biggest_key] + drift, 10, 40)

    return scaled
    
    
def parse_resume(resume_text):
    
    if client is None:
        raise Exception("Gemini API key is missing.")
    
    """
    Parse a resume into structured JSON data.

    This is separate from analyze_resume(), which is used
    for job-specific applicant screening.
    """

    prompt = f"""
You are a resume parser for a recruitment system.

Analyze the resume below and extract the applicant's information.

Return ONLY valid JSON.
Do not include markdown.
Do not include ```json.
Do not include explanations before or after the JSON.

Use EXACTLY this structure:

{{
    "personal": {{
        "first_name": "",
        "middle_name": "",
        "last_name": "",
        "email": "",
        "phone": ""
    }},
    "summary": "",
    "skills": [],
    "education": [],
    "experience": [],
    "certifications": [],
    "projects": []
}}

Rules:

1. Extract information only when it is present in the resume.
2. If information is missing, use an empty string or empty array.
3. Do not invent information.
4. Skills must be returned as a list of strings.
5. Education must be a list of objects.
6. Experience must be a list of objects.
7. Certifications must be a list of strings.
8. Projects must be a list of objects.
9. Keep the information concise but useful.
10. Return valid JSON that can be parsed by Python's json.loads().

For education, use:

{{
    "degree": "",
    "school": "",
    "start_year": "",
    "end_year": ""
}}

For experience, use:

{{
    "job_title": "",
    "company": "",
    "start_date": "",
    "end_date": "",
    "description": ""
}}

For projects, use:

{{
    "name": "",
    "description": ""
}}

RESUME:
{resume_text}
"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

        raw_response = response.text.strip()

        # Remove accidental markdown fences if Gemini returns them
        raw_response = re.sub(
            r"^```json\s*|\s*```$",
            "",
            raw_response,
            flags=re.IGNORECASE
        ).strip()

        parsed_data = json.loads(raw_response)

        return parsed_data

    except json.JSONDecodeError as e:
        print("Resume JSON parsing error:", e)
        print("Gemini response:", raw_response)

        return None

    except Exception as e:
        print("Resume AI parsing error:", e)

        return None