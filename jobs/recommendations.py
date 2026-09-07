import re
from django.core.cache import cache
from .models import Job


from functools import lru_cache


def normalize_text(text):
    """
    Normalize text for comparison
    """
    if not text:
        return ""
    return str(text).lower().strip()


def get_resume_skills(profile):
    """
    Get skills from the application's saved resume_data, preserving original casing.
    """
    resume_data = profile.resume_data or {}
    skills = resume_data.get("skills", [])
    seen = set()
    cleaned = []
    for skill in skills:
        if not skill or not isinstance(skill, str):
            continue
        trimmed = skill.strip()
        if not trimmed:
            continue
        lower_key = trimmed.lower()
        if lower_key not in seen:
            seen.add(lower_key)
            cleaned.append(trimmed)
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


@lru_cache(maxsize=512)
def build_skill_pattern(skill: str):
    """
    Compile a regex pattern for a skill with whole-word / phrase-boundary semantics.
    Handles special characters (C++, C#, .NET, Node.js, R&D, 24/7), case-insensitivity,
    and arbitrary whitespace variation between words.
    """
    tokens = skill.strip().split()
    if not tokens:
        return None

    # Escape tokens so special chars like +, #, ., &, -, / are treated literally
    escaped_tokens = [re.escape(token) for token in tokens]
    phrase = r"\s+".join(escaped_tokens)

    last_char = tokens[-1][-1]
    left_boundary = r"(?<!\w)"

    # Right boundary logic:
    # - If skill ends with '+', ensure not followed by word chars or '+'
    # - If skill ends with '#', ensure not followed by word chars or '#'
    # - If skill ends with word char (e.g. 'C', 'R'), ensure not followed by
    #   word chars OR continuation symbols like '+' ('C++'), '#' ('C#'), or '&[a-zA-Z]' ('R&D')
    if last_char == "+":
        right_boundary = r"(?![\w+])"
    elif last_char == "#":
        right_boundary = r"(?![\w#])"
    else:
        right_boundary = r"(?!(?:&[a-zA-Z]|[\w+#]))"

    return re.compile(f"{left_boundary}{phrase}{right_boundary}", re.IGNORECASE)


def find_matched_skills(applicant_skills, job_text):
    """
    Matches a list of applicant skills against job text using normalized,
    token/phrase-aware matching for any industry.

    Preserves original casing and order of applicant_skills.
    """
    if not applicant_skills or not job_text:
        return []

    matched = []
    for skill in applicant_skills:
        if not skill or not isinstance(skill, str):
            continue
        trimmed = skill.strip()
        if not trimmed:
            continue

        pattern = build_skill_pattern(trimmed)
        if pattern and pattern.search(job_text):
            matched.append(skill)

    return matched


def calculate_job_match(profile, job, applicant_skills=None):
    """
    Calculate how well an applicant matches a job using token/phrase-aware matching.
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
    matched_skills = find_matched_skills(applicant_skills, job_text)

    valid_skills = [
        s for s in applicant_skills
        if s and isinstance(s, str) and s.strip()
    ]
    total_skills = len(valid_skills)
    score = round((len(matched_skills) / total_skills) * 100) if total_skills > 0 else 0

    matched_set = set(matched_skills)
    missing_skills = [
        skill
        for skill in valid_skills
        if skill not in matched_set
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

    # Retrieve active jobs with requirements from cache to avoid repeated DB round-trips
    jobs = cache.get("active_jobs_with_requirements")
    if jobs is None:
        jobs = list(
            Job.objects.filter(status="Active").prefetch_related("requirements_list")
        )
        cache.set("active_jobs_with_requirements", jobs, 300)

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

    # Cache for 15 minutes (900 seconds)
    cache.set(cache_key, recommendations, 900)

    return recommendations