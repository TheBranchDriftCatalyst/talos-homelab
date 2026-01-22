#!/bin/bash
# Split a file into chunks of specified megabytes
# Usage: chunk-file.sh <file> <chunk_size_mb>
# Example: chunk-file.sh bigfile.tar 10  # splits into 10MB chunks

set -e

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <file> <chunk_size_mb>"
    echo "Example: $0 bigfile.tar 10"
    exit 1
fi

FILE="$1"
CHUNK_MB="$2"

if [[ ! -f "$FILE" ]]; then
    echo "Error: File '$FILE' not found"
    exit 1
fi

BASENAME=$(basename "$FILE")
OUTDIR=$(dirname "$FILE")

echo "Splitting '$FILE' into ${CHUNK_MB}MB chunks..."
split -b "${CHUNK_MB}m" "$FILE" "${OUTDIR}/${BASENAME}.part"

echo "Done! Created:"
ls -lh "${OUTDIR}/${BASENAME}.part"*

echo ""
echo "To reassemble: cat ${BASENAME}.part* > ${BASENAME}"
