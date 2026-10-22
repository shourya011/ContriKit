"""Social-auth pipeline steps shared by the OAuth providers."""

from social_core.pipeline.social_auth import associate_by_email


def associate_by_verified_email(backend, details, response=None, user=None, *args, **kwargs):
    """Link an OAuth login to an existing account only via a verified email.

    Google verifies the address it returns. GitHub reports the verification
    status per address in ``/user/emails``, so a missing or unverified address
    must never be used to take over an existing account.
    """
    if user:
        return None

    if backend.name == 'github':
        email = (details or {}).get('email')
        if not email:
            return None

        verified_emails = {
            item['email'].lower()
            for item in (response or {}).get('emails') or []
            if isinstance(item, dict) and item.get('verified') and item.get('email')
        }
        if email.lower() not in verified_emails:
            return None

    return associate_by_email(backend, details, user=user, *args, **kwargs)
