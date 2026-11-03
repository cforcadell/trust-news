"""Small opt-in evaluation controls for internal HTTP services."""

import os
from uuid import UUID


def evaluation_context(request):
    if request is None:
        return False, None
    from fastapi import HTTPException
    cold = request.headers.get("X-Evaluation-Cache", "WARM").upper() == "COLD"
    if cold and os.getenv("EVALUATION_ALLOW_COLD", "false").lower() != "true":
        raise HTTPException(403, "COLD evaluation requires EVALUATION_ALLOW_COLD=true in this service")
    value = request.headers.get("X-Evaluation-Run-ID")
    try:
        run_id = str(UUID(value)) if value else None
    except (ValueError, AttributeError):
        raise HTTPException(400, "X-Evaluation-Run-ID must be a UUID")
    return cold, run_id
