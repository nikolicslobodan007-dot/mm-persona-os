"""Independent, read-only 3D presentation for the existing Office V1.2 API.

No database writes, no new Django app, no new API contract.
"""

from django.shortcuts import render
from django.views.decorators.http import require_GET

from console.auth import console_view


@require_GET
@console_view
def office_3d(request):
    return render(request, "console/office_3d.html")
