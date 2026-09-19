class NotificationNotFound(Exception):
    pass


class NotificationForbidden(Exception):
    pass


__all__ = ["NotificationNotFound", "NotificationForbidden"]
