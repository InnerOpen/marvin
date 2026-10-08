"""Generate a VAPID key pair for Web Push and print it as environment lines.

    python -m marvin.scripts.vapid [--subject mailto:ops@example.com]

Prints VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY and VAPID_SUBJECT for the backend's environment (or a Secret).
Nothing is written anywhere; keep the private key secret. Changing the pair later means every browser has
to subscribe again (the old subscriptions stop working), so generate it once per installation.
"""

from __future__ import annotations

import argparse
import base64
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate() -> tuple[str, str]:
    """A new P-256 key pair: (public key as the uncompressed point, private key as the raw 32-byte scalar),
    both base64url without padding — the forms browsers and pywebpush take."""
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    private = key.private_numbers().private_value.to_bytes(32, "big")
    return _b64url(public), _b64url(private)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m marvin.scripts.vapid", description=__doc__.splitlines()[0])
    parser.add_argument("--subject", default="mailto:admin@example.com", help="a mailto: address or https: URL push services can contact")
    args = parser.parse_args(argv)
    if not args.subject.startswith(("mailto:", "https://")):
        parser.error("--subject must start with mailto: or https://")
    public, private = generate()
    sys.stdout.write(f"VAPID_PUBLIC_KEY={public}\nVAPID_PRIVATE_KEY={private}\nVAPID_SUBJECT={args.subject}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
