import unittest

from backend.utils.latency_metrics import scheduled_analysis_latency_metrics

class AuditMetricsTests(unittest.TestCase):
    def test_exports_scheduled_analysis_latency_window(self):
        metrics = scheduled_analysis_latency_metrics({
                "sample_count": 20,
                "p50_ms": 22000.0,
                "p95_ms": 98000.0,
        })

        self.assertIn("aiops_health_audit_scheduled_analysis_sample_count 20", metrics)
        self.assertIn("aiops_health_audit_scheduled_analysis_duration_p50_ms 22000.0", metrics)
        self.assertIn("aiops_health_audit_scheduled_analysis_duration_p95_ms 98000.0", metrics)


if __name__ == "__main__":
    unittest.main()
