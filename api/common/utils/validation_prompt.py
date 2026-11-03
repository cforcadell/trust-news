"""Pure RAG prompt formatting, shared by production and evaluation."""

from typing import Any, Dict, List, Optional

DEFAULT_RAG_PROMPT = """Actúa como validador factual estricto.
Debes validar la aserción usando exclusivamente las evidencias y contextos proporcionados en el prompt.
Usa origin=explicit como contexto principal de la aserción. Usa origin=inferred solo cuando falte contexto explícito equivalente.
No uses el contexto inferido como evidencia factual suficiente: el veredicto debe apoyarse en evidencias recuperadas o en contradicción directa de esas evidencias.
No uses conocimiento interno salvo razonamiento lógico básico sobre el texto aportado.
No accedas a URLs externas ni supongas que una URL contiene información no incluida en los contextos.
No inventes fuentes, datos ni citas.
Si los contextos/evidencias no contienen soporte directo ni contradicción directa para la aserción, responde UNKNOWN.
Explica porque has tomado su decision de forma breve y objetiva usando URLs y fragmentos concretos.
No digas "según la fuente 1", "Fuente 1", "CONTEXTO 1", "según las evidencias" ni referencias genéricas en descripcion, reason ni evidence_text.
Si devuelves TRUE o FALSE, evidence_used debe contener al menos una referencia a un context_id proporcionado.
En descripcion menciona el dominio o título concreto usado, no su índice interno.
supports indica si la evidencia apoya la aserción: true si la confirma, false si la contradice.
Sólo puedes seleccionar context_id incluidos literalmente en el prompt. No devuelvas URL, source_id,
chunk_id ni evidence_text: el servidor reconstruye esos campos desde el contexto recuperado.
Si ninguna evidencia contiene un fragmento directo que apoye o contradiga la aserción, devuelve UNKNOWN.
Devuelve exclusivamente JSON válido:
{
  "resultado": "TRUE | FALSE | UNKNOWN",
  "descripcion": "Justificación breve basada en URLs y fragmentos concretos",
  "confidence": "HIGH | MEDIUM | LOW",
  "evidence_used": [
    {
      "context_id": "string",
      "supports": true,
      "reason": "string"
    }
  ]
}"""

def format_evidences_for_prompt(evidences: Optional[List[Dict[str, Any]]]) -> str:
    if not evidences:
        return "No hay evidencias disponibles."
    blocks = []
    for idx, source in enumerate(evidences, start=1):
        source_id = source.get("source_id") or f"source-{idx}"
        source_lines = [
            f"FUENTE {idx}",
            f"source_id: {source_id}",
            f"title: {source.get('title', '')}",
            f"url: {source.get('url', '')}",
            f"domain: {source.get('domain', '')}",
            f"source_type: {source.get('source_type', '')}",
            f"trust_score: {source.get('trust_score', '')}",
            f"why_selected: {source.get('why_selected', '')}",
        ]

        contexts = [
            context for context in source.get("contexts") or []
            if isinstance(context, dict) and context.get("citation_eligible") is True
        ]
        if not contexts:
            continue
        for context_idx, context in enumerate(contexts, start=1):
            source_lines.extend([
                f"CONTEXTO CITABLE {context_idx}",
                f"context_id: {context.get('context_id', '')}",
                f"text_sha256: {context.get('text_sha256', '')}",
                f"text: {context.get('text', '')}",
            ])
        blocks.append("\n".join(source_lines))
    return "\n\n".join(blocks) if blocks else "No hay contextos documentales citables disponibles."



def build_rag_prompt(text: str, context: Optional[str], evidences: list, template: str = DEFAULT_RAG_PROMPT) -> str:
    parts = [template]
    if context:
        parts.append(f"Contexto de la noticia:\n{context}")
    parts.append(f"Evidencias proporcionadas:\n{format_evidences_for_prompt(evidences)}")
    parts.append(f"Aserción a validar:\n{text}")
    return "\n\n".join(parts)
