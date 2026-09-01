#!/usr/bin/env python3
"""Build the browser-only (stlite / Pyodide) proof-of-concept of the app.

Reads the real application sources (app.py, ui/**, src/attendance_tracker/**)
and generates webapp/index.html, a single page that boots the whole Streamlit
app inside the browser via stlite — no server, no install; uploaded student
data never leaves the machine because there is nowhere for it to go.

Two asset modes:

  python scripts/build_webapp.py
      Default: the page loads stlite + Pyodide + wheels from public CDNs
      (cdn.jsdelivr.net, pypi.org). Right for normal school networks.

  python scripts/build_webapp.py --vendor
      Downloads every asset (stlite build, Pyodide runtime + needed wasm
      wheels, pure-Python wheels) into webapp/vendor/ and points the page at
      those local copies, so the page works with NO outbound network at all.
      Downloads are cached in --cache-dir (default webapp/vendor/_cache) and
      reused on rebuilds.

The page mounts the app files at their original relative paths and uses a
small generated wrapper (web_main.py) as the entrypoint; the wrapper shims
what cannot work in a browser tab (the local_data/ "remember on this
computer" persistence) and then runs the untouched app.py.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WEBAPP = REPO / "webapp"

STLITE_VERSION = "1.8.1"  # 1.8.0 has broken file uploads — do not lower.
STLITE_CDN_BASE = (
    f"https://cdn.jsdelivr.net/npm/@stlite/browser@{STLITE_VERSION}/build"
)
STLITE_TGZ_URL = (
    "https://registry.npmjs.org/@stlite/browser/-/"
    f"browser-{STLITE_VERSION}.tgz"
)

# Pyodide runtime matching stlite 1.8.1's line (Python 3.13, ABI 2025_0).
PYODIDE_VERSION = "0.29.4"
PYODIDE_CORE_URL = (
    "https://github.com/pyodide/pyodide/releases/download/"
    f"{PYODIDE_VERSION}/pyodide-core-{PYODIDE_VERSION}.tar.bz2"
)
# Per-release prebuilt package bundle + its lockfile (wasm wheels for
# pandas/numpy/etc.). The lockfile ships both here and in the core tarball.
RECIPES_TAG = "0.29-20260507"
RECIPES_BASE = (
    "https://github.com/pyodide/pyodide-recipes/releases/download/"
    f"{RECIPES_TAG}"
)
RECIPES_PACKAGES_URL = f"{RECIPES_BASE}/packages.tar.gz"
RECIPES_LOCK_URL = f"{RECIPES_BASE}/pyodide-lock.json"

# Pyodide-distribution packages the app (and stlite's Streamlit fork) needs.
# The build keeps the dependency closure of these from the lockfile, so the
# vendored runtime stays ~60MB instead of ~1.5GB.
PYODIDE_ROOT_PACKAGES = [
    # app deps
    "pandas", "numpy", "xlrd",
    # runtime plumbing
    "micropip", "pyodide-http",
    # unvendored stdlib pieces
    "hashlib", "ssl", "sqlite3", "lzma",
    # streamlit fork Requires-Dist that live in the Pyodide distribution
    "altair", "cachetools", "pillow", "protobuf", "typing-extensions",
    "starlette", "anyio", "fastparquet", "packaging", "narwhals", "jinja2",
    # common transitive helpers
    "python-dateutil", "pytz", "six", "tzdata",
]

# Pure-Python wheels not in the Pyodide distribution. In CDN mode micropip
# resolves the names from PyPI; in vendor mode these exact wheels are
# downloaded and listed by local URL. The first group is app requirements;
# the second group satisfies the Streamlit fork's name-based dependencies so
# micropip never has to reach pypi.org.
PYPI_WHEELS = [
    # (requirement spec for CDN mode or None, wheel URL)
    ("plotly==6.9.0",
     "https://files.pythonhosted.org/packages/24/18/d8544811ab076f876c4892b3714f5b0dad335e1dc33aef826df431b8325d/plotly-6.9.0-py3-none-any.whl"),
    ("openpyxl==3.1.5",
     "https://files.pythonhosted.org/packages/c0/da/977ded879c29cbd04de313843e76868e6e13408a94ed6b987245dc7c8506/openpyxl-3.1.5-py2.py3-none-any.whl"),
    (None,  # openpyxl dep; PyPI resolution handles it in CDN mode
     "https://files.pythonhosted.org/packages/c1/8b/5fe2cc11fee489817272089c4203e679c63b570a5aaeb18d852ae3cbba6a/et_xmlfile-2.0.0-py3-none-any.whl"),
    (None,
     "https://files.pythonhosted.org/packages/10/cb/f2ad4230dc2eb1a74edf38f1a38b9b52277f75bef262d8908e60d957e13c/blinker-1.9.0-py3-none-any.whl"),
    (None,
     "https://files.pythonhosted.org/packages/d7/c1/eb8f9debc45d3b7918a32ab756658a0904732f75e555402972246b0b8e71/tenacity-9.1.4-py3-none-any.whl"),
    (None,
     "https://files.pythonhosted.org/packages/e1/04/e8135ebd1ad02c56ec633277529b2602ff99ff634be76cdba5744cf554fd/python_multipart-0.0.32-py3-none-any.whl"),
    (None,
     "https://files.pythonhosted.org/packages/04/96/92447566d16df59b2a776c0fb82dbc4d9e07cd95062562af01e408583fc4/itsdangerous-2.2.0-py3-none-any.whl"),
]

# stlite's worker itself requires protobuf>=7.34.1,<8 at boot, but the
# Pyodide 0.29 distribution only ships protobuf 6.31.1. Online, micropip
# fetches a newer pure-Python protobuf from PyPI; for the offline vendored
# build we override the lockfile entry so the same resolution happens from
# a locally served wheel instead.
LOCK_OVERRIDES = {
    "protobuf": {
        "version": "7.36.0",
        "file_name": "protobuf-7.36.0-py3-none-any.whl",
        "sha256":
            "53374d53fc29a67f7dbbf0ade47d7526a0f0137bf0f9c90e48d8a60790ef748c",
        "url": "https://files.pythonhosted.org/packages/01/c3/"
               "629999e78d46c1115c11886d51c6bd68c17ce4a944f1ea3e153a91316a33/"
               "protobuf-7.36.0-py3-none-any.whl",
        "depends": [],
    },
}

CDN_REQUIREMENTS = [
    spec for spec, _ in PYPI_WHEELS if spec is not None
] + ["xlrd==2.0.1"]

# Names of app requirements that in vendor mode resolve from the local
# Pyodide lockfile rather than a vendored PyPI wheel.
VENDOR_LOCKFILE_REQUIREMENTS = ["xlrd"]

STREAMLIT_CONFIG = {
    # stlite ignores .streamlit/config.toml; pass the theme explicitly.
    "theme.base": "light",
    "theme.primaryColor": "#0071e3",
    "theme.backgroundColor": "#ffffff",
    "theme.secondaryBackgroundColor": "#f5f5f7",
    "theme.textColor": "#1d1d1f",
    "client.toolbarMode": "viewer",
    "client.showErrorDetails": "full",
}

WEB_MAIN = '''\
"""Generated entrypoint for the browser (stlite) build — do not edit.

