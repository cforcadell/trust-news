"""Build a read-only order snapshot from a saved order and evaluation results."""

from copy import deepcopy
import json

from evaluation.core.common_metrics import (normalized_words, collect_assertions, assertion_identifier,
                                            missing_expected_numbers, match_incompatibilities)
from evaluation.pipeline.metrics import domain_matches
from evaluation.viewer_contract import validate_order_diagnostic


NEGATION = {"no", "not", "never", "nunca", "jamás", "sin", "ningún", "ninguna"}
STAGES = ("router", "evidence_search", "handoff", "llm", "citations", "consensus")

CHECK_CLASSIFICATION = {
    "EXPECTED_ASSERTION_MISSING": ("DATASET", "BENCHMARK_DEVIATION", "LOW", "METRICS_ONLY"),
    "UNMATCHED_GENERATED_ASSERTION": ("EVALUATOR", "EVALUATION_UNCERTAINTY", "LOW", "METRICS_ONLY"),
    "NUMBER_OR_DATE_MISSING": ("GENERATION", "QUALITY_DEGRADATION", "MEDIUM", "METRICS_ONLY"),
    "NEGATION_MISSING": ("GENERATION", "QUALITY_DEGRADATION", "HIGH", "METRICS_ONLY"),
    "CATEGORY_MISMATCH": ("DATASET", "BENCHMARK_DEVIATION", "LOW", "METRICS_ONLY"),
    "EXPECTED_TOPIC_CODE_MISMATCH": ("DATASET", "BENCHMARK_DEVIATION", "LOW", "METRICS_ONLY"),
    "EXPECTED_EVIDENCE_KIND_MISMATCH": ("DATASET", "POLICY_CONSTRAINT", "LOW", "METRICS_ONLY"),
    "ROUTER_EXPECTED_DOMAIN_MISSING": ("DATASET", "POLICY_CONSTRAINT", "LOW", "METRICS_ONLY"),
    "GOLD_MATCH_INCOMPATIBLE": ("EVALUATOR", "EVALUATION_UNCERTAINTY", "HIGH", "METRICS_ONLY"),
    "SOME_SOURCES_UNUSABLE": ("RETRIEVAL", "QUALITY_DEGRADATION", "LOW", "NO_VERDICT_IMPACT"),
    "RETRIEVAL_CAUSED_ABSTENTION": ("RETRIEVAL", "FUNCTIONAL_FAILURE", "HIGH", "CAUSED_ABSTENTION"),
    "ABSTENTION_DUE_TO_INSUFFICIENT_EVIDENCE": ("VALIDATOR", "QUALITY_DEGRADATION", "INFO", "CAUSED_ABSTENTION"),
    "NO_CITABLE_EVIDENCE": ("RETRIEVAL", "FUNCTIONAL_FAILURE", "HIGH", "BLOCKED_EXECUTION"),
    "ROUTER_NO_SOURCE": ("ROUTER", "FUNCTIONAL_FAILURE", "HIGH", "BLOCKED_EXECUTION"),
    "TECHNICAL_ERROR": ("EXECUTION", "TECHNICAL_FAILURE", "CRITICAL", "BLOCKED_EXECUTION"),
    "HANDOFF_EVIDENCE_MISMATCH": ("EXECUTION", "TECHNICAL_FAILURE", "CRITICAL", "CHANGED_VERDICT"),
    "WRONG_VERDICT": ("VALIDATOR", "FUNCTIONAL_FAILURE", "HIGH", "CHANGED_VERDICT"),
    "VERDICT_EVIDENCE_CONTRADICTION": ("VALIDATOR", "FUNCTIONAL_FAILURE", "HIGH", "CHANGED_VERDICT"),
    "CONSENSUS_ERROR": ("CONSENSUS", "FUNCTIONAL_FAILURE", "HIGH", "CHANGED_VERDICT"),
    "GENERATION_ERROR": ("GENERATION", "FUNCTIONAL_FAILURE", "HIGH", "BLOCKED_EXECUTION"),
    "INVALID_CITATION_ID": ("VALIDATOR", "FUNCTIONAL_FAILURE", "HIGH", "CHANGED_VERDICT"),
    "CITATION_REJECTED": ("VALIDATOR", "FUNCTIONAL_FAILURE", "HIGH", "CHANGED_VERDICT"),
    "JURISDICTION_MISMATCH": ("DATASET", "BENCHMARK_DEVIATION", "LOW", "METRICS_ONLY"),
    "UNSCORED_VALIDATION": ("EVALUATOR", "EVALUATION_UNCERTAINTY", "INFO", "METRICS_ONLY"),
}


