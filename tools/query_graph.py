"""PageSift 1.4–1.6.3 DataGraph query tool (crawl graph, version history, conflicts, claims)."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from lib.tool_helpers import (
    build_client_from_credentials,
    format_tool_error,
    parse_optional_int,
)


class QueryGraphTool(Tool):
    """Query PageSift DataGraph endpoints (/v2/crawl/{id}/graph, /v2/graph/*)."""

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        query_type = (tool_parameters.get("query_type") or "conflicts").strip().lower()
        job_id = (tool_parameters.get("job_id") or "").strip()
        url = (tool_parameters.get("url") or "").strip()
        subject = (tool_parameters.get("subject") or "").strip() or None
        as_of = (tool_parameters.get("as_of") or "").strip() or None
        limit = parse_optional_int(tool_parameters.get("limit"), min_val=1, max_val=1000)
        offset = parse_optional_int(tool_parameters.get("offset"), min_val=0)

        try:
            with build_client_from_credentials(self.runtime.credentials) as client:
                if query_type == "crawl_graph":
                    if not job_id:
                        yield self.create_text_message(
                            "Error: 'job_id' is required when query_type='crawl_graph'."
                        )
                        return
                    res = client.get_crawl_graph(job_id)
                    stats = res.get("stats") or {}
                    total = int(stats.get("nodes") or len(res.get("nodes") or []))
                    truncated = False
                    history_unavailable = False
                    summary = (
                        f"### DataGraph Summary for Crawl `{job_id}` (status: `{res.get('status', '-')}`)\n"
                        f"- **Nodes:** {stats.get('nodes', 0)} | **Blocks:** {stats.get('blocks', 0)}\n"
                        f"- **Citations:** {stats.get('citations', 0)} | "
                        f"**Provenance Edges:** {stats.get('provenanceEdges', 0)}\n"
                        f"- **Claims:** {stats.get('claims', 0)} | "
                        f"**Fact Clusters:** {stats.get('factClusters', 0)} | "
                        f"**Conflicts:** {stats.get('conflicts', 0)}"
                    )

                elif query_type == "history":
                    if not url:
                        yield self.create_text_message(
                            "Error: 'url' is required when query_type='history'."
                        )
                        return
                    res = client.get_graph_history(url=url, as_of=as_of, limit=limit)
                    versions = res.get("versions") or []
                    edges = res.get("edges") or []
                    total = len(versions)
                    truncated = bool(res.get("truncated", False))
                    history_unavailable = False
                    lines = [
                        f"### DataGraph Version History for `{url}` ({total} version(s), {len(edges)} diff edge(s))\n"
                    ]
                    for i, v in enumerate(versions[:25], 1):
                        vid = v.get("versionId") or v.get("contentHash") or "-"
                        ts = v.get("observedAt") or v.get("observedAtMs") or "-"
                        lines.append(f"{i}. `{vid}` @ `{ts}`")
                    summary = "\n".join(lines)

                elif query_type == "conflicts":
                    res = client.get_graph_conflicts(
                        subject=subject,
                        as_of=as_of,
                        limit=limit,
                        offset=offset,
                    )
                    conflicts = res.get("conflicts") or []
                    total = int(res.get("total") or len(conflicts))
                    truncated = bool(res.get("truncated", False))
                    history_unavailable = bool(res.get("historyUnavailable", False))
                    lines = [
                        f"### DataGraph Cross-Source Conflicts: {total} record(s)"
                        + (f" for `{subject}`" if subject else "")
                        + ("\n> Note: historyUnavailable=true for requested asOf." if history_unavailable else "")
                        + "\n"
                    ]
                    for i, c in enumerate(conflicts[:25], 1):
                        subj = c.get("subjectKey") or c.get("subject") or "-"
                        field = c.get("field") or c.get("predicate") or "-"
                        vals = c.get("values") or c.get("variants") or []
                        lines.append(f"{i}. **{subj}**.`{field}` — {len(vals)} conflicting variant(s)")
                    summary = "\n".join(lines)

                elif query_type == "claims":
                    res = client.get_graph_claims(
                        url=url or None,
                        subject=subject,
                        as_of=as_of,
                        limit=limit,
                        offset=offset,
                    )
                    claims = res.get("claims") or []
                    total = int(res.get("total") or len(claims))
                    truncated = bool(res.get("truncated", False))
                    history_unavailable = bool(res.get("historyUnavailable", False))
                    lines = [
                        f"### DataGraph Claim Lifecycles: {total} record(s)"
                        + (f" as of `{as_of}`" if as_of else "")
                        + ("\n> Note: historyUnavailable=true for requested asOf." if history_unavailable else "")
                        + "\n"
                    ]
                    for i, cl in enumerate(claims[:25], 1):
                        subj = cl.get("subjectKey") or cl.get("subject") or "-"
                        field = cl.get("field") or cl.get("predicate") or "-"
                        val = cl.get("value") or cl.get("normalizedValue") or "-"
                        status = cl.get("status") or cl.get("state") or "-"
                        lines.append(f"{i}. **{subj}**.`{field}` = `{val}` (`{status}`)")
                    summary = "\n".join(lines)

                else:
                    yield self.create_text_message(
                        f"Error: Unsupported query_type '{query_type}'."
                    )
                    return

            yield self.create_text_message(summary)
            yield self.create_json_message(res)
            yield self.create_variable_message("query_type", query_type)
            yield self.create_variable_message("total", total)
            yield self.create_variable_message("truncated", truncated)
            yield self.create_variable_message("history_unavailable", history_unavailable)
            yield self.create_variable_message("result", res)

        except Exception as e:
            yield self.create_text_message(format_tool_error(e, f"graph query ({query_type})"))
