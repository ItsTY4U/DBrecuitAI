import re
from .models import Job


def normalize_text(text):
    """
    Normalize text for comparison
    """
    
    if not text:
        return ""
    return str(text).lower()

def get_resume_skills(profile):
    """
    Get skills from the application's saved resume_data.
    """
    
    resume_data = profile.resume_data or {}
    
    skills = resume_data.get("skills", [])
    
    return [
        normalize_text(skill)
        for skill in skills
        if skill
    ]
    
def get_job_text(job):
    """
    Combine all relavant job information.
    """
    
    return normalize_text(
        f"""
        {job.title}
        {job.department}
        {job.description}
        {job.requirements}
        """
    )


def calculate_job_match(profile, job):
    """
    Calculate how well an applicant matches a job.
    """
    
    resume_data = profile.resume_data or {}
    
    applicant_skills = [
        normalize_text(skill)
        for skill in resume_data.get("skills", [])
        if skill
    ]
    
    experience = resume_data.get("experience", [])
    education = resume_data.get("education", [])
    
    
    job_text = get_job_text(job)
    
    
    matched_skills = []
    
    for skill in applicant_skills:
        if skill and skill in job_text:
            matched_skills.append(skill)
            
    # Remove duplicate
    matched_skills = list(set(matched_skills))
    
    if applicant_skills:
        skills_match = round(
            (len(matched_skills) / len(applicant_skills)) * 100
        )
    else:
        skills_match = 0
    
    experience_text = ""
    
    for exp in experience:
        if isinstance(exp, dict):
            experience_text += " ".join([
                str(exp.get("job_title", "")),
                str(exp.get("company", "")),
                str(exp.get("description","")),
            ]) + " "
            
    experience_text = normalize_text(experience_text)
    
    experience_words = set(experience_text.split())
    job_words = set(job_text.split())
    
    matched_experience_words = experience_words.intersection(job_words)
    
    if experience_words:
        experience_match = round(
            (len(matched_experience_words) / len(experience_words)) * 100
        )
    else:
        experience_match = 0
        
    
    education_text = ""
    
    for edu in education:
        if isinstance(edu, dict):
            education_text += " ".join([
                str(edu.get("degree", "")),
                str(edu.get("school", "")),
            ]) + " "
            
    education_text = normalize_text(education_text)
    
    education_words = set(education_text.split())
    matched_education_words = education_words.intersection(job_words)
    
    if education_words:
        education_match = round(
            (len(matched_education_words) / len(education_words )) * 100
        )
    else:
        education_match = 0
        
    # General req
    requirements_text = normalize_text(job.requirements)
    
    resume_text_parts = [
        resume_data.get("summary", ""),
        " ".join(resume_data.get("skills", [])),
        experience_text,
        education_text,
        " ".join(resume_data.get("certifications", [])),
    ]
    
    for project in resume_data.get("projects", []):
        if isinstance(project, dict):
            resume_text_parts.append(
                f"{project.get('name', '')} "
                f"{project.get('description', '')}"
            )
    
    resume_text = normalize_text(" ".join(
        str(part) for part in resume_text_parts if part
    ))
    
    requirements_words = set(requirements_text.split())
    resume_words = set(resume_text.split())
    
    matched_requirements_words = requirements_words.intersection(resume_words)
    
    if requirements_words:
        requirements_match = round(
            (len(matched_requirements_words) / len(requirements_words)) * 100
        )
    else:
        requirements_match = 0
        
    # Final score
    final_score = (
        (skills_match * 0.35) +
        (experience_match * 0.30) +
        (education_match * 0.15) +
        (requirements_match * 0.20)
    )
    
    final_score = round(final_score)
    
    # Kepp score betwwen 0 and 100
    final_score = max(0, min(final_score, 100))
    
    # Match level
    if final_score >= 85:
        match_level = "Strong Match"
    elif final_score >= 70:
        match_level = "Good Match"
    elif final_score >= 50:
        match_level = "Partial Match"
    else:
        match_level = "Weak Match"
    
    # Missing skills
    missing_skills = [
        skill
        for skill in applicant_skills
        if skill not in matched_skills
    ]
    
    # Return
    return{
        "score": final_score,
        
        "skills_match": skills_match,
        "experience_match": experience_match,
        "education_match": education_match,
        "requirements_match": requirements_match,
        
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
        
        "match_level": match_level,
    }
    
    
    
def get_recommended_jobs(profile):
    """
    Get active jobs and rank them based on the applicant's resume.
    """
    
    jobs = Job.objects.filter(
        status="Active"
    ).prefetch_related(
        "requirements_list"
    )
    
    recommendations = []
    
    for job in jobs:
        
        match = calculate_job_match(
            profile,
            job
        )
        
        if match["score"] >= 30:
            recommendations.append({
                "job": job,
                "score": match["score"],
                "matched_skills": match["matched_skills"],
                "missing_skills": match["missing_skills"],
                "match_level": match["match_level"]
            })
        
    # Highest score first
    recommendations.sort(
        key=lambda item: item["score"],
        reverse=True
    )
    
    return recommendations