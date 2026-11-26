from django.db import connection
from django.http import HttpResponse


class HealthCheckMiddleware:
    """Answer load-balancer health checks at /healthz/ before host validation and HTTPS redirects.

    Load balancers call containers by IP address over plain HTTP, which ALLOWED_HOSTS and
    SECURE_SSL_REDIRECT would otherwise reject.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info == "/healthz/":
            try:
                connection.ensure_connection()
            except Exception:  # noqa: BLE001
                return HttpResponse("database unavailable", status=503, content_type="text/plain")
            return HttpResponse("ok", content_type="text/plain")
        return self.get_response(request)
