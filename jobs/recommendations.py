import re
from datetime import datetime
from django.core.cache import cache
from .models import Job
from .ai import extract_resume_text, parse_resume
from .rubric import (
    clamp as _clamp,
    match_level as _match_level,
    normalize_weights as _normalize_weights,
    apply_knockout,
    recommendation_from_score,
    weighted_final_score,
    POTENTIALLY_QUALIFIED_THRESHOLD,
)


def normalize_text(text):
    """
    Normalize text for comparison: lowercases, strips extra whitespace,
    and removes disruptive punctuation while keeping alphanumeric tokens.
    """
    if not text:
        return ""
    text = str(text).lower()
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"[^\w\s\+\#\.\-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def get_resume_skills(profile):
    """
    Get normalized skills from the applicant's saved resume_data or profile.
    Backward-compatible with original helper.
    """
    if not profile:
        return []

    resume_data = getattr(profile, "resume_data", None) or {}
    skills = resume_data.get("skills", [])

    normalized_skills = []
    for skill in skills:
        if skill:
            clean = normalize_text(skill)
            if clean and clean not in normalized_skills:
                normalized_skills.append(clean)

    return normalized_skills


def get_job_text(job):
    """
    Combine all relevant job information for matching:
    title, department, description, requirements, and HR key qualifications.
    """
    if not job:
        return ""

    parts = [
        str(job.title or ""),
        str(job.department or ""),
        str(job.description or ""),
        str(job.requirements or ""),
    ]

    try:
        req_list = job.requirements_list.all()
        for req in req_list:
            if hasattr(req, "text") and req.text:
                parts.append(str(req.text))
    except Exception:
        pass

    return normalize_text(" ".join(parts))


# ==============================================================================
# PIPELINE STEP 1: APPLICANT RESUME
# ==============================================================================

def get_applicant_resume_data(profile):
    """
    Step 1: Retrieve and validate the applicant's processed resume data.

    If resume_data is empty but a default resume or resume_text exists,
    it leverages ai.py's extract_resume_text and parse_resume to extract
    and populate structured information automatically.
    """
    if not profile:
        return None

    resume_data = getattr(profile, "resume_data", None)
    if isinstance(resume_data, dict) and any(resume_data.values()):
        return resume_data

    # Fallback to resume_text or default_resume if resume_data has not been parsed
    resume_text = getattr(profile, "resume_text", "") or ""
    default_resume = getattr(profile, "default_resume", None)

    if not resume_text and default_resume:
        try:
            resume_text = extract_resume_text(default_resume)
            if resume_text:
                profile.resume_text = resume_text
        except Exception:
            resume_text = ""

    if resume_text:
        try:
            parsed = parse_resume(resume_text)
            if parsed and isinstance(parsed, dict):
                profile.resume_data = parsed
                profile.resume_processed = True
                try:
                    profile.save(
                        update_fields=[
                            "resume_text",
                            "resume_data",
                            "resume_processed",
                        ]
                    )
                except Exception:
                    pass
                return parsed
        except Exception:
            pass

    return resume_data if isinstance(resume_data, dict) else None


# ==============================================================================
# PIPELINE STEP 2: ANALYZE RESUME
# ==============================================================================