Adds the app directories to sys.path, disables the parts that cannot work in
a browser tab, then runs the regular app.py unchanged.
"""

import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent
for _p in (str(_APP_DIR), str(_APP_DIR / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

if sys.platform == "emscripten":
    # The Pyodide filesystem is in-memory: writes "succeed" but vanish on
    # reload. Degrade honestly — no saved profiles, no remember toggle.
    from attendance_tracker import storage

    storage.save_profile = lambda *a, **k: None
    storage.save_ui_prefs = lambda *a, **k: None
    storage.has_profile = lambda *a, **k: False
    storage.load_profile = lambda *a, **k: None
    storage.load_ui_prefs = lambda *a, **k: {}

    import streamlit as st

    # Hide the "Remember these files…" toggle: the promise it makes cannot
    # be kept in the browser build, so it should not render at all.
    _real_toggle = st.toggle

    def _toggle(*args, **kwargs):
        if kwargs.get("key") == "remember_setup":
            return False
        return _real_toggle(*args, **kwargs)

    st.toggle = _toggle
    st.session_state.setdefault("suppress_autoload", True)

import runpy

runpy.run_path(str(_APP_DIR / "app.py"), run_name="__main__")
'''

PAGE_TEMPLATE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Attendance Tracker</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E%F0%9F%8F%AB%3C/text%3E%3C/svg%3E" />
<link rel="stylesheet" href="__STLITE_BASE__/stlite.css" />
<style>
  html, body { margin: 0; height: 100%; background: #ffffff; }
  #root { height: 100%; }
  #boot-note {
    position: fixed; inset: 0; display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 14px;
    background: #ffffff; z-index: 9;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
      Helvetica, Arial, sans-serif;
    color: #1d1d1f; pointer-events: none;
  }
  #boot-note .spin {
    width: 28px; height: 28px; border-radius: 50%;
    border: 3px solid #d2d2d7; border-top-color: #0071e3;
    animation: spin 0.9s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  #boot-note p { margin: 0; font-size: 15px; }
  #boot-note small { color: #6e6e73; }
  #boot-note .privacy {
    max-width: 34rem; text-align: center; line-height: 1.5;
    color: #6e6e73; font-size: 13px; padding: 0 1.5rem;
  }
</style>
</head>
<body>
<div id="boot-note">
  <div class="spin"></div>
  <p>Loading the Attendance Tracker&hellip;</p>
  <small>The first visit downloads the app (about 85&nbsp;MB) and can take a
  minute or two on school Wi&#8209;Fi; after that it starts in seconds.</small>
  <p class="privacy">This page is public like any website, but it contains
  only the app &mdash; no student data. Files you upload are opened and
  analyzed entirely inside your browser on this computer; nothing is ever
  sent to any server, and the site cannot see your data. Closing or
  reloading the tab erases everything, so keep your caseload and report
  files handy.</p>
</div>
<div id="root"></div>
<script>
  // App sources, mounted into the in-browser filesystem at these paths.
  const APP_FILES = __APP_FILES__;
</script>
<script type="module">
  import { mount } from "__STLITE_BASE__/stlite.js";

  const abs = (p) => new URL(p, window.location.href).href;
  const requirements = __REQUIREMENTS__.map(
    (r) => (r.startsWith("./") ? abs(r) : r),
  );

  const options = {
    entrypoint: "web_main.py",
    files: APP_FILES,
    requirements,
    streamlitConfig: __STREAMLIT_CONFIG__,
  };
  __PYODIDE_URL_LINE__

  mount(options, document.getElementById("root"));

  // Hide the static loading note once the app has painted real content.
  const note = document.getElementById("boot-note");
  const root = document.getElementById("root");
  const timer = setInterval(() => {
    if (root.querySelector('[data-testid="stApp"], .stApp, iframe')) {
      note.style.display = "none";
      clearInterval(timer);
    }
  }, 500);
</script>
</body>
</html>
"""


