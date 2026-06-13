"""Portal authentication decorator."""

import functools

from django.shortcuts import redirect

from apps.members.models import WorkspaceMembership
from apps.workspaces.models import Workspace


def portal_auth_required(view_func):
    """Decorator that enforces portal session authentication.

    Checks that the user is authenticated, has an active portal session,
    and resolves the portal workspace onto the request.
    """

    @functools.wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("client_portal:magic_link_expired")

        if not request.session.get("is_portal_session"):
            return redirect("client_portal:magic_link_expired")

        workspace_id = request.session.get("portal_workspace_id")
        if not workspace_id:
            return redirect("client_portal:magic_link_expired")

        try:
            workspace = Workspace.objects.get(id=workspace_id)
        except Workspace.DoesNotExist:
            return redirect("client_portal:magic_link_expired")

        # Verify user has client membership in this workspace
        membership = (
            WorkspaceMembership.objects.filter(
                user=request.user,
                workspace=workspace,
            )
            .select_related("custom_role")
            .first()
        )

        if not membership:
            return redirect("client_portal:magic_link_expired")

        request.portal_workspace = workspace
        request.portal_membership = membership

        return view_func(request, *args, **kwargs)

    return _wrapped
