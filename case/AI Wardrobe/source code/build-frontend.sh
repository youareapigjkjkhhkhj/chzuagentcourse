#!/usr/bin/env bash
# ============================================================
#  Kaleido frontend packaging script (portable, Linux/macOS/GitBash)
#  - Locates the project relative to THIS script's directory.
#  - Requires: Node 18+, pnpm 8.x
#  - Output:   <script dir>/deploy-output/frontend/
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
TEMPLATE_DIR="$SCRIPT_DIR/deploy-templates"
OUT_DIR="$SCRIPT_DIR/deploy-output/frontend"

[ -f "$FRONTEND_DIR/package.json" ] || { echo "[ERROR] frontend/package.json not found next to this script."; exit 1; }

# ---- 1. prerequisite check ----
command -v node >/dev/null || { echo "[ERROR] Node not found. Install Node 18+."; exit 1; }
command -v pnpm >/dev/null || { echo "[ERROR] pnpm not found. Install: npm install -g pnpm"; exit 1; }
echo "[INFO] Node $(node -v) / pnpm $(pnpm -v)"

# ---- 2. production env fix: disable mock ----
ENVPRO="$FRONTEND_DIR/.env.pro"
if [ -f "$ENVPRO" ] && grep -q "VITE_USE_MOCK=true" "$ENVPRO"; then
    sed -i.bak 's/VITE_USE_MOCK=true/VITE_USE_MOCK=false/g' "$ENVPRO"
    echo "[FIX]   .env.pro VITE_USE_MOCK=true -> false"
else
    echo "[OK]    .env.pro VITE_USE_MOCK already false"
fi

# ---- 3. install & build ----
cd "$FRONTEND_DIR"
echo "[INFO]  pnpm install ..."
pnpm install
echo "[INFO]  pnpm run build:pro ..."
pnpm run build:pro
[ -d "$FRONTEND_DIR/dist-pro" ] || { echo "[ERROR] dist-pro not generated."; exit 1; }

# ---- 4. collect artifacts ----
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"
cp -r "$FRONTEND_DIR/dist-pro" "$OUT_DIR/dist-pro"
cp "$TEMPLATE_DIR/frontend-Dockerfile" "$OUT_DIR/Dockerfile"
cp "$TEMPLATE_DIR/nginx.conf" "$OUT_DIR/nginx.conf"

echo
echo "============================================================"
echo " Frontend packaging DONE. dist-pro + Dockerfile + nginx.conf:"
echo "   $OUT_DIR"
echo " Next: upload to server /opt/kaleido/frontend and build"
echo "       image (DEPLOY.md section 6.2)"
echo "============================================================"
