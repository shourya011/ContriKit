"""Content Security Policy middleware for ContribKit.

Adds security headers to every response to prevent XSS, data injection,
and other client-side attacks. This is intentionally permissive enough
to allow Bootstrap CDN, Chart.js, and highlight.js which the app uses.
"""

import re


class CSPMiddleware:
    """Adds Content-Security-Policy and Permissions-Policy headers."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Content Security Policy
        response['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
            "https://cdn.jsdelivr.net "
            "https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' "
            "https://cdn.jsdelivr.net "
            "https://cdnjs.cloudflare.com; "
            "img-src 'self' data: https:; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "connect-src 'self' https://api.github.com; "
            "frame-ancestors 'none'; "
            "form-action 'self'; "
            "base-uri 'self'; "
            "object-src 'none'"
        )

        # Permissions Policy
        response['Permissions-Policy'] = (
            "camera=(), "
            "microphone=(), "
            "geolocation=(), "
            "payment=(), "
            "usb=(), "
            "magnetometer=(), "
            "accelerometer=(), "
            "gyroscope=()"
        )

        return response
