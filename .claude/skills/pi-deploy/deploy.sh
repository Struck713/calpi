#!/usr/bin/env bash
# Kept for the pi-deploy skill; the real implementation is scripts/pi.
exec "$(cd "$(dirname "$0")/../../.." && pwd)/scripts/pi" deploy "$@"
