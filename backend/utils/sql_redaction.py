"""Remove SQL data literals before diagnostics leave the database collector."""
import hashlib

import sqlparse
from sqlparse import tokens


REDACTED_QUERY = "[SQL redacted because tokenization failed]"


def query_fingerprint(query):
    return hashlib.sha256(query.encode("utf-8", errors="replace")).hexdigest()


def redact_sql_literals(query):
    """Preserve statement shape while removing comments and data literals."""
    try:
        statements = sqlparse.parse(query)
        if not statements:
            return REDACTED_QUERY, query_fingerprint(REDACTED_QUERY)
        redacted_statements = []
        for statement in statements:
            flattened = list(statement.flatten())
            for index, token in enumerate(flattened):
                if token.ttype in tokens.Comment:
                    token.value = " "
                elif token.ttype in tokens.Literal.String.Symbol:
                    continue
                elif token.ttype in tokens.Literal.String.Single:
                    token.value = "'?'"
                    if index > 0 and flattened[index - 1].value.upper() in {"E", "B", "X", "N"}:
                        flattened[index - 1].value = ""
                    elif (
                        index > 1
                        and flattened[index - 1].value == "&"
                        and flattened[index - 2].value.upper() == "U"
                    ):
                        flattened[index - 2].value = ""
                        flattened[index - 1].value = ""
                elif token.ttype in tokens.Literal:
                    token.value = "?"
            redacted = str(statement).strip()
            if redacted:
                redacted_statements.append(redacted)
        redacted_query = "; ".join(redacted_statements) or REDACTED_QUERY
        return redacted_query, query_fingerprint(redacted_query)
    except Exception:
        return REDACTED_QUERY, query_fingerprint(REDACTED_QUERY)


def redact_query_record(record, *, redact_literals=True):
    """Return a query evidence row without raw literals and with a stable digest."""
    sanitized = dict(record)
    query = sanitized.get("query")
    if not isinstance(query, str) or not query:
        return sanitized
    if sanitized.get("query_redacted") is True and sanitized.get("query_fingerprint"):
        return sanitized
    if redact_literals:
        sanitized["query"], fingerprint = redact_sql_literals(query)
    else:
        fingerprint = query_fingerprint(query)
    sanitized["query_fingerprint"] = fingerprint
    sanitized["query_redacted"] = redact_literals
    return sanitized


def redact_query_data(value, *, redact_literals=True):
    """Recursively sanitize query fields at audit and API persistence boundaries."""
    if isinstance(value, list):
        return [redact_query_data(item, redact_literals=redact_literals) for item in value]
    if isinstance(value, dict):
        sanitized = {
            key: redact_query_data(item, redact_literals=redact_literals)
            for key, item in value.items()
        }
        return redact_query_record(sanitized, redact_literals=redact_literals)
    return value
