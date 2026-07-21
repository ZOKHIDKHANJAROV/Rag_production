from qdrant_client.models import (
    Filter,
    FieldCondition,
    IsEmptyCondition,
    MatchAny,
    MatchValue,
)


def normalize_scope_key(scope_key: str | None) -> str:
    scope = (scope_key or "global").strip()
    return scope or "global"


def scope_filter(scope_keys: list[str] | None = None) -> Filter:
    scopes = [normalize_scope_key(scope) for scope in (scope_keys or ["global"])]
    should = [FieldCondition(key="scope_key", match=MatchAny(any=scopes))]
    if "global" in scopes:
        should.append(IsEmptyCondition(is_empty={"key": "scope_key"}))

    return Filter(
        must_not=[FieldCondition(key="is_deleted", match=MatchValue(value=True))],
        should=should,
    )


def active_filter() -> Filter:
    return Filter(
        must_not=[FieldCondition(key="is_deleted", match=MatchValue(value=True))]
    )


def document_scope_filter(document_id: str, scope_key: str | None = None) -> Filter:
    scope = normalize_scope_key(scope_key)
    should = [FieldCondition(key="scope_key", match=MatchValue(value=scope))]
    if scope == "global":
        should.append(IsEmptyCondition(is_empty={"key": "scope_key"}))

    return Filter(
        must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))],
        should=should,
    )
