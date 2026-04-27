"""
Google Gemini AI helper for lead follow-up suggestions.
"""
import google.generativeai as genai
from flask import current_app


def _get_model():
    api_key = current_app.config.get("GOOGLE_AI_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_AI_API_KEY is not configured.")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("models/gemini-flash-lite-latest")


def _build_lead_context(lead, followups=None):
    """Build a structured text summary of the lead for use in prompts."""
    lines = [
        f"Lead Name: {lead.get('name', 'Unknown')}",
        f"Phone: {lead.get('phone', 'N/A')}",
        f"Stage: {lead.get('stage', 'N/A')}",
        f"Lead Score: {lead.get('lead_score', 'N/A')} / 100",
        f"Lead Source: {lead.get('lead_source', 'N/A')}",
        f"Interested Courses: {lead.get('interested_courses', 'N/A')}",
        f"Career Goal: {lead.get('career_goal', 'N/A')}",
        f"Education: {lead.get('education_status', 'N/A')} — {lead.get('stream', '')}".rstrip(" — "),
        f"Start Timeframe: {lead.get('start_timeframe', 'N/A')}",
        f"Decision Maker: {lead.get('decision_maker', 'Self')}",
        f"Total Follow-ups Done: {lead.get('followup_count', 0)}",
        f"Last Contact Date: {lead.get('last_contact_date', 'N/A')}",
        f"Next Follow-up Date: {lead.get('next_followup_date', 'N/A')}",
    ]
    if lead.get("notes"):
        lines.append(f"Notes: {lead['notes']}")

    context = "\n".join(lines)

    if followups:
        history_lines = []
        for f in followups[:5]:  # Use latest 5 follow-ups for context
            parts = []
            if f.get("created_at"):
                parts.append(f.get("created_at", "")[:10])
            if f.get("method"):
                parts.append(f"via {f['method']}")
            if f.get("outcome"):
                parts.append(f"Outcome: {f['outcome']}")
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
The script should:
- Start with a warm greeting and remind them of the previous conversation
- Reference their specific interest (course, career goal) to personalize
- Have a clear purpose for calling
- End with a soft call-to-action (e.g., invite them to visit, ask if they have questions)
- Be concise (suitable for a 1–2 minute call opener)
- Sound natural, not robotic

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
Based on the lead profile and follow-up history below, recommend the single most effective
next action the counselor should take to move this lead forward toward enrollment.

Your response should:
- Start with a one-line action recommendation
- Give 2–3 bullet points explaining why this is the right action
- Mention the best timing (e.g., "Call tomorrow morning", "Send WhatsApp now")
- Be specific and practical
- Be concise (under 150 words)

Lead Details:
{context}

Provide only the recommendation. No preamble."""

    model = _get_model()
    response = model.generate_content(prompt)
    return response.text


def draft_message_template(lead, method="WhatsApp"):
    """
    Draft a personalized outreach message for the given method (WhatsApp or Email).
    Returns the message text string, or raises on error.
    """
    context = _build_lead_context(lead)

    if method == "Email":
        prompt = f"""You are an education counselor assistant in India.
Write a short, warm, and personalized follow-up email to a prospective student.
The email should:
- Have a subject line (prefix with "Subject: ")
- Be friendly and professional
- Reference their course interest or career goal
- Include a clear call-to-action (visit, call, or reply)
- Be concise (under 120 words in the body)
- Close with a warm sign-off from "The Admissions Team"

Lead Details:
{context}

Write only the email (subject line + body). No explanation."""
    else:  # WhatsApp (default)
        prompt = f"""You are an education counselor assistant in India.
Write a short, friendly, and personalized WhatsApp follow-up message to a prospective student.
The message should:
- Be conversational and warm (suitable for WhatsApp)
- Reference their specific course interest or career goal
- Include a clear soft call-to-action
- Be concise (2–4 sentences max)
- Not use excessive emojis (1–2 is fine)
- Sound personal, not like a broadcast message

Lead Details:
{context}

Write only the WhatsApp message text. No explanation."""

    model = _get_model()
    response = model.generate_content(prompt)
    return response.text
