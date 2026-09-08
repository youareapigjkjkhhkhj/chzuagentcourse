#!/usr/bin/env bash
# ============================================================
#  Kaleido backend packaging script (portable, Linux/macOS/GitBash)
#  - Locates the project relative to THIS script's directory.
#  - Requires: JDK 21, Maven 3.8+
#  - Output:   <script dir>/deploy-output/backend/
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
TEMPLATE_DIR="$SCRIPT_DIR/deploy-templates"
OUT_DIR="$SCRIPT_DIR/deploy-output/backend"

[ -f "$BACKEND_DIR/pom.xml" ] || { echo "[ERROR] backend/pom.xml not found next to this script."; exit 1; }

# ---- 1. prerequisite check ----
command -v mvn  >/dev/null || { echo "[ERROR] Maven not found on PATH."; exit 1; }
command -v java >/dev/null || { echo "[ERROR] Java not found on PATH."; exit 1; }
echo "[INFO] Using:"
mvn -v | head -1
java -version 2>&1 | head -1

# ---- 2. production fix: sharding.yaml datasource host ----
SHARD="$BACKEND_DIR/kaleido-common/kaleido-ds/src/main/resources/sharding.yaml"
if grep -q "jdbc:mysql://127.0.0.1:3306/kaleido_" "$SHARD"; then
    sed -i.bak 's|jdbc:mysql://127.0.0.1:3306/kaleido_|jdbc:mysql://mysql:3306/kaleido_|g' "$SHARD"
    echo "[FIX]   sharding.yaml datasource 127.0.0.1 -> mysql (production mode)"
else
    echo "[OK]    sharding.yaml already points to mysql"
fi

# ---- 3. verify spring-boot plugin declared in all 11 poms ----
# (root pom inherits spring-boot-starter-parent, which already
#  binds the repackage goal; declaring the plugin is enough)
MISSING=0
for m in gateway auth admin notice; do
    grep -q "spring-boot-maven-plugin" "$BACKEND_DIR/kaleido-$m/pom.xml" || {
        echo "[ERROR] spring-boot-maven-plugin missing in kaleido-$m/pom.xml"; MISSING=1; }
done
for m in user wardrobe ai tag coin message recommend; do
    grep -q "spring-boot-maven-plugin" "$BACKEND_DIR/kaleido-biz/kaleido-$m/pom.xml" || {
        echo "[ERROR] spring-boot-maven-plugin missing in kaleido-biz/kaleido-$m/pom.xml"; MISSING=1; }
done
[ "$MISSING" -eq 0 ] || {
    echo "[ERROR] Declare spring-boot-maven-plugin in the 11 service poms first (DEPLOY.md 3.1)."; exit 1; }
echo "[OK]    spring-boot plugin declared in all 11 service poms"

# ---- 4. maven package ----
cd "$BACKEND_DIR"
echo "[INFO]  mvn clean package starting (skip tests) ..."
mvn clean package -DskipTests -pl \
 kaleido-gateway,kaleido-auth,kaleido-admin,kaleido-notice,\
 kaleido-biz/kaleido-user,kaleido-biz/kaleido-wardrobe,kaleido-biz/kaleido-ai,\
 kaleido-biz/kaleido-tag,kaleido-biz/kaleido-coin,kaleido-biz/kaleido-message,\
 kaleido-biz/kaleido-recommend -am

# ---- 5. collect jars ----
mkdir -p "$OUT_DIR/jars"
COPIED=0
for m in gateway auth admin notice; do
    cp "$BACKEND_DIR/kaleido-$m/target/kaleido-$m-1.0.0.jar" "$OUT_DIR/jars/" && COPIED=$((COPIED+1))
done
for m in user wardrobe ai tag coin message recommend; do
    cp "$BACKEND_DIR/kaleido-biz/kaleido-$m/target/kaleido-$m-1.0.0.jar" "$OUT_DIR/jars/" && COPIED=$((COPIED+1))
done
[ "$COPIED" -eq 11 ] || { echo "[ERROR] Expected 11 jars, copied $COPIED."; exit 1; }

# ---- 5.1 self-check: jars must point to mysql, never 127.0.0.1 ----
BUILT_SHARD="$BACKEND_DIR/kaleido-common/kaleido-ds/target/classes/sharding.yaml"
if grep -q "jdbc:mysql://127.0.0.1:3306/kaleido_" "$BUILT_SHARD"; then
    echo "[ERROR] Built jars still contain 127.0.0.1:3306 datasource (they will fail inside containers)."
    echo "        This script was bypassed or patch failed. Re-run THIS script, not plain 'mvn package'."
    exit 1
fi
echo "[OK]    built jars datasource points to mysql:3306"

# ---- 6. ship Dockerfile ----
cp "$TEMPLATE_DIR/backend-Dockerfile" "$OUT_DIR/Dockerfile"

echo
echo "============================================================"
echo " Backend packaging DONE. 11 jars + Dockerfile at:"
echo "   $OUT_DIR"
echo " Next: upload to server /opt/kaleido/backend and build"
echo "       images (DEPLOY.md section 6.1)"
echo "============================================================"
