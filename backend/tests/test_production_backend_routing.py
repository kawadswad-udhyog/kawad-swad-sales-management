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
        """Verify render.yaml rewrites route strictly to confirmed production backend kawad-swad-sales-dev."""
        render_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "render.yaml"))
        self.assertTrue(os.path.exists(render_path), f"render.yaml must exist at {render_path}")

        with open(render_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Must not contain obsolete backend hostname
        self.assertNotIn("kawad-swad-sales-backend.onrender.com", content)
        # Must target confirmed production backend
        self.assertIn("destination: https://kawad-swad-sales-dev.onrender.com/api/*", content)
        self.assertIn("destination: https://kawad-swad-sales-dev.onrender.com/health", content)
        self.assertIn("destination: https://kawad-swad-sales-dev.onrender.com/auth/*", content)
        self.assertIn("value: https://kawad-swad-sales-dev.onrender.com", content)
        self.assertIn("name: kawad-swad-sales-dev", content)

    def test_public_redirects_routing(self):
        """Verify public/_redirects routes strictly to confirmed production backend kawad-swad-sales-dev."""
        redirects_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "public", "_redirects"))
        self.assertTrue(os.path.exists(redirects_path), f"public/_redirects must exist at {redirects_path}")

        with open(redirects_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("kawad-swad-sales-backend.onrender.com", content)
        self.assertIn("https://kawad-swad-sales-dev.onrender.com/api/:splat", content)
        self.assertIn("https://kawad-swad-sales-dev.onrender.com/health", content)
        self.assertIn("https://kawad-swad-sales-dev.onrender.com/auth/:splat", content)

    def test_vite_config_proxy_target(self):
        """Verify vite.config.ts defaults to confirmed backend kawad-swad-sales-dev."""
        vite_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "vite.config.ts"))
        self.assertTrue(os.path.exists(vite_path), f"vite.config.ts must exist at {vite_path}")

        with open(vite_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("https://kawad-swad-sales-backend.onrender.com", content)
        self.assertIn("https://kawad-swad-sales-dev.onrender.com", content)

    def test_no_obsolete_urls_in_frontend_source(self):
        """Verify that no active frontend source files hardcode obsolete kawad-swad-sales-backend.onrender.com as target."""
        src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
        for root, _, files in os.walk(src_dir):
            for file in files:
                if file.endswith((".ts", ".tsx", ".js", ".jsx")):
                    path = os.path.join(root, file)
                    with open(path, "r", encoding="utf-8") as f:
                        for line_no, line in enumerate(f, 1):
                            if "kawad-swad-sales-backend.onrender.com" in line:
                                # Allowed only if part of the safety purge of legacy localStorage values
                                if "saved.includes" in line or "localStorage.removeItem" in line:
                                    continue
                                self.fail(f"Found obsolete target hostname on line {line_no} in {path}: {line.strip()}")

    def test_health_check_contract_definition(self):
        """Verify that main.py defines the exact required health contract fields."""
        main_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app", "main.py"))
        with open(main_path, "r", encoding="utf-8") as f:
            content = f.read()

        required_keys = [
            '"status":',
            '"service":',
            '"google_sheets_connected":',
            '"persistent_writes_enabled":',
            '"spreadsheet_id_configured":',
            '"service_account_configured":',
            '"last_connection_error":',
            '"allow_in_memory_fallback":',
            '"backend":',
            '"google_sheets":',
            '"required_sheets":',
        ]
        for key in required_keys:
            self.assertIn(key, content, f"Health contract key {key} missing from main.py")

if __name__ == "__main__":
    unittest.main()