def analyze_applicant_resume(resume_data, resume_text=""):
    """
    Step 2: Analyze the structured resume data and prepare an enriched profile.

    Extracts:
    - Normalized skills list
    - Structured experience with tenure estimation
    - Highest education degree and field
    - Licenses, certifications, and credentials
    - Full searchable resume text
    """
    if not resume_data or not isinstance(resume_data, dict):
        return {
            "skills": [],
            "experience": [],
            "education": [],
            "certifications": [],
            "total_experience_years": 0,
            "highest_education_level": 0,
            "searchable_text": normalize_text(resume_text),
            "summary": "",
        }

    # 1. Skills
    raw_skills = resume_data.get("skills", []) or []
    skills = []
    for s in raw_skills:
        if s:
            ns = normalize_text(s)
            if ns and ns not in skills:
                skills.append(ns)

    # 2. Experience
    raw_experience = resume_data.get("experience", []) or []
    structured_experience = []
    total_months = 0
    experience_text_parts = []

    current_year = datetime.now().year

    for exp in raw_experience:
        if not isinstance(exp, dict):
            continue
        job_title = str(exp.get("job_title", "")).strip()
        company = str(exp.get("company", "")).strip()
        start_date = str(exp.get("start_date", "")).strip()
        end_date = str(exp.get("end_date", "")).strip()
        description = str(exp.get("description", "")).strip()

        # Rough tenure calculation if years are present
        years_found = re.findall(r"\b(19\d\d|20\d\d)\b", f"{start_date} {end_date}")
        if len(years_found) >= 2:
            try:
                y1 = int(years_found[0])
                y2 = int(years_found[1])
                diff_years = max(0, abs(y2 - y1))
                total_months += diff_years * 12
            except Exception:
                total_months += 12
        elif len(years_found) == 1:
            try:
                y1 = int(years_found[0])
                diff_years = max(0, current_year - y1)
                total_months += min(diff_years, 5) * 12
            except Exception:
                total_months += 12
        else:
            total_months += 12

        experience_text_parts.append(f"{job_title} {company} {description}")
        structured_experience.append({
            "job_title": normalize_text(job_title),
            "company": normalize_text(company),
            "description": normalize_text(description),
            "raw_title": job_title,
            "raw_company": company,
        })

    total_experience_years = max(0.0, round(total_months / 12.0, 1))

    # 3. Education
    raw_education = resume_data.get("education", []) or []
    structured_education = []
    highest_education_level = 0  # 0: None, 1: HS/K-12, 2: Vocational/Assoc, 3: Bachelor, 4: Master/PhD
    education_text_parts = []

    for edu in raw_education:
        if not isinstance(edu, dict):
            continue
        degree = str(edu.get("degree", "")).strip()
        school = str(edu.get("school", "")).strip()
        degree_norm = normalize_text(degree)

        level = 1
        if any(w in degree_norm for w in ["master", "phd", "doctorate", "post graduate", "mba", "ms"]):
            level = 4
        elif any(w in degree_norm for w in ["bachelor", "bs", "ba", "ab", "degree", "college", "graduate"]):
            level = 3
        elif any(w in degree_norm for w in ["associate", "vocational", "diploma", "technical", "tesda"]):
            level = 2
        elif any(w in degree_norm for w in ["high school", "secondary", "k-12", "senior high"]):
            level = 1

        if level > highest_education_level:
            highest_education_level = level

        education_text_parts.append(f"{degree} {school}")
        structured_education.append({
            "degree": degree_norm,
            "raw_degree": degree,
            "school": normalize_text(school),
            "level": level,
        })

    # 4. Certifications / Qualifications
    raw_certifications = resume_data.get("certifications", []) or []
    certifications = [
        normalize_text(c)
        for c in raw_certifications
        if c and normalize_text(c)
    ]

    # 5. Summary & Projects
    summary = str(resume_data.get("summary", "")).strip()
    projects = resume_data.get("projects", []) or []
    project_text_parts = []
    for p in projects:
        if isinstance(p, dict):
            project_text_parts.append(
                f"{p.get('name', '')} {p.get('description', '')}"
            )

    full_searchable = " ".join(filter(None, [
        summary,
        " ".join(skills),
        " ".join(experience_text_parts),
        " ".join(education_text_parts),
        " ".join(certifications),
        " ".join(project_text_parts),
        resume_text,
    ]))

    return {
        "skills": skills,
        "experience": structured_experience,
        "education": structured_education,
        "certifications": certifications,
        "total_experience_years": total_experience_years,
        "highest_education_level": highest_education_level,
        "searchable_text": normalize_text(full_searchable),
        "summary": summary,
    }


# ==============================================================================
# PIPELINE STEP 3: COMPARE WITH ACTIVE JOBS
# ==============================================================================

def _match_phrase_in_text(phrase, text):
    """
    Check if a word or phrase appears in normalized text with word boundaries,
    preventing false positive substring matches (e.g. 'c' in 'docker').
    """
    if not phrase or not text:
        return False
    pattern = r"(?:^|[\s,;./\-_()])" + re.escape(phrase) + r"(?:$|[\s,;./\-_()])"
    return bool(re.search(pattern, text))


def _score_skills_match(applicant_skills, job_text, requirements_text):
    """
    Score Skills (Hard, Soft, & Tools) following the shared rubric:
    90-100 Exceptional: high density (>80%) of core tools & keywords matched
    75-89  Proficient: solid baseline (60-79%) of primary hard skills matched
    60-74  Developing: weak keyword alignment (<60%)
    50-59  Unsatisfactory: zero relevant skills or proficiencies matched
    """
    if not applicant_skills:
        return 50, [], []

    matched_skills = []
    missing_skills = []

    for skill in applicant_skills:
        if _match_phrase_in_text(skill, job_text):
            matched_skills.append(skill)
        else:
            missing_skills.append(skill)

    total_skills = len(applicant_skills)
    ratio = len(matched_skills) / total_skills if total_skills > 0 else 0.0

    if ratio >= 0.80:
        score = 90 + round((ratio - 0.80) / 0.20 * 10)
    elif ratio >= 0.60:
        score = 75 + round((ratio - 0.60) / 0.20 * 14)
    elif ratio >= 0.20:
        score = 60 + round((ratio - 0.20) / 0.40 * 14)
    elif len(matched_skills) > 0:
        score = 60
    else:
        score = 50

    return _clamp(score, 50, 100), matched_skills, missing_skills


