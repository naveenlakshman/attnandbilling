from .errors import SmartCounsellingError


STARTED = "STARTED"
IDENTIFICATION_PENDING = "IDENTIFICATION_PENDING"
IDENTIFIED = "IDENTIFIED"
IN_PROGRESS = "IN_PROGRESS"
OUTCOME_PENDING = "OUTCOME_PENDING"
COMPLETED = "COMPLETED"
ABANDONED = "ABANDONED"

OPEN_STATUSES = (
    STARTED,
    IDENTIFICATION_PENDING,
    IDENTIFIED,
    IN_PROGRESS,
    OUTCOME_PENDING,
)
TERMINAL_STATUSES = (COMPLETED, ABANDONED)

ALLOWED_TRANSITIONS = {
    STARTED: {IDENTIFICATION_PENDING, ABANDONED},
    IDENTIFICATION_PENDING: {IDENTIFIED, ABANDONED},
    IDENTIFIED: {IN_PROGRESS, ABANDONED},
    IN_PROGRESS: {OUTCOME_PENDING, ABANDONED},
    OUTCOME_PENDING: {COMPLETED, ABANDONED},
    COMPLETED: set(),
    ABANDONED: set(),
}


def require_transition(current_status, target_status):
    if current_status in TERMINAL_STATUSES:
        code = "session_completed" if current_status == COMPLETED else "invalid_transition"
        raise SmartCounsellingError(
            code,
            f"A {current_status.lower()} counselling session cannot be changed.",
            409,
        )
    if target_status not in ALLOWED_TRANSITIONS.get(current_status, set()):
        raise SmartCounsellingError(
            "invalid_transition",
            f"Counselling session cannot move from {current_status} to {target_status}.",
            409,
        )
