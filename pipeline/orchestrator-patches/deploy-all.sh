#!/bin/bash
# /root/deploy-all.sh — build karios-migration from current branch + deploy
# Created v7.39 to fill the missing-deploy gap that prevented Phase 5 from working
set -e
REPO=/root/karios-source-code/karios-migration
BIN_OUT=/usr/local/bin/karios-migration
SVC=karios-migration

echo "[deploy-all] $(date) — start"
cd $REPO
echo "[deploy-all] branch: $(git branch --show-current) | HEAD: $(git rev-parse --short HEAD)"

# Build
echo "[deploy-all] go build..."
go build -o /tmp/karios-migration.new ./cmd/karios-migration/ || { echo "[deploy-all] BUILD FAILED"; exit 2; }
ls -la /tmp/karios-migration.new

# Stop service
echo "[deploy-all] stop service..."
systemctl stop $SVC
sleep 2

# Replace binary
echo "[deploy-all] replace binary..."
cp /tmp/karios-migration.new $BIN_OUT
chmod +x $BIN_OUT

# Start service
echo "[deploy-all] start service..."
systemctl start $SVC
sleep 3

# Verify
echo "[deploy-all] verify..."
systemctl is-active $SVC
sleep 1
curl -sI http://192.168.118.106:8089/api/v1/healthz 2>&1 | head -3 || echo "[deploy-all] healthz check failed (may be normal if route renamed)"

echo "[deploy-all] $(date) — DONE — deployed $(git rev-parse --short HEAD)"