def _score_qualifications_match(certifications, resume_text, job):
    """
    Score Qualifications (Licenses & Certifications) following the shared
    rubric:
    90-100 Exceptional: exceeds requirements, holds premium credentials
    75-89  Proficient: meets mandatory local credentials (PRC, TESDA, LTO, certs)
    60-74  Developing: credentials incomplete, but transferable credentials exist
    50-59  Unsatisfactory: completely lacks mandatory non-negotiable licenses

    Returns (score, matched_qualifications, missing_qualifications, has_mandatory_req)
    """
    job_req_text = normalize_text(job.requirements or "")
    key_qual_texts = []
    try:
        for r in job.requirements_list.all():
            if hasattr(r, "text") and r.text:
                key_qual_texts.append(normalize_text(r.text))
    except Exception:
        pass

    combined_job_quals = key_qual_texts + ([job_req_text] if job_req_text else [])
    job_qual_combined_text = " ".join(combined_job_quals)

    # Detect common Philippine regulatory & industry mandatory credentials.
    # NOTE: has_mandatory_req is used to tailor the qualification WEIGHT and
    # the hard-fail explanation text — it no longer decides whether the
    # knockout applies. The knockout (rubric.apply_knockout) is universal.
    mandatory_keywords = [
        "prc", "license", "licensed", "tesda", "nc ii", "nc 2",
        "nc iii", "driver's license", "lto", "board passer", "registered",
        "certification required", "must have license",
    ]

    has_mandatory_req = any(
        kw in job_qual_combined_text for kw in mandatory_keywords
    )

    matched_quals = []
    missing_quals = []

    for key_qual in key_qual_texts:
        if not key_qual:
            continue
        words = [w for w in key_qual.split() if len(w) > 3]
        if words and all(w in resume_text for w in words[:3]):
            matched_quals.append(key_qual)
        else:
            missing_quals.append(key_qual)

    cert_matches = 0
    for cert in certifications:
        if _match_phrase_in_text(cert, job_qual_combined_text):
            cert_matches += 1
            if cert not in matched_quals:
                matched_quals.append(cert)

    if has_mandatory_req:
        applicant_has_credential = False
        for kw in mandatory_keywords:
            if kw in job_qual_combined_text:
                if _match_phrase_in_text(kw, resume_text):
                    applicant_has_credential = True
                    break

        if applicant_has_credential:
            score = 85 + min(15, cert_matches * 5)
        else:
            # Below the shared knockout threshold on purpose — the
            # candidate is missing a detected mandatory credential.
            score = 55
            missing_quals.append("Mandatory license/certification required by JD")
    else:
        if cert_matches > 0 or len(matched_quals) > 0:
            score = 80 + min(20, (cert_matches + len(matched_quals)) * 5)
        elif certifications:
            score = 75
        else:
            score = 70

    return _clamp(score, 50, 100), matched_quals, missing_quals, has_mandatory_req


def _score_experience_match(analyzed_resume, job):
    """
    Score Experience (Tenure & Environment) following the shared rubric:
    90-100 Exceptional: tenure exceeds JD, strong alignment in environment
    75-89  Proficient: meets required years; past environments directly match
    60-74  Developing: shorter tenure or transferable context
    50-59  Unsatisfactory: no relevant experience
    """
    job_text = get_job_text(job)
    job_title = normalize_text(job.title or "")
    job_dept = normalize_text(job.department or "")

    req_years_matches = re.findall(
        r"(\d+)\+?\s*(?:year|yr)s?(?:\s+of\s+experience)?", job_text
    )
    req_years = 0
    if req_years_matches:
        try:
            req_years = min([int(y) for y in req_years_matches if int(y) < 25] or [0])
        except Exception:
            req_years = 0

    applicant_years = analyzed_resume.get("total_experience_years", 0)
    experiences = analyzed_resume.get("experience", [])

    if not experiences:
        return 50

    title_matches = 0
    desc_matches = 0
    job_title_words = [w for w in job_title.split() if len(w) > 3]

    for exp in experiences:
        exp_title = exp.get("job_title", "")
        exp_desc = exp.get("description", "")

        if any(w in exp_title for w in job_title_words):
            title_matches += 1

        if job_dept and job_dept in exp_desc:
            desc_matches += 1

    if req_years > 0:
        if applicant_years >= req_years + 2:
            tenure_score = 90
        elif applicant_years >= req_years:
            tenure_score = 80
        elif applicant_years >= req_years * 0.5:
            tenure_score = 65
        else:
            tenure_score = 55
    else:
        if applicant_years >= 3:
            tenure_score = 85
        elif applicant_years >= 1:
            tenure_score = 75
        else:
            tenure_score = 65

    relevance_bonus = min(10, (title_matches * 5) + (desc_matches * 3))
    final_exp_score = tenure_score + relevance_bonus

    return _clamp(final_exp_score, 50, 100)


