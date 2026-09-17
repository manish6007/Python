"""FastAPI application.

The HTTP layer is thin on purpose: every endpoint validates its input, checks
who is asking, and calls into the tested ``emi_locker`` core. Business rules
live in the core, not here, so the rules are covered by the core's tests and
cannot drift between transports.
"""
from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from emi_locker.db import file_db
from emi_locker.errors import DomainError

from .config import settings
from .routers import (
    admin_router,
    auth_router,
    customer_router,
    distributor_router,
    license_router,
    payment_router,
    retailer_router,
)

DESCRIPTION = """
Backend for the EMI Locker Customer and Retailer apps.

Money is **integer paise** everywhere. An EMI is only ever marked paid by a
verified gateway callback - never by an app reporting success.
"""


def create_app(db_path: str = None) -> FastAPI:
    settings.validate()
    app = FastAPI(title="EMI Locker API", version="0.1.0", description=DESCRIPTION)
    app.state.db_path = db_path or settings.db_path

    # Create the schema up front so the first request does not race on it.
    file_db(app.state.db_path).close()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DomainError)
    def domain_error_handler(request: Request, exc: DomainError):
        """Map business-rule violations onto honest status codes.

        The apps show ``message`` to the user, so it is written for a person:
        "IMEI ... is already on live finance", not "constraint violation".
        """
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": exc.code, "message": str(exc)},
        )

    @app.get("/health", tags=["meta"])
    def health():
        return {"status": "ok", "env": settings.env, "mock_gateway": settings.is_local}

    app.include_router(auth_router.router)
    app.include_router(retailer_router.router)
    app.include_router(customer_router.router)
    app.include_router(distributor_router.router)
    app.include_router(payment_router.router)
    app.include_router(license_router.router)
    app.include_router(admin_router.router)
    return app


app = create_app()


def main() -> None:  # pragma: no cover - manual entry point
    import uvicorn

    host = os.getenv("EMI_HOST", "0.0.0.0")
    port = int(os.getenv("EMI_PORT", "8000"))
    print("EMI Locker API on http://%s:%d  (docs at /docs)" % (host, port))
    uvicorn.run("backend.app.main:app", host=host, port=port, reload=True)


if __name__ == "__main__":  # pragma: no cover
    main()
