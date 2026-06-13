from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def settings_index(request):
    return render(request, "settings_manager/index.html")