def _score_education_match(highest_edu_level, job_text):
    """
    Score Education (Academic Baseline) following the shared rubric:
    90-100 Exceptional: exceeds minimum requirement
    75-89  Proficient: matches minimum required education
    60-74  Developing: below requested level, but field experience offset
    50-59  Unsatisfactory: does not meet baseline
    """
    req_level = 3  # Default expectation: Bachelor's degree (level 3)
    if any(w in job_text for w in ["master", "phd", "doctorate", "mba"]):
        req_level = 4
    elif any(w in job_text for w in ["vocational", "associate", "tesda", "technical diploma"]):
        req_level = 2
    elif any(w in job_text for w in ["high school", "senior high", "k-12", "secondary"]):
        req_level = 1

    diff = highest_edu_level - req_level

    if diff > 0:
        score = 95
    elif diff == 0:
        score = 82
    elif diff == -1:
        score = 65
    else:
        score = 52

    return _clamp(score, 50, 100)


def calculate_job_match(profile, job):
    """
    Calculate how well an applicant matches a job using the shared
    4-criteria rubric:
    1. Qualifications (Licenses & Certifications)
    2. Experience (Tenure & Environment)
    3. Skills (Hard, Soft, & Tools)
    4. Education (Academic Baseline)

    Uses the same knockout rule, weight normalization, match-level bands,
    and recommendation bands as ai.py's analyze_resume — both pull from
    rubric.py so they can't silently disagree.
    """
    resume_data = get_applicant_resume_data(profile)
    resume_text = getattr(profile, "resume_text", "") or ""

    analyzed = analyze_applicant_resume(resume_data, resume_text)
    job_text = get_job_text(job)
    req_text = normalize_text(job.requirements or "")

    # 1. Skills Match
    skills_match, matched_skills, missing_skills = _score_skills_match(
        analyzed["skills"], job_text, req_text
    )

    # 2. Qualifications Match
    qualification_match, matched_quals, missing_quals, has_mandatory_license = (
        _score_qualifications_match(
            analyzed["certifications"], analyzed["searchable_text"], job
        )
    )

    # 3. Experience Match
    experience_match = _score_experience_match(analyzed, job)

    # 4. Education Match
    education_match = _score_education_match(
        analyzed["highest_education_level"], job_text
    )

    # Heuristic per-job weights (a stand-in for the LLM's per-job
    # reasoning in ai.py, since we don't call Gemini for every job in a
    # bulk recommendation pass). Bump education weight when the JD itself
    # calls for a specific degree, mirroring how qualification weight
    # reacts to a detected mandatory license.
    requires_degree = any(
        w in job_text for w in ["bachelor", "degree required", "college graduate"]
    )
    q_weight = 35 if has_mandatory_license else 20
    s_weight = 35 if len(analyzed["skills"]) >= 3 else 25
    exp_weight = 30 if ("senior" in job_text or "lead" in job_text) else 25
    edu_weight = 25 if requires_degree else 15

    weights = _normalize_weights(
        qualification=q_weight,
        experience=exp_weight,
        skills=s_weight,
        education=edu_weight,
    )

    # ---- Step 1: Knockout Layer (Safety Check) — shared with ai.py ----
    # Applies to every job, not just ones with a detected mandatory
    # license, per rubric.apply_knockout.
    if apply_knockout(qualification_match):
        hard_fail_reason = (
            "Lacks the mandatory, non-negotiable license or credential "
            "required for this role."
            if has_mandatory_license else
            "Qualifications score fell below the minimum threshold for "
            "this role."
        )
        return {
            "score": qualification_match,
            "match_level": _match_level(qualification_match),
            "recommendation": "Not Qualified",
            "skills_match": skills_match,
            "experience_match": experience_match,
            "education_match": education_match,
            "qualification_match": qualification_match,
            "matched_skills": matched_skills,
            "missing_skills": missing_skills,
            "matched_qualifications": matched_quals,
            "missing_qualifications": missing_quals,
            "hard_fail": True,
            "hard_fail_reason": hard_fail_reason,
            "criteria_weights": weights,
        }

    # ---- Step 2: Average Scoring Layer ----
    final_score = _clamp(
        round(
            weighted_final_score(
                qualification_match, experience_match, skills_match,
                education_match, weights,
            )
        ),
        0, 100,
    )

    return {
        "score": final_score,
        "match_level": _match_level(final_score),
        "recommendation": recommendation_from_score(final_score),
        "skills_match": skills_match,
        "experience_match": experience_match,
        "education_match": education_match,
        "qualification_match": qualification_match,
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
        "matched_qualifications": matched_quals,
        "missing_qualifications": missing_quals,
        "hard_fail": False,
        "hard_fail_reason": None,
        "criteria_weights": weights,
    }


