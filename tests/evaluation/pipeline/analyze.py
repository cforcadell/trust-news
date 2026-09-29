"""Offline, observation-based diagnosis of saved evaluation campaigns."""

from collections import Counter
import json
from pathlib import Path
import re
from uuid import UUID

from evaluation.core.artifacts import EvaluationError, read_json, write_json
from evaluation.pipeline.metrics import domain_matches, evaluate
from evaluation.pipeline.root_cause import diagnose


def _check(status, detail, **observations):
    return {"status": status, "detail": detail, **observations}


def _domain(source):
    return source.get("domain") or source.get("url") or ""


def _citable(source):
    return [context for context in source.get("contexts") or []
            if context.get("citation_eligible") is True and str(context.get("text") or "").strip()]


def _order_errors(campaign):
    indexed = {}
    for path in campaign.glob("*-order.json"):
        order = read_json(path)
        order_id = order.get("order_id")
        validations = order.get("validations") or {}
        if not isinstance(validations, dict):
            continue
        for assertion_id, validators in validations.items():
            if not isinstance(validators, dict):
                continue
            for validator_id, validation in validators.items():
                if not isinstance(validation, dict) or not validation.get("error"):
                    continue
                # Preserve only the HTTP status, never a provider exception body.
                match = re.search(r"\bHTTP\s+(\d{3})\b", str(validation["error"]))
                indexed[(order_id, str(assertion_id), str(validator_id))] = (
                    "HTTP_" + match.group(1) if match else "PROVIDER_ERROR")
    return indexed


