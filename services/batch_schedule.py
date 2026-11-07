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
