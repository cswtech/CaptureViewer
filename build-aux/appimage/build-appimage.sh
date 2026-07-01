#!/usr/bin/env bash
# Builds a self-contained AppImage for CaptureViewer.
#
# Unlike the Flatpak build, this vendors the Python interpreter, PyGObject,
# GTK4/libadwaita, GStreamer (+ the plugins the app uses) and even glibc's
# dynamic linker straight from the build machine, so the result runs on a
# target machine that has none of this installed. It must therefore be run
# on a machine that already has everything from install-deps.sh installed
# (this *is* how the app's dependencies get captured).
#
# Portability note: the produced AppImage requires a target glibc at least as
# new as the build machine's. Build on the oldest/most common distro you can
# to maximize compatibility (ideally inside an old-LTS container); building
# on a bleeding-edge distro produces an AppImage that won't run on older ones.
#
# Usage: ./build-aux/appimage/build-appimage.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$ROOT/build-aux/appimage"
APPDIR="$WORK/AppDir"
OUT="$WORK/out"
TOOLS="$WORK/tools"
APP_ID="io.github.chamithshehan.CaptureViewer"
PYVER="3.14"
MULTIARCH="x86_64-linux-gnu"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"

command -v ldd >/dev/null || { echo "ldd not found" >&2; exit 1; }
[[ -x "/usr/bin/python$PYVER" ]] || { echo "python$PYVER not found at /usr/bin" >&2; exit 1; }

rm -rf "$APPDIR"
mkdir -p "$APPDIR"/usr/bin "$APPDIR"/usr/lib "$OUT" "$TOOLS"
mkdir -p "$APPDIR/usr/share/applications" "$APPDIR/usr/share/metainfo"
mkdir -p "$APPDIR/usr/share/icons/hicolor/scalable/apps"
LIBDIR="$APPDIR/usr/lib"
PYSITE="$APPDIR/usr/lib/python$PYVER/site-packages"

echo "== python interpreter + stdlib =="
cp "/usr/bin/python$PYVER" "$APPDIR/usr/bin/"
cp -a "/usr/lib/python$PYVER" "$APPDIR/usr/lib/"
rm -rf "$APPDIR/usr/lib/python$PYVER"/{test,idlelib,tkinter,turtledemo}
find "$APPDIR/usr/lib/python$PYVER" -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
mkdir -p "$PYSITE"

echo "== PyGObject (gi) =="
cp -a /usr/lib/python3/dist-packages/gi "$PYSITE/"
find "$PYSITE/gi" -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

echo "== captureviewer app source =="
cp -a "$ROOT/captureviewer" "$PYSITE/"
find "$PYSITE/captureviewer" -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

echo "== GObject-Introspection typelibs =="
mkdir -p "$LIBDIR/girepository-1.0"
cp -a "/usr/lib/$MULTIARCH/girepository-1.0/"*.typelib "$LIBDIR/girepository-1.0/"

echo "== GStreamer plugins + scanner =="
mkdir -p "$LIBDIR/gstreamer-1.0"
cp -a "/usr/lib/$MULTIARCH/gstreamer-1.0/"*.so "$LIBDIR/gstreamer-1.0/"
cp -a "/usr/lib/$MULTIARCH/gstreamer1.0/gstreamer-1.0/gst-plugin-scanner" "$APPDIR/usr/bin/"

echo "== gdk-pixbuf loaders =="
mkdir -p "$LIBDIR/gdk-pixbuf-2.0/loaders"
cp -a "/usr/lib/$MULTIARCH/gdk-pixbuf-2.0/2.10.0/loaders/"*.so "$LIBDIR/gdk-pixbuf-2.0/loaders/"
"/usr/lib/$MULTIARCH/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders" "$LIBDIR/gdk-pixbuf-2.0/loaders/"*.so \
  | sed "s#$LIBDIR/gdk-pixbuf-2.0/loaders#APPDIR_PLACEHOLDER/usr/lib/gdk-pixbuf-2.0/loaders#g" \
  > "$LIBDIR/gdk-pixbuf-2.0/loaders.cache.in"

echo "== icon themes + glib schemas =="
cp -a /usr/share/icons/Adwaita "$APPDIR/usr/share/icons/"
cp -a /usr/share/icons/hicolor "$APPDIR/usr/share/icons/"
mkdir -p "$APPDIR/usr/share/glib-2.0/schemas"
cp -a /usr/share/glib-2.0/schemas/gschemas.compiled "$APPDIR/usr/share/glib-2.0/schemas/" 2>/dev/null || true

echo "== app metadata (desktop, metainfo, icon) =="
cp "$ROOT/data/$APP_ID.desktop" "$APPDIR/"
cp "$ROOT/data/$APP_ID.desktop" "$APPDIR/usr/share/applications/"
cp "$ROOT/data/$APP_ID.metainfo.xml" "$APPDIR/usr/share/metainfo/"
cp "$ROOT/data/icons/$APP_ID.svg" "$APPDIR/$APP_ID.svg"
cp "$ROOT/data/icons/$APP_ID.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/"
"/usr/bin/python$PYVER" -c "
import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf
p = GdkPixbuf.Pixbuf.new_from_file_at_scale('$ROOT/data/icons/$APP_ID.svg', 256, 256, True)
p.savev('$APPDIR/$APP_ID.png', 'png', [], [])
"
cp "$APPDIR/$APP_ID.png" "$APPDIR/.DirIcon"

