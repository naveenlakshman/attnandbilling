from datetime import date, datetime, timezone

import pytest
from services import batch_schedule


@pytest.mark.parametrize('value,days,label',[
    ('2026-11-20',18,'18 days left'),('2026-11-03',1,'1 day left'),
    ('2026-11-02',0,'Ends today'),('2026-11-01',-1,'Ended 1 day ago'),
    ('2026-10-30',-3,'Ended 3 days ago'),(date(2026,11,20),18,'18 days left'),
    (datetime(2026,11,20,12,0),18,'18 days left'),('2026-11-20T00:00:00',18,'18 days left'),
])
def test_end_date_and_remaining_days(value,days,label):
    result=batch_schedule.batch_end_summary(value,today=date(2026,11,2))
    assert result['days_remaining']==days and result['remaining_label']==label
    assert result['date_label']==('20-11-2026' if days==18 else date.fromisoformat(str(value)[:10]).strftime('%d-%m-%Y'))


@pytest.mark.parametrize('value',[None,'','invalid','2026-02-31'])
def test_missing_or_invalid_end_dates_are_not_reported_as_zero_days(value):
    result=batch_schedule.batch_end_summary(value,today=date(2026,11,2))
    assert result['days_remaining'] is None and result['remaining_label']=='End date not set'


def test_uses_india_calendar_day_at_utc_date_boundary(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            value=datetime(2026,11,2,19,0,tzinfo=timezone.utc)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)
    monkeypatch.setattr(batch_schedule,'datetime',Clock)
    assert batch_schedule.batch_end_summary('2026-11-03')['remaining_label']=='Ends today'
