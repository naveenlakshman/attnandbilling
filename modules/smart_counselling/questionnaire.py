ASSESSMENT_VERSION = "SMART_COUNSELLING_V1"

# Shared stable identifiers. Course Intelligence imports these definitions so
# Phase 4 and Phase 5 cannot silently diverge into incompatible taxonomies.


def options(*pairs):
    return [{"code": code, "label": label} for code, label in pairs]


EDUCATION_STATUSES = options(
    ("SSLC", "SSLC"), ("PUC_1", "PUC 1st Year"), ("PUC_2", "PUC 2nd Year"),
    ("DIPLOMA", "Diploma"), ("DEGREE", "Degree Student"),
    ("DEGREE_COMPLETED", "Degree Completed"), ("POSTGRADUATE", "Postgraduate Student"),
    ("POSTGRADUATE_COMPLETED", "Postgraduate Completed"), ("DROPOUT", "Dropout"),
    ("OTHER", "Other"),
)
QUALIFICATIONS = options(
    ("SSLC", "SSLC"), ("PUC_COMMERCE", "PUC Commerce"), ("PUC_SCIENCE", "PUC Science"),
    ("PUC_ARTS", "PUC Arts"), ("BCOM", "B.Com"), ("BBA", "BBA"), ("BCA", "BCA"),
    ("BSC", "B.Sc"), ("BA", "BA"), ("BE_BTECH", "BE/B.Tech"),
    ("DIPLOMA", "Diploma"), ("MCOM", "M.Com"), ("MBA", "MBA"), ("OTHER", "Other"),
)
STREAMS = options(
    ("COMMERCE", "Commerce"), ("SCIENCE", "Science"), ("ARTS", "Arts"),
    ("COMPUTER_SCIENCE", "Computer Science"), ("ENGINEERING", "Engineering"),
    ("MANAGEMENT", "Management"), ("OTHER", "Other"),
)
CURRENT_SITUATIONS = options(
    ("STUDENT", "Student"), ("JOB_SEEKER", "Job Seeker"),
    ("WORKING_PROFESSIONAL", "Working Professional"), ("BUSINESS_OWNER", "Business Owner"),
    ("FREELANCER", "Freelancer"), ("CAREER_BREAK", "Career Break"), ("OTHER", "Other"),
)
CAREER_GOALS = options(
    ("GET_JOB", "Get a Job"), ("IMPROVE_JOB_SKILLS", "Improve Job Skills"),
    ("GET_PROMOTION", "Get a Promotion"), ("LEARN_ACCOUNTING", "Learn Accounting"),
    ("LEARN_COMPUTER_SKILLS", "Learn Computer Skills"),
    ("START_OR_MANAGE_BUSINESS", "Start or Manage a Business"),
    ("FREELANCING", "Freelancing"), ("IMPROVE_COMMUNICATION", "Improve Communication"),
    ("CERTIFICATION", "Earn a Certification"), ("ACADEMIC_SUPPORT", "Academic Support"),
    ("PERSONAL_LEARNING", "Personal Learning"), ("OTHER", "Other"),
)
INTERESTS = options(
    ("ACCOUNTING", "Accounting"), ("TALLY", "Tally"), ("GST", "GST"),
    ("EXCEL_DATA", "Excel & Data"), ("OFFICE_ADMINISTRATION", "Office Administration"),
    ("COMPUTERS", "Computers"), ("PROGRAMMING", "Programming"), ("AI_TOOLS", "AI Tools"),
    ("DIGITAL_MARKETING", "Digital Marketing"), ("COMMUNICATION", "Communication"),
    ("SPOKEN_ENGLISH", "Spoken English"), ("BUSINESS", "Business"), ("OTHER", "Other"),
)
KNOWLEDGE_LEVELS = options(
    ("NONE", "None"), ("BASIC", "Basic"), ("INTERMEDIATE", "Intermediate"), ("GOOD", "Good"),
)
ENGLISH_LEVELS = options(
    ("BEGINNER", "Beginner"), ("AVERAGE", "Average"), ("GOOD", "Good"), ("ADVANCED", "Advanced"),
)
PROGRAMMING_LEVELS = options(
    ("NONE", "None"), ("BASIC", "Basic"), ("SOME_EXPERIENCE", "Some Experience"),
    ("COMFORTABLE", "Comfortable"),
)
START_TIMEFRAMES = options(
    ("IMMEDIATELY", "Immediately"), ("WITHIN_1_MONTH", "Within 1 Month"),
    ("ONE_TO_THREE_MONTHS", "1–3 Months"), ("LATER", "Later"),
    ("JUST_EXPLORING", "Just Exploring"),
)
PREFERRED_DURATIONS = options(
    ("SHORT", "Up to 3 Months"), ("MEDIUM", "3–6 Months"), ("LONG", "6+ Months"),
)
PREFERRED_TIMINGS = options(
    ("MORNING", "Morning"), ("AFTERNOON", "Afternoon"), ("EVENING", "Evening"),
    ("WEEKEND", "Weekend"), ("FLEXIBLE", "Flexible"),
)
LEARNING_MODES = options(("OFFLINE", "In Person"), ("ONLINE", "Online"), ("HYBRID", "Hybrid"))
LANGUAGES = options(("ENGLISH", "English"), ("KANNADA", "Kannada"), ("HINDI", "Hindi"), ("OTHER", "Other"))

