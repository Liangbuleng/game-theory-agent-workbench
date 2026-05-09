"""Optional Phase 1.5 mechanism handlers."""

from __future__ import annotations

from agent.phase1.mechanisms.information_fee import (
    MECHANISM_ID as INFORMATION_FEE_ID,
    build_information_fee_summary,
    can_handle_information_fee,
    render_information_fee_report,
)


def run_mechanism_handlers(
    all_results: dict[str, object],
    manifest: dict[str, object] | None = None,
) -> dict[str, object]:
    """Run optional mechanism handlers detected from result structure."""

    summaries: dict[str, object] = {}
    if can_handle_information_fee(all_results):
        summaries[INFORMATION_FEE_ID] = build_information_fee_summary(all_results)
    return {
        "status": "available" if summaries else "not_applicable",
        "handlers": summaries,
        "manifest_title": (manifest or {}).get("title", ""),
    }


def render_mechanism_sections(
    mechanism_summaries: dict[str, object] | None,
) -> list[str]:
    """Render optional mechanism report sections."""

    if not mechanism_summaries:
        return []
    handlers = mechanism_summaries.get("handlers", {})
    if not isinstance(handlers, dict):
        return []

    lines: list[str] = []
    info_fee = handlers.get(INFORMATION_FEE_ID)
    if isinstance(info_fee, dict):
        lines.extend(render_information_fee_report(info_fee))
    return lines


__all__ = [
    "INFORMATION_FEE_ID",
    "build_information_fee_summary",
    "can_handle_information_fee",
    "render_information_fee_report",
    "render_mechanism_sections",
    "run_mechanism_handlers",
]
