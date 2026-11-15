"""Version-proof route discovery for the auto-discovering security sweeps (14.3).

`app.routes` changed shape in newer FastAPI (included routers are wrapped in private objects), which made the sweeps find zero routes.
The OpenAPI schema is public and stable, so the sweeps enumerate operations from it. Routes hidden from the schema (the static dashboard)
are public by design and are not part of these sweeps."""
import re
from typing import List, Set

HTTP = {"get", "post", "put", "patch", "delete"}


class Op:
    """The few attributes the sweeps read from a route: path, methods, param_convertors."""

    def __init__(self, path: str, methods: Set[str]) -> None:
        self.path, self.methods = path, methods
        self.param_convertors = {p: None for p in re.findall(r"{([^}]+)}", path)}

    def __repr__(self) -> str:
        return f"Op({sorted(self.methods)} {self.path})"


def api_routes(app, contains: str = "", startswith: str = "") -> List[Op]:
    out = []
    for path, item in app.openapi()["paths"].items():
        if (contains and contains not in path) or (startswith and not path.startswith(startswith)):
            continue
        for m in sorted(item):
            if m in HTTP:
                out.append(Op(path, {m.upper()}))            # one entry per (path, method), as one APIRoute used to be
    return out
