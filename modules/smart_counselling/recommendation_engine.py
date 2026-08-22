"""Pure deterministic Smart Counselling recommendation engine V1."""

ENGINE_VERSION = "SMART_COUNSELLING_ENGINE_V1"
WEIGHTS = {"goal": 30, "interests": 30, "education": 15, "skills": 15, "preferences": 10}
GOAL_STRENGTH = {"PRIMARY": 1.0, "STRONG": 0.85, "SUPPORTED": 0.65, "WEAK": 0.35}
MATCH_THRESHOLDS = (
    (90, "EXCELLENT_MATCH"), (80, "STRONG_MATCH"), (70, "GOOD_MATCH"),
    (60, "POSSIBLE_MATCH"), (0, "LOW_MATCH"),
)
DISPLAY_THRESHOLD = 65
BEST_MATCH_THRESHOLD = 80
TOP_LIMIT = 3

EDUCATION_ORDER = {
    "DROPOUT": 0, "OTHER": 0, "SSLC": 1, "PUC_1": 2, "PUC_2": 3,
    "DIPLOMA": 4, "DEGREE": 4, "DEGREE_COMPLETED": 5,
    "POSTGRADUATE": 6, "POSTGRADUATE_COMPLETED": 7,
}
LEVEL_ORDER = {
    "COMPUTER": {"NONE": 0, "BASIC": 1, "INTERMEDIATE": 2, "GOOD": 3},
    "ACCOUNTING": {"NONE": 0, "BASIC": 1, "INTERMEDIATE": 2, "GOOD": 3},
    "EXCEL": {"NONE": 0, "BASIC": 1, "INTERMEDIATE": 2, "GOOD": 3},
    "ENGLISH": {"NONE": 0, "BEGINNER": 0, "AVERAGE": 1, "GOOD": 2, "ADVANCED": 3},
    "PROGRAMMING": {"NONE": 0, "BASIC": 1, "SOME_EXPERIENCE": 2, "COMFORTABLE": 3},
}
ANSWER_BY_DIMENSION = {
    "COMPUTER": "computer_skill", "ACCOUNTING": "accounting_skill", "EXCEL": "excel_skill",
    "ENGLISH": "english_skill", "PROGRAMMING": "programming_experience",
}
STARTING_LEVEL_TARGET = {
    "BEGINNER": (0, 1), "BEGINNER_TO_INTERMEDIATE": (0, 2), "INTERMEDIATE": (2, 2),
    "INTERMEDIATE_TO_ADVANCED": (2, 3), "ADVANCED": (3, 3),
}
LABELS = {
    "GET_JOB": "get a job", "IMPROVE_JOB_SKILLS": "improve your job skills",
    "GET_PROMOTION": "earn a promotion", "LEARN_ACCOUNTING": "learn accounting",
    "LEARN_COMPUTER_SKILLS": "learn computer skills", "START_OR_MANAGE_BUSINESS": "start or manage a business",
    "FREELANCING": "work as a freelancer", "IMPROVE_COMMUNICATION": "improve communication",
    "CERTIFICATION": "earn a certification", "ACADEMIC_SUPPORT": "get academic support",
    "PERSONAL_LEARNING": "learn for personal growth", "ACCOUNTING": "Accounting", "TALLY": "Tally",
    "GST": "GST", "EXCEL_DATA": "Excel and Data", "OFFICE_ADMINISTRATION": "Office Administration",
    "COMPUTERS": "Computers", "PROGRAMMING": "Programming", "AI_TOOLS": "AI Tools",
    "DIGITAL_MARKETING": "Digital Marketing", "COMMUNICATION": "Communication",
    "SPOKEN_ENGLISH": "Spoken English", "BUSINESS": "Business",
}


def _factor(code, strength):
    return {"code": code, "strength": strength, "factor": GOAL_STRENGTH[strength]}


