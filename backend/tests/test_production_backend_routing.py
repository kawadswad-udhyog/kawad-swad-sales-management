import os
os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

import sys
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import unittest

class TestProductionBackendRouting(unittest.TestCase):
    def test_render_yaml_routing(self):
        """Verify render.yaml routes frontend API traffic to kawad-swad-sales-dev and aligns CORS/service name."""
        render_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "render.yaml"))
        self.assertTrue(os.path.exists(render_path), f"render.yaml must exist at {render_path}")

        with open(render_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("kawad-swad-sales-backend.onrender.com", content)
        self.assertNotIn("REPLACE-WITH-PROD-BACKEND-HOST", content)
        self.assertIn("https://kawad-swad-sales-dev.onrender.com/api/*", content)
        self.assertIn("https://kawad-swad-sales-dev.onrender.com/health", content)
        self.assertIn("https://kawad-swad-sales-dev.onrender.com/auth/*", content)
        self.assertIn("https://kawad-swad-sales-frontend.onrender.com", content)
        self.assertIn("sync: false", content)
        self.assertIn("name: kawad-swad-sales-dev", content)

    def test_public_redirects_routing(self):
        """Verify public/_redirects routes /api/*, /health, /auth/* to kawad-swad-sales-dev.onrender.com."""
        redirects_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "public", "_redirects"))
        self.assertTrue(os.path.exists(redirects_path), f"public/_redirects must exist at {redirects_path}")

        with open(redirects_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("kawad-swad-sales-backend.onrender.com", content)
        self.assertNotIn("REPLACE-WITH-PROD-BACKEND-HOST", content)
        self.assertIn("https://kawad-swad-sales-dev.onrender.com/api/:splat", content)
        self.assertIn("https://kawad-swad-sales-dev.onrender.com/health", content)
        self.assertIn("/api/*", content)
        self.assertIn("/index.html", content)

    def test_vite_config_proxy_target(self):
        """Verify vite.config.ts defaults local dev proxy to 127.0.0.1:8000 when VITE_API_URL is unset."""
        vite_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "vite.config.ts"))
        self.assertTrue(os.path.exists(vite_path), f"vite.config.ts must exist at {vite_path}")

        with open(vite_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("https://kawad-swad-sales-backend.onrender.com", content)
        self.assertIn("http://127.0.0.1:8000", content)

    def test_no_obsolete_or_placeholder_target_in_frontend_source(self):
        """Verify frontend source never uses obsolete -backend or placeholder hostnames as active targets."""
        src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
        for root, _, files in os.walk(src_dir):
            for file in files:
                if file.endswith((".ts", ".tsx", ".js", ".jsx")):
                    path = os.path.join(root, file)
                    with open(path, "r", encoding="utf-8") as f:
                        for line_no, line in enumerate(f, 1):
                            for forbidden in ("kawad-swad-sales-backend.onrender.com", "REPLACE-WITH-PROD"):
                                if forbidden in line:
                                    # Allowed only inside explicit security purge/blocklist checks
                                    if "isDisallowedBackendOverride" in line or "lower.includes" in line or "localStorage.removeItem" in line:
                                        continue
                                    self.fail(f"Found forbidden target hostname {forbidden} on line {line_no} in {path}: {line.strip()}")

    def test_health_check_contract_definition(self):
        """Verify main.py keeps public /health minimal while exposing detailed fields only in /health/details."""
        from app.main import health_check
        public = health_check()
        for key in ("status", "service", "google_sheets_connected", "persistent_writes_enabled", "backend"):
            self.assertIn(key, public)
        for sensitive_key in (
            "spreadsheet_id_configured",
            "service_account_configured",
            "last_connection_error",
            "allow_in_memory_fallback",
            "google_sheets",
            "required_sheets",
        ):
            self.assertNotIn(sensitive_key, public)

        main_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app", "main.py"))
        with open(main_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("def health_details(", content)
        for key in ('"spreadsheet_id_configured":', '"service_account_configured":', '"google_sheets":', '"required_sheets":'):
            self.assertIn(key, content)

if __name__ == "__main__":
    unittest.main()
