"""One page of a list endpoint: `limit`/`offset` on the query, and how many there are in all in a header, so a list
answer keeps its shape (a JSON array) for the clients that read all of it."""

from fastapi import Response

TOTAL_COUNT_HEADER = "X-Total-Count"


def paged(query, response: Response, limit: int | None, offset: int):
    """``query`` (an ordered ORM query) cut to one page, with the total of every page in ``X-Total-Count``."""
    response.headers[TOTAL_COUNT_HEADER] = str(query.order_by(None).count())
    query = query.offset(offset) if offset else query
    return query.limit(limit) if limit is not None else query
