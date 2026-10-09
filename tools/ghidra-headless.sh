#!/bin/zsh
# Run Ghidra's headless analyzer with the JDK pinned in this project's .sdkmanrc (via SDKMAN).
# Usage: tools/ghidra-headless.sh <analyzeHeadless args...>
set -e
ROOT=${0:A:h:h}  # repo root (holds .sdkmanrc)
SDKMAN_DIR=${SDKMAN_DIR:-/opt/homebrew/opt/sdkman-cli/libexec}
JAVA_VERSION=$(sed -n 's/^java=//p' "$ROOT/.sdkmanrc")
export JAVA_HOME="$SDKMAN_DIR/candidates/java/$JAVA_VERSION"
[[ -x "$JAVA_HOME/bin/java" ]] || { echo "JDK $JAVA_VERSION not installed: sdk install java $JAVA_VERSION" >&2; exit 1; }
exec "$(brew --prefix ghidra)/libexec/support/analyzeHeadless" "$@"
