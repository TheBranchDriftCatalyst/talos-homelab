#!/bin/bash
# Split a video into playable clips of approximately X megabytes each
# Usage: chunk-video.sh <video_file> <chunk_size_mb>
# Example: chunk-video.sh movie.mp4 10  # splits into ~10MB playable clips

set -e

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <video_file> <chunk_size_mb>"
    echo "Example: $0 movie.mp4 10"
    exit 1
fi

FILE="$1"
CHUNK_MB="$2"

if [[ ! -f "$FILE" ]]; then
    echo "Error: File '$FILE' not found"
    exit 1
fi

# Get file size in MB
FILE_SIZE_MB=$(du -m "$FILE" | cut -f1)

# Get video duration in seconds
DURATION=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$FILE")
DURATION=${DURATION%.*}  # Remove decimals

# Calculate number of chunks and duration per chunk
NUM_CHUNKS=$(( (FILE_SIZE_MB + CHUNK_MB - 1) / CHUNK_MB ))
CHUNK_DURATION=$(( DURATION / NUM_CHUNKS ))

BASENAME="${FILE%.*}"
EXT="${FILE##*.}"

echo "File: $FILE (${FILE_SIZE_MB}MB, ${DURATION}s)"
echo "Splitting into $NUM_CHUNKS clips of ~${CHUNK_DURATION}s each..."
echo ""

for ((i=0; i<NUM_CHUNKS; i++)); do
    START=$((i * CHUNK_DURATION))
    OUTFILE="${BASENAME}_part$((i+1)).${EXT}"

    echo "Creating clip $((i+1))/$NUM_CHUNKS: $OUTFILE (start: ${START}s)"

    if [[ $i -eq $((NUM_CHUNKS - 1)) ]]; then
        # Last chunk - go to end
        ffmpeg -y -hide_banner -loglevel warning -i "$FILE" -ss "$START" -c copy "$OUTFILE"
    else
        ffmpeg -y -hide_banner -loglevel warning -i "$FILE" -ss "$START" -t "$CHUNK_DURATION" -c copy "$OUTFILE"
    fi
done

echo ""
echo "Done! Created:"
ls -lh "${BASENAME}_part"*
