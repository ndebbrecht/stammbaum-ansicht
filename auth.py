import argparse
import base64
import getpass
import hashlib
import hmac
from pathlib import Path
import secrets


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600000)
    return "pbkdf2_sha256:600000:" + base64.b64encode(salt).decode() + ":" + base64.b64encode(digest).decode()


def verify_password(password, encoded):
    try:
        algorithm, iterations, salt_text, digest_text = encoded.strip().split(":")
        if algorithm != "pbkdf2_sha256" or iterations != "600000":
            return False
        salt = base64.b64decode(salt_text, validate=True)
        expected = base64.b64decode(digest_text, validate=True)
        if len(salt) != 16 or len(expected) != 32:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600000)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a password hash outside the public repository")
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    password = getpass.getpass("Passwort: ")
    confirmation = getpass.getpass("Wiederholen: ")
    if not password or password != confirmation:
        parser.error("Passwords must match and not be empty")
    output = Path(arguments.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = output.open("x", encoding="utf-8")
    try:
        output.chmod(0o600)
        descriptor.write(hash_password(password) + "\n")
    finally:
        descriptor.close()
