"""The one password rule, applied wherever a password is set: registration, a reset, a change of password."""


def check_password_length(password: str) -> str:
    """``password`` if it is at least SECURITY_PASSWORD_MIN_LENGTH characters, else a ValueError saying the minimum."""
    from marvin.services.platform_policy import security

    minimum = max(1, security("SECURITY_PASSWORD_MIN_LENGTH"))
    if len(password or "") < minimum:
        raise ValueError(f"the password must be at least {minimum} characters")
    return password
