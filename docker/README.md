# Docker Development Services

This docker-compose configuration provides local services for testing all client integrations.

## Services Overview

### Core Services

#### 1. **Mailpit** - Email Testing
- **Ports**:
  - 1025 (SMTP)
  - 8025 (Web UI)
- **URL**: http://localhost:8025
- **Purpose**: Test email notifications and SMTP functionality
- **Credentials**: Accepts any username/password

#### 2. **PostgreSQL** - Database
- **Port**: 5432
- **Credentials**:
  - User: `default`
  - Password: `default`
- **Purpose**: Application database

#### 3. **Apprise** - Notification Gateway
- **Port**: 8000
- **URL**: http://localhost:8000
- **Purpose**: Local Apprise API target for testing the Apprise integration (`marvin-integration-apprise`)
- **Config**: `./docker/config/`

#### 4. **HTTPBin** - HTTP Testing
- **Port**: 8080
- **URL**: http://localhost:8080
- **Purpose**: Test HTTP requests and webhooks

### Client Testing Services

#### 5. **OpenLDAP** - LDAP Server
- **Ports**:
  - 1389 (LDAP)
  - 1636 (LDAPS)
- **URL**: ldap://localhost:1389
- **Base DN**: `dc=example,dc=com`
- **Admin Credentials**:
  - Username: `admin`
  - Password: `adminpassword`
  - DN: `cn=admin,dc=example,dc=com`
- **Test Users**:
  - `uid=user01,ou=users,dc=example,dc=com` (password: `password01`)
  - `uid=user02,ou=users,dc=example,dc=com` (password: `password02`)
- **Test Group**: `cn=developers,ou=users,dc=example,dc=com`

#### 6. **phpLDAPadmin** - LDAP Web UI
- **Port**: 8081
- **URL**: http://localhost:8081
- **Purpose**: Manage OpenLDAP via web interface
- **Login**:
  - DN: `cn=admin,dc=example,dc=com`
  - Password: `adminpassword`

#### 7. **HashiCorp Vault** - Secrets Management
- **Port**: 8200
- **URL**: http://localhost:8200
- **Mode**: Development (unsealed, in-memory)
- **Root Token**: `root-token-for-dev`
- **Web UI**: http://localhost:8200/ui
- **Purpose**: Test Vault client secret operations

⚠️ **Warning**: This is a DEV mode Vault. Data is NOT persisted and is lost on restart.

#### 8. **Mock OAuth Server** - OAuth 2.0 Testing
- **Port**: 8082
- **Base URL**: http://localhost:8082
- **Endpoints**:
  - Token: `POST /as/resourceOwner`
  - Validate: `POST /rs/validate/AppIdClaimsTrust`
- **Implementation**: WireMock with response templating
- **Purpose**: Test OAuth client without ESG access

## Quick Start

### Start All Services
```bash
docker-compose -f docker/docker-compose.dev.yml up -d
```

### Start Specific Services
```bash
# Only LDAP
docker-compose -f docker/docker-compose.dev.yml up -d openldap phpldapadmin

# Only Vault
docker-compose -f docker/docker-compose.dev.yml up -d vault

# Only OAuth Mock
docker-compose -f docker/docker-compose.dev.yml up -d mock-oauth
```

### View Logs
```bash
docker-compose -f docker/docker-compose.dev.yml logs -f [service-name]
```

### Stop All Services
```bash
docker-compose -f docker/docker-compose.dev.yml down
```

### Stop and Remove Volumes
```bash
docker-compose -f docker/docker-compose.dev.yml down -v
```

## Environment Configuration

### LDAP Client Testing

Add to your `.env`:
```bash
# LDAP Configuration
LDAP_AUTH_ENABLED=true
LDAP_SERVER_URL=ldap://localhost:1389
LDAP_BASE_DN=dc=example,dc=com
LDAP_QUERY_BIND=cn=admin,dc=example,dc=com
LDAP_QUERY_PASSWORD=adminpassword
LDAP_TLS_INSECURE=true
LDAP_ENABLE_START_TLS=false
LDAP_USER_SEARCH_FILTER=(uid={{username}})
LDAP_ID_ATTRIBUTE=uid
LDAP_MAIL_ATTRIBUTE=mail
LDAP_NAME_ATTRIBUTE=cn
```

### Vault Client Testing

Add to your `.env`:
```bash
# Vault Configuration
VAULT_ENABLED=true
VAULT_ADDR=http://localhost:8200
VAULT_TOKEN=root-token-for-dev
VAULT_SKIP_VERIFY=true
VAULT_TIMEOUT=30000
VAULT_ENABLE_CACHING=true
VAULT_CACHE_DURATION=300000
VAULT_MAX_RETRIES=3
VAULT_RETRY_DELAY=1000
```

### OAuth Client Testing (Mock)

