"""Pagination for the newsroom API.

Deliberately backward compatible: `/article/list/` still returns a plain JSON
array (what the current frontend expects), while `/article/list/?page=2` returns
the standard `{count, next, previous, results}` envelope so the feed can be
paged without changing the existing callers.
"""

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class NewspaperPagination(PageNumberPagination):
    page_size = 12
    page_query_param = "page"
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response(
            {
                "count": self.page.paginator.count,
                "num_pages": self.page.paginator.num_pages,
                "page": self.page.number,
                "page_size": self.get_page_size(self.request),
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "results": data,
            }
        )


def wants_pagination(request):
    """True when the caller explicitly asked for a page.

    Without this the article list would silently change from `[...]` to
    `{results: [...]}`, which would break the deployed frontend.
    """
    if not request:
        return False
    for key in ("page", "page_size", "limit", "offset"):
        if key in request.query_params:
            return True
    return False