def _check(code, status, detail, *refs, issue_type=None, origin=None, nature=None,
           severity=None, impact=None, root_cause_id=None, recommended_action=None):
    """Build an operator-facing check with a severity independent of its result."""
    value = {"code": code, "status": status, "detail": detail}
    if issue_type is None and status in {"FAIL", "PARTIAL"}:
        issue_type = "error" if status == "FAIL" else "warning"
    if issue_type:
        value["type"] = issue_type
    fallback = (("DATASET", "BENCHMARK_DEVIATION", "LOW", "METRICS_ONLY")
                if code.startswith("CONTEXT_") else
                ("EXECUTION", "FUNCTIONAL_FAILURE", "HIGH" if issue_type == "error" else "MEDIUM", "UNKNOWN"))
    default_origin, default_nature, default_severity, default_impact = CHECK_CLASSIFICATION.get(code, fallback)
    value.update({"origin": origin or default_origin, "nature": nature or default_nature,
                  "severity": severity or default_severity, "impact": impact or default_impact})
    if root_cause_id:
        value["root_cause_id"] = root_cause_id
    if recommended_action:
        value["recommended_action"] = recommended_action
    if refs:
        value["observation_refs"] = list(refs)
    return value


def _stage(execution_status, assessment, observations=None, checks=None, missing_reason=None):
    value = {"execution_status": execution_status, "assessment": assessment,
             "observations": observations or {}, "checks": checks or []}
    if assessment in {"NOT_EVALUATED", "SKIPPED"}:
        value["missing_reason"] = missing_reason or "No hay datos suficientes para evaluar esta etapa."
    return value


def _router_misalignment_detail(expected_domains, sources):
    """Describe an expected-domain miss without presenting it as a technical failure."""
    expected = ", ".join(expected_domains) or "ningún dominio anotado"
    selected = []
    for source in sources or []:
        if not isinstance(source, dict) or not source.get("domain"):
            continue
        label = str(source["domain"])
        source_type = source.get("source_type")
        authority = source.get("authority_level")
        if source_type or authority:
            label += f" ({source_type or '—'} / {authority or '—'})"
        selected.append(label)
    return (
        f"Desalineamiento de dominio: se esperaba {expected}; Router seleccionó "
        f"{', '.join(selected) or 'dominios no identificados'}. Ninguno coincide con el dominio "
        "anotado, pero Router sí devolvió fuentes elegibles; se registra como aviso de evaluación."
    )


def _retrieval_detail(bundle, citable):
    """Explain why retrieval did or did not produce usable evidence."""
    if not bundle:
        return "Evidence Search terminó sin fuentes: el proveedor no devolvió candidatos, por lo que no pudo generarse texto citable."
    outcomes = []
    for source in bundle:
        if not isinstance(source, dict):
            continue
        name = source.get("domain") or source.get("url") or source.get("source_id") or "fuente desconocida"
        status = source.get("fetch_status") or "estado de descarga no registrado"
        error = source.get("fetch_error")
        contexts = len(source.get("contexts") or [])
        outcome = f"{name}: {status}, {contexts} contextos"
        if source.get("url_normalized") and source.get("fetched_url"):
            outcome += f", URL normalizada a {source['fetched_url']}"
        if error:
            outcome += f", causa {error}"
        outcomes.append(outcome)
    prefix = ("No se obtuvo ningún contexto citable" if not citable else
              f"Se obtuvieron {citable} contextos citables, pero algunas fuentes fallaron")
    return f"{prefix}. Resultado por fuente: {'; '.join(outcomes) or 'sin detalle por fuente'}."


def _technical_error_detail(errors):
    """Expose the recorded execution cause without reducing it to a generic label."""
    parts = []
    for error in errors or []:
        if not isinstance(error, dict):
            parts.append(str(error))
            continue
        fields = [f"etapa={error.get('stage') or 'desconocida'}", f"código={error.get('code') or 'desconocido'}"]
        for key in ("exception_type", "status_code", "reason"):
            if error.get(key) not in (None, ""):
                fields.append(f"{key}={error[key]}")
        parts.append(", ".join(fields))
    return "La validación no produjo una decisión por estos errores registrados: " + ("; ".join(parts) or "causa no registrada") + "."


def _similarity(expected, generated):
    wanted = normalized_words(expected)
    actual = normalized_words(generated)
    return len(wanted & actual) / len(wanted) if wanted else 0.0


def _generation_validation_detail(issues):
    parts = []
    for issue in issues or []:
        if not isinstance(issue, dict):
            continue
        assertion = issue.get("assertion_id")
        if not assertion and issue.get("assertion_index") is not None:
            assertion = f"índice {issue['assertion_index']}"
        location = issue.get("location") or "respuesta"
        scope = issue.get("jurisdiction_scope")
        fields = ", ".join(issue.get("present_jurisdiction_fields") or []) or "ningún código"
        context = f"Aserción {assertion or 'no identificada'}, campo {location}"
        if scope:
            context += f", scope={scope}, campos informados={fields}"
        parts.append(f"{context}: {issue.get('message') or issue.get('code') or 'contrato inválido'}")
    return "; ".join(parts)


