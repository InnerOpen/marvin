# API Token Security Settings

This document describes the configurable security settings for API tokens and password hashing in Marvin.

## Overview

As of the User API Tokens Security Upgrade, all sensitive tokens (user API tokens, API client secrets, and passwords) are hashed using bcrypt before storage. Several aspects of token generation and hashing can be configured via environment variables.

## Settings

All settings are defined in `src/marvin/core/settings/settings.py` and can be overridden via environment variables.

### Token Prefixes

#### `SECURITY_TOKEN_PREFIX_USER`
- **Type**: `str`
- **Default**: `"marvin_tk_"`
- **Description**: Prefix for user API tokens (Personal Access Tokens)
- **Format**: Token format will be `{prefix}{random-base64url-string}`
- **Example**: `marvin_tk_kDvke5gRwb7j4uEgsLgiSrLWHG6KQHpkVxGDJKKVBMA`

#### `SECURITY_TOKEN_PREFIX_CLIENT`
- **Type**: `str`
- **Default**: `"marvin_sk_"`
- **Description**: Prefix for API client secret keys (workspace-scoped tokens)
- **Format**: Token format will be `{prefix}{random-base64url-string}`
- **Example**: `marvin_sk_j6t5KPNNlJvmJb3T_oq96Wo3U9eEfnDlPaXgYAN87hM`

### Token Generation

#### `SECURITY_TOKEN_RANDOM_BYTES`
- **Type**: `int`
- **Default**: `32`
- **Description**: Number of random bytes used for token generation. When base64url encoded, 32 bytes produces a 43-character string.
- **Valid Range**: 16-64 recommended (produces 22-86 character tokens)
- **Security Note**: Higher values = more entropy = more secure tokens

**Token Length Formula**: `ceil(bytes * 4/3)` characters

| Bytes | Characters | Security Level |
|-------|-----------|---------------|
| 16    | 22        | Minimum (128-bit) |
| 24    | 32        | Good (192-bit) |
| 32    | 43        | Excellent (256-bit) ⭐ Default |
| 48    | 64        | Overkill (384-bit) |

### Password Hashing

#### `SECURITY_BCRYPT_ROUNDS`
- **Type**: `int`
- **Default**: `12`
- **Valid Range**: `4-31` (enforced by bcrypt)
- **Description**: Bcrypt cost factor (work factor). Each increment doubles the computation time.
- **Performance Impact**:
  - **10**: ~60ms (fast, minimum for production)
  - **12**: ~250ms (recommended balance) ⭐ Default
  - **14**: ~1 second (high security)
  - **16**: ~4 seconds (very high security, may impact UX)

**Security vs Performance Trade-off**:
- Higher rounds = slower hashing = more secure against brute-force
- Lower rounds = faster hashing = better UX but less secure
- Recommended: 12-14 for production systems

**When to Increase**:
- High-value targets (admin accounts, financial systems)
- Regulatory compliance requirements
- When hardware capabilities improve (every 2 years, consider +1)

**When to Keep Default (12)**:
- Standard applications
- Good balance of security and performance
- Industry standard as of 2024

## Environment Variable Configuration

Set these in your `.env` file or environment:

```bash
# Token Prefixes
SECURITY_TOKEN_PREFIX_USER=marvin_tk_
SECURITY_TOKEN_PREFIX_CLIENT=marvin_sk_

# Token Generation
SECURITY_TOKEN_RANDOM_BYTES=32

# Password Hashing
SECURITY_BCRYPT_ROUNDS=12
```

## Implementation Details

### Where Settings Are Used

1. **User API Tokens** (`src/marvin/repos/users/long_live_tokens.py`)
   - Uses `SECURITY_TOKEN_PREFIX_USER`
   - Uses `SECURITY_TOKEN_RANDOM_BYTES`
   - Uses `SECURITY_BCRYPT_ROUNDS` (via hasher)

2. **API Clients** (`src/marvin/repos/platform/api_clients.py`)
   - Uses `SECURITY_TOKEN_PREFIX_CLIENT`
   - Uses `SECURITY_TOKEN_RANDOM_BYTES`
   - Uses `SECURITY_BCRYPT_ROUNDS` (via hasher)

3. **Password Hasher** (`src/marvin/core/security/hasher.py`)
   - Uses `SECURITY_BCRYPT_ROUNDS`

4. **Authentication** (`src/marvin/core/dependencies/dependencies.py`)
   - Uses `SECURITY_TOKEN_PREFIX_USER` for token detection

### Token Detection Logic

The authentication system automatically detects token type by prefix:

```python
# User API Token (marvin_tk_*)
if token.startswith(settings.SECURITY_TOKEN_PREFIX_USER):
    # Validate as user API token

# JWT Token (eyJ*)
elif token.startswith("eyJ"):
    # Validate as JWT
```

**Important**: If you change `SECURITY_TOKEN_PREFIX_USER`, ensure it doesn't conflict with:
- JWT tokens (start with `eyJ`)
- API client tokens (default: `marvin_sk_`)

## Testing Configuration Changes

After changing settings, verify token generation works correctly:

```bash
# 1. Restart the server
task py

# 2. Create a test token
curl -X POST http://localhost:8080/api/api-tokens \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Token"}'

# 3. Verify token prefix matches your setting
# Token should start with SECURITY_TOKEN_PREFIX_USER value

# 4. Check bcrypt rounds in database
sqlite3 marvin.db "SELECT token_hash FROM long_live_tokens LIMIT 1;"
# Hash should start with $2b${SECURITY_BCRYPT_ROUNDS}$
```

## Migration Notes

### Changing Token Prefixes

✅ **Safe**: You can change prefixes at any time. Existing tokens with old prefixes will continue to work.

### Changing Random Bytes

✅ **Safe**: You can change this at any time. Only affects newly generated tokens.

### Changing Bcrypt Rounds

⚠️ **Careful**: Existing hashes won't be affected, but:
- New tokens will use the new rounds
- Mixed rounds in database is normal and safe
- Consider the performance impact on your users
- Test hash generation time before deploying:

```python
import time
from marvin.core.security.hasher import get_hasher

hasher = get_hasher()
start = time.time()
hasher.hash("test_password")
duration = (time.time() - start) * 1000
print(f"Hash time: {duration:.0f}ms")
```

## Security Best Practices

1. **Never change settings to weaken security** (e.g., reducing bcrypt rounds below 12)
2. **Use environment variables** for production configuration, not hardcoded values
3. **Monitor hash times** in production to ensure acceptable UX (<500ms)
4. **Rotate tokens regularly** by asking users to create new ones
5. **Audit token usage** via `last_used_at` timestamps

## Related Documentation

- [API Token Lifecycle](./api-token-lifecycle.md) *(if exists)*
- [Authentication Guide](./authentication.md) *(if exists)*
- [Security Best Practices](./security.md) *(if exists)*

## Questions?

For questions about these settings or security in general, consult:
- [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
- [Bcrypt Documentation](https://en.wikipedia.org/wiki/Bcrypt)
