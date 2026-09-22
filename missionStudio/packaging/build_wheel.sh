#!/usr/bin/env bash
#
#  ISC License
#
#  Copyright (c) 2026, Autonomous Vehicle Systems Lab, University of Colorado at Boulder
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
#  THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
#  WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
#  MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
#  ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
#  WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
#  ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
#  OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
#
#
# Builds missionstudio's own wheel + sdist -- the Basilisk-independent part
# of packaging. This has been run for real in this project's development
# sandbox (no Basilisk build there, but none is needed for this step):
#
#     python3 -m pip install build
#     ./packaging/build_wheel.sh
#     # -> dist/missionstudio-<version>-py3-none-any.whl
#     # -> dist/missionstudio-<version>.tar.gz
#
# A real bug was caught doing this the first time: missionstudio/scenarios/
# *.json (the two-body validation scenario) was silently missing from the
# built wheel, because setuptools' packages.find() only picks up Python
# packages (dirs with __init__.py) and scenarios/ has none. Fixed in
# pyproject.toml's [tool.setuptools.package-data] -- see that file's own
# comment. Verified by actually building the wheel, installing it into a
# throwaway venv, and running `missionstudio validate` against the
# installed copy of that file; do the same after any packaging change here.
#
# This script does NOT bundle Basilisk -- see install.sh and this
# directory's README.md for why (this project does not have a Basilisk
# wheel to vendor in this development sandbox; a real release build must
# supply one).

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(dirname "$script_dir")"
dist_dir="${1:-$project_dir/dist}"

cd "$project_dir"

# setuptools' own build backend writes its temp output to ./build (gitignored,
# disposable) -- a stale one left over from a PREVIOUS run of this script
# genuinely breaks the NEXT run: both `python3 -c "import ..."` and
# `python3 -m ...` insert the current directory at the front of sys.path,
# so a leftover ./build/ directory silently SHADOWS the real installed
# `build` package (it has no __main__.py, so `python3 -m build` then fails
# with "No module named build.__main__"). Caught by actually re-running this
# script twice in a row in this project's development sandbox, not a
# hypothetical -- always start from a clean slate here.
rm -rf "$project_dir/build"

if ! python3 -m pip show build >/dev/null 2>&1; then
    echo "Installing the PEP 517 'build' frontend (python3 -m pip install build)..."
    python3 -m pip install --quiet build
fi

echo "Building missionstudio wheel + sdist into $dist_dir ..."
python3 -m build --wheel --sdist --outdir "$dist_dir"

echo
echo "Built:"
ls -1 "$dist_dir"/missionstudio-*