def _diagnose(row, order_errors):
    metrics = row.get("metrics") or evaluate(row)
    root_cause = row.get("root_cause") or diagnose({**row, "metrics": metrics})
    expected = row.get("expected") or {}
    route = row.get("router") or {}
    retrieval = row.get("retrieval") or {}
    inputs = row.get("validator_input") or {}
    output = row.get("validator_output") or {}
    validator = row.get("validator") or {}
    bundle = inputs.get("evidences", retrieval.get("evidences", [])) or []
    if not isinstance(bundle, list):
        bundle = []
    used = output.get("evidence_used") or []
    if not isinstance(used, list):
        used = []
    findings = []
    checks = {}

    extraction = metrics.get("extraction") or row.get("extraction") or {}
    extraction_status = extraction.get("status", "NOT_EVALUATED")
    status = "PASS" if extraction_status == "EXTRACTION_PASS" else (
        "FAIL" if extraction_status == "EXTRACTION_ERROR" else "NOT_EVALUATED")
    match = extraction.get("match") or {}
    checks["extraction"] = _check(status, extraction_status, expected_text=expected.get("text"),
        generated_text=match.get("generated_text") or (row.get("assertion") or {}).get("text"),
        expected_category_ids=expected.get("category_ids") or [],
        generated_category_id=match.get("generated_category_id"), match_score=match.get("match_score"))
    if status == "FAIL":
        findings.append({"stage": "extraction", "code": "EXTRACTION_ERROR",
                         "detail": "The generated assertion or category did not match the dataset expectation."})

    sources = route.get("sources") or []
    selected = list(dict.fromkeys(_domain(source) for source in sources if isinstance(source, dict) and _domain(source)))
    acceptable = expected.get("acceptable_domains") or []
    matched = [domain for domain in selected if any(domain_matches(domain, wanted) for wanted in acceptable)]
    if route.get("status") not in {"COMPLETED", "INJECTED"}:
        route_status, detail = "NOT_EVALUATED", "No router decision was recorded for this validation."
    elif not selected:
        route_status, detail = "FAIL", "The router selected no domains."
    elif not acceptable:
        route_status, detail = "NOT_EVALUATED", "The dataset has no acceptable_domains annotation."
    elif matched:
        route_status, detail = "PASS", "At least one selected domain matches an acceptable domain."
    else:
        route_status, detail = "FAIL", "No selected domain matches an acceptable domain."
    checks["routing"] = _check(route_status, detail, selected_domains=selected,
                                acceptable_domains=acceptable, matched_domains=matched,
                                route_state=route.get("route_state"))
    if route_status == "FAIL":
        findings.append({"stage": "routing", "code": "ROUTER_NO_SOURCE" if not selected else "ROUTER_WRONG_SOURCE",
                         "detail": detail})

    source_rows = []
    citable = 0
    failed = 0
    for source in bundle:
        if not isinstance(source, dict):
            continue
        contexts = _citable(source)
        citable += len(contexts)
        fetch = source.get("fetch_status")
        failed += fetch in {"failed", "empty_text"}
        source_rows.append({"source_id": source.get("source_id"), "domain": _domain(source),
                            "url": source.get("url"), "fetch_status": fetch,
                            "citable_contexts": len(contexts)})
    references = [source.get("url") for source in expected.get("reference_sources") or []
                  if isinstance(source, dict) and source.get("url")]
    reference_matches = [source["url"] for source in source_rows if source["citable_contexts"]
                         and any(domain_matches(source["domain"], reference) for reference in references)]
    facts = expected.get("reference_facts") or []
    lexical = (metrics.get("retrieval") or {}).get("lexical_reference_coverage")
    if retrieval.get("status") != "COMPLETED":
        retrieval_status, detail = "NOT_EVALUATED", "No completed retrieval was recorded."
    elif not citable:
        retrieval_status, detail = "FAIL", "Retrieval delivered no citable contexts."
    elif references and not reference_matches:
        retrieval_status, detail = "FAIL", "No reference domain produced a citable context."
    elif failed:
        retrieval_status, detail = "PARTIAL", "Some sources failed to provide text."
    elif facts and lexical is not None and lexical < 1:
        retrieval_status, detail = "PARTIAL", "Reference fact word coverage is incomplete; this is a lexical proxy."
    elif references or facts:
        retrieval_status, detail = "PASS", "Available reference checks passed."
    else:
        retrieval_status, detail = "NOT_EVALUATED", "The dataset has no reference sources or facts to assess relevance."
    checks["retrieval"] = _check(retrieval_status, detail, sources=source_rows,
                                  citable_contexts=citable, failed_sources=failed,
                                  reference_domains_found=reference_matches,
                                  lexical_reference_coverage=lexical)
    if retrieval_status in {"FAIL", "PARTIAL"}:
        findings.append({"stage": "retrieval", "code": "NO_CITABLE_CONTEXT" if not citable else
                         "REFERENCE_SOURCE_MISSING" if references and not reference_matches else
                         "FETCH_FAILURES" if failed else "LOW_LEXICAL_COVERAGE", "detail": detail})

    handoff = metrics.get("handoff") or {}
    handoff_status = handoff.get("status", "NOT_EVALUATED")
    status = "PASS" if handoff_status == "PASS" else (
        "FAIL" if handoff_status == "HANDOFF_EVIDENCE_MISMATCH" else "NOT_EVALUATED")
    detail = ("Recorded retrieval and validator input hashes match." if status == "PASS" else
              "Recorded retrieval and validator input hashes differ." if status == "FAIL" else
              "Both boundary hashes were not recorded; delivery cannot be verified.")
    checks["handoff"] = _check(status, detail,
        retrieval_hash=inputs.get("retrieval_evidence_bundle_hash"),
        validator_input_hash=inputs.get("validator_input_evidence_bundle_hash"))
    if status == "FAIL":
        findings.append({"stage": "handoff", "code": "HANDOFF_EVIDENCE_MISMATCH", "detail": detail})

    eligible = {(source.get("source_id"), context.get("context_id"))
                for source in bundle if isinstance(source, dict)
                for context in _citable(source)}
    citations = []
    for citation in used:
        if not isinstance(citation, dict):
            continue
        key = (citation.get("source_id"), citation.get("context_id"))
        citations.append({"source_id": key[0], "context_id": key[1], "url": citation.get("url"),
                          "in_delivered_evidence": key in eligible})
    invalid = [citation for citation in citations if not citation["in_delivered_evidence"]]
    verdict = output.get("effective_verdict", output.get("resultado"))
    if not verdict:
        citation_status, detail = "NOT_EVALUATED", "The validator produced no verdict."
    elif invalid:
        citation_status, detail = "FAIL", "At least one cited context was absent or ineligible in the delivered evidence."
    elif verdict in {"TRUE", "FALSE"} and citable and not citations:
        citation_status, detail = "FAIL", "A decisive verdict cites none of the delivered contexts."
    elif citations:
        citation_status, detail = "PASS", "All cited context IDs occur in the delivered citable evidence."
    else:
        citation_status, detail = "NOT_EVALUATED", "No citations were claimed."
    checks["citations"] = _check(citation_status, detail, delivered_citable_contexts=citable,
                                  citations=citations)
    if citation_status == "FAIL":
        findings.append({"stage": "citations", "code": "INVALID_CITATION" if invalid else "NO_CITATIONS",
                         "detail": detail})

    provider_error = order_errors.get((row.get("order_id"), str(row.get("assertion_id")),
                                       str(validator.get("id"))))
    errors = row.get("errors") or []
    validation = metrics.get("validation") or {}
    if errors:
        validation_status, detail = "FAIL", "The validator execution failed."
        code = provider_error or errors[0].get("code") or "TECHNICAL_ERROR"
        findings.append({"stage": "validation", "code": code, "detail": detail})
    elif not verdict:
        validation_status, detail = "NOT_EVALUATED", "No validator verdict was recorded."
    elif verdict == expected.get("expected_verdict"):
        validation_status, detail = "PASS", "The validator verdict matches the expected verdict."
    else:
        validation_status, detail = "FAIL", "The validator verdict differs from the expected verdict."
        findings.append({"stage": "validation", "code": validation.get("status") or "WRONG_VERDICT",
                         "detail": detail})
    checks["validation"] = _check(validation_status, detail, expected=expected.get("expected_verdict"),
                                    verdict=verdict, error_stage=errors[0].get("stage") if errors else None,
                                    provider_error_code=provider_error)

    grounding = metrics.get("grounding") or {}
    grounding_status = grounding.get("status", "NOT_EVALUATED")
    status = "PASS" if grounding_status == "GROUNDING_PASS" else (
        "FAIL" if grounding_status in {"LLM_CITATION_ERROR", "GROUNDING_ERROR"} else "NOT_EVALUATED")
    checks["grounding"] = _check(status, grounding_status,
                                  claimed=grounding.get("claimed_count"),
                                  verified=grounding.get("verified_count"),
                                  rejected=grounding.get("rejected_count"))
    if status == "FAIL":
        findings.append({"stage": "grounding", "code": grounding_status,
                         "detail": "The production grounding audit rejected evidence use."})

    consensus = metrics.get("consensus") or {}
    consensus_status = consensus.get("status", "NOT_EVALUATED")
    status = "PASS" if consensus_status == "CONSENSUS_PASS" else (
        "FAIL" if consensus_status == "CONSENSUS_ERROR" else "NOT_EVALUATED")
    checks["consensus"] = _check(status, consensus_status, verdict=consensus.get("verdict"))
    if status == "FAIL":
        findings.append({"stage": "consensus", "code": "CONSENSUS_ERROR",
                         "detail": "The aggregate verdict differs from the expected verdict."})

    return {"run_id": row.get("run_id"), "dataset_id": row.get("dataset_id"),
            "case_id": row.get("case_id"), "repetition": (row.get("provenance") or {}).get("repetition"),
            "order_id": row.get("order_id"), "validator": validator,
            "execution_mode": row.get("execution_mode"),
            "root_cause": root_cause.get("code"),
            "checks": checks, "findings": findings}


