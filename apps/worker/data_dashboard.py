from __future__ import annotations

from intelligence.dashboard import DashboardInput, DashboardSummary, build_dashboard_summary


def build_worker_dashboard_summary(dashboard_input: DashboardInput) -> DashboardSummary:
    return build_dashboard_summary(dashboard_input)
