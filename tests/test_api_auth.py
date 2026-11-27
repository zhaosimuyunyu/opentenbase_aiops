import os
import importlib.util
import unittest
from unittest.mock import patch


class ApiAuthenticationTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("fastapi"), "FastAPI is not installed")
    def test_api_routes_require_configured_bearer_key(self):
        from fastapi.testclient import TestClient
        from backend import app as app_module

        with patch.object(app_module.config, "AIOPS_API_KEY", "test-api-key"):
            with TestClient(app_module.app) as client:
                missing = client.get("/api/not-a-route")
                wrong = client.get(
                    "/api/not-a-route", headers={"Authorization": "Bearer wrong"}
                )
                valid = client.get(
                    "/api/not-a-route", headers={"Authorization": "Bearer test-api-key"}
                )
                metrics = client.get("/metrics")
                metrics_with_key = client.get(
                    "/metrics", headers={"Authorization": "Bearer test-api-key"}
                )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(missing.headers["www-authenticate"], "Bearer")
        self.assertEqual(valid.status_code, 404)
        self.assertEqual(metrics.status_code, 401)
        self.assertNotEqual(metrics_with_key.status_code, 401)

    def test_streamlit_api_client_attaches_key_without_mutating_caller_headers(self):
        from frontend.api_client import get

        caller_headers = {"X-Request-ID": "request-1"}
        with patch.dict(os.environ, {"AIOPS_API_KEY": "test-api-key"}), patch(
            "frontend.api_client._requests.get", return_value="response"
        ) as request:
            response = get("http://aiops-api:8000/api/status", headers=caller_headers)

        self.assertEqual(response, "response")
        self.assertEqual(caller_headers, {"X-Request-ID": "request-1"})
        self.assertEqual(
            request.call_args.kwargs["headers"],
            {"X-Request-ID": "request-1", "Authorization": "Bearer test-api-key"},
        )

    def test_readiness_exposes_authentication_state_without_the_secret(self):
        from backend.utils.readiness import build_readiness

        readiness = build_readiness(
            {"connected": True}, {"connected": True},
            security={"api_key_authentication": True},
        )

        self.assertTrue(readiness["security"]["api_key_authentication"])
        self.assertNotIn("test-api-key", str(readiness))


if __name__ == "__main__":
    unittest.main()
