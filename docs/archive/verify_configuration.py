#!/usr/bin/env python3
"""
Verification script for Marvin configuration settings upgrade.

This script verifies:
1. All new settings are loaded correctly
2. Settings have expected default values
3. Publishing controller uses settings (no hardcoded values)
4. Dependencies use settings (no hardcoded values)

Run with: uv run python verify_configuration.py
"""

from src.marvin.core.config import get_app_settings


def verify_settings():
    """Verify all configuration settings are loaded correctly."""
    print("=" * 70)
    print("MARVIN CONFIGURATION SETTINGS VERIFICATION")
    print("=" * 70)

    settings = get_app_settings()

    # Authentication Settings
    print("\n📋 AUTHENTICATION SETTINGS")
    print("-" * 70)
    assert hasattr(settings, "AUTH_COOKIE_NAME"), "AUTH_COOKIE_NAME missing"
    print(f"✅ AUTH_COOKIE_NAME: {settings.AUTH_COOKIE_NAME}")
    assert settings.AUTH_COOKIE_NAME == "marvin.access_token", "Incorrect default"

    # Token Security Settings
    print("\n🔒 TOKEN SECURITY SETTINGS")
    print("-" * 70)
    assert hasattr(settings, "SECURITY_TOKEN_PREFIX_USER"), "SECURITY_TOKEN_PREFIX_USER missing"
    print(f"✅ SECURITY_TOKEN_PREFIX_USER: {settings.SECURITY_TOKEN_PREFIX_USER}")
    assert settings.SECURITY_TOKEN_PREFIX_USER == "marvin_tk_", "Incorrect default"

    assert hasattr(settings, "SECURITY_TOKEN_PREFIX_CLIENT"), "SECURITY_TOKEN_PREFIX_CLIENT missing"
    print(f"✅ SECURITY_TOKEN_PREFIX_CLIENT: {settings.SECURITY_TOKEN_PREFIX_CLIENT}")
    assert settings.SECURITY_TOKEN_PREFIX_CLIENT == "marvin_sk_", "Incorrect default"

    assert hasattr(settings, "SECURITY_TOKEN_RANDOM_BYTES"), "SECURITY_TOKEN_RANDOM_BYTES missing"
    print(f"✅ SECURITY_TOKEN_RANDOM_BYTES: {settings.SECURITY_TOKEN_RANDOM_BYTES}")
    assert settings.SECURITY_TOKEN_RANDOM_BYTES == 32, "Incorrect default"

    assert hasattr(settings, "SECURITY_BCRYPT_ROUNDS"), "SECURITY_BCRYPT_ROUNDS missing"
    print(f"✅ SECURITY_BCRYPT_ROUNDS: {settings.SECURITY_BCRYPT_ROUNDS}")
    assert settings.SECURITY_BCRYPT_ROUNDS == 12, "Incorrect default"

    # Publishing API Settings
    print("\n📡 PUBLISHING API SETTINGS")
    print("-" * 70)
    assert hasattr(settings, "PUBLISHING_DEFAULT_STATUS"), "PUBLISHING_DEFAULT_STATUS missing"
    print(f"✅ PUBLISHING_DEFAULT_STATUS: {settings.PUBLISHING_DEFAULT_STATUS}")
    assert settings.PUBLISHING_DEFAULT_STATUS == "published", "Incorrect default"

    assert hasattr(settings, "PUBLISHING_DEFAULT_PAGE_SIZE"), "PUBLISHING_DEFAULT_PAGE_SIZE missing"
    print(f"✅ PUBLISHING_DEFAULT_PAGE_SIZE: {settings.PUBLISHING_DEFAULT_PAGE_SIZE}")
    assert settings.PUBLISHING_DEFAULT_PAGE_SIZE == 20, "Incorrect default"

    assert hasattr(settings, "PUBLISHING_MAX_PAGE_SIZE"), "PUBLISHING_MAX_PAGE_SIZE missing"
    print(f"✅ PUBLISHING_MAX_PAGE_SIZE: {settings.PUBLISHING_MAX_PAGE_SIZE}")
    assert settings.PUBLISHING_MAX_PAGE_SIZE == 100, "Incorrect default"

    assert hasattr(settings, "PUBLISHING_UNKNOWN_ENTRY_TYPE"), "PUBLISHING_UNKNOWN_ENTRY_TYPE missing"
    print(f"✅ PUBLISHING_UNKNOWN_ENTRY_TYPE: {settings.PUBLISHING_UNKNOWN_ENTRY_TYPE}")
    assert settings.PUBLISHING_UNKNOWN_ENTRY_TYPE == "unknown", "Incorrect default"

    print("\n" + "=" * 70)
    print("✅ ALL SETTINGS VERIFIED SUCCESSFULLY")
    print("=" * 70)
    print()
    print("Summary:")
    print(f"  • {1} Authentication setting")
    print(f"  • {4} Token security settings")
    print(f"  • {4} Publishing API settings")
    print(f"  • Total: {9} new configurable settings")
    print()
    print("All settings have correct default values matching previous hardcoded values.")
    print("No breaking changes - existing deployments will work without modification.")
    print()