echo "== resolving shared library closure =="
declare -A SEEN
copy_dep() {
  local src="$1" base
  base="$(basename "$src")"
  [[ -n "${SEEN[$base]:-}" ]] && return
  SEEN[$base]=1
  cp -n "$src" "$LIBDIR/" 2>/dev/null || true
  local dep
  while IFS= read -r dep; do
    [[ -z "$dep" ]] && continue
    copy_dep "$dep"
  done < <(ldd "$src" 2>/dev/null | awk '/=> \// {print $3}')
}
walk_seed() {
  local src="$1" dep
  while IFS= read -r dep; do
    [[ -z "$dep" ]] && continue
    copy_dep "$dep"
  done < <(ldd "$src" 2>/dev/null | awk '/=> \// {print $3}')
}

copy_dep "/lib64/ld-linux-x86-64.so.2"
walk_seed "$APPDIR/usr/bin/python$PYVER"
walk_seed "$APPDIR/usr/bin/gst-plugin-scanner"
walk_seed "/usr/lib/$MULTIARCH/libgtk-4.so.1"
walk_seed "/usr/lib/$MULTIARCH/libadwaita-1.so.0"
copy_dep "/usr/lib/$MULTIARCH/libgtk-4.so.1"
copy_dep "/usr/lib/$MULTIARCH/libadwaita-1.so.0"
for f in "$APPDIR"/usr/lib/python"$PYVER"/lib-dynload/*.so \
         "$PYSITE"/gi/*.so \
         "$LIBDIR"/gstreamer-1.0/*.so \
         "$LIBDIR"/gdk-pixbuf-2.0/loaders/*.so; do
  walk_seed "$f"
done

echo "== validating dependency closure =="
missing=0
while IFS= read -r -d '' f; do
  out="$(LD_LIBRARY_PATH="$LIBDIR" ldd "$f" 2>/dev/null || true)"
  if grep -q "not found" <<<"$out"; then
    echo "MISSING deps for $f:"
    grep "not found" <<<"$out"
    missing=1
  fi
done < <(find "$APPDIR" -name "*.so*" -print0; find "$APPDIR/usr/bin" -type f -print0)
if [[ "$missing" -ne 0 ]]; then
  echo "One or more libraries are missing from the bundle (see above)." >&2
  exit 1
fi

echo "== writing AppRun =="
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/usr/bin/env bash
set -e
HERE="$(dirname "$(readlink -f "${0}")")"

export LD_LIBRARY_PATH="$HERE/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export GI_TYPELIB_PATH="$HERE/usr/lib/girepository-1.0"
export GST_PLUGIN_PATH="$HERE/usr/lib/gstreamer-1.0"
export GST_PLUGIN_SYSTEM_PATH_1_0=""
export GST_PLUGIN_SYSTEM_PATH=""
export GST_REGISTRY_FORK="no"
export GST_PLUGIN_SCANNER="$HERE/usr/bin/gst-plugin-scanner"
export XDG_DATA_DIRS="$HERE/usr/share${XDG_DATA_DIRS:+:$XDG_DATA_DIRS}"
export GSETTINGS_SCHEMA_DIR="$HERE/usr/share/glib-2.0/schemas"
export PYTHONHOME="$HERE/usr"
export PYTHONPATH="$HERE/usr/lib/python3.14:$HERE/usr/lib/python3.14/lib-dynload:$HERE/usr/lib/python3.14/site-packages"
export PYTHONDONTWRITEBYTECODE=1

CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/captureviewer-appimage"
mkdir -p "$CACHE_DIR"
export GST_REGISTRY="$CACHE_DIR/gstreamer-1.0-registry.bin"
sed "s#APPDIR_PLACEHOLDER#$HERE#g" "$HERE/usr/lib/gdk-pixbuf-2.0/loaders.cache.in" > "$CACHE_DIR/loaders.cache"
export GDK_PIXBUF_MODULE_FILE="$CACHE_DIR/loaders.cache"

exec "$HERE/usr/lib/ld-linux-x86-64.so.2" --library-path "$HERE/usr/lib" \
  "$HERE/usr/bin/python3.14" -m captureviewer "$@"
APPRUN
chmod +x "$APPDIR/AppRun"
chmod +x "$APPDIR/usr/bin/python$PYVER" "$APPDIR/usr/bin/gst-plugin-scanner"

echo "== fetching appimagetool =="
if [[ ! -x "$TOOLS/appimagetool.AppImage" ]]; then
  curl -fL --retry 3 -o "$TOOLS/appimagetool.AppImage" "$APPIMAGETOOL_URL"
  chmod +x "$TOOLS/appimagetool.AppImage"
fi

echo "== packaging AppImage =="
ARCH=x86_64 "$TOOLS/appimagetool.AppImage" --appimage-extract-and-run "$APPDIR" "$OUT/CaptureViewer-x86_64.AppImage"

echo
echo "Done: $OUT/CaptureViewer-x86_64.AppImage"
du -h "$OUT/CaptureViewer-x86_64.AppImage"
