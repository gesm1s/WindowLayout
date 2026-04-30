#!/bin/bash
# WindowLayout — installasjonsscript
# Kjør med: bash install.sh

set -e

APP_NAME="WindowLayout.app"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$SCRIPT_DIR/$APP_NAME"
DEST="/Applications/$APP_NAME"

if [ ! -d "$SRC" ]; then
    echo "Feil: Finner ikke $APP_NAME i samme mappe som scriptet."
    echo "Pass på at du har pakket ut ZIP-filen og kjører install.sh derfra."
    exit 1
fi

echo "Installerer $APP_NAME..."
rm -rf "$DEST"
ditto "$SRC" "$DEST"
xattr -cr "$DEST"
echo "Ferdig! Start WindowLayout fra Launchpad eller Finder → Programmer."
echo ""
echo "Husk: Første gang må du gi tilgang under Systeminnstillinger → Personvern og sikkerhet → Tilgjengelighet."
