# Marvin Configuration Settings

This document describes the customizable settings available in Marvin, focusing on the recent additions from the API Token Security Upgrade and Publishing API implementation.

## Security Settings

### Token Security

Configure token generation and hashing behavior:

```bash
# Token Prefixes
SECURITY_TOKEN_PREFIX_USER="marvin_tk_"      # User API tokens (Personal Access Tokens)
SECURITY_TOKEN_PREFIX_CLIENT="marvin_sk_"    # API client secret keys

# Token Generation
SECURITY_TOKEN_RANDOM_BYTES=32               # Random bytes for token generation (32 = 43 chars base64url)

# Bcrypt Hashing
SECURITY_BCRYPT_ROUNDS=12                    # Bcrypt cost factor (4-31, higher = more secure but slower)
```

**Best Practices:**
- `SECURITY_BCRYPT_ROUNDS`: 12 is recommended for production. Increase to 14+ for higher security at cost of performance.
- `SECURITY_TOKEN_RANDOM_BYTES`: 32 bytes provides 256 bits of entropy. Don't reduce below 24.
- Token prefixes help identify token types in logs and support tools.

## Authentication Settings

### Cookie Configuration

```bash
AUTH_COOKIE_NAME="marvin.access_token"       # Name of the authentication cookie
```

**Use Case:**
- Change if you need custom branding or to avoid conflicts with other applications
- Must be a valid cookie name (no spaces or special characters except dots, hyphens, underscores)

## Publishing API Settings

Configure behavior for the public publishing API used by external sites (Astro, Next.js, etc.).

### Entry Status Filter

```bash
PUBLISHING_DEFAULT_STATUS="published"        # Default entry status for publishing API
```

**Use Cases:**
- Set to `"draft"` to preview unpublished content in development
- Set to `"review"` for editorial workflows
- Default `"published"` ensures only production-ready content is exposed

### Pagination Limits

```bash
PUBLISHING_DEFAULT_PAGE_SIZE=20              # Default entries per page
PUBLISHING_MAX_PAGE_SIZE=100                 # Maximum entries per page
```

**Best Practices:**
- Default page size affects initial load performance for consuming sites
- Max page size prevents excessive database queries
- Smaller sites may want `DEFAULT=10` for faster responses
- Larger sites with build-time generation may want `DEFAULT=50, MAX=200`

### Fallback Values

```bash
PUBLISHING_UNKNOWN_ENTRY_TYPE="unknown"      # Fallback when entry type is missing
```

**Use Case:**
- Customize the fallback value returned when an entry has no entry type
- Consuming sites can use this to handle edge cases gracefully

## Environment Variables

All settings can be configured via environment variables in `.env` file:

```bash
# Example .env configuration
SECURITY_TOKEN_PREFIX_USER=myapp_tk_
SECURITY_TOKEN_PREFIX_CLIENT=myapp_sk_
SECURITY_BCRYPT_ROUNDS=13
AUTH_COOKIE_NAME=myapp.session
PUBLISHING_DEFAULT_PAGE_SIZE=25
PUBLISHING_MAX_PAGE_SIZE=200
```

## Configuration Examples

### Development Environment

```bash
# Fast token generation, draft previews
SECURITY_BCRYPT_ROUNDS=4
PUBLISHING_DEFAULT_STATUS=draft
PUBLISHING_DEFAULT_PAGE_SIZE=10
```

### Production Environment

```bash
# High security, optimized for performance
SECURITY_BCRYPT_ROUNDS=13
PUBLISHING_DEFAULT_STATUS=published
PUBLISHING_DEFAULT_PAGE_SIZE=50
PUBLISHING_MAX_PAGE_SIZE=100
```

### High-Security Environment

```bash
# Maximum security settings
SECURITY_BCRYPT_ROUNDS=14
SECURITY_TOKEN_RANDOM_BYTES=48
PUBLISHING_DEFAULT_STATUS=published
```

## Testing Settings

You can verify your settings are loaded correctly:

```bash
uv run python -c "from src.marvin.core.config import get_app_settings; s = get_app_settings(); \
  print(f'Token Prefix (User): {s.SECURITY_TOKEN_PREFIX_USER}'); \
  print(f'Token Prefix (Client): {s.SECURITY_TOKEN_PREFIX_CLIENT}'); \
  print(f'Bcrypt Rounds: {s.SECURITY_BCRYPT_ROUNDS}'); \
  print(f'Cookie Name: {s.AUTH_COOKIE_NAME}'); \
  print(f'Default Page Size: {s.PUBLISHING_DEFAULT_PAGE_SIZE}')"
```

## Related Documentation

- [API Token Security Settings](./api-token-security-settings.md) - Detailed security model
- [Publishing API Guide](./phase-3-publishing.md) - Publishing API endpoints and usage
- [Sprint Complete](./SPRINT-COMPLETE.md) - Full feature documentation
