from collections import Counter
import hashlib
import math
import re

from qdrant_client.models import SparseVector


LEXICAL_HASH_SPACE = 2**32 - 1


def lexical_tokens(value: str) -> list[str]:
    return re.findall(r"[\w\u0400-\u04ff]{2,}", (value or "").lower())


def lexical_vector(
    text: str,
    title: str | None = None,
    section: str | None = None,
    filename: str | None = None,
) -> SparseVector:
    """Build a normalized sparse lexical vector with metadata boosts."""
    terms = Counter(lexical_tokens(text))
    for value, weight in ((title, 3), (section, 2), (filename, 2)):
        for token in lexical_tokens(value):
            terms[token] += weight

    weighted: dict[int, float] = {}
    for token, frequency in terms.items():
        token_hash = int.from_bytes(
            hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest(),
            byteorder="big",
        ) % LEXICAL_HASH_SPACE
        weighted[token_hash] = weighted.get(token_hash, 0.0) + 1.0 + math.log(frequency)

    norm = math.sqrt(sum(weight * weight for weight in weighted.values()))
    if not norm:
        return SparseVector(indices=[], values=[])

    ordered = sorted(weighted.items())
    return SparseVector(
        indices=[index for index, _ in ordered],
        values=[weight / norm for _, weight in ordered],
    )
