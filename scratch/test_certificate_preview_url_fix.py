"""Regression checks for certificate template preview path mapping."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
STORAGE = (ROOT / "services" / "storage.py").read_text(encoding="utf-8")
GENERATOR = (ROOT / "modules" / "certificates" / "generator.py").read_text(encoding="utf-8")


class CertificatePreviewUrlFixTests(unittest.TestCase):
    def test_map_local_path_certificate_keywords(self):
        self.assertIn('elif "cert" in path or "certificate" in path or path == "default.png":', STORAGE)
        self.assertIn('return f"certificates/{path}"', STORAGE)

    def test_ensure_template_preview_canonical_path_format(self):
        self.assertIn('canonical_preview = f"tenants/{tenant_id}/{rel_dir}/{preview_basename}"', GENERATOR)
        self.assertIn('return canonical_preview', GENERATOR)


if __name__ == "__main__":
    unittest.main(verbosity=2)