def _generation(dataset, order, generated):
    expected = dataset["assertions"]
    observed = []
    for index, assertion in enumerate(generated):
        observed.append({"assertion_id": assertion_identifier(assertion, index),
                         "text": str(assertion.get("text") or assertion.get("assertion") or ""),
                         "categoryId": assertion.get("categoryId"),
                         "topic_code": assertion.get("topic_code"),
                         "evidence_kind": assertion.get("evidence_kind"),
                         "context": assertion.get("context") or {},
                         "context_confidence": assertion.get("context_confidence") or {},
                         "search_hints": assertion.get("search_hints") or {}})
    expected_rows = [{"case_id": item["id"], "text": item.get("text") or "",
                      "required_terms": item.get("required_terms") or [],
                      "category_ids": item.get("category_ids") or [],
                      "source_excerpt": item.get("source_excerpt"),
                      "expected_topic_code": item.get("expected_topic_code"),
                      "expected_evidence_kind": item.get("expected_evidence_kind"),
                      "accepted_evidence_kinds": item.get("accepted_evidence_kinds") or [],
                      "expected_context": item.get("expected_context"),
                      "approximate_values": item.get("approximate_values") or []}
                     for item in expected]
    threshold = float(dataset.get("match_threshold") or 0.5)
    candidates = []
    for ei, item in enumerate(expected):
        reference = " ".join(item.get("required_terms") or []) or item.get("text") or ""
        for gi, actual in enumerate(observed):
            score = _similarity(reference, actual["text"])
            reasons = match_incompatibilities(item, actual["text"])
            candidates.append((score, ei, gi, reasons))
    used_expected, used_generated = set(), set()
    matches = []
    for score, ei, gi, reasons in sorted(candidates, key=lambda row: (bool(row[3]), -row[0], row[1], row[2])):
        if reasons or score < threshold or ei in used_expected or gi in used_generated:
            continue
        used_expected.add(ei)
        used_generated.add(gi)
        matches.append({"case_id": expected[ei]["id"], "assertion_id": observed[gi]["assertion_id"],
                        "score": round(score, 6), "method": "required_terms_coverage" if expected[ei].get("required_terms") else "word_coverage",
                        "status": "INCOMPATIBLE" if reasons else "HEURISTIC_MATCH",
                        "incompatibility_reasons": reasons})
    checks = []
    for ei, item in enumerate(expected):
        if ei not in used_expected:
            incompatible = next((row for row in sorted(
                candidates, key=lambda candidate: -candidate[0])
                if row[1] == ei and row[0] >= threshold and row[3] and row[2] not in used_generated), None)
            if incompatible:
                score, _, gi, reasons = incompatible
                actual = observed[gi]
                ref = f"/order/generation/observations/generated_assertions/{gi}"
                matches.append({"case_id": item["id"], "assertion_id": actual["assertion_id"],
                                "score": round(score, 6), "method": "required_terms_coverage",
                                "status": "INCOMPATIBLE", "incompatibility_reasons": reasons})
                checks.append(_check(
                    "GOLD_MATCH_INCOMPATIBLE", "PARTIAL",
                    f"El caso {item['id']} y la afirmación generada comparten vocabulario, pero no son "
                    f"semánticamente puntuables: {', '.join(reasons)}. "
                    f"Esperado: {item.get('text') or '—'}; generado: {actual['text'] or '—'}. "
                    "No se heredará el veredicto gold.", ref, issue_type="warning",
                    root_cause_id=f"gold-match:{item['id']}",
                    recommended_action="Revisar el caso gold o el emparejamiento antes de puntuar validadores."
                ))
                continue
            best = max((score for score, expected_index, _, _ in candidates if expected_index == ei), default=0.0)
            checks.append(_check("EXPECTED_ASSERTION_MISSING", "FAIL",
                                 f"No se emparejó el caso {item['id']}: la mejor cobertura léxica fue {best:.3f}, "
                                 f"por debajo del umbral {threshold:.3f}. Texto esperado: {item.get('text') or '—'}.",
                                 f"/order/generation/observations/expected_assertions/{ei}", issue_type="warning"))
            continue
        match = next(m for m in matches if m["case_id"] == item["id"])
        gi = next(i for i, a in enumerate(observed) if a["assertion_id"] == match["assertion_id"])
        actual = observed[gi]
        ref = f"/order/generation/observations/generated_assertions/{gi}"
        lost_numbers = missing_expected_numbers(item, actual["text"])
        if lost_numbers:
            checks.append(_check("NUMBER_OR_DATE_MISSING", "PARTIAL",
                                 f"La afirmación generada omitió {', '.join(lost_numbers)} presentes en el texto esperado. "
                                 f"Esperado: {item.get('text') or '—'}; generado: {actual['text'] or '—'}.", ref,
                                 issue_type="warning"))
        wanted_negation = normalized_words(item.get("text") or "") & NEGATION
        if wanted_negation and not (normalized_words(actual["text"]) & NEGATION):
            checks.append(_check("NEGATION_MISSING", "PARTIAL",
                                 f"El texto esperado contiene la negación {', '.join(sorted(wanted_negation))}, "
                                 f"pero la afirmación generada no conserva ninguna negación: {actual['text'] or '—'}.", ref,
                                 issue_type="warning"))
        category_ids = item.get("category_ids") or []
        if category_ids and actual["categoryId"] is not None and int(actual["categoryId"]) not in category_ids:
            checks.append(_check("CATEGORY_MISMATCH", "FAIL",
                                 f"Desalineamiento de categoría: se esperaba una de {category_ids} y Generate Assertions "
                                 f"asignó {actual['categoryId']!r}.", ref,
                                 issue_type="warning"))
        for field, actual_field in (("expected_topic_code", "topic_code"),):
            if item.get(field) and item[field] != actual[actual_field]:
                checks.append(_check(field.upper() + "_MISMATCH", "FAIL",
                                     f"Desalineamiento de {actual_field}: se esperaba {item[field]!r} y Generate Assertions "
                                     f"produjo {actual[actual_field]!r}.", ref, issue_type="warning"))
        accepted_kinds = set(item.get("accepted_evidence_kinds") or [])
        if item.get("expected_evidence_kind"):
            accepted_kinds.add(item["expected_evidence_kind"])
        if accepted_kinds and actual["evidence_kind"] not in accepted_kinds:
            checks.append(_check("EXPECTED_EVIDENCE_KIND_MISMATCH", "FAIL",
                                 f"Desalineamiento de evidence_kind: se aceptaba {sorted(accepted_kinds)!r} y "
                                 f"Generate Assertions produjo {actual['evidence_kind']!r}.", ref,
                                 issue_type="warning"))
        expected_context = item.get("expected_context") or {}
        for field in ("entities", "locations", "temporal_context"):
            wanted = expected_context.get(field) or []
            key = "value" if field == "temporal_context" else "name"
            actual_values = {str(value.get(key) or "").casefold() for value in actual["context"].get(field) or []
                             if isinstance(value, dict)}
            missing = [value for value in wanted if value.casefold() not in actual_values]
            if missing:
                checks.append(_check("CONTEXT_" + field.upper() + "_MISSING", "PARTIAL",
                                     f"Falta contexto {field}: se esperaba {', '.join(missing)}; valores generados: "
                                     f"{', '.join(sorted(actual_values)) or 'ninguno'}.", ref,
                                     issue_type="warning"))
        jurisdiction = expected_context.get("jurisdiction") or {}
        actual_jurisdiction = actual["context"].get("jurisdiction") or {}
        if any(actual_jurisdiction.get(key) != value for key, value in jurisdiction.items()):
            checks.append(_check("JURISDICTION_MISMATCH", "PARTIAL",
                                 f"Desalineamiento de jurisdicción: se esperaba {json.dumps(jurisdiction, ensure_ascii=False)} "
                                 f"y se generó {json.dumps(actual_jurisdiction, ensure_ascii=False)}.", ref,
                                 issue_type="warning"))
    for gi, item in enumerate(observed):
        if gi not in used_generated:
            checks.append(_check("UNMATCHED_GENERATED_ASSERTION", "PARTIAL",
                                 f"La afirmación generada {item['assertion_id']} no alcanzó el umbral {threshold:.3f} para "
                                 f"ningún caso esperado. Texto generado: {item['text'] or '—'}.",
                                 f"/order/generation/observations/generated_assertions/{gi}", issue_type="warning"))
    document = order.get("document") or {}
    generator = document.get("generator") or {}
    trace = order.get("generation_evaluation_trace") or {}
    observations = {"provider": trace.get("provider") or generator.get("provider"),
                    "model": trace.get("model") or generator.get("model"),
                    "config_version": trace.get("config_version", generator.get("config_version")),
                    "temperature": trace.get("temperature"),
                    "structured_attempts": trace.get("structured_attempts"),
                    "usage": deepcopy(trace.get("usage") or []),
                    "repair_used": trace.get("repair_used"),
                    "duration_seconds": trace.get("duration_seconds"),
                    "error_type": trace.get("error_type"),
                    "validation_issues": trace.get("validation_issues") or [],
                    "expected_assertions": expected_rows, "generated_assertions": observed,
                    "matches": matches}
    if not generated and order.get("assertions_error"):
        validation_detail = _generation_validation_detail(trace.get("validation_issues"))
        cause = validation_detail or order.get("assertions_error") or trace.get("error_type")
        checks.append(_check("GENERATION_ERROR", "FAIL",
                             f"Generate Assertions no produjo afirmaciones. Causa registrada: {cause}.", issue_type="error"))
    if generator.get("service") == "news-handler":
        return _stage("SKIPPED", "SKIPPED", observations, checks,
                      "La orden recibió afirmaciones pre-generadas; Generate Assertions no se ejecutó.")
    if not generated and not order.get("assertions_error"):
        return _stage("NOT_RECORDED", "NOT_EVALUATED", observations, checks,
                      "No se registraron afirmaciones ni un error de generación.")
    # Dataset comparison findings are useful quality signals, but they do not
    # prove that the execution pipeline itself has broken.
    assessment = "FAIL" if any(c.get("type") == "error" and c["status"] == "FAIL" for c in checks) else (
        "PARTIAL" if any(c["status"] in {"FAIL", "PARTIAL"} for c in checks) else "PASS")
    return _stage("FAILED" if order.get("assertions_error") else "COMPLETED", assessment, observations, checks)


