"""ForgeLab compiler-as-a-service (FastAPI).

Exposes the compiler over HTTP so AI agents can validate, import, export, and
transform ForgeLab IR. Import/export endpoints currently route to domain stubs
and return 501 until those land.
"""

from typing import Any

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse

from forgelab.auth.fastapi import mount_dev_auth, require_auth
from forgelab.auth.models import Principal
from forgelab.core import (
    IncompatibleVersionError,
    UnknownToolError,
    default_registry,
    validate,
)
from forgelab.spec import SPEC_VERSION, json_schema

app = FastAPI(
    title="ForgeLab",
    summary="The LLVM of design — universal design IR + compiler.",
    version=SPEC_VERSION,
)
_registry = default_registry()
mount_dev_auth(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "spec_version": SPEC_VERSION}


@app.get("/spec")
def spec() -> dict[str, Any]:
    """Return the ForgeDocument JSON Schema."""
    return json_schema()


@app.post("/validate")
def validate_document(
    document: dict[str, Any],
    _principal: Principal = Depends(require_auth("forge:read")),  # noqa: B008
) -> JSONResponse:
    """Validate a posted ForgeLab document."""
    try:
        validate(document)
    except IncompatibleVersionError as exc:
        return JSONResponse(status_code=400, content={"valid": False, "error": str(exc)})
    except Exception as exc:  # pydantic ValidationError and friends
        return JSONResponse(status_code=400, content={"valid": False, "error": str(exc)})
    return JSONResponse(status_code=200, content={"valid": True})


@app.post("/export/{tool}")
def export_document(
    tool: str,
    document: dict[str, Any],
    _principal: Principal = Depends(require_auth("forge:export")),  # noqa: B008
) -> JSONResponse:
    """Export a document to a tool's native format (stubs return 501)."""
    try:
        doc = validate(document)
        exporter = _registry.get_exporter(tool)
    except UnknownToolError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=400, content={"valid": False, "error": str(exc)})
    try:
        exporter().from_ir(doc)
    except NotImplementedError as exc:
        return JSONResponse(status_code=501, content={"error": str(exc)})
    return JSONResponse(status_code=200, content={"ok": True})
