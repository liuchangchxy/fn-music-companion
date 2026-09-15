#!/bin/bash
set -eu

APPDEST="${TRIM_APPDEST:-/var/apps/fn-music-companion/target}"
PKGVAR="${TRIM_PKGVAR:-/var/apps/fn-music-companion/var}"
DOCKER_DIR="${APPDEST}/docker"
AUTH_FILE="${PKGVAR}/authorized-paths"
OVERRIDE_FILE="${DOCKER_DIR}/docker-compose.override.yaml"
COMPOSE_FILE="${DOCKER_DIR}/docker-compose.yaml"

mkdir -p "${PKGVAR}"

# 1. Parse TRIM_DATA_ACCESSIBLE_PATHS into array
IFS=':' read -r -a RAW_PATHS <<< "${TRIM_DATA_ACCESSIBLE_PATHS:-}"

CLEAN_PATHS=()
for p in "${RAW_PATHS[@]}"; do
  # Trim whitespace
  p="$(echo "$p" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  if [ -n "$p" ] && [ -d "$p" ]; then
    CLEAN_PATHS+=("$p")
  fi
done

# 2. Save authorized paths to PKGVAR for backend reading
TMP_AUTH="${AUTH_FILE}.tmp.$$"
: > "$TMP_AUTH"
for p in "${CLEAN_PATHS[@]}"; do
  echo "$p" >> "$TMP_AUTH"
done
mv -f "$TMP_AUTH" "$AUTH_FILE"

# 3. Detect source (ro) and output (rw) roles if configured
SRC_DIR=""
OUT_DIR=""
ROLES_FILE="${PKGVAR}/mount-roles.json"
CONFIG_FILE="${PKGVAR}/v6-state/config.json"
if [ -f "$ROLES_FILE" ]; then
  SRC_DIR="$(grep -o '"source_dir"[[:space:]]*:[[:space:]]*"[^"]*"' "$ROLES_FILE" | head -n1 | cut -d'"' -f4 || true)"
  OUT_DIR="$(grep -o '"output_dir"[[:space:]]*:[[:space:]]*"[^"]*"' "$ROLES_FILE" | head -n1 | cut -d'"' -f4 || true)"
elif [ -f "$CONFIG_FILE" ]; then
  SRC_DIR="$(grep -o '"source_dir"[[:space:]]*:[[:space:]]*"[^"]*"' "$CONFIG_FILE" | head -n1 | cut -d'"' -f4 || true)"
  OUT_DIR="$(grep -o '"output_dir"[[:space:]]*:[[:space:]]*"[^"]*"' "$CONFIG_FILE" | head -n1 | cut -d'"' -f4 || true)"
fi

# 4. Generate docker-compose.override.yaml
if [ -d "$DOCKER_DIR" ]; then
  TMP_OVERRIDE="${OVERRIDE_FILE}.tmp.$$"
  {
    echo "services:"
    echo "  organizer:"
    echo "    environment:"
    echo "      TRIM_DATA_ACCESSIBLE_PATHS: \"${TRIM_DATA_ACCESSIBLE_PATHS:-}\""
    if [ "${#CLEAN_PATHS[@]}" -gt 0 ]; then
      echo "    volumes:"
      for p in "${CLEAN_PATHS[@]}"; do
        IS_OUT=0
        if [ -n "$OUT_DIR" ]; then
          case "$p" in
            "$OUT_DIR"|"$OUT_DIR"/*) IS_OUT=1 ;;
            *)
              case "$OUT_DIR" in
                "$p"/*) IS_OUT=1 ;;
              esac
              ;;
          esac
        fi

        IS_SRC=0
        if [ -n "$SRC_DIR" ]; then
          case "$p" in
            "$SRC_DIR"|"$SRC_DIR"/*) IS_SRC=1 ;;
            *)
              case "$SRC_DIR" in
                "$p"/*) IS_SRC=1 ;;
              esac
              ;;
          esac
        fi

        if [ "$IS_SRC" -eq 1 ] && [ "$IS_OUT" -eq 0 ]; then
          echo "      - \"${p}:${p}:ro\""
        else
          echo "      - \"${p}:${p}:rw\""
        fi
      done
    fi
  } > "$TMP_OVERRIDE"
  mv -f "$TMP_OVERRIDE" "$OVERRIDE_FILE"

  # 4. Trigger docker compose up to apply mounts dynamically
  if [ -f "$COMPOSE_FILE" ] && command -v docker >/dev/null 2>&1; then
    export TRIM_PKGVAR="${PKGVAR}"
    docker compose -p fn-music-companion -f "$COMPOSE_FILE" -f "$OVERRIDE_FILE" up -d --remove-orphans >/dev/null 2>&1 || true
  fi
fi

exit 0
