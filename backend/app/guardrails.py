"""SQL safety layer. The AI writes SQL; this makes sure it can only ever read."""
import re

from .config import get_settings

settings = get_settings()

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|copy|"
    r"vacuum|call|do|merge|comment|reindex|cluster|lock|listen|notify|"
    r"pg_read_file|pg_ls_dir|dblink|pg_sleep|pg_terminate_backend|pg_cancel_backend)\b",
    re.IGNORECASE,
)


class UnsafeSQLError(ValueError):
    pass


def sanitize(sql: str) -> str:
    """Allow exactly one read-only SELECT/WITH...SELECT statement, capped in size."""
    sql = sql.strip().rstrip(";").strip()

    if not sql:
        raise UnsafeSQLError("Empty query.")
    # one statement only
    if ";" in sql:
        raise UnsafeSQLError("Only a single statement is allowed.")
    # must be a read
    if not re.match(r"^(select|with)\b", sql, re.IGNORECASE):
        raise UnsafeSQLError("Only SELECT queries are allowed.")
    # no write / DDL / dangerous keywords anywhere
    if _FORBIDDEN.search(sql):
        raise UnsafeSQLError("Query contains a forbidden keyword.")
    # block multi-statement tricks and comments used to smuggle SQL
    if "--" in sql or "/*" in sql:
        raise UnsafeSQLError("Comments are not allowed in generated SQL.")

    # enforce a hard row cap
    if re.search(r"\blimit\b", sql, re.IGNORECASE) is None:
        sql = f"{sql}\nLIMIT {settings.MAX_ROWS}"
    return sql