def verify_no_hardcoded_values():
    """Verify no hardcoded values remain in code."""
    print("=" * 70)
    print("HARDCODED VALUE CHECK")
    print("=" * 70)

    # Check publishing controller
    with open("src/marvin/routes/publish/publishing_controller.py") as f:
        content = f.read()

    print("\n📄 Checking publishing_controller.py...")

    # Should NOT contain hardcoded values
    assert '"published"' not in content, "Hardcoded 'published' status found"
    print("✅ No hardcoded 'published' status")

    assert '"unknown"' not in content, "Hardcoded 'unknown' entry type found"
    print("✅ No hardcoded 'unknown' entry type")

    assert "Query(20," not in content, "Hardcoded page size 20 found"
    print("✅ No hardcoded page size")

    assert "le=100" not in content, "Hardcoded max page size 100 found"
    print("✅ No hardcoded max page size")

    # Should contain settings usage
    assert "settings.PUBLISHING_DEFAULT_STATUS" in content, "Missing settings usage"
    print("✅ Uses settings.PUBLISHING_DEFAULT_STATUS")

    assert "settings.PUBLISHING_UNKNOWN_ENTRY_TYPE" in content, "Missing settings usage"
    print("✅ Uses settings.PUBLISHING_UNKNOWN_ENTRY_TYPE")

    assert "settings.PUBLISHING_DEFAULT_PAGE_SIZE" in content, "Missing settings usage"
    print("✅ Uses settings.PUBLISHING_DEFAULT_PAGE_SIZE")

    assert "settings.PUBLISHING_MAX_PAGE_SIZE" in content, "Missing settings usage"
    print("✅ Uses settings.PUBLISHING_MAX_PAGE_SIZE")

    # Check dependencies
    with open("src/marvin/core/dependencies/dependencies.py") as f:
        content = f.read()

    print("\n📄 Checking dependencies.py...")

    # Should NOT contain hardcoded cookie name
    assert '"marvin.access_token"' not in content, "Hardcoded cookie name found"
    print("✅ No hardcoded cookie name")

    # Should contain settings usage
    assert "settings.AUTH_COOKIE_NAME" in content, "Missing settings usage"
    print("✅ Uses settings.AUTH_COOKIE_NAME")

    print("\n" + "=" * 70)
    print("✅ NO HARDCODED VALUES FOUND - ALL EXTERNALIZED")
    print("=" * 70)
    print()


if __name__ == "__main__":
    try:
        verify_settings()
        verify_no_hardcoded_values()
        print("🎉 CONFIGURATION UPGRADE VERIFICATION COMPLETE!")
        print()
    except AssertionError as e:
        print(f"\n❌ VERIFICATION FAILED: {e}")
        exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        exit(1)