def _eligibility(prospect, course):
    reasons = []
    if not course.get("recommendationReady"):
        reasons.append({"code": "COURSE_NOT_RECOMMENDATION_READY", "message": "Course Intelligence is not approved and ready."})
    minimum = (course.get("profile") or {}).get("minimum_education_level")
    actual = prospect.get("education_status_code")
    if minimum and (actual not in EDUCATION_ORDER or EDUCATION_ORDER.get(actual, -1) < EDUCATION_ORDER[minimum]):
        reasons.append({"code": "MINIMUM_EDUCATION_NOT_MET", "message": f"Requires education level {minimum}."})
    suitability = course.get("educationSuitability") or []
    # Taxonomy domains are known by the prospect fields. Evaluate each configured
    # hard set independently, rather than allowing a stream to satisfy a qualification.
    all_allowed = {x["education_code"] for x in suitability if x["suitability_type"] == "ALLOWED"}
    qual_domain = {x for x in all_allowed if x not in {"COMMERCE", "SCIENCE", "ARTS", "COMPUTER_SCIENCE", "ENGINEERING", "MANAGEMENT"}}
    stream_domain = all_allowed - qual_domain
    if qual_domain and prospect.get("qualification") not in qual_domain:
        reasons.append({"code": "QUALIFICATION_NOT_ALLOWED", "message": "The course has a different qualification requirement."})
    if stream_domain and prospect.get("stream_code") not in stream_domain:
        reasons.append({"code": "STREAM_NOT_ALLOWED", "message": "The course has a different stream requirement."})
    for requirement in course.get("prerequisites") or []:
        dimension = requirement["skill_dimension"]
        required = requirement["minimum_level"]
        answer = prospect.get(ANSWER_BY_DIMENSION[dimension])
        if answer is None and required != "NONE":
            reasons.append({"code": f"{dimension}_PREREQUISITE_NOT_MET", "message": f"Requires {required.lower().replace('_', ' ')} {dimension.lower()} knowledge."})
        elif answer is not None and LEVEL_ORDER[dimension].get(answer, -1) < LEVEL_ORDER[dimension][required]:
            reasons.append({"code": f"{dimension}_PREREQUISITE_NOT_MET", "message": f"Requires {required.lower().replace('_', ' ')} {dimension.lower()} knowledge."})
    return reasons


def _goal(prospect, course):
    goal = prospect.get("primary_goal")
    match = next((x for x in course.get("goals", []) if x["goal_code"] == goal), None)
    if not goal: return None
    if not match:
        return {"factor": 0.0, "matched": [], "unmatched": [{"code": "GOAL_NOT_SUPPORTED", "message": "This course is not directly aligned with the primary career goal."}], "tie": 0.0}
    strength = match["match_strength"]
    return {"factor": GOAL_STRENGTH[strength], "matched": [{"code": "goal_match", "message": f"Aligned with your goal to {LABELS.get(goal, goal.lower())}."}], "unmatched": [], "tie": GOAL_STRENGTH[strength]}


def _interests(prospect, course):
    selected = set(prospect.get("interests") or [])
    if not selected: return None
    matches = sorted((_factor(x["interest_code"], x["match_strength"]) for x in course.get("interests", []) if x["interest_code"] in selected), key=lambda x: (-x["factor"], x["code"]))
    if not matches:
        return {"factor": 0.0, "matched": [], "unmatched": [{"code": "INTEREST_NOT_MATCHED", "message": "Your selected interests are not a primary focus of this course."}], "tie": 0.0}
    factor = matches[0]["factor"] if len(matches) == 1 else matches[0]["factor"] * 0.8 + matches[1]["factor"] * 0.2
    messages = [{"code": "interest_match", "message": f"Matches your interest in {LABELS.get(x['code'], x['code'].replace('_', ' ').title())}."} for x in matches[:2]]
    return {"factor": factor, "matched": messages, "unmatched": [], "tie": matches[0]["factor"]}