def _validation_stages(row):
    metrics = row.get("metrics") or {}
    router = row.get("router") or {}
    retrieval = row.get("retrieval") or {}
    output = row.get("validator_output") or {}
    inputs = row.get("validator_input") or {}
    expected = row.get("expected") or {}
    errors = row.get("errors") or []
    validator = row.get("validator") or {}
    scoring_eligible = row.get("provenance", {}).get("scoring_eligible", True)
    verdict = output.get("effective_verdict", output.get("resultado"))
    evidence_strategy = validator.get("evidence_search_strategy")
    route_metric = (metrics.get("routing") or {}).get("status")
    route_obs = deepcopy(router)
    route_obs["evidence_search_strategy"] = evidence_strategy
    acceptable = expected.get("acceptable_domains") or []
    route_obs["acceptable_domains"] = acceptable
    route_obs["matching_domains"] = [source.get("domain") for source in router.get("sources") or []
                                     if isinstance(source, dict) and any(
                                         domain_matches(source.get("domain") or "", wanted) for wanted in acceptable)]
    route_obs["expected_domain_matches"] = [
        {"domain": wanted,
         "matching_selected_domains": [source.get("domain") for source in router.get("sources") or []
                                         if isinstance(source, dict) and
                                         domain_matches(source.get("domain") or "", wanted)]}
        for wanted in acceptable]
    if router.get("status") in {"COMPLETED", "INJECTED"}:
        route_status = route_metric if route_metric in {"PASS", "FAIL"} else "NOT_EVALUATED"
        route_checks = []
        if route_status == "FAIL":
            if not (router.get("sources") or []):
                route_checks.append(_check("ROUTER_NO_SOURCE", "FAIL",
                                           f"Router terminó con estado {router.get('route_state') or router.get('status') or 'desconocido'}, "
                                           f"pero no entregó dominios elegibles. Diagnóstico: "
                                           f"{router.get('diagnostic_code') or (router.get('diagnostics') or {}).get('reason') or 'causa no registrada'}.",
                                           issue_type="error"))
            else:
                route_checks.append(_check("ROUTER_EXPECTED_DOMAIN_MISSING", "FAIL",
                                           _router_misalignment_detail(acceptable, router.get("sources") or []),
                                           issue_type="warning"))
        route_assessment = "PARTIAL" if route_checks and route_checks[0].get("type") == "warning" else route_status
        route = _stage("COMPLETED", route_assessment, route_obs, route_checks,
                       missing_reason="No hay dominios aceptables anotados o la ruta fue inyectada.")
    elif router.get("status") == "SKIPPED" or (evidence_strategy and evidence_strategy != "LOCAL"):
        route_obs["skip_reason"] = "EXTERNAL_EVIDENCE_STRATEGY" if evidence_strategy != "LOCAL" else "EVALUATION_MODE"
        reason = (f"La estrategia {evidence_strategy} obtiene evidencia sin usar Source Router."
                  if evidence_strategy and evidence_strategy != "LOCAL" else
                  "El modo de evaluación omitió Router.")
        route = _stage("SKIPPED", "SKIPPED", route_obs, missing_reason=reason)
    else:
        route = _stage("NOT_RECORDED", "NOT_EVALUATED", route_obs, missing_reason="No se guardó decisión del Router.")
    bundle = retrieval.get("evidences") or []
    fetch_failures = sum(s.get("fetch_status") in {"failed", "empty_text"} for s in bundle)
    citable = sum(c.get("citation_eligible") is True for s in bundle for c in s.get("contexts") or [])
    if retrieval.get("search_skipped") == "no_eligible_local_sources":
        evidence = _stage("SKIPPED", "SKIPPED", deepcopy(retrieval),
                          [_check("ROUTER_NO_SOURCE", "SKIPPED",
                                  "No se llamó a Evidence Search porque Router no entregó dominios elegibles.")],
                          missing_reason="Router no entregó dominios elegibles; Evidence Search no se ejecutó.")
    elif retrieval.get("status") == "COMPLETED":
        evidence_status = "FAIL" if not citable else "PARTIAL" if fetch_failures else "PASS"
        evidence_obs = deepcopy(retrieval)
        evidence_obs["reference_evidence"] = deepcopy(expected.get("reference_evidence") or [])
        evidence_obs["reference_sources"] = deepcopy(expected.get("reference_sources") or [])
        evidence_checks = []
        if not citable:
            evidence_checks.append(_check("NO_CITABLE_EVIDENCE", "FAIL",
                                          _retrieval_detail(bundle, citable), issue_type="error"))
        elif fetch_failures:
            decisive_expected = expected.get("expected_verdict") in {"TRUE", "FALSE"}
            caused_abstention = verdict == "UNKNOWN" and decisive_expected and scoring_eligible
            code = "RETRIEVAL_CAUSED_ABSTENTION" if caused_abstention else "SOME_SOURCES_UNUSABLE"
            if caused_abstention:
                evidence_status = "FAIL"
            evidence_checks.append(_check(
                code, "FAIL" if caused_abstention else "PARTIAL", _retrieval_detail(bundle, citable),
                issue_type="error" if caused_abstention else "warning",
                root_cause_id=(f"retrieval-abstention:{row.get('assertion_id')}:{validator.get('id')}"
                               if caused_abstention else None),
                recommended_action=("Ampliar el fallback manteniendo la misma clase de autoridad y revisar las fuentes "
                                    "que devolvieron 403, 404 o texto vacío."
                                    if caused_abstention else None)
            ))
        evidence = _stage("COMPLETED", evidence_status, evidence_obs, evidence_checks)
    elif retrieval.get("status") in {"INJECTED", "SKIPPED"}:
        evidence = _stage("SKIPPED", "SKIPPED", deepcopy(retrieval), missing_reason="La evidencia se inyectó o se omitió la búsqueda.")
    else:
        evidence = _stage("NOT_RECORDED", "NOT_EVALUATED", deepcopy(retrieval), missing_reason="No se guardó respuesta de Evidence Search.")
    hash_version = "v2" if inputs.get("retrieval_evidence_bundle_hash_v2") and inputs.get(
        "validator_input_evidence_bundle_hash_v2") else "v1"
    suffix = "_v2" if hash_version == "v2" else ""
    retrieved_hash = inputs.get("retrieval_evidence_bundle_hash" + suffix)
    delivered_hash = inputs.get("validator_input_evidence_bundle_hash" + suffix)
    v1_retrieved = inputs.get("retrieval_evidence_bundle_hash")
    v1_delivered = inputs.get("validator_input_evidence_bundle_hash")
    handoff_obs = {"retrieval_hash": retrieved_hash, "validator_input_hash": delivered_hash,
                   "hash_version": hash_version, "v1_retrieval_hash": v1_retrieved,
                   "v1_validator_input_hash": v1_delivered}
    if retrieved_hash and delivered_hash:
        good = retrieved_hash == delivered_hash and (
            not (v1_retrieved and v1_delivered) or v1_retrieved == v1_delivered
        )
        handoff = _stage("COMPLETED", "PASS" if good else "FAIL", handoff_obs,
                         [_check("BUNDLE_HASH_MATCH" if good else "HANDOFF_EVIDENCE_MISMATCH",
                                 "PASS" if good else "FAIL",
                                 ("La evidencia entregada al validador coincide con la recuperada: "
                                  f"hash={retrieved_hash}." if good else
                                  "La evidencia cambió entre recuperación y validación: "
                                  f"hash recuperado={retrieved_hash}; hash entregado={delivered_hash}."))])
    else:
        handoff = _stage("NOT_RECORDED", "NOT_EVALUATED", handoff_obs,
                         missing_reason="Faltan hashes de uno o ambos límites de entrega.")
    audit = deepcopy((row.get("grounding") or {}).get("validation") or {})
    llm_obs = {"provider": row.get("validator", {}).get("provider"),
               "model": output.get("resolved_model") or row.get("validator", {}).get("model"),
               "config_version": row.get("validator", {}).get("config_version"),
               "temperature": row.get("validator", {}).get("temperature"),
               "original_verdict": output.get("resultado") or audit.get("original_verdict"),
               "effective_verdict": verdict,
               "expected_verdict": expected.get("expected_verdict"), "errors": deepcopy(errors),
               "validation_seconds": row.get("timings", {}).get("validation_seconds"),
               "grounding": audit, "prompt_hash": inputs.get("prompt_hash"),
               "usage": deepcopy(output.get("usage"))}
    if errors:
        llm = _stage("FAILED", "FAIL", llm_obs,
                     [_check("TECHNICAL_ERROR", "FAIL", _technical_error_detail(errors))])
    elif audit.get("basis") == "ROUTER_NO_SOURCE":
        llm = _stage("SKIPPED", "NOT_EVALUATED", llm_obs,
                     [_check("ROUTER_NO_SOURCE", "NOT_EVALUATED",
                             "No se llamó al LLM porque Router no entregó dominios elegibles.")])
    elif audit.get("basis") == "NO_CITABLE_EVIDENCE":
        llm = _stage("SKIPPED", "NOT_EVALUATED", llm_obs,
                     [_check("NO_CITABLE_EVIDENCE", "NOT_EVALUATED",
                             "No se llamó al LLM porque no había contextos citables.")])
    elif not verdict:
        llm = _stage("NOT_RECORDED", "NOT_EVALUATED", llm_obs, missing_reason="No hay veredicto guardado.")
    elif not scoring_eligible:
        llm = _stage("COMPLETED", "NOT_EVALUATED", llm_obs,
                     [_check("UNSCORED_VALIDATION", "NOT_EVALUATED",
                             "La validación pertenece a una afirmación generada sin caso gold emparejado; "
                             "se muestra para diagnóstico, pero no se puntúa.")],
                     missing_reason="No existe un veredicto gold aplicable a esta afirmación generada.")
    elif verdict == "UNKNOWN" and any(
            check.get("code") == "RETRIEVAL_CAUSED_ABSTENTION" for check in evidence.get("checks", [])):
        llm = _stage(
            "COMPLETED", "NOT_EVALUATED", llm_obs,
            [_check("ABSTENTION_DUE_TO_INSUFFICIENT_EVIDENCE", "NOT_EVALUATED",
                    "El validador se abstuvo con evidencia insuficiente. La causa se atribuye a Retrieval y no "
                    "se contabiliza como un veredicto LLM incorrecto.", issue_type="warning")],
            missing_reason="Evidence Search no entregó evidencia suficiente para exigir una decisión."
        )
    else:
        correct = verdict == expected.get("expected_verdict")
        contradiction = (metrics.get("evidence_coherence") or {}).get("status") == "VERDICT_EVIDENCE_CONTRADICTION"
        if correct:
            verdict_detail = f"El veredicto efectivo {verdict!r} coincide con el esperado."
        elif contradiction:
            verdict_detail = ("La evidencia citable contiene un valor equivalente al de la afirmación, pero el "
                              f"validador produjo {verdict!r}; veredicto original={llm_obs['original_verdict']!r}.")
        else:
            verdict_detail = (f"Decisión incorrecta: se esperaba {expected.get('expected_verdict')!r}, pero el "
                              f"validador produjo {verdict!r}; veredicto original={llm_obs['original_verdict']!r}.")
        llm = _stage("COMPLETED", "PASS" if correct else "FAIL", llm_obs,
                     [_check("VERDICT_MATCH" if correct else
                             "VERDICT_EVIDENCE_CONTRADICTION" if contradiction else "WRONG_VERDICT",
                             "PASS" if correct else "FAIL", verdict_detail)])
    delivered = inputs.get("evidences") if isinstance(inputs.get("evidences"), list) else bundle
    contexts = [{"source_id": source.get("source_id"), "url": source.get("url"),
                 "relationship_to_origin": source.get("relationship_to_origin"),
                 "document_provenance": deepcopy(source.get("document_provenance")),
                 "context_id": context.get("context_id"), "text": context.get("text"),
                 "citation_eligible": context.get("citation_eligible"),
                 "origin": context.get("origin"),
                 "document_sha256": context.get("document_sha256"),
                 "selected_chunk_id": context.get("selected_chunk_id")}
                for source in delivered if isinstance(source, dict)
                for context in source.get("contexts") or [] if isinstance(context, dict)]
    by_pair = {(item["source_id"], item["context_id"]): item for item in contexts}
    sources = {item["source_id"] for item in contexts}
    citation_trace = output.get("evaluation_citation_trace") or {}
    raw_claims = citation_trace.get("claims") if isinstance(citation_trace.get("claims"), list) else (
        audit.get("claimed_evidence") or output.get("evidence_used") or [])
    citations_obs = []
    for index, claim in enumerate(raw_claims):
        if not isinstance(claim, dict):
            citations_obs.append({"index": index, "valid_identity": False, "reason": "INVALID_EVIDENCE_ITEM"})
            continue
        source_id, context_id = claim.get("source_id"), claim.get("context_id")
        resolved = by_pair.get((source_id, context_id))
        reason = ("SOURCE_ID_NOT_DELIVERED" if source_id not in sources else
                  "CONTEXT_ID_NOT_DELIVERED" if resolved is None else
                  "CONTEXT_NOT_CITABLE" if not resolved.get("citation_eligible") or not resolved.get("text") else
                  "VALID_IDENTITY")
        citations_obs.append({"index": index, "source_id": source_id, "context_id": context_id,
                              "valid_identity": reason == "VALID_IDENTITY", "reason": reason,
                              "supports": claim.get("supports"), "context": deepcopy(resolved) if resolved else None})
    issues = audit.get("issues") or []
    rejected = audit.get("rejected_count") or 0
    citation_obs = {"contexts": contexts, "citations": citations_obs,
                    "audit_issues": deepcopy(issues), "claimed_count": audit.get("claimed_count"),
                    "verified_count": audit.get("verified_count"), "rejected_count": rejected}
    invalid = [item for item in citations_obs if not item["valid_identity"]]
    if not verdict:
        citations = _stage("NOT_RECORDED", "NOT_EVALUATED", citation_obs,
                           missing_reason="No hay respuesta del validador.")
    elif invalid or rejected:
        invalid_detail = "; ".join(
            f"{item.get('source_id') or 'sin source_id'}/{item.get('context_id') or 'sin context_id'}: {item['reason']}"
            for item in invalid
        )
        audit_detail = ", ".join(str(item.get("code") or item) for item in issues)
        citations = _stage("COMPLETED", "FAIL", citation_obs,
                           [_check("INVALID_CITATION_ID" if invalid else "CITATION_REJECTED", "FAIL",
                                   f"La auditoría rechazó {len(invalid) or rejected} citas porque no pudo vincularlas "
                                   f"a contexto citable. Detalle: {invalid_detail or audit_detail or 'motivo no registrado'}.")])
    elif not citations_obs:
        citations = _stage("COMPLETED", "NOT_EVALUATED", citation_obs,
                           missing_reason="El validador no declaró citas verificables.")
    else:
        citations = _stage("COMPLETED", "PASS", citation_obs,
                           [_check("CITATION_ID_VALID", "PASS", "IDs de citas presentes y citables; apoyo semántico no evaluado.")])
    aggregate = row.get("consensus") or {}
    consensus_obs = {key: deepcopy(aggregate[key]) for key in
                     ("status", "verdict", "decision_status", "reason_code", "distribution", "counts",
                      "consensus_policy", "consensus_policy_version", "scores", "winner",
                      "validations_count", "responses_count", "errors_count", "excluded_validators")
                     if key in aggregate}
    consensus_obs["expected_verdict"] = expected.get("expected_verdict")
    consensus_obs["votes"] = [{"validator_id": item.get("validator"), "verdict": item.get("result"),
                                "weight": item.get("effective_weight"), "validator_type": item.get("validator_type"),
                                "error": item.get("error") or item.get("error_details"),
                                "audit_status": (item.get("evidence_validation") or {}).get("status")}
                               for item in aggregate.get("details") or [] if isinstance(item, dict)]
    if not scoring_eligible:
        consensus = _stage("COMPLETED" if aggregate.get("status") == "COMPLETED" else "NOT_RECORDED",
                           "NOT_EVALUATED", consensus_obs,
                           missing_reason="La afirmación no tiene caso gold emparejado; el consenso no se puntúa.")
    elif aggregate.get("status") == "COMPLETED" and aggregate.get("verdict"):
        good = aggregate["verdict"] == expected.get("expected_verdict")
        consensus = _stage("COMPLETED", "PASS" if good else "FAIL", consensus_obs,
                           [_check("CONSENSUS_MATCH" if good else "CONSENSUS_ERROR", "PASS" if good else "FAIL",
                                   (f"El consenso {aggregate['verdict']!r} coincide con el esperado. " if good else
                                    f"El consenso produjo {aggregate['verdict']!r}, pero se esperaba "
                                    f"{expected.get('expected_verdict')!r}. Motivo del agregado: "
                                    f"{aggregate.get('reason_code') or 'no registrado'}; distribución: "
                                    f"{json.dumps(aggregate.get('distribution') or {}, ensure_ascii=False)}."))])
    else:
        consensus = _stage("NOT_RECORDED", "NOT_EVALUATED", consensus_obs,
                           missing_reason="No hay consenso persistido para esta validación.")
    return {"router": route, "evidence_search": evidence, "handoff": handoff,
            "llm": llm, "citations": citations, "consensus": consensus}


