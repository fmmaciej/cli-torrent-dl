"""Regression checks that import only the installed tordl distribution."""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "engines.py"

CONFIGURE = """
import asyncio
import json
import sys
from pathlib import Path
from tordl import config as cfg
from tordl import core, func

cfg.init_cfg()
Path(cfg.CFG_ENGINES_FILE).write_text(Path(sys.argv[1]).read_text())
cfg.SEARCH_ENGINES = ["OfflineA", "OfflineB"]
cfg.PAGE_NUM_DOWNLOAD = 1
cfg.FETCH_MISSING_MAGNET_LINKS = True
"""


class InstalledRuntimeTests(unittest.TestCase):
    def run_python(self, source):
        with tempfile.TemporaryDirectory(prefix="tordl-test-") as temporary:
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    textwrap.dedent(source),
                    str(FIXTURE),
                ],
                cwd=temporary,
                env={**os.environ, "XDG_CONFIG_HOME": temporary},
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_installed_modules(self):
        self.run_python("""
            from importlib.metadata import version
            from tordl import config, func
            from tordl import app, core, engines, rpc

            assert version("tordl") == "1.10.post2"
            assert callable(core.DlFacade)
            assert callable(core.Api)
            assert callable(func.run_api)
            assert callable(app.App)
            assert callable(rpc.JsonRpcClient)
            assert engines.NyaaTracker.NAME == "Nyaa"
        """)

    def test_loop_initialization(self):
        self.run_python("""
            import asyncio
            from tordl import config, func

            loop = func._mk_loop(None)
            try:
                assert asyncio.get_event_loop() is loop
                assert func._mk_loop(loop) is loop
                async def value():
                    return 42
                assert loop.run_until_complete(value()) == 42
            finally:
                loop.close()
                asyncio.set_event_loop(None)
        """)

    def test_search_and_missing_magnets(self):
        self.run_python(
            CONFIGURE
            + """
async def exercise():
    facade = core.DlFacade(loop=asyncio.get_running_loop())
    assert len(facade.engines) == 2
    results = await facade.fetch_pages("debian")
    assert len(results) == 2
    assert any(not result.magnet_url for result in results)
    await facade.fetch_magnet_links(results)
    assert all(result.magnet_url for result in results)
    results = facade.aggregate_same_magnets(results)
    assert len(results) == 1
    assert {origin.NAME for origin in results[0].origins} == set(cfg.SEARCH_ENGINES)

asyncio.run(exercise())
"""
        )

    def test_api_json(self):
        self.run_python(
            CONFIGURE
            + """
loop = func._mk_loop(None)
try:
    result = json.loads(func.run_api("debian", pretty_json=False, loop=loop))
    assert len(result["result"]) == 1
    item = result["result"][0]
    assert set(item["origins"]) == set(cfg.SEARCH_ENGINES)
    assert item["seeds"] == 2
    assert item["magnet_url"] == "magnet:?xt=urn:btih:" + "a" * 40
finally:
    loop.close()
    asyncio.set_event_loop(None)
"""
        )

    def test_search_failures_are_isolated(self):
        self.run_python(
            CONFIGURE
            + """
async def exercise():
    loop = asyncio.get_running_loop()
    initial = core.DlFacade(loop)
    Good = next(cls for cls in initial.engines if cls.NAME == "OfflineB")
    class Broken(Good):
        NAME = "Broken"
        async def search(self, expression):
            raise ValueError("broken provider")
    class NoResponse(Good):
        NAME = "NoResponse"
        async def search(self, expression):
            return None
    class Empty(Good):
        NAME = "Empty"
        async def search(self, expression):
            return []
    facade = core.DlFacade(loop, dl_classes=[Good, Broken, NoResponse, Empty])
    results = await facade.fetch_pages("debian")
    assert len(results) == 1
    assert set(facade.search_errors) == {"Broken", "NoResponse"}
    assert "broken provider" in facade.search_errors["Broken"]
    assert "Empty" not in facade.search_errors
    assert facade.successful_engines == {"OfflineB", "Empty"}
    class Sometimes(Empty):
        NAME = "Sometimes"
        async def search(self, expression):
            self.calls = getattr(self, "calls", 0) + 1
            if self.calls == 1:
                return []
            raise ValueError("second page failed")
    cfg.PAGE_NUM_DOWNLOAD = 2
    facade = core.DlFacade(loop, dl_classes=[Sometimes])
    assert await facade.fetch_pages("debian") == []
    assert facade.successful_engines == {"Sometimes"}
    assert "Sometimes" in facade.search_errors

asyncio.run(exercise())
"""
        )

    def test_parser_and_http_errors_are_recorded(self):
        self.run_python(
            CONFIGURE
            + """
from unittest.mock import AsyncMock, MagicMock, patch

class Parser(core.BaseDl):
    NAME = "Parser"
    BASE_URL = "https://example.invalid"
    def _mk_search_url(self, expression):
        return self.BASE_URL
    async def _get_url(self, url):
        return b"changed markup"
    def _process_search(self, response):
        raise ValueError("changed markup")

async def exercise():
    facade = core.DlFacade(asyncio.get_running_loop(), dl_classes=[Parser])
    assert await facade.fetch_pages("debian") == []
    assert facade.search_errors["Parser"] == "parser: changed markup"
    response = MagicMock()
    response.raise_for_status.side_effect = RuntimeError("HTTP 503")
    response.read = AsyncMock(return_value=b"not a search page")
    request = MagicMock()
    request.__aenter__.return_value = response
    session = MagicMock()
    session.__aenter__.return_value = session
    session.get.return_value = request
    engine = Parser()
    with patch("tordl.core.ClientSession", return_value=session):
        assert await core.BaseDl._get_url(engine, Parser.BASE_URL) is None
        assert engine.last_error == ("network", "HTTP 503")
        response.read.assert_not_awaited()
        response.raise_for_status.side_effect = None
        response.read.side_effect = TimeoutError()
        assert await core.BaseDl._get_url(engine, Parser.BASE_URL) is None
        assert engine.last_error == ("network", "request timed out")

asyncio.run(exercise())
"""
        )

    def test_failed_magnet_lookup_does_not_block_others(self):
        self.run_python(
            CONFIGURE
            + """
async def exercise():
    loop = asyncio.get_running_loop()
    initial = core.DlFacade(loop)
    Good = next(cls for cls in initial.engines if cls.NAME == "OfflineB")
    class Broken(Good):
        NAME = "Broken"
        async def search(self, expression):
            return [core.SearchResult(self, self.NAME, "/a", 1, 0, "1GB")]
        async def get_magnet_url(self, result):
            raise ValueError("missing link")
    class Healthy(Broken):
        NAME = "Healthy"
        async def get_magnet_url(self, result):
            return "magnet:?xt=urn:btih:" + "a" * 40
    facade = core.DlFacade(loop, dl_classes=[Broken, Healthy])
    results = await facade.fetch_pages("debian")
    await asyncio.wait_for(facade.fetch_magnet_links(results), timeout=1)
    assert sum(bool(result.magnet_url) for result in results) == 1
    assert facade.magnet_errors == {"Broken": "magnet: missing link"}

asyncio.run(exercise())
"""
        )

    def test_search_cancellation_cleans_up_tasks(self):
        self.run_python(
            CONFIGURE
            + """
async def exercise():
    cleaned = []
    class Slow(core.BaseDl):
        NAME = "Slow"
        BASE_URL = "https://example.invalid"
        async def search(self, expression):
            try:
                await asyncio.sleep(60)
            finally:
                cleaned.append("search")
    facade = core.DlFacade(asyncio.get_running_loop(), dl_classes=[Slow])
    try:
        async with asyncio.timeout(0.01):
            await facade.fetch_pages("debian")
    except TimeoutError:
        pass
    else:
        raise AssertionError("deadline was not enforced")
    assert cleaned == ["search"]
    assert asyncio.all_tasks() == {asyncio.current_task()}

asyncio.run(exercise())
"""
        )

    def test_magnet_cancellation_cleans_up_tasks(self):
        self.run_python(
            CONFIGURE
            + """
async def exercise():
    cleaned = []
    class Slow(core.BaseDl):
        NAME = "Slow"
        BASE_URL = "https://example.invalid"
        async def search(self, expression):
            return [core.SearchResult(self, "Debian", "/a", 1, 0, "1GB")]
        async def get_magnet_url(self, result):
            try:
                await asyncio.sleep(60)
            finally:
                cleaned.append("magnet")
    facade = core.DlFacade(asyncio.get_running_loop(), dl_classes=[Slow])
    results = await facade.fetch_pages("debian")
    try:
        async with asyncio.timeout(0.01):
            await facade.fetch_magnet_links(results)
    except TimeoutError:
        pass
    else:
        raise AssertionError("deadline was not enforced")
    assert cleaned == ["magnet"]
    assert await facade.fetch_magnet_links([]) == []
    assert asyncio.all_tasks() == {asyncio.current_task()}

asyncio.run(exercise())
"""
        )


if __name__ == "__main__":
    unittest.main()
