#!/bin/zsh
set -euo pipefail

SOURCE_DIR="${0:A:h}"
RUNTIME_DIR="${AINEKO_RUNTIME_DIR:-$HOME/Library/Application Support/Aineko/delivery-controller}"
POLICY_DIR="$RUNTIME_DIR/policies"

mkdir -p "$RUNTIME_DIR" "$POLICY_DIR" "$HOME/Library/Logs/Aineko"
cp "$SOURCE_DIR/delivery.py" "$RUNTIME_DIR/delivery.py"
cp "$SOURCE_DIR/workspace.py" "$RUNTIME_DIR/workspace.py"
cp "$SOURCE_DIR"/policies/*.json "$POLICY_DIR/"
chmod +x "$RUNTIME_DIR/delivery.py" "$RUNTIME_DIR/workspace.py"

python3 -m py_compile "$RUNTIME_DIR/delivery.py" "$RUNTIME_DIR/workspace.py"
echo "Aineko delivery runtime synced: $RUNTIME_DIR"
