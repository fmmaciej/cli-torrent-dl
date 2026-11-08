# Fork maintenance

This fork supports srtor's use of tordl as an installed Python dependency.
The upstream project is
[X0R0X/cli-torrent-dl](https://github.com/X0R0X/cli-torrent-dl); the initial base is
`c76640bdb951c2d7a7dd5e1e5ce3c05cfa5a7317`.

## Patch set

- Preserve the Python 3.12 loop-initialization fix originally committed locally as
  `d0aab317e3dbc55bf4a8620cb42a8f5db25ff36d`: after selecting the loop policy,
  create and set a loop explicitly. A caller-supplied loop is reused.
- Discover the actual `tordl` package at the repository root. Upstream's
  `find_packages(where='tordl')` produced a wheel containing metadata alone.
- Declare the setuptools build backend and Python 3.12 minimum. The patched
  distribution version is `1.10.post1`.
- Keep only direct runtime dependencies in `requirements.txt`: aiohttp,
  Beautiful Soup, pyxdg, pyperclip, and uvloop on supported Unix platforms.
  Remove obsolete transitive/publishing pins. The aiohttp lower bound excludes
  upstream's yanked 3.11.14 release.
- Add offline regression checks against the installed wheel.

Retain upstream authorship and the MIT license. Keep subsequent changes small,
documented, and suitable for contributing upstream. This fork does not add a
second search framework, client, or daemon.

## Verification

From the fork checkout, with uv available:

```sh
uv build --python 3.12
uv run --no-project --python 3.12 --with dist/tordl-1.10.post1-py3-none-any.whl \
  python -m unittest discover -s tests -v
```

The subprocess checks run Python in isolated mode from a temporary directory.
They import the installed package rather than falling back to this checkout and
use a temporary `XDG_CONFIG_HOME`. Fixture engines exercise search, missing-magnet
retrieval, aggregation, and JSON output without contacting indexers or rTorrent.

Consumers should pin a reviewed fork commit, not the moving branch. srtor's uv
lockfile owns its complete resolved environment; this fork does not freeze the
old upstream machine's environment into application requirements.

## Remaining upstream limitations

Import `tordl.config` before `tordl.core` to avoid the existing circular import.
For helper/UI imports, load `config` and then `func` first, as upstream's launcher
does; importing `app` before `func` encounters another existing import cycle.
The `Api` constructor does not correctly forward custom engine classes; direct
`DlFacade(loop=..., dl_classes=...)` remains the clearer boundary. Existing
scraper behavior and error reporting have not been rewritten. No live provider
health claim is made by these offline tests.
