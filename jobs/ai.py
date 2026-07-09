from google import genai
from django.conf import settings
import pdfplumber
import json

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
    requirements = "\n".join(
        f"- {r.text}" for r in job.requirements_list.all()
    )
    prompt = f"""
    You are an Expert HR recruiter assistant.
    
    Evaluate this applicant for the folliwing job
    
    Job Title:
    {job.title}
    
    Department:
    {job.department}
    
    Description:
    {job.description}
    
    Requirements:
    {requirements}
    
    Return ONLY JSON in this Format:
    
    {{
        "first_name":"",
        "middle_initial":"",
        "last_name":"",
        "email":"",
        "phone":"",
        "score": 92,
        "recommendation": "Qualified",
        "summary": "...",
        "strengths": [
            "...",
            "..."
        ],
        "weaknesses": [
            "...",
            "..."
        ]
    }}
    Resume:
    {resume_text}
    """
    
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    text = response.text.strip()
    if text.startswith("```"):
        text = text.replace("```json","")
        text = text.replace("```", "")
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print(text)
        raise Exception("Gemini returned invalid JSON")