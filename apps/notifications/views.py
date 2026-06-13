from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import (
    Channel,
    EventType,
    Notification,
    NotificationPreference,
    QuietHours,
)


@login_required
@require_GET
def notification_drawer(request):
    """HTMX partial: renders the 50 most recent notifications for the drawer."""
    notifications = Notification.objects.filter(user=request.user).order_by("-created_at")[:50]
    return render(
        request,
        "notifications/partials/drawer.html",
        {
            "notifications": notifications,
        },
    )


@login_required
@require_GET
def notification_list(request):
    """Full notification history page with filtering."""
    event_type = request.GET.get("event_type", "")
    read_status = request.GET.get("read_status", "")

    qs = Notification.objects.filter(user=request.user)

    if event_type:
        qs = qs.filter(event_type=event_type)
    if read_status == "read":
        qs = qs.filter(is_read=True)
    elif read_status == "unread":
        qs = qs.filter(is_read=False)

    # Pagination
    page = int(request.GET.get("page", 1))
    per_page = 30
    offset = (page - 1) * per_page
    notifications = qs[offset : offset + per_page]
    total = qs.count()
    has_next = total > offset + per_page
    has_prev = page > 1

    context = {
        "notifications": notifications,
        "event_types": EventType.choices,
        "selected_event_type": event_type,
        "selected_read_status": read_status,
        "page": page,
        "has_next": has_next,
        "has_prev": has_prev,
        "total": total,
    }

    if request.htmx:
        return render(request, "notifications/partials/history_list.html", context)
    return render(request, "notifications/history.html", context)


@login_required
@require_POST
def mark_as_read(request, notification_id):
    """Mark a single notification as read."""
    Notification.objects.filter(id=notification_id, user=request.user, is_read=False).update(
        is_read=True, read_at=timezone.now()
    )

    if request.htmx:
        return render(request, "notifications/partials/empty.html")
    return JsonResponse({"ok": True})


@login_required
@require_POST
def mark_all_read(request):
    """Mark all notifications as read."""
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True, read_at=timezone.now())

    if request.htmx:
        return notification_drawer(request)
    return JsonResponse({"ok": True})


@login_required
@require_GET
def unread_count(request):
    """JSON endpoint for polling unread badge count."""
    count = Notification.objects.filter(user=request.user, is_read=False).count()
    return JsonResponse({"count": count})


@login_required
def preferences(request):
    """Notification preferences page - per event type / channel toggles + quiet hours."""
    if request.method == "POST":
        return _save_preferences(request)

    # Build preference matrix: event_type → channel → enabled
    prefs = NotificationPreference.objects.filter(user=request.user)
    pref_map = {}
    for p in prefs:
        pref_map[(p.event_type, p.channel)] = p.is_enabled

    from .engine import DEFAULT_CHANNELS

    matrix = []
    for event_value, event_label in EventType.choices:
        channel_toggles = []
        for ch_value, ch_label in Channel.choices:
            if (event_value, ch_value) in pref_map:
                enabled = pref_map[(event_value, ch_value)]
            else:
                enabled = DEFAULT_CHANNELS.get(event_value, {}).get(ch_value, False)
            channel_toggles.append(
                {
                    "channel": ch_value,
                    "label": ch_label,
                    "field_name": f"pref_{event_value}_{ch_value}",
                    "enabled": enabled,
                }
            )
        matrix.append(
            {
                "event_type": event_value,
                "event_label": event_label,
                "channel_toggles": channel_toggles,
            }
        )

    quiet_hours, _ = QuietHours.objects.get_or_create(user=request.user)

    context = {
        "matrix": matrix,
        "channel_choices": Channel.choices,
        "quiet_hours": quiet_hours,
    }
    return render(request, "notifications/preferences.html", context)


def _save_preferences(request):
    """Handle POST from preferences form."""
    user = request.user

    # Save channel toggles
    for event_value, _ in EventType.choices:
        for ch_value, _ in Channel.choices:
            field_name = f"pref_{event_value}_{ch_value}"
            is_enabled = field_name in request.POST

            NotificationPreference.objects.update_or_create(
                user=user,
                event_type=event_value,
                channel=ch_value,
                defaults={"is_enabled": is_enabled},
            )

    # Save quiet hours
    quiet_hours, _ = QuietHours.objects.get_or_create(user=user)
    quiet_hours.is_enabled = "quiet_hours_enabled" in request.POST
    from datetime import time as dt_time

    start = request.POST.get("quiet_hours_start", "").strip()
    end = request.POST.get("quiet_hours_end", "").strip()
    if start:
        parts = start.split(":")
        quiet_hours.start_time = dt_time(int(parts[0]), int(parts[1]))
    if end:
        parts = end.split(":")
        quiet_hours.end_time = dt_time(int(parts[0]), int(parts[1]))
    quiet_hours.timezone = request.POST.get("quiet_hours_timezone", "UTC").strip()
    quiet_hours.digest_mode = "digest_mode" in request.POST
    quiet_hours.save()

    from django.contrib import messages

    messages.success(request, "Notification preferences saved.")

    return redirect("notifications:preferences")
