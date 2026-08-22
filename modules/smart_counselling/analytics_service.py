"""Central SQL-backed Phase 9 management analytics definitions."""

from datetime import date, datetime, timedelta

from db import get_conn

from .errors import SmartCounsellingError, validation_error


def _date(value, field):
    try: return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except (TypeError, ValueError): raise validation_error("Choose a valid analytics date.", {field: "Use YYYY-MM-DD."})


def _filters(conn, actor, args):
    today=date.today(); default_from=(today-timedelta(days=6)).isoformat(); start=_date(args.get("date_from") or default_from,"dateFrom"); end=_date(args.get("date_to") or today.isoformat(),"dateTo")
    if start>end: raise validation_error("Start date must be on or before end date.",{"dateFrom":"Invalid range."})
    branch_id=int(args.get("branch_id")) if str(args.get("branch_id") or "").isdigit() else None
    counsellor_id=int(args.get("counsellor_id")) if str(args.get("counsellor_id") or "").isdigit() else None
    if not actor.can_view_all_branches:
        if branch_id and branch_id!=actor.branch_id: raise SmartCounsellingError("branch_forbidden","You cannot report on another branch.",403)
        branch_id=actor.branch_id
    if actor.role=="staff":
        if counsellor_id and counsellor_id!=actor.id: raise SmartCounsellingError("forbidden","You cannot report on another counsellor.",403)
        counsellor_id=actor.id
    if branch_id and not conn.execute("SELECT id FROM branches WHERE id=? AND institute_id=? AND is_active=1",(branch_id,actor.institute_id)).fetchone(): raise SmartCounsellingError("branch_forbidden","The selected branch is unavailable.",403)
    if counsellor_id:
        user=conn.execute("SELECT id,branch_id FROM users WHERE id=? AND institute_id=? AND is_active=1",(counsellor_id,actor.institute_id)).fetchone()
        if not user or (branch_id and user["branch_id"] and int(user["branch_id"])!=branch_id): raise SmartCounsellingError("forbidden","The selected counsellor is unavailable.",403)
    recommended=int(args.get("recommended_course_id")) if str(args.get("recommended_course_id") or "").isdigit() else None
    primary=int(args.get("primary_course_id")) if str(args.get("primary_course_id") or "").isdigit() else None
    for value in (recommended,primary):
        if value and not conn.execute("SELECT id FROM courses WHERE id=? AND institute_id=?",(value,actor.institute_id)).fetchone(): raise SmartCounsellingError("not_found","The selected course was not found.",404)
    return {"dateFrom":start,"dateTo":end,"branchId":branch_id,"counsellorId":counsellor_id,"recommendedCourseId":recommended,"primaryCourseId":primary}


def _scope(actor,f,alias="cs"):
    c=[f"{alias}.institute_id=?",f"substr({alias}.started_at,1,10)>=?",f"substr({alias}.started_at,1,10)<=?"];p=[actor.institute_id,f["dateFrom"],f["dateTo"]]
    if f["branchId"]: c.append(f"{alias}.branch_id=?");p.append(f["branchId"])
    if f["counsellorId"]: c.append(f"{alias}.counsellor_user_id=?");p.append(f["counsellorId"])
    if f["recommendedCourseId"]: c.append(f"EXISTS(SELECT 1 FROM recommendation_runs fr JOIN recommendation_results fx ON fx.recommendation_run_id=fr.id AND fx.institute_id=fr.institute_id WHERE fr.institute_id={alias}.institute_id AND fr.counselling_session_id={alias}.id AND fr.status='COMPLETED' AND fx.course_id=?)");p.append(f["recommendedCourseId"])
    if f["primaryCourseId"]: c.append(f"EXISTS(SELECT 1 FROM counselling_course_interests fi WHERE fi.institute_id={alias}.institute_id AND fi.counselling_session_id={alias}.id AND fi.course_id=? AND fi.is_primary=1)");p.append(f["primaryCourseId"])
    return " AND ".join(c),p


def _count(conn,sql,params): return int(conn.execute(sql,tuple(params)).fetchone()["n"] or 0)


