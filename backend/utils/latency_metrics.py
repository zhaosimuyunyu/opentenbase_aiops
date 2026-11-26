def scheduled_analysis_latency_metrics(sample):
    return [
        "# TYPE aiops_health_audit_scheduled_analysis_sample_count gauge",
        f"aiops_health_audit_scheduled_analysis_sample_count {sample['sample_count']}",
        "# TYPE aiops_health_audit_scheduled_analysis_duration_p50_ms gauge",
        f"aiops_health_audit_scheduled_analysis_duration_p50_ms {sample['p50_ms']}",
        "# TYPE aiops_health_audit_scheduled_analysis_duration_p95_ms gauge",
        f"aiops_health_audit_scheduled_analysis_duration_p95_ms {sample['p95_ms']}",
    ]