def collect_app_files() -> dict[str, str]:
    """The real app sources, keyed by their repo-relative mount path."""
    files: dict[str, str] = {"web_main.py": WEB_MAIN}
    sources = [REPO / "app.py"]
    sources += sorted((REPO / "ui").rglob("*.py"))
    sources += sorted((REPO / "src" / "attendance_tracker").rglob("*.py"))
    for path in sources:
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(REPO).as_posix()
        files[rel] = path.read_text("utf-8")
    return files


def download(url: str, dest: Path) -> Path:
    """curl a URL into dest (cached: skipped when dest already exists)."""
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  cached: {dest.name}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    subprocess.run(
        ["curl", "-fsSL", "--retry", "3", "-o", str(tmp), url], check=True
    )
    tmp.rename(dest)
    return dest


def lockfile_closure(lock: dict, roots: list[str]) -> dict[str, dict]:
    """Packages reachable from roots via the lockfile's depends graph."""
    packages = lock["packages"]
    norm = {name.lower().replace("_", "-"): name for name in packages}
    keep: dict[str, dict] = {}
    stack = list(roots)
    while stack:
        name = stack.pop().lower().replace("_", "-")
        actual = norm.get(name)
        if actual is None:
            print(f"  WARNING: {name} not in pyodide-lock.json, skipping")
            continue
        if actual in keep:
            continue
        keep[actual] = packages[actual]
        stack.extend(packages[actual].get("depends", []))
    return keep