# ==============================================================================
# PIPELINE STEP 4: RANK JOBS
# ==============================================================================

def rank_jobs(recommendations):
    """
    Step 4: Rank jobs based on the applicant's match score.

    Tie-breaking hierarchy:
    1. Score (descending)
    2. Skills Match (descending)
    3. Experience Match (descending)
    4. Job posted date / ID (newest first)
    """
    if not recommendations:
        return []

    return sorted(
        recommendations,
        key=lambda item: (
            item.get("score", 0),
            item.get("skills_match", 0),
            item.get("experience_match", 0),
            getattr(item.get("job"), "posted_date", None) or "",
            getattr(item.get("job"), "id", 0),
        ),
        reverse=True,
    )


def _build_candidate_summary(job, top_skills):
    """
    Candidate-facing summary line for a recommendation card. Deliberately
    avoids HR-facing language (raw score, recommendation label) — this is
    shown to the applicant, not a hiring manager.
    """
    if top_skills:
        skills_text = ", ".join(s.title() for s in top_skills[:3])
        return f"Your background in {skills_text} lines up well with this role."
    return f"Your profile overlaps well with what {job.title} is looking for."


# ==============================================================================
# PIPELINE STEP 5: RECOMMEND BEST JOBS
# ==============================================================================

def get_recommended_jobs(profile, min_score=None, limit=None):
    """
    Step 5: Recommend best jobs for the applicant.

    Full Pipeline:
    Applicant Resume -> Analyze Resume -> Compare With Active Jobs -> Rank Jobs -> Recommend Best Jobs

    Returns a ranked list of dictionaries ready for templates and views.

    Hard-failed jobs (missing a mandatory qualification) are always
    excluded here, regardless of min_score, since a knockout means "Not
    Qualified" no matter what the leftover qualification_match number
    happens to be. The default min_score is the rubric's own
    "Potentially Qualified" cutoff, so this section only ever surfaces
    jobs the rubric itself calls a real match — anything weaker belongs
    on the full jobs listing, not under "Recommended".
    """
    if min_score is None:
        min_score = POTENTIALLY_QUALIFIED_THRESHOLD
    if not profile:
        return []

    profile_id = getattr(profile, "id", None)
    processed_at = getattr(profile, "resume_processed_at", None)
    cache_key = f"job_recs_{profile_id}_{processed_at}"

    if profile_id:
        cached_recommendations = cache.get(cache_key)
        if cached_recommendations is not None:
            return cached_recommendations[:limit] if limit else cached_recommendations

    resume_data = get_applicant_resume_data(profile)
    if not resume_data:
        return []

    jobs = Job.objects.filter(
        status="Active"
    ).prefetch_related(
        "requirements_list"
    )

    recommendations = []

    for job in jobs:
        match = calculate_job_match(profile, job)

        # A hard fail is "Not Qualified" by rubric definition, no matter
        # what match["score"] (== qualification_match) happens to be —
        # never let it into a "Recommended for you" section.
        if match["hard_fail"]:
            continue

        if match["score"] >= min_score:
            top_skills = match["matched_skills"][:4]
            recommendations.append({
                "job": job,
                "score": match["score"],
                "match_level": match["match_level"],
                "recommendation": match["recommendation"],
                "matched_skills": top_skills,
                "missing_skills": match["missing_skills"],
                "matched_qualifications": match["matched_qualifications"],
                "missing_qualifications": match["missing_qualifications"],
                "skills_match": match["skills_match"],
                "experience_match": match["experience_match"],
                "education_match": match["education_match"],
                "qualification_match": match["qualification_match"],
                "summary": _build_candidate_summary(job, top_skills),
            })

    ranked_recommendations = rank_jobs(recommendations)

    if profile_id:
        cache.set(cache_key, ranked_recommendations, timeout=300)

    if limit and limit > 0:
        return ranked_recommendations[:limit]

    return ranked_recommendations