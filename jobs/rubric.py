"""
Single source of truth for the resume-screening rubric.

Both ai.py (Gemini-based analyze_resume) and recommendation.py
(heuristic-based job recommendations) import from here instead of
hardcoding thresholds, so a future rubric change — or a bug fix — only
has to happen in one place.
"""

# ---- Per-criterion score bounds (rubric scale is 50-100) ----
CRITERION_SCORE_MIN = 50
CRITERION_SCORE_MAX = 100

# ---- Step 1: Knockout Layer (Safety Check) ----
# Per the rubric PDF: if the Qualifications score falls below this
# threshold, the applicant is a hard fail — full stop, regardless of the
# other three scores. This applies to EVERY job, not only ones where a
# mandatory license/credential was detected in the JD. If that's ever
# meant to be conditional, change it here and both pipelines follow.
QUALIFICATION_KNOCKOUT_THRESHOLD = 60

# ---- Step 2: Weighting ----
WEIGHT_MIN = 10
WEIGHT_MAX = 40
WEIGHT_TOTAL = 100
DEFAULT_WEIGHT = WEIGHT_TOTAL // 4  # 25 — used when a weight is missing

# ---- Final recommendation bands (Step 2 decision matrix) ----
QUALIFIED_THRESHOLD = 85.0
POTENTIALLY_QUALIFIED_THRESHOLD = 70.0

# ---- match_level bands (mirrors the rubric's per-criterion table) ----
EXCEPTIONAL_THRESHOLD = 90
PROFICIENT_THRESHOLD = 75
DEVELOPING_THRESHOLD = 60


def clamp(value, low, high):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = low
    return max(low, min(value, high))


def match_level(score):
    """Rubric per-criterion band label for a 50-100 score."""
    if score >= EXCEPTIONAL_THRESHOLD:
        return "Exceptional"
    if score >= PROFICIENT_THRESHOLD:
        return "Proficient"
    if score >= DEVELOPING_THRESHOLD:
        return "Developing"
    return "Unsatisfactory"


def recommendation_from_score(score):
    """Step 2 decision-matrix label for a final weighted score."""
    if score >= QUALIFIED_THRESHOLD:
        return "Qualified"
    if score >= POTENTIALLY_QUALIFIED_THRESHOLD:
        return "Potentially Qualified"
    return "Not Qualified"


def apply_knockout(qualification_match):
    """
    Step 1 of the rubric: universal safety check, independent of whether
    the job has a detected mandatory license requirement. Returns True
    if the candidate should hard-fail before any averaging happens.
    """
    return qualification_match < QUALIFICATION_KNOCKOUT_THRESHOLD


def normalize_weights(qualification, experience, skills, education):
    """
    Clamp each weight to [WEIGHT_MIN, WEIGHT_MAX], then proportionally
    scale so the four weights sum to exactly WEIGHT_TOTAL while staying
    as close to the clamped values as possible.
    """
    raw = {
        "qualification_weight": clamp(qualification, WEIGHT_MIN, WEIGHT_MAX),
        "experience_weight": clamp(experience, WEIGHT_MIN, WEIGHT_MAX),
        "skills_weight": clamp(skills, WEIGHT_MIN, WEIGHT_MAX),
        "education_weight": clamp(education, WEIGHT_MIN, WEIGHT_MAX),
    }

    total = sum(raw.values())
    if total == WEIGHT_TOTAL:
        return raw

    scaled = {k: v * WEIGHT_TOTAL / total for k, v in raw.items()}
    scaled = {k: clamp(round(v), WEIGHT_MIN, WEIGHT_MAX) for k, v in scaled.items()}

    # Fix any rounding drift by nudging the largest weight.
    drift = WEIGHT_TOTAL - sum(scaled.values())
    if drift != 0:
        biggest_key = max(scaled, key=scaled.get)
        scaled[biggest_key] = clamp(scaled[biggest_key] + drift, WEIGHT_MIN, WEIGHT_MAX)

    return scaled


def weighted_final_score(qualification_match, experience_match, skills_match,
                            education_match, weights):
    """Step 2: the weighted average using this job's criteria_weights."""
    return (
        qualification_match * (weights["qualification_weight"] / 100.0)
        + experience_match * (weights["experience_weight"] / 100.0)
        + skills_match * (weights["skills_weight"] / 100.0)
        + education_match * (weights["education_weight"] / 100.0)
    )