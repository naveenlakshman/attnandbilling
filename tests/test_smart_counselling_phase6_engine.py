from copy import deepcopy

from modules.smart_counselling.recommendation_engine import ENGINE_VERSION, evaluate_course, rank_courses


def prospect(**changes):
    value={"education_status_code":"DEGREE","qualification":"BCOM","stream_code":"COMMERCE","primary_goal":"GET_JOB","interests":["ACCOUNTING","TALLY"],"computer_skill":"BASIC","accounting_skill":"BASIC","excel_skill":"BASIC","english_skill":"AVERAGE","programming_experience":"NONE"}
    value.update(changes); return value


def course(course_id,name,goal="GET_JOB",interest="ACCOUNTING",strength="PRIMARY",starting="BEGINNER",requirements=None,preferred=None,ready=True):
    return {"course":{"id":course_id,"course_name":name,"course_category":"Certificate Course","is_active":1},"profile":{"minimum_education_level":"PUC_2","starting_skill_level":starting,"updated_at":"2026-08-22 10:00:00"},"recommendationReady":ready,"goals":[{"goal_code":goal,"match_strength":strength,"is_primary":1}],"interests":[{"interest_code":interest,"match_strength":strength,"is_primary":1}],"educationSuitability":[{"education_code":x,"suitability_type":"PREFERRED"} for x in (preferred or ["BCOM","COMMERCE"])],"prerequisites":requirements or [{"skill_dimension":x,"minimum_level":"NONE"} for x in ("COMPUTER","ACCOUNTING","EXCEL","ENGLISH","PROGRAMMING")],"skillsTaught":[{"skill_code":interest,"is_primary":1}]}


def test_golden_commerce_accounting_job_seeker():
    courses=[course(1,"DFA",strength="PRIMARY"),course(2,"Tally",strength="STRONG"),course(3,"Advanced Excel",interest="EXCEL_DATA",strength="SUPPORTED")]
    ranked=rank_courses(prospect(),courses)
    assert ENGINE_VERSION=="SMART_COUNSELLING_ENGINE_V1"
    assert [x["course"]["course"]["course_name"] for x in ranked["top"]]==["DFA","Tally"]
    assert ranked["top"][0]["score"] > ranked["top"][1]["score"]


def test_golden_programming_prerequisite_excludes_unqualified_but_beginner_remains():
    advanced_req=[{"skill_dimension":x,"minimum_level":"BASIC" if x=="PROGRAMMING" else "NONE"} for x in ("COMPUTER","ACCOUNTING","EXCEL","ENGLISH","PROGRAMMING")]
    advanced=course(10,"Advanced Python",interest="PROGRAMMING",requirements=advanced_req,starting="INTERMEDIATE")
    beginner=course(11,"Python Foundation",interest="PROGRAMMING",starting="BEGINNER")
    result=rank_courses(prospect(interests=["PROGRAMMING"],programming_experience="NONE"),[advanced,beginner])
    assert [x["course"]["course"]["id"] for x in result["top"]]==[11]
    excluded=next(x for x in result["all"] if x["course"]["course"]["id"]==10)
    assert excluded["eligibilityStatus"]=="INELIGIBLE"


def test_golden_communication_course_beats_accounting():
    communication=course(20,"Spoken English",goal="IMPROVE_COMMUNICATION",interest="SPOKEN_ENGLISH")
    accounting=course(21,"Accounting",goal="LEARN_ACCOUNTING",interest="ACCOUNTING")
    result=rank_courses(prospect(primary_goal="IMPROVE_COMMUNICATION",interests=["SPOKEN_ENGLISH"]),[accounting,communication])
    assert result["top"][0]["course"]["course"]["id"]==20


def test_invariants_determinism_ties_irrelevant_fields_and_many_interests():
    courses=[course(2,"Second"),course(1,"First")]
    base=rank_courses(prospect(),deepcopy(courses)); repeated=rank_courses(prospect(name="Ignored",gender="Ignored"),deepcopy(courses))
    assert [(x["course"]["course"]["id"],x["score"]) for x in base["top"]]==[(x["course"]["course"]["id"],x["score"]) for x in repeated["top"]]
    assert base["top"][0]["course"]["course"]["id"]==1
    many=course(3,"Many"); many["interests"] += [{"interest_code":x,"match_strength":"WEAK","is_primary":0} for x in ("TALLY","GST","BUSINESS")]
    score=evaluate_course(prospect(interests=["ACCOUNTING","TALLY","GST","BUSINESS"]),many)["score"]
    assert 0 <= score <= 100


def test_missing_optional_data_is_neutral_and_no_match_is_explicit():
    item=course(1,"Unrelated",goal="CERTIFICATION",interest="AI_TOOLS",preferred=[])
    item["educationSuitability"]=[]; item["profile"]["starting_skill_level"]=None
    result=rank_courses(prospect(qualification=None,stream_code=None),[item])
    assert result["status"]=="NO_STRONG_MATCH" and result["top"]==[]


def test_disabled_or_not_ready_course_never_ranks_and_hard_education_excludes():
    disabled=course(1,"Disabled",ready=False)
    advanced=course(2,"Postgraduate"); advanced["profile"]["minimum_education_level"]="POSTGRADUATE"
    result=rank_courses(prospect(education_status_code="PUC_2"),[disabled,advanced])
    assert result["top"]==[] and all(x["eligibilityStatus"]=="INELIGIBLE" for x in result["all"])
