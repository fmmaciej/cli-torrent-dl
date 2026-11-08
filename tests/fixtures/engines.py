"""Offline tordl-compatible fixtures; never perform HTTP requests."""

from tordl.core import BaseDl, SearchResult

MAGNET = "magnet:?xt=urn:btih:" + "a" * 40


class OfflineA(BaseDl):
    NAME = "OfflineA"
    BASE_URL = "https://example.invalid"

    async def search(self, expression):
        return [SearchResult(self, "Debian", "/a", 1, 0, "1GB")]

    async def get_magnet_url(self, result):
        return MAGNET


class OfflineB(OfflineA):
    NAME = "OfflineB"

    async def search(self, expression):
        return [SearchResult(self, "Debian", "/b", 2, 1, "1GB", MAGNET)]
