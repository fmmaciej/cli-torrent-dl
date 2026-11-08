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

            assert version("tordl") == "1.10.post1"
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


if __name__ == "__main__":
    unittest.main()
