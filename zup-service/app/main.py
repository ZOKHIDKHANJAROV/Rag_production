import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse


app = FastAPI(title="1C ZUP Search Proxy")

ZUP_API_BASE_URL = os.getenv("ZUP_API_BASE_URL", "").rstrip("/")
ZUP_EMPLOYEES_PATH = os.getenv("ZUP_EMPLOYEES_PATH", "/employees")
ZUP_SEARCH_PARAM = os.getenv("ZUP_SEARCH_PARAM", "q")
ZUP_API_TOKEN = os.getenv("ZUP_API_TOKEN", "")
ZUP_AUTH_HEADER = os.getenv("ZUP_AUTH_HEADER", "Authorization")
ZUP_REQUEST_TIMEOUT = int(os.getenv("ZUP_REQUEST_TIMEOUT", "30"))
INTERNAL_SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "")
SERVICE_AUTH_HEADER = "X-Service-Token"

client: httpx.AsyncClient | None = None
EMPLOYEE_FIELDS = (
    "pinfl", "id_pers", "name", "tab_num", "ent_code", "dep_code", "group_code",
    "subgroup_code", "prof", "prof_code", "grade", "gender", "address", "born_date",
    "passport_num", "educ", "speciality", "catg_name", "csn_card", "employee_uid", "fired",
)


@app.middleware("http")
async def require_service_token(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    if not INTERNAL_SERVICE_TOKEN:
        return JSONResponse(status_code=503, content={"detail": "Internal service token is not configured"})
    if request.headers.get(SERVICE_AUTH_HEADER, "") != INTERNAL_SERVICE_TOKEN:
        return JSONResponse(status_code=401, content={"detail": "Invalid internal service token"})
    return await call_next(request)


@app.on_event("startup")
async def startup_event():
    global client
    client = httpx.AsyncClient(timeout=httpx.Timeout(ZUP_REQUEST_TIMEOUT, connect=5.0))


@app.on_event("shutdown")
async def shutdown_event():
    if client:
        await client.aclose()


def extract_records(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "value", "items", "results", "employees"):
        records = payload.get(key)
        if isinstance(records, list):
            return [item for item in records if isinstance(item, dict)]
    return [payload] if any(key in payload for key in EMPLOYEE_FIELDS) else []


def normalize_employee(record: dict) -> dict:
    return {field: record.get(field) for field in EMPLOYEE_FIELDS if record.get(field) not in (None, "")}


def upstream_headers():
    return {ZUP_AUTH_HEADER: ZUP_API_TOKEN} if ZUP_API_TOKEN else {}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "zup-service", "configured": bool(ZUP_API_BASE_URL)}


@app.get("/employees/search")
async def search_employees(query: str, limit: int = 20):
    if not ZUP_API_BASE_URL:
        raise HTTPException(status_code=503, detail="1C ZUP API is not configured")
    if client is None:
        raise HTTPException(status_code=503, detail="ZUP HTTP client is not initialized")

    normalized_query = query.strip()
    if len(normalized_query) < 2:
        raise HTTPException(status_code=400, detail="Search query must contain at least two characters")

    try:
        response = await client.get(
            f"{ZUP_API_BASE_URL}/{ZUP_EMPLOYEES_PATH.lstrip('/')}",
            params={ZUP_SEARCH_PARAM: normalized_query, "limit": max(1, min(limit, 100))},
            headers=upstream_headers(),
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="1C ZUP API is unavailable") from exc

    return {"employees": [normalize_employee(record) for record in extract_records(response.json())]}
