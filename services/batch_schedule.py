"""Display batch end dates relative to the institute's Indian calendar day."""
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def batch_end_summary(end_date, today=None):
    empty = dict(date=None, date_label=None, days_remaining=None,
                 remaining_label='End date not set', badge_class='bg-light text-secondary border')
    if not end_date:
        return empty
    try:
        if isinstance(end_date, datetime):
            end = end_date.date()
        elif isinstance(end_date, date):
            end = end_date
        else:
            end = date.fromisoformat(str(end_date).strip()[:10])
    except (ValueError, TypeError):
        return empty
    today = today or datetime.now(IST).date()
    days = (end - today).days
    if days < 0:
        count = -days
        label = f"Ended {count} day{'s' if count != 1 else ''} ago"
        badge = 'bg-danger text-white'
    elif days == 0:
        label, badge = 'Ends today', 'bg-warning text-dark'
    else:
        label = f"{days} day{'s' if days != 1 else ''} left"
        badge = 'bg-warning text-dark' if days <= 10 else 'bg-white text-secondary border'
    return dict(date=end.isoformat(), date_label=end.strftime('%d-%m-%Y'), days_remaining=days,
                remaining_label=label, badge_class=badge)


def batch_start_summary(start_date, working_days=None, holidays=None, today=None):
    """Summarise a batch start using the institute's academy calendar.

    Academy days include the start date and today when they are configured
    working days, while configured holidays are excluded.
    """
    empty = dict(
        date=None,
        date_label=None,
        academy_days_elapsed=None,
        status_label='Start date not set',
        badge_class='bg-light text-secondary border',
    )
    if not start_date:
        return empty
    try:
        if isinstance(start_date, datetime):
            start = start_date.date()
        elif isinstance(start_date, date):
            start = start_date
        else:
            start = date.fromisoformat(str(start_date).strip()[:10])
    except (ValueError, TypeError):
        return empty

    today = today or datetime.now(IST).date()
    academy_weekdays = {
        int(day) for day in (working_days if working_days is not None else range(6))
        if str(day).strip().isdigit() and 0 <= int(day) <= 6
    }
    if not academy_weekdays:
        academy_weekdays = set(range(6))
    holiday_dates = {
        str(value).strip()[:10] for value in (holidays or set()) if value
    }

    def is_academy_day(value):
        return value.weekday() in academy_weekdays and value.isoformat() not in holiday_dates

    if start > today:
        cursor = today + timedelta(days=1)
        academy_days_until_start = 0
        while cursor <= start:
            if is_academy_day(cursor):
                academy_days_until_start += 1
            cursor += timedelta(days=1)
        if academy_days_until_start == 0:
            label = 'Starts on next academy day'
        else:
            label = (
                f"Starts in {academy_days_until_start} academy "
                f"day{'s' if academy_days_until_start != 1 else ''}"
            )
        elapsed = 0
        badge = 'bg-info-subtle text-info-emphasis border border-info-subtle'
    else:
        cursor = start
        elapsed = 0
        while cursor <= today:
            if is_academy_day(cursor):
                elapsed += 1
            cursor += timedelta(days=1)
        if start == today:
            label = 'Starts today'
        else:
            label = f"{elapsed} academy day{'s' if elapsed != 1 else ''} completed"
        badge = 'bg-white text-secondary border'

    return dict(
        date=start.isoformat(),
        date_label=start.strftime('%d-%m-%Y'),
        academy_days_elapsed=elapsed,
        status_label=label,
        badge_class=badge,
    )
