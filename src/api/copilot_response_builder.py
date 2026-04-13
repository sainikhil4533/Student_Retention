from __future__ import annotations


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(normalized)
    return ordered


def _compact_key_points(items: list[str], max_points: int = 8) -> list[str]:
    summary_prefixes = (
        "Highest ",
        "Lowest ",
        "Largest ",
        "Worst ",
        "Most improved ",
        "Most worsening ",
        "Next most pressured ",
        "Primary driver: ",
        "Next diagnostic bucket: ",
    )
    if any(item.startswith(summary_prefixes) for item in items):
        return items
    if len(items) <= max_points:
        return items
    leading_count = max(max_points - 2, 1)
    visible = items[:leading_count]
    trailing = items[-1]
    omitted_count = max(len(items) - leading_count - 1, 0)
    visible.append(f"Additional grounded details were condensed to keep this answer readable ({omitted_count} more).")
    if trailing not in visible:
        visible.append(trailing)
    return visible


def build_grounded_response(
    *,
    opening: str,
    key_points: list[str] | None = None,
    tools_used: list[dict] | None = None,
    limitations: list[str] | None = None,
    closing: str | None = None,
) -> str:
    lines: list[str] = [opening.strip()]

    normalized_key_points = _compact_key_points(
        _dedupe_preserve_order([point.strip() for point in (key_points or []) if str(point).strip()])
    )
    if normalized_key_points:
        lines.append("")
        lines.append("What I found:")
        for point in normalized_key_points:
            lines.append(f"- {point}")

    normalized_tools = _dedupe_preserve_order([
        str(item.get("summary") or "").strip()
        for item in (tools_used or [])
        if str(item.get("summary") or "").strip()
    ])
    if normalized_tools:
        lines.append("")
        lines.append("Data used:")
        for summary in normalized_tools:
            lines.append(f"- {summary}")

    normalized_limitations = _dedupe_preserve_order([item.strip() for item in (limitations or []) if str(item).strip()])
    if normalized_limitations:
        lines.append("")
        lines.append("Current limits:")
        for item in normalized_limitations:
            lines.append(f"- {item}")

    if closing and closing.strip():
        lines.append("")
        lines.append(closing.strip())

    return "\n".join(lines)
