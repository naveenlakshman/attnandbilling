"""
Google Gemini AI helper for lead follow-up suggestions.
"""
from datetime import datetime, timedelta, timezone

import google.generativeai as genai
from flask import current_app

IST = timezone(timedelta(hours=5, minutes=30))


def _get_model():
    api_key = current_app.config.get("GOOGLE_AI_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_AI_API_KEY is not configured.")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("models/gemini-flash-lite-latest")


def _format_date_for_ai(value):
    if not value:
        return "N/A"

    raw = str(value).strip()
    parsed = None

    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        for fmt in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d",
        ):
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue

    if not parsed:
        return raw

    has_time = len(raw) > 10
    if parsed.tzinfo:
        parsed = parsed.astimezone(IST)
    elif has_time:
        parsed = parsed + timedelta(hours=5, minutes=30)

    if has_time:
        return parsed.strftime("%d-%m-%Y %I:%M %p (%A)")
    return parsed.strftime("%d-%m-%Y (%A)")


def _current_date_context(now=None):
    now_ist = now.astimezone(IST) if now and now.tzinfo else (now or datetime.now(IST))
    return [
        "Current Date Context (authoritative):",
        f"Today: {now_ist.strftime('%d-%m-%Y')} ({now_ist.strftime('%A')})",
        f"Current Time: {now_ist.strftime('%I:%M %p')} IST",
        "Timezone: Asia/Kolkata",
        "Important: Do not infer today's day from the last follow-up date.",
        "Avoid weekend/weekday-specific greetings unless they match today's day above.",
    ]


def _build_lead_context(lead, followups=None, now=None):
    """Build a structured text summary of the lead for use in prompts."""
    lines = _current_date_context(now) + [
        "",
        f"Lead Name: {lead.get('name', 'Unknown')}",
        f"Phone: {lead.get('phone', 'N/A')}",
        f"Stage: {lead.get('stage', 'N/A')}",
        f"Lead Score: {lead.get('lead_score', 'N/A')} / 100",
        f"Lead Source: {lead.get('lead_source', 'N/A')}",
        f"Interested Courses: {lead.get('interested_courses', 'N/A')}",
        f"Career Goal: {lead.get('career_goal', 'N/A')}",
        f"Education: {lead.get('education_status', 'N/A')} - {lead.get('stream', '')}".rstrip(" - "),
        f"Start Timeframe: {lead.get('start_timeframe', 'N/A')}",
        f"Decision Maker: {lead.get('decision_maker', 'Self')}",
        f"Total Follow-ups Done: {lead.get('followup_count', 0)}",
        f"Last Contact Date: {_format_date_for_ai(lead.get('last_contact_date'))}",
        f"Next Follow-up Date: {_format_date_for_ai(lead.get('next_followup_date'))}",
    ]

    if lead.get("notes"):
        lines.append(f"Notes: {lead['notes']}")

    context = "\n".join(lines)

    if followups:
        history_lines = []
        for f in followups[:5]:
            parts = []
            if f.get("created_at"):
                parts.append(_format_date_for_ai(f.get("created_at")))
            if f.get("user_full_name"):
                parts.append(f"Counselor: {f['user_full_name']}")
            if f.get("method"):
                parts.append(f"via {f['method']}")
            if f.get("outcome"):
                parts.append(f"Outcome: {f['outcome']}")
            if f.get("next_followup_date"):
                parts.append(f"Next: {_format_date_for_ai(f.get('next_followup_date'))}")
            if f.get("note"):
                parts.append(f"Note: {f['note']}")
            history_lines.append(" | ".join(parts))

        if history_lines:
            context += "\n\nFollow-up History (most recent first):\n" + "\n".join(history_lines)

    return context


def generate_followup_script(lead, followups=None):
    """
    Generate a personalized phone call script for a counselor to use
    when calling this lead for a follow-up.
    Returns the script text string, or raises on error.
    """
    context = _build_lead_context(lead, followups)
    prompt = f"""You are an expert education counselor assistant in India.
A counselor is about to call a prospective student for a follow-up.
Generate a natural, friendly, and persuasive phone call opening script in English.

Rules:
- Use the Current Date Context as the source of truth.
- Never say "weekend", "Monday", "morning", etc. unless it matches the current date/time.
- Respect the latest follow-up outcome and note.
- Start with a warm greeting and remind them of the previous conversation.
- Reference their specific interest, course, or career goal.
- Have a clear purpose for calling.
- End with a soft call-to-action such as inviting them to visit or asking if they have questions.
- Keep it suitable for a 1-2 minute call opener.
- Sound natural, not robotic.

Lead Details:
{context}

Generate only the script text. Do not include any introductory explanation."""

    model = _get_model()
    response = model.generate_content(prompt)
    return response.text


def suggest_next_action(lead, followups=None):
    """
    Suggest the single best next action the counselor should take for this lead.
    Returns the suggestion text string, or raises on error.
    """
    context = _build_lead_context(lead, followups)
    prompt = f"""You are an expert CRM advisor for an education institute in India.
Based on the lead profile, today's date, and follow-up history below, recommend the single most effective
next action the counselor should take to move this lead forward toward enrollment.

Your response should:
- Use the Current Date Context as the source of truth.
- Start with a one-line action recommendation.
- Give 2-3 bullet points explaining why this is the right action.
- Mention the best timing, such as "send WhatsApp now" or "call tomorrow morning".
- Be specific and practical.
- Be concise, under 150 words.

Lead Details:
{context}

Provide only the recommendation. No preamble."""

    model = _get_model()
    response = model.generate_content(prompt)
    return response.text


def draft_message_template(lead, followups=None, method="WhatsApp"):
    """
    Draft a personalized outreach message for the given method (WhatsApp or Email).
    Returns the message text string, or raises on error.
    """
    context = _build_lead_context(lead, followups)

    if method == "Email":
        prompt = f"""You are an education counselor assistant in India.
Write a short, warm, and personalized follow-up email to a prospective student.

Rules:
- Use the Current Date Context as the source of truth.
- Avoid incorrect day-specific greetings like "hope you had a good weekend" unless the current day makes it true and useful.
- Respect the latest follow-up outcome and note; if they did not respond, gently acknowledge that without blaming them.
- Have a subject line prefixed with "Subject: ".
- Be friendly and professional.
- Reference their course interest or career goal.
- Include a clear call-to-action to visit, call, or reply.
- Keep the body under 120 words.
- Close with a warm sign-off from "The Admissions Team".

Lead Details:
{context}

Write only the email, subject line plus body. No explanation."""
    else:
        prompt = f"""You are an education counselor assistant in India.
Write a short, friendly, and personalized WhatsApp follow-up message to a prospective student.

Rules:
- Use the Current Date Context as the source of truth.
- Avoid incorrect day-specific greetings like "hope you're having a good weekend"; only mention weekend if today is Saturday or Sunday.
- Prefer evergreen greetings such as "Hi {lead.get('name', 'there')}," unless day-specific wording is definitely correct.
- Be conversational and warm, suitable for WhatsApp.
- Reference their specific course interest or career goal.
- Respect the latest follow-up outcome and note; if they did not respond, keep it polite and non-pushy.
- Include a clear soft call-to-action.
- Keep it to 2-4 short sentences.
- Use at most 1 emoji.
- Sound personal, not like a broadcast message.

Lead Details:
{context}

Write only the WhatsApp message text. No explanation."""

    model = _get_model()
    response = model.generate_content(prompt)
    return response.text
