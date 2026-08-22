"""Central Phase 8 outcome, reason, next-action, and follow-up policy."""

OUTCOME_POLICIES = {
    "READY_FOR_ADMISSION": {"label": "Ready for Admission", "primary": True, "interested": True, "followup": False, "actions": ["PROCEED_TO_ADMISSION"], "reasons": []},
    "DEMO_REQUESTED": {"label": "Demo Requested", "primary": False, "interested": True, "followup": True, "actions": ["SCHEDULE_DEMO", "CALL_BACK"], "reasons": []},
    "FOLLOWUP_REQUIRED": {"label": "Interested — Follow-up Required", "primary": False, "interested": False, "followup": True, "actions": ["CALL_BACK", "SEND_COURSE_INFORMATION", "WAIT_FOR_PROSPECT"], "reasons": []},
    "PARENT_DISCUSSION_REQUIRED": {"label": "Parent Discussion Required", "primary": False, "interested": False, "followup": True, "actions": ["PARENT_DISCUSSION_FOLLOWUP", "CALL_BACK", "SEND_COURSE_INFORMATION"], "reasons": []},
    "FEE_CONCERN": {"label": "Fee Concern", "primary": True, "interested": True, "followup": True, "actions": ["FEE_DISCUSSION", "CALL_BACK", "SEND_COURSE_INFORMATION"], "reasons": ["COURSE_FEE_HIGH", "NEEDS_INSTALLMENT", "PARENT_APPROVAL", "COMPARING_PRICE", "OTHER"]},
    "TIMING_CONCERN": {"label": "Timing Concern", "primary": True, "interested": True, "followup": True, "actions": ["TIMING_DISCUSSION", "CALL_BACK", "WAIT_FOR_PROSPECT"], "reasons": ["BATCH_TIME_NOT_SUITABLE", "START_DATE_NOT_SUITABLE", "WORK_SCHEDULE", "COLLEGE_SCHEDULE", "OTHER"]},
    "COMPARING_OTHER_INSTITUTES": {"label": "Comparing Other Institutes", "primary": False, "interested": False, "followup": True, "actions": ["CALL_BACK", "SEND_COURSE_INFORMATION", "WAIT_FOR_PROSPECT"], "reasons": []},
    "NOT_READY": {"label": "Not Ready Yet", "primary": False, "interested": False, "followup": True, "actions": ["CALL_BACK", "WAIT_FOR_PROSPECT", "SEND_COURSE_INFORMATION"], "reasons": []},
    "NOT_INTERESTED": {"label": "Not Interested", "primary": False, "interested": False, "followup": False, "actions": ["NO_FURTHER_ACTION", "CALL_BACK"], "reasons": ["COURSE_NOT_RELEVANT", "LOCATION", "FEE", "TIMING", "JOINING_ELSEWHERE", "JUST_ENQUIRING", "OTHER"]},
    "NO_SUITABLE_COURSE": {"label": "No Suitable Course", "primary": False, "interested": False, "followup": False, "actions": ["NO_FURTHER_ACTION", "OTHER"], "reasons": []},
}

NEXT_ACTION_LABELS = {
    "PROCEED_TO_ADMISSION": "Proceed to Admission", "SCHEDULE_DEMO": "Schedule Demo",
    "CALL_BACK": "Call Back", "PARENT_DISCUSSION_FOLLOWUP": "Parent Discussion Follow-up",
    "FEE_DISCUSSION": "Fee Discussion", "TIMING_DISCUSSION": "Timing Discussion",
    "SEND_COURSE_INFORMATION": "Send Course Information", "WAIT_FOR_PROSPECT": "Wait for Prospect",
    "NO_FURTHER_ACTION": "No Further Action", "OTHER": "Other",
}

REASON_LABELS = {
    "COURSE_FEE_HIGH": "Course fee is high", "NEEDS_INSTALLMENT": "Needs installment options",
    "PARENT_APPROVAL": "Needs parent approval", "COMPARING_PRICE": "Comparing prices",
    "BATCH_TIME_NOT_SUITABLE": "Batch time is not suitable", "START_DATE_NOT_SUITABLE": "Start date is not suitable",
    "WORK_SCHEDULE": "Work schedule", "COLLEGE_SCHEDULE": "College schedule",
    "COURSE_NOT_RELEVANT": "Course is not relevant", "LOCATION": "Location",
    "FEE": "Fee", "TIMING": "Timing", "JOINING_ELSEWHERE": "Joining elsewhere",
    "JUST_ENQUIRING": "Just enquiring", "OTHER": "Other",
}


def policy_dto():
    return [{"code": code, "label": p["label"], "requiresPrimary": p["primary"],
             "requiresInterestedCourse": p["interested"], "requiresFollowup": p["followup"],
             "nextActions": [{"code": a, "label": NEXT_ACTION_LABELS[a]} for a in p["actions"]],
             "reasons": [{"code": r, "label": REASON_LABELS[r]} for r in p["reasons"]]}
            for code, p in OUTCOME_POLICIES.items()]
