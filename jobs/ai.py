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
    
    key_qualifications ="\n".join(
        f"- {r.text}"
        for r in job.requirements_list.all()
    )
    
    prompt = f"""
    You are an Expert HR recruiter assistant for a recruitment
    decision-support system.

    Evaluate the applicant for the following job.
    
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

    Analyze how well the applicant matches this specific job.

    Consider:

    1. Skills
    2. Work experience
    3. Education
    4. Certifications
    5. Projects
    6. Job requirements
    7. HR key qualifications

    Do not assume that the applicant has a qualification unless there
    is evidence of it in the resume.

    Return ONLY valid JSON.

    Use EXACTLY this structure:

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

        "qualification_match": 0
    }}


    RULES

    1. "score" must be an integer from 0 to 100.

    2. "skills_match" must be an integer from 0 to 100.

    3. "experience_match" must be an integer from 0 to 100.

    4. "education_match" must be an integer from 0 to 100.

    5. "qualification_match" must be an integer from 0 to 100.

    6. "match_level" must be one of:
    - "Strong Match"
    - "Good Match"
    - "Partial Match"
    - "Weak Match"

    7. "recommendation" must be one of:
    - "Highly Qualified"
    - "Qualified"
    - "Partially Qualified"
    - "Not Qualified"

    8. "matched_qualifications" must contain qualifications that
    are supported by evidence in the applicant's resume.

    9. "missing_qualifications" must contain important job
    qualifications that are required or preferred but are not
    supported by the resume.

    10. Do not invent skills, experience, education, certifications,
        or qualifications.

    11. Keep the summary concise but explain the main reason for
        the applicant's score.

    12. Keep strengths and weaknesses concise.

    13. If there is no evidence for a qualification, do not assume
        that the applicant has it.

    14. Return valid JSON that can be parsed using Python's
        json.loads().

    15. Do not include Markdown.

    16. Do not include ```json.

    17. Do not include explanations before or after the JSON.
    
    18. Do not determine the final overall score.
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

    # Calculate final AI score
    skills_match = int(data.get("skills_match", 0))
    experience_match = int(data.get("experience_match", 0))
    education_match = int(data.get("education_match", 0))
    qualification_match = int(data.get("qualification_match", 0))
    
    # Keep value within 0 - 100
    skills_match = max(0, min(skills_match, 100))
    experience_match = max(0, min(experience_match, 100))
    education_match = max(0, min(education_match, 100))
    qualification_match = max(0, min(qualification_match, 100))
    
    # Final score
    final_score = (
        (skills_match * 0.35) + (experience_match * 0.30) + (education_match * 0.15) + (qualification_match * 0.20)
    )
    
    final_score = round(final_score)
    
    # Store value
    data["skills_match"] = skills_match
    data["experience_match"] = experience_match
    data["education_match"] = education_match
    data["qualification_match"] = qualification_match
    
    data["score"] = final_score
    
    # Determine match level
    if final_score >= 85:
        data["match_level"] = "Strong Match"
    elif final_score >= 70:
        data["match_level"] = "Good Match"
    elif final_score >= 50:
        data["match_level"] = "Partial Match"
    else:
        data["match_level"] = "Weak Match"
        
    # Determine recommendation
    if final_score >= 85:
        data["recommendation"] = "Highly Qualified"
    elif final_score >= 70:
        data["recommendation"] = "Qualified"
    elif final_score >= 50:
        data["recommendation"] = "Partially Qualified"
    else:
        data["recommendation"] = "Not Qualified"
        
    return data
    
    
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