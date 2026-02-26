#!/usr/bin/env bash
# check-pii.sh — Pre-commit hook to catch personal IPs, hostnames, and emails
# in staged files. Prevents accidental commits of PII.
#
# Allowlist: .pii-allowlist (one regex per line, comments with #)

set -euo pipefail

RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

ALLOWLIST_FILE=".pii-allowlist"

# --- Patterns to detect ---
# Each entry: "regex|description"
PATTERNS=(
  # Tailscale CGNAT range (100.64.0.0 – 100.127.255.255)
  '\b100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.[0-9]{1,3}\.[0-9]{1,3}\b|Tailscale IP (100.64-127.x.x)'
  # Private IPs: 10.x.x.x
  '\b10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\b|Private IP (10.x.x.x)'
  # Private IPs: 172.16-31.x.x
  '\b172\.(1[6-9]|2[0-9]|3[01])\.[0-9]{1,3}\.[0-9]{1,3}\b|Private IP (172.16-31.x.x)'
  # Private IPs: 192.168.x.x
  '\b192\.168\.[0-9]{1,3}\.[0-9]{1,3}\b|Private IP (192.168.x.x)'
  # Real Tailscale MagicDNS hostnames (not example.ts.net)
  '[a-z0-9-]+\.[a-z0-9]+\.ts\.net\b|Tailscale MagicDNS hostname'
)

# --- Load allowlist ---
ALLOWLIST=()
if [[ -f "$ALLOWLIST_FILE" ]]; then
  while IFS= read -r line; do
    # Skip empty lines and comments
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    ALLOWLIST+=("$line")
  done < "$ALLOWLIST_FILE"
fi

is_allowed() {
  local match="$1"
  for pattern in "${ALLOWLIST[@]}"; do
    if echo "$match" | grep -qE "$pattern"; then
      return 0
    fi
  done
  return 1
}

# --- Scan staged diff ---
DIFF=$(git diff --cached --unified=0 --no-color -- . ':!.pii-allowlist' 2>/dev/null || true)

if [[ -z "$DIFF" ]]; then
  exit 0
fi

FOUND=0
CURRENT_FILE=""

while IFS= read -r line; do
  # Track which file we're in
  if [[ "$line" =~ ^diff\ --git\ a/(.+)\ b/ ]]; then
    CURRENT_FILE="${BASH_REMATCH[1]}"
    continue
  fi

  # Only check added lines
  [[ "$line" =~ ^\+ ]] || continue
  [[ "$line" =~ ^\+\+\+ ]] && continue

  for entry in "${PATTERNS[@]}"; do
    REGEX="${entry%%|*}"
    DESC="${entry##*|}"

    MATCHES=$(echo "$line" | grep -oE "$REGEX" 2>/dev/null || true)
    if [[ -n "$MATCHES" ]]; then
      while IFS= read -r match; do
        [[ -z "$match" ]] && continue
        if ! is_allowed "$match"; then
          if [[ $FOUND -eq 0 ]]; then
            echo -e "${RED}PII Check: Personal data detected in staged changes${NC}"
            echo ""
          fi
          echo -e "  ${YELLOW}${DESC}${NC}: ${RED}${match}${NC}"
          echo "    File: ${CURRENT_FILE}"
          echo "    Line: ${line:1}"
          echo ""
          FOUND=$((FOUND + 1))
        fi
      done <<< "$MATCHES"
    fi
  done
done <<< "$DIFF"

if [[ $FOUND -gt 0 ]]; then
  echo -e "${RED}Found ${FOUND} potential PII match(es).${NC}"
  echo ""
  echo "If these are intentional (example values, documentation), add"
  echo "an allowlist pattern to ${ALLOWLIST_FILE}:"
  echo "  echo '192\\.168\\.1\\.100' >> ${ALLOWLIST_FILE}"
  echo ""
  echo "To bypass this check once: git commit --no-verify"
  exit 1
fi

exit 0
