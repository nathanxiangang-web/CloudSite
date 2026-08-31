import math
from datetime import datetime, timedelta


WINDOWS_PER_CYCLE = 4
WINDOW_INTERVAL = timedelta(hours=6)
CYCLE_INTERVAL = timedelta(hours=24)


def calculate_window_target(
    remaining_folders: int,
    windows_completed: int,
    windows_total: int = WINDOWS_PER_CYCLE,
) -> int:
    if remaining_folders <= 0:
        return 0
    windows_left = max(1, windows_total - windows_completed)
    return math.ceil(remaining_folders / windows_left)


def next_window_due_at(anchor_at: datetime, windows_completed: int) -> datetime:
    return anchor_at + WINDOW_INTERVAL * (windows_completed + 1)


def next_cycle_anchor(anchor_at: datetime) -> datetime:
    return anchor_at + CYCLE_INTERVAL
