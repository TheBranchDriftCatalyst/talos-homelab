#!/bin/bash
# Generate Posterizarr overlay PNGs from a color palette
# Usage: ./generate-posterizarr-overlays.sh [output_dir] [--theme synthwave|neon|mono|custom]
#
# Color themes:
#   synthwave - Cyan (#00FFFF) primary, Magenta (#FF00FF) accent
#   neon      - Hot pink (#FF1493) primary, Electric blue (#00BFFF) accent
#   mono      - White (#FFFFFF) primary, Gray (#808080) accent
#   custom    - Use OVERLAY_PRIMARY and OVERLAY_ACCENT env vars

set -e

# Default output directory
OUTPUT_DIR="${1:-/tmp/posterizarr-overlays}"
THEME="${2:-synthwave}"

# Color palettes
declare -A THEMES
THEMES[synthwave_primary]="#00FFFF"
THEMES[synthwave_accent]="#FF00FF"
THEMES[neon_primary]="#FF1493"
THEMES[neon_accent]="#00BFFF"
THEMES[mono_primary]="#FFFFFF"
THEMES[mono_accent]="#808080"

# Parse theme or use custom colors
case "$THEME" in
  --theme)
    THEME="$3"
    ;;
esac

if [[ "$THEME" == "custom" ]]; then
  PRIMARY="${OVERLAY_PRIMARY:-#00FFFF}"
  ACCENT="${OVERLAY_ACCENT:-#FF00FF}"
else
  PRIMARY="${THEMES[${THEME}_primary]:-#00FFFF}"
  ACCENT="${THEMES[${THEME}_accent]:-#FF00FF}"
fi

echo "=== Posterizarr Overlay Generator ==="
echo "Theme: $THEME"
echo "Primary color: $PRIMARY"
echo "Accent color: $ACCENT"
echo "Output: $OUTPUT_DIR"
echo ""

mkdir -p "$OUTPUT_DIR"

# Generate poster overlay (1000x1500)
echo "Creating poster overlay (1000x1500)..."
magick -size 1000x1500 xc:transparent \
  \( -size 1000x1500 xc:transparent \
     -stroke "$PRIMARY" -strokewidth 60 -fill none \
     -draw "rectangle 30,30 970,1470" \
     -blur 0x25 \
     -channel A -evaluate multiply 0.5 +channel \
  \) -composite \
  \( -size 1000x1500 xc:transparent \
     -stroke "$PRIMARY" -strokewidth 30 -fill none \
     -draw "rectangle 15,15 985,1485" \
     -blur 0x15 \
     -channel A -evaluate multiply 0.7 +channel \
  \) -composite \
  \( -size 1000x1500 xc:transparent \
     -stroke "$PRIMARY" -strokewidth 4 -fill none \
     -draw "roundrectangle 6,6 994,1494 8,8" \
     -blur 0x3 \
  \) -composite \
  \( -size 1000x1500 xc:transparent \
     -stroke "$PRIMARY" -strokewidth 2 -fill none \
     -draw "roundrectangle 6,6 994,1494 8,8" \
  \) -composite \
  "$OUTPUT_DIR/overlay-${THEME}.png"

# Generate background overlay (1920x1080)
echo "Creating background overlay (1920x1080)..."
magick -size 1920x1080 xc:transparent \
  \( -size 1920x1080 xc:transparent \
     -stroke "$PRIMARY" -strokewidth 80 -fill none \
     -draw "rectangle 40,40 1880,1040" \
     -blur 0x30 \
     -channel A -evaluate multiply 0.5 +channel \
  \) -composite \
  \( -size 1920x1080 xc:transparent \
     -stroke "$PRIMARY" -strokewidth 40 -fill none \
     -draw "rectangle 20,20 1900,1060" \
     -blur 0x18 \
     -channel A -evaluate multiply 0.7 +channel \
  \) -composite \
  \( -size 1920x1080 xc:transparent \
     -stroke "$PRIMARY" -strokewidth 4 -fill none \
     -draw "roundrectangle 8,8 1912,1072 10,10" \
     -blur 0x3 \
  \) -composite \
  \( -size 1920x1080 xc:transparent \
     -stroke "$PRIMARY" -strokewidth 2 -fill none \
     -draw "roundrectangle 8,8 1912,1072 10,10" \
  \) -composite \
  "$OUTPUT_DIR/backgroundoverlay-${THEME}.png"

# Generate season overlay (same as poster)
echo "Creating season overlay..."
cp "$OUTPUT_DIR/overlay-${THEME}.png" "$OUTPUT_DIR/seasonoverlay-${THEME}.png"

# Generate title card overlay (1920x1080, same as background)
echo "Creating title card overlay..."
cp "$OUTPUT_DIR/backgroundoverlay-${THEME}.png" "$OUTPUT_DIR/titlecardoverlay-${THEME}.png"

# Generate collection overlay (1000x1500, same as poster)
echo "Creating collection overlay..."
cp "$OUTPUT_DIR/overlay-${THEME}.png" "$OUTPUT_DIR/collectionoverlay-${THEME}.png"

echo ""
echo "=== Generated overlays ==="
ls -lh "$OUTPUT_DIR"/*.png

echo ""
echo "=== Posterizarr config snippet ==="
cat << EOF
"PrerequisitePart": {
  "overlayfile": "/config/overlays/overlay-${THEME}.png",
  "seasonoverlayfile": "/config/overlays/seasonoverlay-${THEME}.png",
  "collectionoverlayfile": "/config/overlays/collectionoverlay-${THEME}.png",
  "backgroundoverlayfile": "/config/overlays/backgroundoverlay-${THEME}.png",
  "titlecardoverlayfile": "/config/overlays/titlecardoverlay-${THEME}.png"
}
EOF

echo ""
echo "To upload to Posterizarr pod:"
echo "  kubectl cp $OUTPUT_DIR media/\$(kubectl get pod -n media -l app=posterizarr -o jsonpath='{.items[0].metadata.name}'):/config/overlays/"