def _markdown(report):
    summary = report["summary"]
    lines = ["# Campaign analysis", "", f"Campaign: `{report['campaign']}`", "",
             f"Manifest status: `{report['manifest_status']}`. Validations: **{summary['validations']}**. "
             f"Recorded execution errors: **{summary['execution_errors']}**.", "",
             "Stage status counts:", ""]
    for stage, counts in summary["stage_statuses"].items():
        lines.append(f"- {stage}: " + ", ".join(f"{status} {count}" for status, count in counts.items()))
    lines += ["", "A domain is judged only when acceptable_domains is annotated. Source relevance needs "
              "reference sources or facts. Citation checks establish identity and eligibility, not semantic support.", "",
              "## Validations", "",
              "| Case | Rep | Validator | Verdict | Extraction | Routing | Retrieval | Handoff | Citations | Grounding | Consensus |",
              "|---|---:|---|---|---|---|---|---|---|---|---|"]
    for item in report["validations"]:
        checks = item["checks"]
        values = [item["case_id"], item["repetition"], item["validator"].get("id"),
                  checks["validation"].get("verdict") or "—",
                  *(checks[stage]["status"] for stage in
                    ("extraction", "routing", "retrieval", "handoff", "citations", "grounding", "consensus"))]
        lines.append("| " + " | ".join(str(value if value is not None else "—").replace("|", "\\|") for value in values) + " |")
    for item in report["validations"]:
        checks = item["checks"]
        lines += ["", f"### {item['case_id']} · repetition {item['repetition']} · {item['validator'].get('id') or 'unknown validator'}",
                  "", f"Run: `{item['run_id']}`. Model: `{item['validator'].get('model') or 'unknown'}`. "
                  f"Root cause: `{item['root_cause'] or 'none'}`.", ""]
        for stage, check in checks.items():
            lines.append(f"- **{stage} — {check['status']}**: {check['detail']}")
        route = checks["routing"]
        lines.append("- Selected domains: " + (", ".join(route["selected_domains"]) or "none recorded"))
        lines.append("- Acceptable domains: " + (", ".join(route["acceptable_domains"]) or "not annotated"))
        sources = checks["retrieval"]["sources"]
        lines.append("- Retrieved sources: " + ("; ".join(
            f"{source['url'] or source['domain']} ({source['fetch_status'] or 'unknown'}, "
            f"{source['citable_contexts']} citable contexts)" for source in sources) or "none"))
        citations = checks["citations"]["citations"]
        lines.append("- Cited contexts: " + ("; ".join(
            f"{citation['source_id']}/{citation['context_id']} "
            f"({'delivered' if citation['in_delivered_evidence'] else 'missing'})" for citation in citations) or "none"))
        if item["findings"]:
            lines.append("- Findings: " + "; ".join(
                f"{finding['stage']} `{finding['code']}`" for finding in item["findings"]))
    return "\n".join(lines) + "\n"


