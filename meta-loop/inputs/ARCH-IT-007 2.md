# Requirement: ARCH-IT-007

Add SSH key management to the Karios migration backend.

Agents should be able to:
- Generate SSH key pairs (RSA, Ed25519, ECDSA) for VM migration authentication
- Store SSH public keys associated with source/target environments
- List, view, and delete SSH keys via API
- Use SSH keys automatically during vSphere-to-Karios migration
- Test SSH key connectivity before using in production

API Endpoints needed:
- POST /api/v1/ssh-keys — Generate new SSH key pair
- GET /api/v1/ssh-keys — List all SSH keys for account
- GET /api/v1/ssh-keys/{id} — Get specific SSH key details  
- DELETE /api/v1/ssh-keys/{id} — Delete SSH key
- POST /api/v1/ssh-keys/{id}/test — Test SSH key connectivity

Tech Stack: Go backend, PostgreSQL for storage, Redis for caching
Priority: HIGH — needed for multi-host migration authentication
