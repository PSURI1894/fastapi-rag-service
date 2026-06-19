"""FastAPI RAG service — a production-shaped API around a (mock) RAG pipeline.

The package is intentionally split by responsibility so each concept lives in
one file you can read top-to-bottom:

    config.py        -> typed settings from the environment
    logging_config.py-> structured logging setup
    schemas.py       -> Pydantic models = the API contract
    security.py      -> authentication, expressed as a dependency
    repositories/    -> data access behind an interface (swap in a DB later)
    services/        -> business logic (the RAG pipeline)
    dependencies.py  -> wiring: how routes get their repo/service
    routers/         -> the HTTP endpoints
    main.py          -> the app factory that assembles all of the above
"""

__version__ = "0.1.0"
