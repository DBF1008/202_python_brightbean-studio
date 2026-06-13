def unread_notification_count(request):
    """Add unread notification count to all template contexts."""
    if hasattr(request, "user") and request.user.is_authenticated:
        from .models import Notification

        count = Notification.objects.filter(user=request.user, is_read=False).count()
        return {"unread_notification_count": count}
    return {"unread_notification_count": 0}