Add to your `.env`:
```bash
# OAuth Configuration (Mock Server)
OAUTH_ENABLED=true
ESG_ENVIRONMENT=DEV
OAUTH_TOKEN_ENDPOINT=http://localhost:8082/as/resourceOwner
OAUTH_VALIDATE_ENDPOINT=http://localhost:8082/rs/validate/AppIdClaimsTrust
OAUTH_CLIENT_ID=srvAP138830DEV
OAUTH_CLIENT_SECRET=mock-secret-123
OAUTH_ENABLE_CACHING=true
OAUTH_CACHE_DURATION=28800000
OAUTH_INTENT=testing
```

## Testing Examples

### LDAP Client Test

```typescript
import { LDAPClient } from './src/clients/ldap';

const ldap = LDAPClient.fromEnv();
await ldap.connect();

// Test authentication
const result = await ldap.authenticate('user01', 'password01');
console.log('Auth result:', result);

// Search for user
const user = await ldap.findUser('user01');
console.log('User:', user);

await ldap.disconnect();
```

### Vault Client Test

```bash
# First, initialize Vault with test data
docker exec vault vault kv put secret/myapp/database host=localhost port=5432 username=admin password=secret123

# Then test from Node.js
```

```typescript
import { VaultClient } from './src/clients/vault';

const vault = VaultClient.fromEnv();

// Write a secret
await vault.writeSecret('secret/data/myapp/config', {
  api_key: 'test-key-123',
  environment: 'development'
});

// Read the secret
const secret = await vault.readSecret('secret/data/myapp/config');
console.log('Secret:', secret.data);

// List secrets
const keys = await vault.listSecrets('secret/metadata/myapp');
console.log('Keys:', keys);
```

### OAuth Client Test

```typescript
import { OAuthClient } from './src/clients/oauth';

const oauth = OAuthClient.fromEnv();

// Generate token
const tokenResponse = await oauth.generateToken();
console.log('Token:', tokenResponse.access_token);

// Validate token
const isValid = await oauth.validateToken(tokenResponse.access_token);
console.log('Valid:', isValid);

// Test invalid token
const invalidResult = await oauth.validateToken('invalid_token_123');
console.log('Invalid result:', invalidResult); // Should be false
```

## Service Health Checks

### LDAP
```bash
# Test LDAP connection
ldapsearch -x -H ldap://localhost:1389 -D "cn=admin,dc=example,dc=com" -w adminpassword -b "dc=example,dc=com"

# Or via Docker
docker exec openldap ldapsearch -x -H ldap://localhost:1389 -D "cn=admin,dc=example,dc=com" -w adminpassword -b "dc=example,dc=com"
```

### Vault
```bash
# Check Vault status
curl http://localhost:8200/v1/sys/health

# Or via CLI
docker exec vault vault status
```

### OAuth Mock
```bash
# Test token endpoint
curl -X POST http://localhost:8082/as/resourceOwner \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&scope=AppIdClaimsTrust"

# Test validation endpoint
curl -X POST http://localhost:8082/rs/validate/AppIdClaimsTrust \
  -H "Authorization: Bearer test_token_123"
```

## Troubleshooting

### LDAP Issues
- **Connection refused**: Ensure OpenLDAP is running: `docker ps | grep openldap`
- **Invalid credentials**: Check credentials match the environment variables
- **TLS errors**: Set `LDAP_TLS_INSECURE=true` for development

### Vault Issues
- **Sealed vault**: This shouldn't happen in dev mode, but restart the container
- **Token invalid**: Ensure you're using `root-token-for-dev`
- **Connection refused**: Check Vault is running: `docker ps | grep vault`

### OAuth Mock Issues
- **No response**: Check WireMock logs: `docker logs mock-oauth`
- **Wrong response**: Check mapping files in `docker/wiremock/mappings/`
- **Template errors**: Ensure WireMock started with `--global-response-templating`

## Web Interfaces

| Service | URL | Purpose |
|---------|-----|---------|
| Mailpit | http://localhost:8025 | View test emails |
| phpLDAPadmin | http://localhost:8081 | Manage LDAP entries |
| Vault UI | http://localhost:8200/ui | Manage secrets (Token: `root-token-for-dev`) |
| Apprise | http://localhost:8000 | Notification service |
| HTTPBin | http://localhost:8080 | HTTP testing |

## Data Persistence

- **OpenLDAP**: Persisted in `openldap_data` volume
- **Vault**: NOT persisted (dev mode, in-memory)
- **PostgreSQL**: NOT configured for persistence (add volume if needed)

## Cleanup

```bash
# Stop all services
docker-compose -f docker/docker-compose.dev.yml down

# Remove all data
docker-compose -f docker/docker-compose.dev.yml down -v

# Remove images
docker-compose -f docker/docker-compose.dev.yml down --rmi all
```

## Production Notes

⚠️ **These services are for DEVELOPMENT ONLY**:

1. **Vault**: Uses dev mode (unsealed, in-memory, root token exposed)
2. **LDAP**: Simple configuration with default passwords
3. **OAuth Mock**: Not a real OAuth server, just for testing
4. **All services**: No encryption, weak credentials, exposed ports

For production:
- Use real ESG OAuth endpoints
- Configure production LDAP with proper security
- Deploy Vault with proper unsealing and HA
- Enable TLS/SSL on all services
- Use strong passwords and rotate credentials
- Restrict network access
