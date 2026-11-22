"""PageSift 1.6.3 Context compilation, temporal search, and VOI Action tool."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from lib.tool_helpers import (
    build_client_from_credentials,
    collect_warnings,
    format_tool_error,
    normalize_context_documents,
    parse_bool,
    parse_optional_int,
    parse_string_list,
)

ACTION_MODES = {"verify", "research", "watch", "changes", "context"}


class ContextPackTool(Tool):
    """
    Evidence-grounded Context retrieval, token-budgeted ContextPack compilation,
    and VOI-governed Action execution via PageSift 1.6.3 (/v2/context/{pack,search,action}).
    """

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        mode = (tool_parameters.get("mode") or "pack").strip().lower() or "pack"
        query = (tool_parameters.get("query") or "").strip()
        subject_key = (tool_parameters.get("subject_key") or "").strip() or None
        source_ids = parse_string_list(tool_parameters.get("source_ids"))
        required_fields = parse_string_list(tool_parameters.get("required_fields"))

        if mode != "changes" and not query and not subject_key:
            # `watch` mode can run with explicit candidate_urls without a query
            candidate_check = parse_string_list(tool_parameters.get("candidate_urls"))
            if not (mode == "watch" and candidate_check):
                yield self.create_text_message(
                    "Error: 'query' (or 'subject_key') is required for this Context mode."
                )
                return

        try:
            documents = normalize_context_documents(tool_parameters.get("documents"), "documents")

            payload: dict[str, Any] = {}
            if query:
                payload["query"] = query
            if source_ids:
                payload["sourceIds"] = source_ids
            if documents:
                payload["documents"] = documents
            if subject_key:
                payload["subjectKey"] = subject_key
            if required_fields:
                payload["requiredFields"] = required_fields

            as_of = (tool_parameters.get("as_of") or "").strip()
            if as_of:
                payload["asOf"] = as_of
            effective_at = (tool_parameters.get("effective_at") or "").strip()
            if effective_at:
                payload["effectiveAt"] = effective_at

            payload["includeUnverified"] = parse_bool(
                tool_parameters.get("include_unverified"), default=False
            )
            payload["enableSemanticSketch"] = parse_bool(
                tool_parameters.get("enable_semantic_sketch"), default=True
            )

            # Pack & Action shared compilation options
            if mode != "search":
                budget_tokens = (
                    parse_optional_int(
                        tool_parameters.get("budget_tokens"),
                        min_val=64,
                        max_val=1_048_576,
                        default=2048,
                    )
                    or 2048
                )
                payload["budgetTokens"] = budget_tokens
                payload["selector"] = (
                    tool_parameters.get("selector") or "submodularClosure"
                ).strip()
                payload["ordering"] = (tool_parameters.get("ordering") or "edgeSalience").strip()
                payload["mustKeepConflicts"] = parse_bool(
                    tool_parameters.get("must_keep_conflicts"), default=True
                )
                payload["mustKeepTableHeaders"] = parse_bool(
                    tool_parameters.get("must_keep_table_headers"), default=True
                )
                payload["mustKeepQualifiers"] = parse_bool(
                    tool_parameters.get("must_keep_qualifiers"), default=True
                )

            with build_client_from_credentials(self.runtime.credentials) as client:
                if mode == "search":
                    res = client.context_search(payload)
                elif mode in ACTION_MODES:
                    payload["mode"] = mode
                    payload["allowNetworkAcquisition"] = parse_bool(
                        tool_parameters.get("allow_network_acquisition"), default=False
                    )
                    candidate_urls = parse_string_list(tool_parameters.get("candidate_urls"))
                    if candidate_urls:
                        payload["candidateUrls"] = candidate_urls
                    allowed_hosts = parse_string_list(tool_parameters.get("allowed_hosts"))
                    if allowed_hosts:
                        payload["allowedHosts"] = allowed_hosts
                    max_acq = parse_optional_int(
                        tool_parameters.get("max_acquisition_requests"),
                        min_val=0,
                        max_val=64,
                        default=4,
                    )
                    if max_acq is not None:
                        payload["maxAcquisitionRequests"] = max_acq
                    min_sources = parse_optional_int(
                        tool_parameters.get("min_independent_sources"),
                        min_val=1,
                        max_val=256,
                        default=1,
                    )
                    if min_sources is not None:
                        payload["minIndependentSources"] = min_sources
                    max_stale = parse_optional_int(
                        tool_parameters.get("max_staleness_ms"), min_val=0
                    )
                    if max_stale is not None:
                        payload["maxStalenessMs"] = max_stale
                    since_seq = parse_optional_int(
                        tool_parameters.get("since_delta_seq"), min_val=0
                    )
                    if since_seq is not None:
                        payload["sinceDeltaSeq"] = since_seq

                    res = client.context_action(payload)
                else:
                    res = client.context_pack(payload)

            warnings = collect_warnings(res)
            compiled_context = ""
            provenance_manifest: list[Any] = []
            stopping_reason = ""
            budget_insufficient = False

            if mode == "search":
                report = res.get("report") or {}
                hits = report.get("hits") or []
                conflicts = report.get("conflicts") or []
                lines = [
                    f"### Context Search Results: {len(hits)} hit(s)"
                    + (f", {len(conflicts)} conflict(s)" if conflicts else "")
                    + "\n"
                ]
                for i, hit in enumerate(hits[:30], 1):
                    unit = hit.get("unit") or hit
                    loc = unit.get("location") or {}
                    src = loc.get("sourceUrl") or unit.get("sourceUrl") or ""
                    score = hit.get("rankScore")
                    score_str = f" (score: {score:.3f})" if isinstance(score, (int, float)) else ""
                    text = str(unit.get("text") or hit.get("excerpt") or "").strip()
                    lines.append(f"{i}. **{src}**{score_str}\n{text}\n")
                compiled_context = "\n".join(lines)
            elif mode in ACTION_MODES:
                outcome = res.get("outcome") or {}
                stopping_reason = str(outcome.get("stoppingReason") or "")
                pack = outcome.get("pack") or {}
                compiled_context = str(pack.get("compiledContext") or "")
                provenance_manifest = list(pack.get("provenanceManifest") or [])
                budget_insufficient = bool(pack.get("budgetInsufficient", False))
                if not compiled_context:
                    # Changes mode or empty acquisition result: render concise summary
                    deltas = outcome.get("deltas") or []
                    reused = outcome.get("reusedExistingContext")
                    compiled_context = (
                        f"### Context Action (`{mode}`) Finished\n"
                        f"- **Stopping Reason:** `{stopping_reason or 'completed'}`\n"
                        f"- **Reused Existing Context:** `{reused}`\n"
                        f"- **Deltas Returned:** {len(deltas)}"
                    )
            else:
                pack = res.get("pack") or {}
                compiled_context = str(pack.get("compiledContext") or "")
                provenance_manifest = list(pack.get("provenanceManifest") or [])
                budget_insufficient = bool(pack.get("budgetInsufficient", False))

            yield self.create_text_message(compiled_context)
            yield self.create_json_message(res)
            yield self.create_variable_message("compiled_context", compiled_context)
            yield self.create_variable_message("provenance_manifest", provenance_manifest)
            yield self.create_variable_message("stopping_reason", stopping_reason)
            yield self.create_variable_message("budget_insufficient", budget_insufficient)
            yield self.create_variable_message("warnings", warnings)
            yield self.create_variable_message("result", res)

        except Exception as e:
            yield self.create_text_message(format_tool_error(e, "context compilation"))
