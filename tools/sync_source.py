"""Persistent Loop data-source sync tool for Dify using PageSift 1.5–1.6.3 (/v2/sources)."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from lib.tool_helpers import (
    build_client_from_credentials,
    format_tool_error,
    parse_bool,
    parse_json_object,
    parse_optional_int,
    parse_string_list,
)


class SyncSourceTool(Tool):
    """Manage long-lived PageSift Loop data sources (/v2/sources/*)."""

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        action = (tool_parameters.get("action") or "run").strip().lower() or "run"
        source_id = (tool_parameters.get("source_id") or "").strip()

        try:
            with build_client_from_credentials(self.runtime.credentials) as client:
                if action == "create":
                    seeds = parse_string_list(tool_parameters.get("seeds"))
                    if not seeds:
                        yield self.create_text_message(
                            "Error: 'seeds' (at least 1 HTTP/HTTPS URL) is required when action='create'."
                        )
                        return

                    payload: dict[str, Any] = {
                        "seeds": seeds,
                        "maxDepth": parse_optional_int(
                            tool_parameters.get("max_depth"), min_val=0, max_val=100, default=2
                        ),
                        "allowSubdomains": parse_bool(
                            tool_parameters.get("allow_subdomains"), default=False
                        ),
                        "allowBrowser": parse_bool(
                            tool_parameters.get("allow_browser"), default=True
                        ),
                    }
                    if source_id:
                        payload["id"] = source_id
                    name = (tool_parameters.get("name") or "").strip()
                    if name:
                        payload["name"] = name
                    inc = parse_string_list(tool_parameters.get("include_paths"))
                    if inc:
                        payload["includePaths"] = inc
                    exc = parse_string_list(tool_parameters.get("exclude_paths"))
                    if exc:
                        payload["excludePaths"] = exc
                    req_fields = parse_string_list(tool_parameters.get("required_fields"))
                    if req_fields:
                        payload["requiredFields"] = req_fields
                    extract_schema = parse_json_object(
                        tool_parameters.get("extract_schema"), "extract_schema"
                    )
                    if extract_schema is not None:
                        payload["extractSchema"] = extract_schema

                    budget: dict[str, Any] = {}
                    max_req = parse_optional_int(
                        tool_parameters.get("max_requests_per_tick"), min_val=1, max_val=1000
                    )
                    if max_req is not None:
                        budget["maxRequestsPerTick"] = max_req
                    target_items = parse_optional_int(
                        tool_parameters.get("target_items"), min_val=1
                    )
                    if target_items is not None:
                        budget["targetItems"] = target_items
                    if budget:
                        payload["budget"] = budget

                    res = client.create_source(payload)
                    src = res.get("source") or {}
                    eff_id = str(src.get("id") or source_id)
                    summary = (
                        f"### Loop Data Source Saved: `{eff_id}`\n"
                        f"- **Name:** {src.get('name') or '-'}\n"
                        f"- **Seeds:** {len(src.get('seeds') or seeds)} URL(s)\n"
                        f"- **Instance ID:** `{src.get('instanceId', '-')}`"
                    )

                elif action == "list":
                    eff_id = ""
                    res = client.list_sources()
                    sources = res.get("sources") or []
                    lines = [f"### Registered Loop Data Sources ({len(sources)})\n"]
                    for i, s in enumerate(sources, 1):
                        sid = s.get("id", "")
                        sname = s.get("name") or ""
                        s_seeds = s.get("seeds") or []
                        label = f"`{sid}` ({sname})" if sname else f"`{sid}`"
                        lines.append(f"{i}. {label} — {len(s_seeds)} seed(s)")
                    summary = "\n".join(lines)

                elif action == "get":
                    if not source_id:
                        yield self.create_text_message(
                            "Error: 'source_id' is required when action='get'."
                        )
                        return
                    eff_id = source_id
                    res = client.get_source(eff_id)
                    src = res.get("source") or {}
                    summary = (
                        f"### Loop Data Source `{eff_id}`\n"
                        f"- **Name:** {src.get('name') or '-'}\n"
                        f"- **Seeds:** {', '.join(src.get('seeds') or [])}\n"
                        f"- **Max Depth:** {src.get('maxDepth', '-')} | "
                        f"**Allow Browser:** `{src.get('allowBrowser', True)}`"
                    )

                elif action == "delete":
                    if not source_id:
                        yield self.create_text_message(
                            "Error: 'source_id' is required when action='delete'."
                        )
                        return
                    eff_id = source_id
                    res = client.delete_source(eff_id)
                    summary = f"### Loop Data Source Deleted: `{eff_id}` (`deleted={res.get('deleted', True)}`)"

                elif action == "run":
                    if not source_id:
                        yield self.create_text_message(
                            "Error: 'source_id' is required when action='run'."
                        )
                        return
                    eff_id = source_id
                    force_all = parse_bool(tool_parameters.get("force_all"), default=False)
                    max_requests = parse_optional_int(
                        tool_parameters.get("max_requests_per_tick"), min_val=1, max_val=1000
                    )
                    res = client.trigger_sync(
                        eff_id,
                        force_all=force_all,
                        max_requests=max_requests,
                    )
                    delta = res.get("delta") or {}
                    summary = (
                        f"### Loop Sync Tick Completed (`{eff_id}`)\n"
                        f"- **Tick ID:** `{delta.get('tickId', '-')}`\n"
                        f"- **Added:** {len(delta.get('added') or [])} | "
                        f"**Changed:** {len(delta.get('changed') or [])} | "
                        f"**Unchanged:** {len(delta.get('unchanged') or [])} | "
                        f"**Removed:** {len(delta.get('removed') or [])} | "
                        f"**Errors:** {len(delta.get('errors') or [])}"
                    )

                elif action == "state":
                    if not source_id:
                        yield self.create_text_message(
                            "Error: 'source_id' is required when action='state'."
                        )
                        return
                    eff_id = source_id
                    as_of = (tool_parameters.get("as_of") or "").strip() or None
                    res = client.get_source_state(eff_id, as_of=as_of)
                    state = res.get("state") or {}
                    inv = state.get("inventory") or state.get("resources") or []
                    clusters = state.get("factClusters") or []
                    conflicts = state.get("conflicts") or []
                    summary = (
                        f"### Loop Source State View (`{eff_id}`)"
                        + (f" as of `{as_of}`" if as_of else "")
                        + "\n"
                        f"- **Resources Tracked:** {len(inv)}\n"
                        f"- **Active Claims:** {state.get('activeClaimCount', state.get('activeClaims', '-'))} | "
                        f"**Unverified Claims:** {state.get('unverifiedClaimCount', state.get('unverifiedClaims', '-'))}\n"
                        f"- **Fact Clusters:** {len(clusters)}"
                        + (" (truncated)" if state.get("factClustersTruncated") else "")
                        + f" | **Conflicts:** {len(conflicts)}"
                    )

                elif action == "deltas":
                    if not source_id:
                        yield self.create_text_message(
                            "Error: 'source_id' is required when action='deltas'."
                        )
                        return
                    eff_id = source_id
                    tick_id = (tool_parameters.get("tick_id") or "").strip()
                    if tick_id:
                        res = client.get_source_delta(eff_id, tick_id)
                        delta = res.get("delta") or {}
                        summary = (
                            f"### Loop Sync Delta `{tick_id}` (`{eff_id}`)\n"
                            f"- **Added:** {len(delta.get('added') or [])} | "
                            f"**Changed:** {len(delta.get('changed') or [])} | "
                            f"**Removed:** {len(delta.get('removed') or [])}"
                        )
                    else:
                        limit = parse_optional_int(
                            tool_parameters.get("limit"), min_val=1, max_val=500, default=20
                        )
                        res = client.list_source_deltas(eff_id, limit=limit)
                        deltas = res.get("deltas") or []
                        lines = [f"### Recent Loop Sync Deltas for `{eff_id}` ({len(deltas)})\n"]
                        for i, d in enumerate(deltas[:20], 1):
                            tid = d.get("tickId", "-")
                            lines.append(
                                f"{i}. `{tid}` — +{len(d.get('added') or [])} / "
                                f"~{len(d.get('changed') or [])} / -{len(d.get('removed') or [])}"
                            )
                        summary = "\n".join(lines)
                else:
                    yield self.create_text_message(
                        f"Error: Unsupported sync action '{action}'."
                    )
                    return

            yield self.create_text_message(summary)
            yield self.create_json_message(res)
            yield self.create_variable_message("action", action)
            yield self.create_variable_message("source_id", eff_id)
            yield self.create_variable_message("result", res)

        except Exception as e:
            yield self.create_text_message(format_tool_error(e, f"loop sync ({action})"))
