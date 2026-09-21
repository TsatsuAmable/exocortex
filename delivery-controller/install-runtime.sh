#!/bin/zsh
set -euo pipefail

SOURCE_DIR="${0:A:h}"
RUNTIME_DIR="${AINEKO_RUNTIME_DIR:-$HOME/Library/Application Support/Aineko/delivery-controller}"
POLICY_DIR="$RUNTIME_DIR/policies"

mkdir -p "$RUNTIME_DIR" "$POLICY_DIR" "$HOME/Library/Logs/Aineko"
cp "$SOURCE_DIR/delivery.py" "$RUNTIME_DIR/delivery.py"
cp "$SOURCE_DIR/workspace.py" "$RUNTIME_DIR/workspace.py"
cp "$SOURCE_DIR/nemosyne_continuous.py" "$RUNTIME_DIR/nemosyne_continuous.py"
cp "$SOURCE_DIR/tick_all.py" "$RUNTIME_DIR/tick_all.py"
cp "$SOURCE_DIR/autopilot.py" "$RUNTIME_DIR/autopilot.py"
cp "$SOURCE_DIR/webhook.py" "$RUNTIME_DIR/webhook.py"
cp "$SOURCE_DIR"/policies/*.json "$POLICY_DIR/"
chmod +x "$RUNTIME_DIR/delivery.py" "$RUNTIME_DIR/workspace.py" "$RUNTIME_DIR/nemosyne_continuous.py" "$RUNTIME_DIR/tick_all.py" "$RUNTIME_DIR/autopilot.py" "$RUNTIME_DIR/webhook.py"

python3 -m py_compile "$RUNTIME_DIR/delivery.py" "$RUNTIME_DIR/workspace.py" "$RUNTIME_DIR/nemosyne_continuous.py" "$RUNTIME_DIR/tick_all.py" "$RUNTIME_DIR/autopilot.py" "$RUNTIME_DIR/webhook.py"
echo "Aineko delivery runtime synced: $RUNTIME_DIR"
