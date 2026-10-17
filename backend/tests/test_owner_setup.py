"""The public owner-setup route was removed. First-account recovery is the local script."""
import os
os.environ.setdefault("SALES_TESTING", "1")

import unittest
import app.routers.auth as auth_router


class TestOwnerSetupRemoved(unittest.TestCase):
    def test_no_public_setup_route(self):
        self.assertFalse(hasattr(auth_router, "setup_owner"))
        paths = []
        for route in getattr(auth_router.router, "routes", []):
            paths.append(getattr(route, "path", ""))
        self.assertFalse(any("setup" in path for path in paths))


if __name__ == "__main__":
    unittest.main()
