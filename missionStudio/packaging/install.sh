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
# End-user Linux installer: creates a private virtualenv, installs
# missionstudio (+ the 'gui' extra) into it, installs a vendored Basilisk
# wheel into the SAME venv if one is given, and drops a launcher script.
#
# This is the "vendor a prebuilt wheel pinned to a specific Basilisk
# release/commit" default install path flagged in missionStudio/README.md
# since Phase 0. It has been run and verified for the missionstudio-only
# path in this project's development sandbox (build a wheel with
# build_wheel.sh, run this script against it, launch `missionstudio
# validate` from the installed venv); the Basilisk-wheel path is written
# against pip's ordinary wheel-install behavior (nothing missionstudio
# -specific) but could NOT be verified end-to-end here, because this
# sandbox has no built Basilisk wheel to test against (see the main
# README's "Environment honesty note" -- the same Conan Center network
# block that stopped a from-source Basilisk build also means there is no
# vendorable wheel sitting around here to test this script's other path
# with). See this directory's README.md for the full picture.
#
# Usage:
#   ./install.sh [--prefix DIR] [--basilisk-wheel PATH_OR_URL] [--missionstudio-wheel PATH] [--no-desktop-entry]
#
#   --prefix DIR               Where to create the venv (default: ~/.local/share/missionstudio)
#   --basilisk-wheel PATH      Path or URL to a prebuilt Basilisk wheel to vendor into the venv.
#                               Omit this and the script installs missionstudio only, with a
#                               clear note that Run/Check Kernels/Monte Carlo won't work until
#                               a Basilisk build is added to the venv some other way.
#   --missionstudio-wheel PATH Install this local wheel instead of building/fetching one
#                               (defaults to running build_wheel.sh next to this script).
#   --no-desktop-entry          Skip installing a ~/.local/share/applications/*.desktop entry.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(dirname "$script_dir")"

prefix="${HOME}/.local/share/missionstudio"
basilisk_wheel=""
missionstudio_wheel=""
install_desktop_entry=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prefix) prefix="$2"; shift 2 ;;
        --basilisk-wheel) basilisk_wheel="$2"; shift 2 ;;
        --missionstudio-wheel) missionstudio_wheel="$2"; shift 2 ;;
        --no-desktop-entry) install_desktop_entry=0; shift ;;
        -h|--help)
            sed -n '/^# Usage:/,/^set -euo/p' "$0" | sed '$d; s/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

venv_dir="$prefix/venv"
echo "Creating virtualenv at $venv_dir ..."
python3 -m venv "$venv_dir"
# shellcheck source=/dev/null
source "$venv_dir/bin/activate"
python3 -m pip install --quiet --upgrade pip

if [[ -z "$missionstudio_wheel" ]]; then
    echo "No --missionstudio-wheel given -- building one with build_wheel.sh ..."
    "$script_dir/build_wheel.sh" "$prefix/dist"
    # Newest-BUILT, not lexicographically-last: build_wheel.sh never cleans
    # its output directory, so re-running this script against the same
    # --prefix after a version bump leaves old and new wheels side by side
    # (e.g. missionstudio-1.10.0-*.whl and missionstudio-1.9.0-*.whl) --
    # plain `ls | tail -n1` string-sorts "1.10.0" before "1.9.0" ('1' <
    # '9' at the first differing character) and would silently pick the
    # OLDER wheel. `ls -t` sorts by modification time instead, so the one
    # build_wheel.sh just built above is always first.
    missionstudio_wheel=$(ls -1t "$prefix"/dist/missionstudio-*.whl | head -n1)
fi

echo "Installing missionstudio (+ gui extra) from $missionstudio_wheel ..."
python3 -m pip install --quiet "${missionstudio_wheel}[gui]"

if [[ -n "$basilisk_wheel" ]]; then
    echo "Installing vendored Basilisk wheel from $basilisk_wheel ..."
    python3 -m pip install --quiet "$basilisk_wheel"
    basilisk_status="Basilisk was installed into this venv from: $basilisk_wheel"
else
    basilisk_status="No Basilisk wheel was provided (--basilisk-wheel) -- 'missionstudio validate' and the
GUI will open, but Run/Check Kernels/Monte Carlo need a Basilisk build on this venv's
PYTHONPATH. Re-run this script with --basilisk-wheel, or 'pip install' one into
$venv_dir yourself, once you have one."
fi

launcher="$prefix/missionstudio"
cat > "$launcher" <<EOF
#!/usr/bin/env bash
source "$venv_dir/bin/activate"
exec missionstudio "\$@"
EOF
chmod +x "$launcher"

if [[ "$install_desktop_entry" -eq 1 ]] && [[ -n "${XDG_DATA_HOME:-${HOME:-}}" ]]; then
    applications_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    mkdir -p "$applications_dir"
    sed "s|@INSTALL_PREFIX@|$prefix|g" "$script_dir/missionstudio.desktop.in" > "$applications_dir/missionstudio.desktop"
    desktop_status="Desktop entry installed to $applications_dir/missionstudio.desktop"

    # Renders the app icon (gui/icons.py -- procedurally drawn via
    # QPainter, no bitmap asset shipped in the repo) into the standard
    # XDG hicolor icon theme location, so Icon=missionstudio in the
    # .desktop entry above resolves to it instead of falling back to a
    # generic icon. Needs the 'gui' extra (PySide6, just installed above)
    # and a Qt platform plugin able to render off-screen, which the
    # 'offscreen' plugin always provides -- no display/X server needed,
    # even on a headless install. Non-fatal: a failure here (e.g. no Qt
    # platform plugins at all) still leaves a working desktop entry, just
    # with the generic fallback icon.
    icons_dir="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"
    mkdir -p "$icons_dir"
    if QT_QPA_PLATFORM=offscreen python3 -c "
from missionstudio.gui.icons import ensure_icon_file
ensure_icon_file('$icons_dir/missionstudio.png')
" 2>/dev/null; then
        icon_status="App icon installed to $icons_dir/missionstudio.png"
    else
        icon_status="Could not render the app icon (non-fatal) -- the desktop entry will use a generic icon."
    fi
else
    desktop_status="Desktop entry skipped."
    icon_status=""
fi

echo
echo "Installed missionstudio to $venv_dir"
echo "$desktop_status"
if [[ -n "$icon_status" ]]; then
    echo "$icon_status"
fi
echo "$basilisk_status"
echo
echo "Launch it with: $launcher gui"
echo "(or: source $venv_dir/bin/activate && missionstudio gui)"
