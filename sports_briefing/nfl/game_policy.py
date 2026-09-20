UPCOMING_GAME_STATUSES = frozenset(
    {"scheduled", "created", "time-tbd", "flex-schedule"}
)


def is_upcoming_game_status(status: str) -> bool:
    return status.lower() in UPCOMING_GAME_STATUSES