def vendor_assets(cache: Path) -> None:
    vendor = WEBAPP / "vendor"
    cache.mkdir(parents=True, exist_ok=True)

    # 1. stlite build directory (entry JS + chunks + fonts + wheels).
    stlite_dir = vendor / "stlite"
    if not (stlite_dir / "stlite.js").exists():
        tgz = download(
            STLITE_TGZ_URL, cache / f"stlite-browser-{STLITE_VERSION}.tgz"
        )
        print("  extracting stlite build/")
        with tempfile.TemporaryDirectory(dir=cache) as td:
            with tarfile.open(tgz, "r:gz") as tf:
                tf.extractall(td, filter="data")
            build = Path(td) / "package" / "build"
            if stlite_dir.exists():
                shutil.rmtree(stlite_dir)
            shutil.copytree(build, stlite_dir)
        for m in stlite_dir.rglob("*.map"):
            m.unlink()
    else:
        print("  stlite already vendored")

    # 2. Pyodide core runtime.
    pyodide_dir = vendor / "pyodide"
    if not (pyodide_dir / "pyodide.mjs").exists():
        core = download(
            PYODIDE_CORE_URL,
            cache / f"pyodide-core-{PYODIDE_VERSION}.tar.bz2",
        )
        print("  extracting pyodide core")
        with tempfile.TemporaryDirectory(dir=cache) as td:
            with tarfile.open(core, "r:bz2") as tf:
                tf.extractall(td, filter="data")
            src = Path(td) / "pyodide"
            pyodide_dir.mkdir(parents=True, exist_ok=True)
            for item in src.iterdir():
                target = pyodide_dir / item.name
                if not target.exists():
                    shutil.move(str(item), target)
    else:
        print("  pyodide core already vendored")

    # 3. Lockfile + the wasm/pure wheels the app needs from the recipes
    #    bundle (dependency closure only — not all 400MB of packages).
    lock_path = download(
        RECIPES_LOCK_URL, cache / f"pyodide-lock-{RECIPES_TAG}.json"
    )
    lock = json.loads(lock_path.read_text("utf-8"))
    override_files = set()
    for name, override in LOCK_OVERRIDES.items():
        entry = lock["packages"][name]
        entry["version"] = override["version"]
        entry["file_name"] = override["file_name"]
        entry["sha256"] = override["sha256"]
        entry["depends"] = override["depends"]
        cached = download(override["url"], cache / override["file_name"])
        target = pyodide_dir / override["file_name"]
        if not target.exists():
            shutil.copy2(cached, target)
        override_files.add(override["file_name"])
    keep = lockfile_closure(lock, PYODIDE_ROOT_PACKAGES)
    wanted = {
        info["file_name"] for info in keep.values()
    } - override_files
    missing = [f for f in wanted if not (pyodide_dir / f).exists()]
    if missing:
        pkgs_tgz = download(
            RECIPES_PACKAGES_URL, cache / f"packages-{RECIPES_TAG}.tar.gz"
        )
        print(f"  extracting {len(missing)} wheels from packages.tar.gz")
        with tarfile.open(pkgs_tgz, "r:gz") as tf:
            for member in tf:
                base = Path(member.name).name
                if base in wanted and not (pyodide_dir / base).exists():
                    fobj = tf.extractfile(member)
                    (pyodide_dir / base).write_bytes(fobj.read())
    else:
        print("  pyodide package wheels already vendored")
    # The recipes lockfile is the source of truth for the vendored wheels.
    (pyodide_dir / "pyodide-lock.json").write_text(
        json.dumps(lock), "utf-8"
    )

    # 4. Pure-Python wheels from PyPI.
    wheels_dir = vendor / "wheels"
    wheels_dir.mkdir(parents=True, exist_ok=True)
    for _, url in PYPI_WHEELS:
        name = url.rsplit("/", 1)[1]
        cached = download(url, cache / name)
        target = wheels_dir / name
        if not target.exists():
            shutil.copy2(cached, target)

    print(f"  vendor size: "
          f"{sum(f.stat().st_size for f in vendor.rglob('*') if f.is_file() and cache not in f.parents) / 1e6:.0f} MB"
          )


def build_page(vendored: bool) -> None:
    files = collect_app_files()
    files_json = json.dumps(files, indent=None).replace("<", "\\u003c")

    if vendored:
        stlite_base = "./vendor/stlite"
        requirements = [
            "./vendor/wheels/" + url.rsplit("/", 1)[1]
            for _, url in PYPI_WHEELS
        ] + VENDOR_LOCKFILE_REQUIREMENTS
        pyodide_line = (
            'options.pyodideUrl = abs("./vendor/pyodide/pyodide.mjs");'
        )
    else:
        stlite_base = STLITE_CDN_BASE
        requirements = CDN_REQUIREMENTS
        pyodide_line = "// default Pyodide CDN"

    page = (
        PAGE_TEMPLATE
        .replace("__STLITE_BASE__", stlite_base)
        .replace("__APP_FILES__", files_json)
        .replace("__REQUIREMENTS__", json.dumps(requirements))
        .replace("__STREAMLIT_CONFIG__", json.dumps(STREAMLIT_CONFIG))
        .replace("__PYODIDE_URL_LINE__", pyodide_line)
    )
    WEBAPP.mkdir(exist_ok=True)
    (WEBAPP / "index.html").write_text(page, "utf-8")
    # st.navigation rewrites the URL to /overview, /patterns, ... — on static
    # hosts that serve a 404.html fallback (e.g. GitHub Pages), a reload on
    # those paths must land back on the app instead of a raw 404 page.
    (WEBAPP / "404.html").write_text(page, "utf-8")
    mode = "vendored (local assets)" if vendored else "CDN"
    print(f"wrote {WEBAPP / 'index.html'} and 404.html "
          f"({len(page) / 1024:.0f} KB, {len(files)} app files, {mode})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--vendor", action="store_true",
        help="download all assets into webapp/vendor/ and reference them "
             "locally (fully offline page)",
    )
    parser.add_argument(
        "--cache-dir", type=Path, default=WEBAPP / "vendor" / "_cache",
        help="where downloads are cached (default: webapp/vendor/_cache)",
    )
    args = parser.parse_args()
    if args.vendor:
        print("vendoring assets…")
        vendor_assets(args.cache_dir.resolve())
    build_page(vendored=args.vendor)


if __name__ == "__main__":
    main()