def _education(prospect, course):
    preferred = {x["education_code"] for x in course.get("educationSuitability", []) if x["suitability_type"] == "PREFERRED"}
    if not preferred: return None
    actual = {prospect.get("qualification"), prospect.get("stream_code")} - {None}
    matches = preferred & actual
    if matches:
        labels = ", ".join(sorted(x.replace("_", " ").title() for x in matches))
        return {"factor": min(1.0, 0.7 + 0.15 * (len(matches) - 1)), "matched": [{"code": "preferred_background_match", "message": f"Well suited to your {labels} background."}], "unmatched": [], "tie": 0.0}
    return {"factor": 0.5, "matched": [], "unmatched": [{"code": "preferred_background_not_matched", "message": "Your background is eligible, though it is not one of this course's preferred backgrounds."}], "tie": 0.0}


def _skills(prospect, course):
    starting = (course.get("profile") or {}).get("starting_skill_level")
    if not starting: return None
    observed = []
    for dimension, answer_key in ANSWER_BY_DIMENSION.items():
        answer = prospect.get(answer_key)
        if answer is not None: observed.append(LEVEL_ORDER[dimension].get(answer, 0))
    if not observed: return None
    level = sum(observed) / len(observed)
    low, high = STARTING_LEVEL_TARGET[starting]
    distance = low - level if level < low else level - high if level > high else 0
    factor = max(0.4, 1.0 - 0.2 * distance)
    if factor >= 0.8:
        return {"factor": factor, "matched": [{"code": "entry_skill_fit", "message": "Your current skill level suits this course's entry level."}], "unmatched": [], "tie": 0.0}
    return {"factor": factor, "matched": [], "unmatched": [{"code": "entry_level_consideration", "message": "The course entry level may be less closely matched to your current skills."}], "tie": 0.0}


def _label(score):
    return next(label for minimum, label in MATCH_THRESHOLDS if score >= minimum)


def evaluate_course(prospect, course):
    reasons = _eligibility(prospect, course)
    if reasons:
        return {"course": course, "eligibilityStatus": "INELIGIBLE", "ineligibilityReasons": reasons, "rawScore": None, "score": None, "matchLabel": None, "matchedFactors": [], "unmatchedFactors": [], "goalTie": 0.0, "interestTie": 0.0}
    dimensions = {"goal": _goal(prospect, course), "interests": _interests(prospect, course), "education": _education(prospect, course), "skills": _skills(prospect, course)}
    applicable = {key: value for key, value in dimensions.items() if value is not None}
    denominator = sum(WEIGHTS[key] for key in applicable)
    raw = sum(WEIGHTS[key] * value["factor"] for key, value in applicable.items())
    score = round(raw / denominator * 100) if denominator else 0
    return {
        "course": course, "eligibilityStatus": "ELIGIBLE", "ineligibilityReasons": [],
        "rawScore": round(raw, 6), "score": score, "matchLabel": _label(score),
        "matchedFactors": [item for value in applicable.values() for item in value["matched"]],
        "unmatchedFactors": [item for value in applicable.values() for item in value["unmatched"]],
        "goalTie": (applicable.get("goal") or {}).get("tie", 0.0),
        "interestTie": (applicable.get("interests") or {}).get("tie", 0.0),
    }


def rank_courses(prospect, courses):
    evaluated = [evaluate_course(prospect, course) for course in courses]
    eligible = [item for item in evaluated if item["eligibilityStatus"] == "ELIGIBLE"]
    eligible.sort(key=lambda x: (-x["score"], -x["rawScore"], -x["goalTie"], -x["interestTie"], int(x["course"]["course"]["id"])))
    for rank, item in enumerate(eligible, 1): item["rank"] = rank
    top = [x for x in eligible if x["score"] >= DISPLAY_THRESHOLD][:TOP_LIMIT]
    other = [x for x in eligible if x["score"] < DISPLAY_THRESHOLD][:5]
    status = "MATCHES_FOUND" if top else "NO_STRONG_MATCH"
    return {"status": status, "top": top, "other": other, "all": evaluated}