PROFILE_ENUMS = {
    "educationStatus": EDUCATION_STATUSES,
    "qualification": QUALIFICATIONS,
    "stream": STREAMS,
    "currentSituation": CURRENT_SITUATIONS,
    "gender": options(("MALE", "Male"), ("FEMALE", "Female"), ("OTHER", "Other"), ("PREFER_NOT_TO_SAY", "Prefer not to say")),
}

ANSWER_OPTIONS = {
    "current_situation": CURRENT_SITUATIONS,
    "primary_goal": CAREER_GOALS,
    "interests": INTERESTS,
    "computer_skill": KNOWLEDGE_LEVELS,
    "accounting_skill": KNOWLEDGE_LEVELS,
    "excel_skill": KNOWLEDGE_LEVELS,
    "english_skill": ENGLISH_LEVELS,
    "programming_experience": PROGRAMMING_LEVELS,
    "start_timeframe": START_TIMEFRAMES,
    "preferred_duration": PREFERRED_DURATIONS,
    "preferred_timing": PREFERRED_TIMINGS,
    "preferred_learning_mode": LEARNING_MODES,
    "preferred_language": LANGUAGES,
}


def codes(option_list):
    return {item["code"] for item in option_list}


QUESTIONNAIRE_DTO = {
    "assessmentVersion": ASSESSMENT_VERSION,
    "profile": PROFILE_ENUMS,
    "careerGoals": CAREER_GOALS,
    "interests": INTERESTS,
    "skills": {
        "knowledge": KNOWLEDGE_LEVELS,
        "english": ENGLISH_LEVELS,
        "programming": PROGRAMMING_LEVELS,
    },
    "startTimeframes": START_TIMEFRAMES,
    "preferences": {
        "durations": PREFERRED_DURATIONS,
        "timings": PREFERRED_TIMINGS,
        "learningModes": LEARNING_MODES,
        "languages": LANGUAGES,
    },
    "conditional": {
        "programmingExperienceWhenInterest": "PROGRAMMING",
        "currentYearForEducation": ["PUC_1", "PUC_2", "DIPLOMA", "DEGREE", "POSTGRADUATE"],
        "streamForEducation": ["PUC_1", "PUC_2", "DIPLOMA", "DEGREE", "DEGREE_COMPLETED", "POSTGRADUATE", "POSTGRADUATE_COMPLETED"],
    },
}


EDUCATION_TO_CRM = {
    "SSLC": "School Student", "PUC_1": "PUC Student", "PUC_2": "PUC Student",
    "DIPLOMA": "Degree Student", "DEGREE": "Degree Student", "DEGREE_COMPLETED": "Graduate",
    "POSTGRADUATE": "Degree Student", "POSTGRADUATE_COMPLETED": "Graduate",
    "DROPOUT": "Other", "OTHER": "Other",
}
STREAM_TO_CRM = {item["code"]: item["label"] for item in STREAMS}
GOAL_TO_CRM = {
    "GET_JOB": "Job", "IMPROVE_JOB_SKILLS": "Skill Development", "GET_PROMOTION": "Skill Development",
    "LEARN_ACCOUNTING": "Skill Development", "LEARN_COMPUTER_SKILLS": "Skill Development",
    "START_OR_MANAGE_BUSINESS": "Business", "FREELANCING": "Career Switch",
    "IMPROVE_COMMUNICATION": "Skill Development", "CERTIFICATION": "Skill Development",
    "ACADEMIC_SUPPORT": "Skill Development", "PERSONAL_LEARNING": "Skill Development", "OTHER": "Other",
}
TIMEFRAME_TO_CRM = {
    "IMMEDIATELY": "Immediately", "WITHIN_1_MONTH": "Within 1 Month",
    "ONE_TO_THREE_MONTHS": "Exploring", "LATER": "Exploring", "JUST_EXPLORING": "Exploring",
}
