import re
from datetime import datetime
from functools import lru_cache
from typing import List, Optional, Tuple

from django.core.cache import cache

from .ai import extract_resume_text, parse_resume
from .models import Job
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

    escaped_tokens = [re.escape(token) for token in tokens]
    phrase = r"\s+".join(escaped_tokens)

    last_char = tokens[-1][-1]
    left_boundary = r"(?<!\w)"

    if last_char == "+":
        right_boundary = r"(?![\w+])"
    elif last_char == "#":
        right_boundary = r"(?![\w#])"
    else:
        right_boundary = r"(?!(?:&[a-zA-Z]|[\w+#]))"

    return re.compile(f"{left_boundary}{phrase}{right_boundary}", re.IGNORECASE)


def find_matched_skills(applicant_skills: List[str], job_text: str) -> List[str]:
    """
    Matches a list of applicant skills against job text using normalized,
    token/phrase-aware matching for any industry. Preserves original casing and order.
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
            matched.append(trimmed)

    return matched


def _match_phrase_in_text(phrase: str, text: str) -> bool:
    """
    Check if a word or phrase appears in normalized text with word boundaries,
    preventing false positive substring matches (e.g. 'c' in 'docker').
    """
    if not phrase or not text:
        return False
    pattern = build_skill_pattern(phrase)
    if pattern:
        return bool(pattern.search(text))
    escaped = re.escape(phrase)
    pattern = r"(?:^|[\s,;./\-_()])" + escaped + r"(?:$|[\s,;./\-_()])"
    return bool(re.search(pattern, text, re.IGNORECASE))


def _score_skills_match(applicant_skills: List[str], job_text: str, requirements_text: str) -> Tuple[int, List[str], List[str]]:
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

    num_matched = len(matched_skills)
    total_skills = len(applicant_skills)
    ratio = num_matched / total_skills if total_skills > 0 else 0.0

    if num_matched >= 5 or (num_matched >= 4 and ratio >= 0.50):
        score = 92 + min(8, num_matched)
    elif num_matched >= 3 or (num_matched >= 2 and ratio >= 0.50):
        score = 80 + min(9, round(ratio * 15))
    elif num_matched >= 2 or (num_matched >= 1 and ratio >= 0.30):
        score = 70 + min(4, num_matched * 2)
    elif num_matched >= 1:
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

        if job_dept and (job_dept in exp_desc or job_dept in exp_title):
            desc_matches += 1

    has_relevance = (title_matches > 0) or (desc_matches > 0)

    if req_years > 0:
        if applicant_years >= req_years + 2:
            base_score = 90 if has_relevance else 65
        elif applicant_years >= req_years:
            base_score = 80 if has_relevance else 60
        elif applicant_years >= req_years * 0.5:
            base_score = 65 if has_relevance else 55
        else:
            base_score = 55
    else:
        if applicant_years >= 3:
            base_score = 85 if has_relevance else 62
        elif applicant_years >= 1:
            base_score = 75 if has_relevance else 58
        else:
            base_score = 65 if has_relevance else 52

    relevance_bonus = min(10, (title_matches * 5) + (desc_matches * 3))
    final_exp_score = base_score + relevance_bonus

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

    # Calculate domain & title alignment between resume experience and job
    experiences = analyzed.get("experience", [])
    job_title_words = [w for w in normalize_text(job.title or "").split() if len(w) > 3]
    title_matches = sum(
        1 for exp in experiences
        if any(w in exp.get("job_title", "") for w in job_title_words)
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
            "title_matches": title_matches,
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
        "title_matches": title_matches,
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
# FIELD TAXONOMY & STRONGEST FIELD IDENTIFICATION
# ==============================================================================

FIELD_TAXONOMY = {
    "IT": {
        "display_name": "Technology & IT",
        "departments": {
            "it", "information technology", "engineering", "software engineering",
            "technology", "tech", "development", "web development", "computer science",
            "software development", "it support", "qa",
        },
        "titles": [
            "software engineer", "developer", "web developer", "front end", "frontend",
            "back end", "backend", "full stack", "fullstack", "programmer", "systems analyst",
            "devops", "ui/ux", "ux designer", "ui designer", "it support", "it specialist",
            "it technician", "network engineer", "network administrator", "database administrator",
            "dba", "qa engineer", "qa tester", "software tester", "data analyst", "data scientist",
            "data engineer", "cloud engineer", "solutions architect", "scrum master", "cybersecurity",
            "information security", "helpdesk technician", "it clerk", "computer technician",
            "mobile developer", "ios developer", "android developer", "tech lead",
        ],
        "skills": [
            "python", "javascript", "typescript", "java", "c++", "c#", ".net", "dotnet",
            "react", "react.js", "reactjs", "angular", "vue", "vue.js", "node", "node.js",
            "nodejs", "django", "flask", "fastapi", "spring boot", "express", "sql",
            "postgresql", "postgres", "mysql", "sqlite", "mongodb", "redis", "docker",
            "kubernetes", "aws", "azure", "gcp", "git", "github", "gitlab", "html",
            "html5", "css", "css3", "tailwind", "bootstrap", "sass", "scss", "rest api",
            "restful api", "rest", "api", "graphql", "ci/cd", "machine learning", "deep learning",
            "linux", "bash", "software development", "web development", "mobile development",
            "android", "ios", "flutter", "react native", "figma", "json", "nosql",
            "pandas", "numpy", "tensorflow", "pytorch", "ui/ux", "wireframing", "agile", "scrum",
        ],
        "education": [
            "computer science", "information technology", "computer engineering",
            "software engineering", "information systems", "data science", "comsci",
            "bsit", "bscs", "bsce",
        ],
        "certifications": [
            "aws", "azure", "cisco", "ccna", "comptia", "google cloud", "pmp", "scrum master",
        ],
    },
    "Sales": {
        "display_name": "Sales & Marketing",
        "departments": {
            "sales", "marketing", "business development", "commercial", "advertising", "retail",
        },
        "titles": [
            "sales staff", "sales representative", "sales rep", "sales associate",
            "sales executive", "sales manager", "sales lead", "account executive",
            "account manager", "business development", "bizdev", "telemarketer",
            "telesales", "retail sales", "retail associate", "merchandiser",
            "marketing specialist", "marketing manager", "marketing associate",
            "brand manager", "sales consultant", "promodiser",
        ],
        "skills": [
            "b2b sales", "b2c sales", "cold calling", "lead generation", "sales pipeline",
            "crm", "salesforce", "hubspot", "negotiation", "closing deals", "client acquisition",
            "sales forecasting", "quota achievement", "product presentation",
            "account management", "upselling", "cross-selling", "market research",
            "digital marketing", "seo", "sem", "social media marketing", "merchandising",
            "customer acquisition", "sales strategy", "direct sales", "telemarketing",
        ],
        "education": [
            "marketing", "business administration", "commerce", "entrepreneurship",
            "bsba marketing",
        ],
        "certifications": [
            "hubspot", "salesforce", "google digital marketing",
        ],
    },
    "Warehouse": {
        "display_name": "Warehouse & Logistics",
        "departments": {
            "warehouse", "logistics", "supply chain", "distribution", "inventory",
        },
        "titles": [
            "warehouse helper", "warehouse worker", "warehouse associate", "warehouse staff",
            "warehouse supervisor", "forklift operator", "forklift driver", "inventory clerk",
            "inventory specialist", "stocker", "stock clerk", "picker", "packer",
            "material handler", "logistics coordinator", "logistics assistant",
            "shipping clerk", "receiving clerk", "dispatcher", "dock worker",
            "warehouse assistant",
        ],
        "skills": [
            "inventory management", "forklift", "forklift operation", "forklift certified",
            "picking", "packing", "picking and packing", "order picking", "order fulfillment",
            "stocking", "shipping", "receiving", "shipping and receiving", "pallet jack",
            "material handling", "cargo handling", "loading and unloading", "load and unload",
            "cycle counting", "warehouse management", "wms", "logistics", "supply chain",
            "stock inventory", "freight",
        ],
        "education": [
            "supply chain management", "logistics management",
        ],
        "certifications": [
            "forklift license", "forklift certification", "tesda heavy equipment",
        ],
    },
    "Administrative": {
        "display_name": "Administrative & Office",
        "departments": {
            "administrative", "administration", "office", "clerical", "secretarial",
            "general admin",
        },
        "titles": [
            "admin staff", "administrative assistant", "admin assistant",
            "administrative staff", "office clerk", "executive assistant",
            "office administrator", "receptionist", "front desk", "office manager",
            "data entry", "data entry specialist", "data entry clerk",
            "data entry operator", "secretary", "records clerk", "billing clerk",
            "clerical assistant", "clerk", "document controller",
        ],
        "skills": [
            "office administration", "data entry", "record keeping", "document management",
            "calendar management", "meeting scheduling", "filing", "clerical support",
            "secretarial duties", "microsoft office", "office 365", "excel", "word",
            "typing", "typing speed", "wpm", "spreadsheet management", "front desk",
            "phone etiquette", "correspondence", "documentation", "record organization",
            "office coordination",
        ],
        "education": [
            "office administration", "bsoa", "business administration", "secretarial",
        ],
        "certifications": [
            "civil service", "tesda bookkeeping",
        ],
    },
    "Security": {
        "display_name": "Security & Safety",
        "departments": {
            "security", "safety", "loss prevention", "asset protection",
        },
        "titles": [
            "security guard", "security officer", "safety officer", "patrol officer",
            "watchman", "bouncer", "cctv operator", "loss prevention officer",
            "security supervisor", "surveillance officer", "guard",
        ],
        "skills": [
            "surveillance", "patrolling", "cctv", "cctv monitoring", "access control",
            "incident reporting", "incident response", "physical security",
            "emergency response", "asset protection", "perimeter security",
            "crowd control", "first aid", "security inspection", "guarding",
            "security protocol",
        ],
        "education": [
            "criminology", "security management",
        ],
        "certifications": [
            "sosia", "security guard license", "security license", "safety officer",
            "so2", "osh",
        ],
    },
    "Operations": {
        "display_name": "Operations & Food Service",
        "departments": {
            "operations", "food & beverage", "f&b", "hospitality", "restaurant",
            "cafe", "food service", "dining",
        },
        "titles": [
            "barista", "cafe staff", "food server", "waiter", "waitress", "bartender",
            "restaurant crew", "service crew", "dining crew", "kitchen staff", "cook",
            "chef", "baker", "counter staff", "store crew", "fast food crew",
            "crew member", "restaurant worker",
        ],
        "skills": [
            "coffee brewing", "coffee brewing knowledge", "espresso", "latte art",
            "drink preparation", "food preparation", "food handling", "point of sale",
            "pos", "cash handling", "table service", "food safety", "sanitation",
            "kitchen operations", "menu knowledge", "brewing", "beverage preparation",
            "barista skills",
        ],
        "education": [
            "hospitality management", "hotel and restaurant management", "hrm",
            "culinary arts",
        ],
        "certifications": [
            "tesda barista", "barista nc ii", "food safety certification", "servsafe",
        ],
    },
    "Human Resources": {
        "display_name": "Human Resources",
        "departments": {
            "human resources", "hr", "people operations", "talent acquisition", "recruitment",
        },
        "titles": [
            "hr assistant", "hr officer", "hr specialist", "hr manager", "recruiter",
            "talent acquisition", "people operations", "payroll officer",
            "compensation and benefits", "hr generalist", "human resources coordinator",
        ],
        "skills": [
            "recruitment", "talent acquisition", "applicant screening", "candidate sourcing",
            "interviewing", "onboarding", "employee relations", "payroll",
            "compensation and benefits", "hr compliance", "labor law",
            "personnel administration", "performance management", "hris",
        ],
        "education": [
            "human resource management", "psychology", "behavioral science",
            "industrial relations",
        ],
        "certifications": [
            "shrm", "chra",
        ],
    },
    "Production": {
        "display_name": "Production & Manufacturing",
        "departments": {
            "production", "manufacturing", "assembly", "plant operations", "industrial",
        },
        "titles": [
            "production worker", "machine operator", "assembly line worker", "assembler",
            "manufacturing technician", "plant worker", "fabricator",
            "quality control inspector", "qc inspector", "production helper", "factory worker",
        ],
        "skills": [
            "assembly line", "machine operation", "product assembly", "quality inspection",
            "quality control", "manufacturing process", "blueprint reading",
            "equipment operation", "preventive maintenance", "production quota",
            "soldering", "tool handling", "fabrication",
        ],
        "education": [
            "mechanical engineering", "industrial engineering",
        ],
        "certifications": [
            "tesda smaw", "nc ii",
        ],
    },
    "Finance": {
        "display_name": "Finance & Accounting",
        "departments": {
            "finance", "accounting", "auditing", "financial services",
        },
        "titles": [
            "accountant", "accounting assistant", "accounting clerk", "bookkeeper",
            "financial analyst", "auditor", "tax associate", "accounts payable",
            "accounts receivable", "finance manager", "controller",
        ],
        "skills": [
            "bookkeeping", "accounting", "financial reporting", "general ledger",
            "balance sheet", "financial analysis", "bank reconciliation",
            "accounts payable", "accounts receivable", "taxation", "auditing",
            "quickbooks", "sap", "xero", "financial statements", "tax preparation",
        ],
        "education": [
            "accountancy", "accounting", "finance", "financial management", "bsa",
        ],
        "certifications": [
            "cpa", "certified public accountant", "cma",
        ],
    },
}


def get_job_field(job) -> str:
    """
    Classify a Job into its canonical field category (e.g. 'IT', 'Sales', 'Warehouse').
    Matches against department synonyms, then department text, then title keywords.
    Falls back to normalized department string if unmapped.
    """
    if not job:
        return ""

    dept_raw = str(getattr(job, "department", "") or "").strip()
    dept_norm = normalize_text(dept_raw)
    title_norm = normalize_text(getattr(job, "title", "") or "")

    # 1. Match exact department synonym
    for field_key, field_data in FIELD_TAXONOMY.items():
        if dept_norm in field_data["departments"]:
            return field_key

    # 2. Match department substring
    for field_key, field_data in FIELD_TAXONOMY.items():
        if any(d in dept_norm for d in field_data["departments"]):
            return field_key

    # 3. Match job title keywords
    for field_key, field_data in FIELD_TAXONOMY.items():
        if any(_match_phrase_in_text(kw, title_norm) for kw in field_data["titles"]):
            return field_key

    # Fallback to normalized department or 'General'
    return dept_raw if dept_raw else "General"


def identify_strongest_field(analyzed_resume: dict) -> Tuple[Optional[str], Optional[str], dict]:
    """
    Identify the applicant's single strongest professional field from their analyzed resume.

    Weights:
    - Experience Job Titles: 25 pts each (max 75 pts) - primary career trajectory
    - Explicit Skills: 15 pts each (max 90 pts) - demonstrated competencies
    - Relevant Education Degree: 20 pts (max 40 pts) - academic grounding
    - Certifications: 15 pts each (max 45 pts) - licensed credentials
    - Experience Description: 3 pts per keyword (max 15 pts)
    - Summary & Searchable Text: 2 pts per keyword (max 10 pts)

    Returns:
        (strongest_field_key, strongest_field_display, field_scores)
        If no field has a positive score, returns (None, None, field_scores).
    """
    if not analyzed_resume or not isinstance(analyzed_resume, dict):
        return None, None, {}

    skills = analyzed_resume.get("skills", [])
    experiences = analyzed_resume.get("experience", [])
    educations = analyzed_resume.get("education", [])
    certifications = analyzed_resume.get("certifications", [])
    summary = analyzed_resume.get("summary", "")
    searchable_text = analyzed_resume.get("searchable_text", "")

    field_scores = {}

    for field_key, field_data in FIELD_TAXONOMY.items():
        score = 0.0

        # 1. Experience Job Titles (25 pts per title match, up to 75 pts)
        title_points = 0
        desc_points = 0
        for exp in experiences:
            exp_title = exp.get("job_title", "")
            exp_desc = exp.get("description", "")
            if any(_match_phrase_in_text(kw, exp_title) for kw in field_data["titles"]):
                title_points += 25
            for kw in field_data["skills"]:
                if _match_phrase_in_text(kw, exp_desc):
                    desc_points += 3
        score += min(75, title_points)
        score += min(15, desc_points)

        # 2. Skills (15 pts per match, up to 90 pts)
        skill_points = 0
        for s in skills:
            if any(_match_phrase_in_text(kw, s) for kw in field_data["skills"]):
                skill_points += 15
        score += min(90, skill_points)

        # 3. Education (20 pts per match, up to 40 pts)
        edu_points = 0
        for edu in educations:
            deg = edu.get("degree", "")
            if any(_match_phrase_in_text(kw, deg) for kw in field_data["education"]):
                edu_points += 20
        score += min(40, edu_points)

        # 4. Certifications (15 pts per match, up to 45 pts)
        cert_points = 0
        for cert in certifications:
            if any(_match_phrase_in_text(kw, cert) for kw in field_data["certifications"]):
                cert_points += 15
        score += min(45, cert_points)

        # 5. Summary mentions (2 pts each, up to 10 pts)
        summary_points = 0
        for kw in field_data["titles"] + field_data["skills"][:10]:
            if _match_phrase_in_text(kw, summary):
                summary_points += 2
        score += min(10, summary_points)

        # 6. Fallback Searchable Text (1 pt each, up to 6 pts)
        if score > 0:
            extra = sum(1 for kw in field_data["skills"][:10] if _match_phrase_in_text(kw, searchable_text))
            score += min(6, extra)

        field_scores[field_key] = round(score, 1)

    if not field_scores or max(field_scores.values()) <= 0:
        return None, None, field_scores

    # Tie-breaking: pick field with highest score
    sorted_fields = sorted(
        field_scores.items(),
        key=lambda item: item[1],
        reverse=True
    )

    top_field_key, top_score = sorted_fields[0]
    top_display = FIELD_TAXONOMY[top_field_key]["display_name"]

    return top_field_key, top_display, field_scores


def get_applicant_strongest_field(profile) -> Tuple[Optional[str], Optional[str]]:
    """
    Public helper to get (strongest_field_key, strongest_field_display)
    for a given applicant profile.
    """
    if not profile:
        return None, None
    resume_data = get_applicant_resume_data(profile)
    if not resume_data:
        return None, None
    resume_text = getattr(profile, "resume_text", "") or ""
    analyzed = analyze_applicant_resume(resume_data, resume_text)
    field_key, field_display, _ = identify_strongest_field(analyzed)
    return field_key, field_display


# ==============================================================================
# PIPELINE STEP 5: RECOMMEND BEST JOBS
# ==============================================================================

def get_recommended_jobs(profile, min_score=None, limit=None):
    """
    Step 5: Recommend best jobs for the applicant.

    Full Pipeline:
    Applicant Resume -> Analyze Resume -> Identify Strongest Field ->
    Filter Active Jobs by Strongest Field -> Compare & Score -> Rank Jobs -> Recommend Best Jobs

    Category Isolation Rule:
    Identifies the applicant's single strongest professional field (e.g. IT, Sales,
    Warehouse, Operations) from their uploaded resume, and exclusively evaluates
    and recommends jobs from that category only. For example, a tech-focused resume
    gets tech jobs only.
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

    resume_text = getattr(profile, "resume_text", "") or ""
    analyzed = analyze_applicant_resume(resume_data, resume_text)

    # 1. Identify applicant's single strongest field
    strongest_field, strongest_display, _ = identify_strongest_field(analyzed)
    if not strongest_field:
        return []

    # 2. Retrieve active jobs and isolate exclusively to the applicant's strongest field
    all_jobs = Job.objects.filter(
        status="Active"
    ).prefetch_related(
        "requirements_list"
    )

    category_jobs = [
        job for job in all_jobs
        if get_job_field(job) == strongest_field
    ]

    if not category_jobs:
        return []

    recommendations = []

    for job in category_jobs:
        match = calculate_job_match(profile, job)

        # A hard fail is "Not Qualified" by rubric definition — never recommend
        if match["hard_fail"]:
            continue

        matched_skills = match.get("matched_skills", [])
        title_matched = match.get("title_matches", 0) > 0
        matched_quals = match.get("matched_qualifications", [])

        # STRICT FILTER:
        # Must have at least 1 verified matched skill OR direct title/qualification match.
        if not matched_skills and not title_matched and not matched_quals:
            continue

        if match["score"] >= min_score:
            top_skills = matched_skills[:4]
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
                "field": strongest_field,
                "field_display": strongest_display,
            })

    ranked_recommendations = rank_jobs(recommendations)

    if profile_id:
        cache.set(cache_key, ranked_recommendations, timeout=300)

    if limit and limit > 0:
        return ranked_recommendations[:limit]

    return ranked_recommendations