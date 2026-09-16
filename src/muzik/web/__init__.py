"""The web adapter — a thin sibling of the CLI over the same engine (ADR-0001,
ADR-0010). It knows nothing the engine doesn't: runs go through ``engine.run``,
review decisions through ``engine.clear_review_queue``, providers through
``muzik.wiring``. Run it with ``python -m muzik.web``.
"""
