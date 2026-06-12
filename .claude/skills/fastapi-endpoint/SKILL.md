---
name: fastapi-endpoint
description: Conventions for a Spore FastAPI endpoint — Pydantic schema, token auth dependency,
  service-layer separation, structured error envelope, and a pytest contract test. Use for any backend route.
---
- Router → service → repository. No DB calls in routers.
- Auth via the shared token dependency. Validate input with Pydantic; never trust client JSON.
- Return the standard {ok, data, error} envelope. Log structured events with a request id.
- Every endpoint gets a pytest contract test (happy path + auth failure + bad input).