def get_analytics(actor,args):
    conn=get_conn()
    try:
        f=_filters(conn,actor,args); where,params=_scope(actor,f)
        row=conn.execute(f"""SELECT COUNT(*) sessions,COUNT(DISTINCT cs.lead_id) prospects,
          SUM(CASE WHEN cs.status='COMPLETED' THEN 1 ELSE 0 END) completed,SUM(CASE WHEN cs.status IN ('STARTED','IDENTIFICATION_PENDING','IDENTIFIED','IN_PROGRESS','OUTCOME_PENDING') THEN 1 ELSE 0 END) open_sessions,
          SUM(CASE WHEN cs.status='ABANDONED' THEN 1 ELSE 0 END) abandoned,SUM(CASE WHEN cs.outcome='READY_FOR_ADMISSION' THEN 1 ELSE 0 END) ready,
          SUM(CASE WHEN cs.outcome IN ('FOLLOWUP_REQUIRED','PARENT_DISCUSSION_REQUIRED','FEE_CONCERN','TIMING_CONCERN','COMPARING_OTHER_INSTITUTES','NOT_READY','DEMO_REQUESTED') THEN 1 ELSE 0 END) followups_required,
          SUM(CASE WHEN cs.outcome='PARENT_DISCUSSION_REQUIRED' THEN 1 ELSE 0 END) parent_discussions,SUM(CASE WHEN cs.outcome='DEMO_REQUESTED' THEN 1 ELSE 0 END) demos,SUM(CASE WHEN cs.outcome='NO_SUITABLE_COURSE' THEN 1 ELSE 0 END) no_suitable
          FROM counselling_sessions cs WHERE {where}""",tuple(params)).fetchone()
        overview={"sessions":int(row["sessions"] or 0),"uniqueProspects":int(row["prospects"] or 0),"completed":int(row["completed"] or 0),"open":int(row["open_sessions"] or 0),"abandoned":int(row["abandoned"] or 0),"readyForAdmission":int(row["ready"] or 0),"followupsRequired":int(row["followups_required"] or 0),"parentDiscussions":int(row["parent_discussions"] or 0),"demoRequests":int(row["demos"] or 0),"noSuitableCourse":int(row["no_suitable"] or 0)}
        converted_leads=_count(conn,f"""SELECT COUNT(DISTINCT cs.lead_id) n FROM counselling_sessions cs JOIN students st ON st.lead_id=cs.lead_id AND st.institute_id=cs.institute_id WHERE {where}""",params)
        converted_sessions=_count(conn,f"""SELECT COUNT(*) n FROM counselling_sessions cs WHERE {where} AND cs.status='COMPLETED' AND EXISTS(SELECT 1 FROM students st WHERE st.institute_id=cs.institute_id AND st.lead_id=cs.lead_id)""",params)
        overview.update({"convertedLeads":converted_leads,"sessionConversionRate":round(converted_sessions*100/overview["completed"],1) if overview["completed"] else 0,"leadConversionRate":round(converted_leads*100/overview["uniqueProspects"],1) if overview["uniqueProspects"] else 0})
        funnel_defs=[("STARTED","Sessions created",f"SELECT COUNT(*) n FROM counselling_sessions cs WHERE {where}",params,"sessions"),("IDENTIFIED","Lead linked",f"SELECT COUNT(*) n FROM counselling_sessions cs WHERE {where} AND cs.lead_id IS NOT NULL",params,"sessions"),("PROFILE_COMPLETED","Assessment record exists",f"SELECT COUNT(*) n FROM counselling_sessions cs WHERE {where} AND EXISTS(SELECT 1 FROM counselling_assessments a WHERE a.institute_id=cs.institute_id AND a.counselling_session_id=cs.id)",params,"sessions"),("ASSESSMENT_COMPLETED","Completed assessment exists",f"SELECT COUNT(*) n FROM counselling_sessions cs WHERE {where} AND EXISTS(SELECT 1 FROM counselling_assessments a WHERE a.institute_id=cs.institute_id AND a.counselling_session_id=cs.id AND a.status='COMPLETED')",params,"sessions"),("RECOMMENDATION_GENERATED","Completed recommendation run exists",f"SELECT COUNT(*) n FROM counselling_sessions cs WHERE {where} AND EXISTS(SELECT 1 FROM recommendation_runs r WHERE r.institute_id=cs.institute_id AND r.counselling_session_id=cs.id AND r.status='COMPLETED')",params,"sessions"),("COURSE_INTEREST_RECORDED","Any structured interest exists",f"SELECT COUNT(*) n FROM counselling_sessions cs WHERE {where} AND EXISTS(SELECT 1 FROM counselling_course_interests i WHERE i.institute_id=cs.institute_id AND i.counselling_session_id=cs.id)",params,"sessions"),("COMPLETED","Session status completed",f"SELECT COUNT(*) n FROM counselling_sessions cs WHERE {where} AND cs.status='COMPLETED'",params,"sessions"),("READY_FOR_ADMISSION","Completed ready outcome",f"SELECT COUNT(*) n FROM counselling_sessions cs WHERE {where} AND cs.status='COMPLETED' AND cs.outcome='READY_FOR_ADMISSION'",params,"sessions"),("CONVERTED","Unique counselled leads linked to students",f"SELECT COUNT(DISTINCT cs.lead_id) n FROM counselling_sessions cs JOIN students st ON st.institute_id=cs.institute_id AND st.lead_id=cs.lead_id WHERE {where}",params,"leads")]
        funnel=[{"code":code,"label":label,"count":_count(conn,sql,p),"unit":unit} for code,label,sql,p,unit in funnel_defs]
        outcomes=[{"code":x["outcome"] or "PENDING","count":int(x["n"])} for x in conn.execute(f"SELECT cs.outcome,COUNT(*) n FROM counselling_sessions cs WHERE {where} AND cs.status='COMPLETED' GROUP BY cs.outcome ORDER BY n DESC",tuple(params)).fetchall()]
        final_run="r.id=(SELECT MAX(r2.id) FROM recommendation_runs r2 WHERE r2.institute_id=cs.institute_id AND r2.counselling_session_id=cs.id AND r2.status='COMPLETED')"
        recommended=[{"courseId":int(x["course_id"]),"courseName":x["course_name"] or f"Course #{x['course_id']}","count":int(x["n"])} for x in conn.execute(f"""SELECT rr.course_id,c.course_name,COUNT(*) n FROM counselling_sessions cs JOIN recommendation_runs r ON r.institute_id=cs.institute_id AND r.counselling_session_id=cs.id AND {final_run} JOIN recommendation_results rr ON rr.institute_id=r.institute_id AND rr.recommendation_run_id=r.id LEFT JOIN courses c ON c.id=rr.course_id AND c.institute_id=rr.institute_id WHERE {where} AND rr.result_rank<=3 GROUP BY rr.course_id,c.course_name ORDER BY n DESC LIMIT 10""",tuple(params)).fetchall()]
        primary=[{"courseId":int(x["course_id"]),"courseName":x["course_name"] or f"Course #{x['course_id']}","count":int(x["n"])} for x in conn.execute(f"""SELECT i.course_id,c.course_name,COUNT(*) n FROM counselling_sessions cs JOIN counselling_course_interests i ON i.institute_id=cs.institute_id AND i.counselling_session_id=cs.id AND i.is_primary=1 LEFT JOIN courses c ON c.id=i.course_id AND c.institute_id=i.institute_id WHERE {where} GROUP BY i.course_id,c.course_name ORDER BY n DESC LIMIT 10""",tuple(params)).fetchall()]
        align=conn.execute(f"""SELECT SUM(CASE WHEN p.course_id=t.course_id THEN 1 ELSE 0 END) matches,SUM(CASE WHEN p.course_id IS NOT NULL AND p.course_id<>t.course_id THEN 1 ELSE 0 END) different,SUM(CASE WHEN p.course_id IS NULL THEN 1 ELSE 0 END) no_primary FROM counselling_sessions cs LEFT JOIN counselling_course_interests p ON p.institute_id=cs.institute_id AND p.counselling_session_id=cs.id AND p.is_primary=1 LEFT JOIN recommendation_results t ON t.institute_id=cs.institute_id AND t.recommendation_run_id=(SELECT MAX(rx.id) FROM recommendation_runs rx WHERE rx.institute_id=cs.institute_id AND rx.counselling_session_id=cs.id AND rx.status='COMPLETED') AND t.result_rank=1 WHERE {where}""",tuple(params)).fetchone()
        counsellors=[{"id":int(x["id"]),"name":x["name"],"sessions":int(x["sessions"]),"completed":int(x["completed"] or 0),"completionRate":round(int(x["completed"] or 0)*100/int(x["sessions"]),1) if x["sessions"] else 0,"readyForAdmission":int(x["ready"] or 0),"followupsCreated":int(x["followups"] or 0)} for x in conn.execute(f"""SELECT u.id,u.full_name name,COUNT(*) sessions,SUM(CASE WHEN cs.status='COMPLETED' THEN 1 ELSE 0 END) completed,SUM(CASE WHEN cs.outcome='READY_FOR_ADMISSION' THEN 1 ELSE 0 END) ready,SUM(CASE WHEN cs.completion_followup_id IS NOT NULL THEN 1 ELSE 0 END) followups FROM counselling_sessions cs JOIN users u ON u.id=cs.counsellor_user_id AND u.institute_id=cs.institute_id WHERE {where} GROUP BY u.id,u.full_name ORDER BY sessions DESC""",tuple(params)).fetchall()]
        no_suitable_reasons=[]
        for x in conn.execute(f"""SELECT a.question_key,a.answer_value,COUNT(*) n FROM counselling_sessions cs JOIN counselling_assessments ca ON ca.institute_id=cs.institute_id AND ca.counselling_session_id=cs.id JOIN counselling_assessment_answers a ON a.assessment_id=ca.id AND a.question_key IN ('qualification','primary_goal','interests') WHERE {where} AND cs.outcome='NO_SUITABLE_COURSE' GROUP BY a.question_key,a.answer_value ORDER BY n DESC""",tuple(params)).fetchall(): no_suitable_reasons.append({"dimension":x["question_key"],"value":str(x["answer_value"] or "").strip('"'),"count":int(x["n"])})
        followup=conn.execute(f"""SELECT COUNT(*) total,SUM(CASE WHEN f.next_followup_date=substr(CURRENT_TIMESTAMP,1,10) THEN 1 ELSE 0 END) due_today,SUM(CASE WHEN f.next_followup_date<substr(CURRENT_TIMESTAMP,1,10) THEN 1 ELSE 0 END) overdue,SUM(CASE WHEN f.next_followup_date>substr(CURRENT_TIMESTAMP,1,10) THEN 1 ELSE 0 END) upcoming FROM counselling_sessions cs JOIN followups f ON f.id=cs.completion_followup_id AND f.institute_id=cs.institute_id WHERE {where}""",tuple(params)).fetchone()
        branches=[{"id":int(x["id"]),"name":x["branch_name"]} for x in conn.execute("SELECT id,branch_name FROM branches WHERE institute_id=? AND is_active=1 ORDER BY branch_name",(actor.institute_id,)).fetchall() if actor.can_view_all_branches or int(x["id"])==int(actor.branch_id or 0)]
        counsellor_options=[{"id":int(x["id"]),"name":x["full_name"],"branchId":x["branch_id"]} for x in conn.execute("SELECT id,full_name,branch_id FROM users WHERE institute_id=? AND is_active=1 AND role IN ('staff','admin') ORDER BY full_name",(actor.institute_id,)).fetchall() if actor.role!="staff" or int(x["id"])==actor.id]
        courses=[{"id":int(x["id"]),"name":x["course_name"]} for x in conn.execute("SELECT id,course_name FROM courses WHERE institute_id=? ORDER BY course_name",(actor.institute_id,)).fetchall()]
        return {"asOf":date.today().isoformat(),"filters":f,"filterOptions":{"branches":branches,"counsellors":counsellor_options,"courses":courses},"overview":overview,"funnel":funnel,"outcomes":outcomes,"courses":{"recommended":recommended,"primarySelected":primary,"alignment":{"matchedTop":int(align["matches"] or 0),"differentChoice":int(align["different"] or 0),"noPrimaryChoice":int(align["no_primary"] or 0)}},"noSuitableCourse":{"count":overview["noSuitableCourse"],"dimensions":no_suitable_reasons},"counsellors":counsellors,"followups":{"total":int(followup["total"] or 0),"dueToday":int(followup["due_today"] or 0),"overdue":int(followup["overdue"] or 0),"upcoming":int(followup["upcoming"] or 0)},"definitions":{"sessionConversion":"Completed sessions whose lead is now linked to a student / completed sessions.","leadConversion":"Unique counselled leads linked to a student / unique counselled leads.","counsellorAttribution":"Process metrics only; admissions are not attributed to one counsellor when multiple staff counselled a lead."}}
    finally: conn.close()
