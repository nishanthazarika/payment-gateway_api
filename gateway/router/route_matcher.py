from gateway.config import Route


class TrieNode:
    def __init__(self):
        self.children: dict[str, "TrieNode"] = {}
        self.route: Route | None = None
        self.is_prefix: bool = False
        self.param_name: str | None = None  # for :id style params


class RouteMatcher:
    """
    Trie-based path matcher supporting:
    - Exact match:   /api/v1/users
    - Prefix match:  /api/v1/users/*  (matches /api/v1/users/123/profile)
    - Path params:   /api/v1/users/:id
    """

    def __init__(self):
        self.root = TrieNode()

    def add_route(self, route: Route):
        segments = self._split(route.path)
        node = self.root

        for seg in segments:
            if seg.startswith(":"):
                # path parameter — store under wildcard key
                key = ":"
                if key not in node.children:
                    node.children[key] = TrieNode()
                node = node.children[key]
                node.param_name = seg[1:]
            else:
                if seg not in node.children:
                    node.children[seg] = TrieNode()
                node = node.children[seg]

        node.route = route
        node.is_prefix = route.prefix_match

    def match(self, path: str, method: str) -> tuple[Route | None, dict]:
        """Returns (matched_route, path_params) or (None, {}) if no match."""
        segments = self._split(path)
        params = {}
        result = self._search(self.root, segments, 0, params)

        if result and method.upper() in result.methods:
            return result, params
        return None, {}

    def _search(self, node: TrieNode, segments: list[str], idx: int, params: dict) -> Route | None:
        # we've consumed all segments
        if idx == len(segments):
            return node.route

        seg = segments[idx]

        # try exact match first
        if seg in node.children:
            result = self._search(node.children[seg], segments, idx + 1, params)
            if result:
                return result

        # try param match
        if ":" in node.children:
            child = node.children[":"]
            params[child.param_name] = seg
            result = self._search(child, segments, idx + 1, params)
            if result:
                return result
            del params[child.param_name]

        # check if current node is a prefix match (catches remaining segments)
        if node.is_prefix and node.route:
            return node.route

        return None

    @staticmethod
    def _split(path: str) -> list[str]:
        return [s for s in path.strip("/").split("/") if s]