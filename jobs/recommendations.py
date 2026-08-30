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
    
    requirements = " ".join(
        requirement.text
        for requirement in job.requirements_list.all()
    )
    
    return normalize_text(
        f"""
        {job.title}
        {job.department}
        {job.description}
        {requirements}
        """
    )


def calculate_job_match(profile, job):
    """
    Calculate how well an applicant matches a job.
    """
    
    applicant_skills = get_resume_skills(profile)
    
    if not applicant_skills:
        return {
            "score": 0,
            "matched_skills": [],
            "missing_skills": []
        }
        
    job_text = get_job_text(job)
    
    matched_skills = []
    
    for skill in applicant_skills:
        if skill in job_text:
            matched_skills.append(skill)
            
    # Remove duplicate
    matched_skills = list(set(matched_skills))
    
    total_skills = len(applicant_skills)
    
    # score = round(
    #          (len(matched_skills) / total_skills) * 100
    # )
    
    # missing_skills = [
    #     skill
    #     for skill in applicant_skills
    #     if skill not in matched_skills
    # ]
    if total_skills == 0:
        score = 0
    else:
        score = round(
            (len(matched_skills) / total_skills) * 100
        )
        
    missing_skills = [
        skill
        for skill in applicant_skills
        if skill not in matched_skills
    ]
    
    return{
        "score": score,
        "matched_skills": matched_skills,
        "missing_skills": missing_skills
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
        
        if match["score"] >= 50:
            recommendations.append({
                "job": job,
                "score": match["score"],
                "matched_skills": match["matched_skills"],
                "missing_skills": match["missing_skills"]
            })
        
    # Highest score first
    recommendations.sort(
        key=lambda item: item["score"],
        reverse=True
    )
    
    return recommendations