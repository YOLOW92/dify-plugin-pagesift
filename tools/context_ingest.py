"""PageSift 1.6.3 persistent Context ingestion, reconciliation, delta & calibration management tool."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from lib.tool_helpers import (
    build_client_from_credentials,
    format_tool_error,
    normalize_context_documents,
    parse_bool,
    parse_json_object,
    parse_optional_int,
)


class ContextIngestTool(Tool):
    """Manage PageSift 1.6.3 Context store: ingest, sync, units, deltas_poll, deltas_ack, learn."""

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        op = (tool_parameters.get("operation") or "ingest").strip().lower() or "ingest"
        source_id = (tool_parameters.get("source_id") or "").strip()

        try:
            with build_client_from_credentials(self.runtime.credentials) as client:
                if op == "ingest":
                    documents = normalize_context_documents(
                        tool_parameters.get("documents"), "documents"
                    )
                    if not documents:
                        yield self.create_text_message(
                            "Error: 'documents' JSON is required when operation='ingest'."
                        )
                        return
                    eff_source = source_id or "default"
                    payload: dict[str, Any] = {
                        "sourceId": eff_source,
                        "documents": documents,
                        "persist": parse_bool(tool_parameters.get("persist"), default=True),
                        "matchMode": (tool_parameters.get("match_mode") or "boundedUot").strip(),
                    }
                    res = client.context_ingest(payload)
                    live_count = int(res.get("liveUnitCount") or 0)
                    delta = res.get("delta") or {}
                    summary = (
                        f"### Context Ingest Completed (`{eff_source}`)\n"
                        f"- **Persisted:** `{res.get('persisted')}`\n"
                        f"- **Live KnowledgeUnits:** {live_count}\n"
                        f"- **Delta Seq:** `{delta.get('deltaSeq', '-')}`"
                    )

                elif op == "sync":
                    if not source_id:
                        yield self.create_text_message(
                            "Error: 'source_id' is required when operation='sync'."
                        )
                        return
                    eff_source = source_id
                    payload = {
                        "sourceId": eff_source,
                        "matchMode": (tool_parameters.get("match_mode") or "boundedUot").strip(),
                    }
                    res = client.context_sync(payload)
                    vis = res.get("visibility") or {}
                    live_count = int(res.get("liveUnitCount") or 0)
                    summary = (
                        f"### Context Sync Reconciled (`{eff_source}`)\n"
                        f"- **Indexed Tick:** `{vis.get('indexedTickSeq', '-')}` / "
                        f"Store Tick `{vis.get('storeTickSeq', '-')}` (lag: `{vis.get('lagTicks', 0)}`)\n"
                        f"- **Instance Matched:** `{vis.get('instanceMatched', True)}`"
                    )

                elif op == "units":
                    if not source_id:
                        yield self.create_text_message(
                            "Error: 'source_id' is required when operation='units'."
                        )
                        return
                    eff_source = source_id
                    payload = {
                        "sourceId": eff_source,
                        "limit": parse_optional_int(
                            tool_parameters.get("limit"), min_val=1, max_val=10_000, default=100
                        )
                        or 100,
                    }
                    url_filter = (tool_parameters.get("url_filter") or "").strip()
                    if url_filter:
                        payload["url"] = url_filter
                    as_of = (tool_parameters.get("as_of") or "").strip()
                    if as_of:
                        payload["asOf"] = as_of
                    res = client.context_units(payload)
                    units = res.get("units") or []
                    live_count = int(res.get("total") or len(units))
                    lines = [f"### KnowledgeUnits for `{eff_source}` ({len(units)} of {live_count})\n"]
                    for i, u in enumerate(units[:25], 1):
                        uid = u.get("unitId", "")
                        status = u.get("status", "active")
                        loc = u.get("location") or {}
                        src = loc.get("sourceUrl", "")
                        preview = str(u.get("text") or "").strip().replace("\n", " ")[:120]
                        lines.append(f"{i}. `{uid}` [{status}] ({src}) — {preview}")
                    summary = "\n".join(lines)

                elif op == "deltas_poll":
                    if not source_id:
                        yield self.create_text_message(
                            "Error: 'source_id' is required when operation='deltas_poll'."
                        )
                        return
                    eff_source = source_id
                    payload = {
                        "sourceId": eff_source,
                        "limit": parse_optional_int(
                            tool_parameters.get("limit"), min_val=1, max_val=10_000, default=50
                        )
                        or 50,
                    }
                    consumer_id = (tool_parameters.get("consumer_id") or "").strip()
                    if consumer_id:
                        payload["consumerId"] = consumer_id
                    res = client.context_deltas_poll(payload)
                    poll = res.get("poll") or {}
                    deltas = poll.get("deltas") or []
                    live_count = len(deltas)
                    summary = (
                        f"### Context Deltas Polled (`{eff_source}`)\n"
                        f"- **Instance ID:** `{poll.get('instanceId', '-')}`\n"
                        f"- **Deltas Returned:** {len(deltas)}\n"
                        f"- **Resync Required:** `{poll.get('resyncRequired', False)}`"
                    )

                elif op == "deltas_ack":
                    eff_source = source_id
                    consumer_id = (tool_parameters.get("consumer_id") or "").strip()
                    instance_id = (tool_parameters.get("instance_id") or "").strip()
                    acked_seq = parse_optional_int(
                        tool_parameters.get("acked_delta_seq"), min_val=0
                    )
                    if not eff_source or not consumer_id or not instance_id or acked_seq is None:
                        yield self.create_text_message(
                            "Error: 'source_id', 'consumer_id', 'instance_id', and 'acked_delta_seq' "
                            "are all required for operation='deltas_ack'."
                        )
                        return
                    payload = {
                        "sourceId": eff_source,
                        "consumerId": consumer_id,
                        "instanceId": instance_id,
                        "ackedDeltaSeq": acked_seq,
                    }
                    res = client.context_deltas_ack(payload)
                    cp = res.get("checkpoint") or {}
                    live_count = int(cp.get("ackedDeltaSeq") or acked_seq)
                    summary = (
                        f"### Consumer Checkpoint Acknowledged (`{eff_source}`)\n"
                        f"- **Consumer:** `{consumer_id}`\n"
                        f"- **Committed Delta Seq:** `{live_count}`"
                    )

                elif op == "learn_status":
                    eff_source = source_id or "__learn__"
                    res = client.context_learn_status()
                    learn = res.get("learn") or {}
                    live_count = int(learn.get("sampleCount") or 0)
                    summary = (
                        f"### Context Learn Calibration Status (Read-Only)\n"
                        f"- **Enabled:** `{learn.get('enabled')}` | **Frozen:** `{learn.get('frozen')}`\n"
                        f"- **Drift Guard:** `{learn.get('driftGuard')}` | "
                        f"**Samples:** {live_count} | **Drift Fallbacks:** {learn.get('driftFallbacks', 0)}"
                    )

                elif op == "learn_update":
                    eff_source = source_id or "__learn__"
                    learn_payload = parse_json_object(
                        tool_parameters.get("learn_config"), "learn_config"
                    )
                    if not learn_payload:
                        yield self.create_text_message(
                            "Error: 'learn_config' JSON object is required for operation='learn_update'."
                        )
                        return
                    res = client.context_learn_update(learn_payload)
                    learn = res.get("learn") or {}
                    live_count = int(learn.get("sampleCount") or 0)
                    summary = (
                        f"### Context Learn State Updated\n"
                        f"- **Enabled:** `{learn.get('enabled')}` | **Frozen:** `{learn.get('frozen')}`\n"
                        f"- **Drift Triggered:** `{res.get('driftTriggered', False)}` | **Samples:** {live_count}"
                    )

                else:
                    yield self.create_text_message(
                        f"Error: Unsupported Context operation '{op}'."
                    )
                    return

            yield self.create_text_message(summary)
            yield self.create_json_message(res)
            yield self.create_variable_message("operation", op)
            yield self.create_variable_message("source_id", eff_source)
            yield self.create_variable_message("live_unit_count", live_count)
            yield self.create_variable_message("result", res)

        except Exception as e:
            yield self.create_text_message(format_tool_error(e, f"context {op}"))