def build_order_diagnostic(dataset, order, rows, *, campaign_id, repetition, parent_run_id=None,
                           order_artifact=None):
    """Create one snapshot from a saved order; no service or LLM calls."""
    order_id = str(order.get("order_id") or "")
    generated = collect_assertions(order)
    generation = _generation(dataset, order, generated)
    observed_matches = {item["assertion_id"]: item for item in generation["observations"]["matches"]}
    scorable_matches = {assertion_id: item["case_id"] for assertion_id, item in observed_matches.items()
                        if item.get("status") != "INCOMPATIBLE"}
    assertions = []
    for index, item in enumerate(generated):
        assertion_id = assertion_identifier(item, index)
        match = observed_matches.get(assertion_id)
        assertions.append({"assertion_id": assertion_id,
                           "text": str(item.get("text") or item.get("assertion") or ""),
                           "expected_case_id": scorable_matches.get(assertion_id),
                           "candidate_case_id": match.get("case_id") if match else None,
                           "match_status": match.get("status") if match else "UNMATCHED"})
    assertion_ids = {item["assertion_id"] for item in assertions}
    validations = []
    for row in rows:
        assertion_id = str(row.get("assertion_id") or "")
        validator_id = str((row.get("validator") or {}).get("id") or "")
        if assertion_id not in assertion_ids or not validator_id:
            continue
        raw_validator = row.get("validator") or {}
        validator = {key: raw_validator.get(key) for key in
                     ("validator_type", "provider", "model", "config_version",
                      "temperature", "evidence_search_strategy")}
        diagnostic_row = deepcopy(row)
        provenance = diagnostic_row.setdefault("provenance", {})
        provenance["scoring_eligible"] = bool(provenance.get("scoring_eligible", True) and
                                                assertion_id in scorable_matches)
        validations.append({"run_id": row["run_id"], "assertion_id": assertion_id,
                            "validator_id": validator_id, "validator": validator,
                            "evaluation_match": deepcopy(observed_matches.get(assertion_id)),
                            "stages": _validation_stages(diagnostic_row)})
    snapshot = {"schema_version": "order-diagnostic-v1",
                "identity": {"campaign_id": campaign_id, "dataset_id": dataset["id"],
                             "order_id": order_id, "repetition": repetition,
                             "parent_run_id": parent_run_id},
                "artifact_refs": {"order": order_artifact or f"{parent_run_id}-order.json",
                                  "results": [{"run_id": row["run_id"], "path": row["run_id"] + ".json"}
                                              for row in validations]},
                "order": {"status": str(order.get("status") or "UNKNOWN"),
                          "original_text": str(order.get("text") or dataset.get("news") or ""),
                          "generation": generation, "assertions": assertions},
                "validations": validations}
    return validate_order_diagnostic(snapshot)
