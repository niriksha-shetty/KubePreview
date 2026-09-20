import hashlib
import hmac
import logging

logger = logging.getLogger("kubepreview.security")


def verify_signature(payload_body: bytes, secret: str, signature_header: str | None) -> bool:
    """Verify GitHub HMAC-SHA256 signature against X-Hub-Signature-256 header.

    :param payload_body: Raw bytes of the HTTP request body.
    :param secret: The shared secret key configured for the webhook.
    :param signature_header: Value of X-Hub-Signature-256 header (e.g., 'sha256=...').
    :return: True if valid, False otherwise.
    """
    if not secret:
        logger.warning("GITHUB_WEBHOOK_SECRET is empty. Skipping signature verification.")
        return True

    if not signature_header:
        logger.error("Missing X-Hub-Signature-256 header in request.")
        return False

    if not signature_header.startswith("sha256="):
        logger.error("Invalid signature format (expected 'sha256=<hash>'). Header: %s", signature_header)
        return False

    expected_signature = signature_header.split("sha256=", 1)[1].strip()

    mac = hmac.new(
        secret.encode("utf-8"),
        msg=payload_body,
        digestmod=hashlib.sha256,
    )
    computed_signature = mac.hexdigest()

    is_valid = hmac.compare_digest(computed_signature, expected_signature)
    if not is_valid:
        logger.error(
            "Signature verification failed. Computed: %s, Expected: %s",
            computed_signature,
            expected_signature,
        )

    return is_valid
