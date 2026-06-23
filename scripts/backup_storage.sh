#!/usr/bin/env bash
set -euo pipefail

destination="${1:?usage: backup_storage.sh /absolute/backup/directory}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$destination"
docker compose -f compose.production.yaml exec -T app sh -c 'tar -C /app/backend -czf - storage' > "$destination/financial-mining-storage-$timestamp.tgz"
echo "Backup written to $destination/financial-mining-storage-$timestamp.tgz"
