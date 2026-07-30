"""Regression checks for rate limiting authentication updates."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = (ROOT / "extensions.py").read_text(encoding="utf-8")


class RateLimitExtensionTests(unittest.TestCase):
    def test_public_auth_limit_uses_post_methods_and_composite_key(self):
        self.assertIn('methods=["POST"]', EXTENSIONS)
        self.assertIn('key_func=get_auth_rate_limit_key', EXTENSIONS)
        self.assertIn('def get_auth_rate_limit_key():', EXTENSIONS)
        self.assertIn('return f"{ip}:{username}"', EXTENSIONS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
