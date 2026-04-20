#!/bin/bash
set -e

LF_DIR=/opt/langfuse
mkdir -p $LF_DIR
cd $LF_DIR

# Generate one-shot secrets
PG_PW=$(openssl rand -base64 24 | tr -d '/=+' | head -c 32)
NEXTAUTH_SECRET=$(openssl rand -base64 32)
SALT=$(openssl rand -base64 32)
ENCRYPTION_KEY=$(openssl rand -hex 32)
INIT_USER_PASSWORD=$(openssl rand -base64 16 | tr -d '/=+' | head -c 16)
LF_PUBLIC_KEY="pk-lf-$(openssl rand -hex 16)"
LF_SECRET_KEY="sk-lf-$(openssl rand -hex 16)"

# Save the credentials we need to read back AFTER init
cat > $LF_DIR/.bootstrap.env <<EOF
LANGFUSE_HOST=http://192.168.118.106:3000
LANGFUSE_PUBLIC_KEY=$LF_PUBLIC_KEY
LANGFUSE_SECRET_KEY=$LF_SECRET_KEY
LANGFUSE_INIT_USER_EMAIL=ops@karios.local
LANGFUSE_INIT_USER_PASSWORD=$INIT_USER_PASSWORD
EOF
chmod 600 $LF_DIR/.bootstrap.env

cat > $LF_DIR/docker-compose.yml <<COMPOSE
services:
  langfuse-db:
    image: postgres:15
    restart: always
    environment:
      POSTGRES_USER: langfuse
      POSTGRES_PASSWORD: $PG_PW
      POSTGRES_DB: langfuse
    volumes:
      - langfuse-db-data:/var/lib/postgresql/data
    ports:
      - "127.0.0.1:54320:5432"

  langfuse:
    image: langfuse/langfuse:2
    restart: always
    depends_on:
      - langfuse-db
    environment:
      DATABASE_URL: postgresql://langfuse:$PG_PW@langfuse-db:5432/langfuse
      NEXTAUTH_URL: http://192.168.118.106:3000
      NEXTAUTH_SECRET: "$NEXTAUTH_SECRET"
      SALT: "$SALT"
      ENCRYPTION_KEY: "$ENCRYPTION_KEY"
      TELEMETRY_ENABLED: "false"
      LANGFUSE_INIT_ORG_ID: "kairos-org"
      LANGFUSE_INIT_ORG_NAME: "KAIROS"
      LANGFUSE_INIT_PROJECT_ID: "kairos-pipeline"
      LANGFUSE_INIT_PROJECT_NAME: "kairos-pipeline"
      LANGFUSE_INIT_PROJECT_PUBLIC_KEY: "$LF_PUBLIC_KEY"
      LANGFUSE_INIT_PROJECT_SECRET_KEY: "$LF_SECRET_KEY"
      LANGFUSE_INIT_USER_EMAIL: "ops@karios.local"
      LANGFUSE_INIT_USER_NAME: "kairos-ops"
      LANGFUSE_INIT_USER_PASSWORD: "$INIT_USER_PASSWORD"
    ports:
      - "192.168.118.106:3000:3000"

volumes:
  langfuse-db-data:
COMPOSE

echo "=== docker-compose.yml written ==="
echo "=== bringing up Langfuse stack (this may pull ~500MB images) ==="
docker compose up -d 2>&1 | tail -10
echo "=== waiting for Langfuse to become healthy ==="
for i in $(seq 1 60); do
    if curl -fsS http://localhost:3000/api/public/health 2>/dev/null | grep -q OK 2>/dev/null; then
        echo "  ✓ Langfuse healthy after ${i}0s"
        break
    fi
    sleep 10
done

echo "=== final health ==="
curl -sS http://localhost:3000/api/public/health 2>&1 | head -3

echo "=== INIT_* keys (already populated in env) ==="
echo "PUBLIC_KEY=$LF_PUBLIC_KEY"
echo "SECRET_KEY=$LF_SECRET_KEY (truncated): ${LF_SECRET_KEY:0:14}..."
