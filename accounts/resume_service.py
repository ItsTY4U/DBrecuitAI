import io
import json
import re
import pdfplumber
from google import genai
from django.conf import settings

client = None

if settings.GEMINI_API_KEY:
    client = genai.Client(api_key=settings.GEMINI_API_KEY)

def extract_resume_text(pdf_path):
    text = ""
    
    # Handle Django FieldFile, File, or other file-like objects
    if hasattr(pdf_path, "open") and not hasattr(pdf_path, "read"):
        try:
            pdf_path.open("rb")
        except Exception:
            pass

    source = pdf_path
    if hasattr(pdf_path, "read"):
        try:
            content = pdf_path.read()
            if hasattr(pdf_path, "seek"):
                pdf_path.seek(0)
            source = io.BytesIO(content)
        except Exception:
            source = pdf_path

    with pdfplumber.open(source) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            
            if page_text:
                text += page_text + "\n"
                
    return text

def parse_resume(resume_text):
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