def analyze_campaign(campaign: Path, output: Path | None = None) -> tuple[Path, Path]:
    campaign = Path(campaign)
    manifest = read_json(campaign / "manifest.json")
    if manifest.get("schema_version") != "evaluation-manifest-v1":
        raise EvaluationError("--analyze requires an evaluation-manifest-v1 campaign")
    run_ids = manifest.get("runs")
    if not isinstance(run_ids, list):
        raise EvaluationError("Campaign manifest has no runs list")
    order_errors = _order_errors(campaign)
    validations = []
    execution_errors = 0
    for run_id in run_ids:
        try:
            if str(UUID(str(run_id))) != run_id:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise EvaluationError(f"Invalid run ID in campaign manifest: {run_id}") from exc
        row = read_json(campaign / f"{run_id}.json")
        if row.get("run_id") != run_id or row.get("schema_version") != "evaluation-result-v1":
            raise EvaluationError(f"Run artifact identity or schema mismatch: {run_id}")
        execution_errors += bool(row.get("errors"))
        validations.append(_diagnose(row, order_errors))
    stage_counts = {}
    for stage in ("extraction", "routing", "retrieval", "handoff", "citations",
                  "validation", "grounding", "consensus"):
        stage_counts[stage] = dict(Counter(item["checks"][stage]["status"] for item in validations))
    report = {"schema_version": "evaluation-analysis-v1", "campaign": str(campaign),
              "manifest_status": manifest.get("status"),
              "summary": {"validations": len(validations), "execution_errors": execution_errors,
                          "stage_statuses": stage_counts,
                          "finding_codes": dict(Counter(finding["code"] for item in validations
                                                        for finding in item["findings"]))},
              "validations": validations}
    destination = Path(output) if output else campaign / "analysis"
    destination.mkdir(parents=True, exist_ok=False)
    json_path, markdown_path = destination / "analysis.json", destination / "analysis.md"
    write_json(json_path, report)
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, markdown_path
