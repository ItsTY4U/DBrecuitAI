import re
from django.core.cache import cache
from .models import Job


def normalize_text(text):
    """
    Normalize text for comparison
    """
    if not text:
        return ""
    return str(text).lower().strip()


def get_resume_skills(profile):
    """
    Get skills from the application's saved resume_data.
    """
    resume_data = profile.resume_data or {}
    skills = resume_data.get("skills", [])
    seen = set()
    cleaned = []
    for skill in skills:
        norm = normalize_text(skill)
        if norm and norm not in seen:
            seen.add(norm)
            cleaned.append(norm)
    return cleaned


def get_job_text(job):
    """
    Combine all relevant job information.
    """
    requirements = " ".join(
        requirement.text
        for requirement in job.requirements_list.all()
    )
    return normalize_text(
        f"{job.title} {job.department} {job.description} {requirements}"
    )


def calculate_job_match(profile, job, applicant_skills=None):
    """
    Calculate how well an applicant matches a job.
    """
    if applicant_skills is None:
        applicant_skills = get_resume_skills(profile)

    if not applicant_skills:
        return {
            "score": 0,
            "matched_skills": [],
            "missing_skills": []
        }

    job_text = get_job_text(job)
    matched_skills = [
        skill for skill in applicant_skills
        if skill in job_text
    ]

    total_skills = len(applicant_skills)
    score = round((len(matched_skills) / total_skills) * 100) if total_skills > 0 else 0

    missing_skills = [
        skill
        for skill in applicant_skills
        if skill not in matched_skills
    ]

    return {
        "score": score,
        "matched_skills": matched_skills,
        "missing_skills": missing_skills
    }


def get_recommended_jobs(profile):
    """
    Get active jobs and rank them based on the applicant's resume.
    Uses caching and early exit to maximize speed.
    """
    applicant_skills = get_resume_skills(profile)
    if not applicant_skills:
        return []

    # Check cache based on profile ID and last resume processed timestamp
    processed_time = (
        profile.resume_processed_at.isoformat()
        if profile.resume_processed_at
        else "none"
    )
    cache_key = f"rec_jobs_{profile.id}_{processed_time}"
    cached_recommendations = cache.get(cache_key)
    if cached_recommendations is not None:
        return cached_recommendations

    jobs = Job.objects.filter(
        status="Active"
    ).prefetch_related(
        "requirements_list"
    )

    recommendations = []
    for job in jobs:
        match = calculate_job_match(
            profile,
            job,
            applicant_skills=applicant_skills
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

    # Cache for 10 minutes (600 seconds)
    cache.set(cache_key, recommendations, 600)

    return recommendations