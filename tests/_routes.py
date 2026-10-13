"""The app's API routes as one flat list, each with its full path.

FastAPI (0.14x) keeps an included router nested — `app.routes` holds one entry per `include_router` — so a walk of
`app.routes` no longer reaches the endpoints. `iter_route_contexts` yields each one as it is served; here each becomes
a copy of its APIRoute carrying the full path (and its pattern), so tests read it as they always have.
"""

import copy

from fastapi.routing import APIRoute, iter_route_contexts
from starlette.routing import compile_path


def api_routes(app) -> list[APIRoute]:
    routes = []
    for context in iter_route_contexts(app.routes):
        if not isinstance(context.route, APIRoute):
            continue
        route = copy.copy(context.route)
        route.path = context.path
        route.path_regex, route.path_format, route.param_convertors = compile_path(context.path)
        route.methods = set(context.methods)
        routes.append(route)
    return routes
