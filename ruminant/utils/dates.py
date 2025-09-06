"""Date and week utilities."""

from datetime import datetime, timedelta
from typing import List, Tuple
import pytz


def get_week_date_range(year: int, week: int) -> Tuple[datetime, datetime]:
    """Get the start and end dates for a given year and week number (ISO 8601)."""
    # Get the first day of the year
    jan_4 = datetime(year, 1, 4, tzinfo=pytz.utc)
    # Find the start of week 1 (Monday)
    week_1_start = jan_4 - timedelta(days=jan_4.weekday())
    # Calculate the start of the requested week
    week_start = week_1_start + timedelta(weeks=week - 1)
    week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
    return week_start, week_end


def get_last_complete_week() -> Tuple[int, int]:
    """Get the year and week number of the last complete week."""
    now = datetime.now()
    last_week = now - timedelta(days=7)
    return last_week.isocalendar()[0], last_week.isocalendar()[1]


def get_current_week() -> Tuple[int, int]:
    """Get the year and week number of the current week."""
    now = datetime.now()
    return now.isocalendar()[0], now.isocalendar()[1]


def get_week_list(num_weeks: int, end_year: int = None, end_week: int = None) -> List[Tuple[int, int]]:
    """Get a list of (year, week) tuples for the last num_weeks weeks."""
    if end_year is None or end_week is None:
        end_year, end_week = get_last_complete_week()
    
    weeks = []
    current_year, current_week = end_year, end_week
    
    for i in range(num_weeks):
        weeks.append((current_year, current_week))
        
        # Move to previous week
        current_week -= 1
        if current_week < 1:
            # Move to previous year
            current_year -= 1
            # Get the last week of the previous year
            dec_31 = datetime(current_year, 12, 31)
            current_week = dec_31.isocalendar()[1]
    
    # Return in chronological order (oldest first)
    return list(reversed(weeks))


def format_week_range(year: int, week: int) -> str:
    """Format a week range as a string."""
    week_start, week_end = get_week_date_range(year, week)
    return f"{week_start.strftime('%Y-%m-%d')} to {week_end.strftime('%Y-%m-%d')}"


def is_in_week_range(timestamp_str: str, week_start: datetime, week_end: datetime) -> bool:
    """Check if the timestamp falls within the specified week range."""
    from dateutil.parser import parse
    timestamp = parse(timestamp_str)
    return week_start <= timestamp <= week_end