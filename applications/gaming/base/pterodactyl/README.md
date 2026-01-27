# Pterodactyl / Kubectyl Game Server Panel

Kubernetes-native game server management panel using Kubectyl (Pterodactyl fork).

## Access

- **Panel URL**: http://pterodactyl.talos00
- **Add to /etc/hosts**: `192.168.1.54 pterodactyl.talos00`

## Initial Setup

### 1. Create Admin User

```bash
kubectl exec -it -n gaming deploy/pterodactyl-panel -- php artisan p:user:make
```

Follow the prompts to create your admin account.

### 2. Register Kuber Cluster

1. Login to Panel at http://pterodactyl.talos00
2. Go to **Clusters** → **Create New**
3. Fill in:
   - **Name**: `homelab-cluster`
   - **Host**: `pterodactyl-kuber.gaming.svc.cluster.local`
   - **Port**: `8080`
   - **Memory**: `16384` (16GB available)
   - **Disk**: `102400` (100GB available)
4. Click **Create**
5. Go to the cluster's **Configuration** tab
6. Copy the `uuid`, `token_id`, and `token` values

### 3. Update Kuber Config

Edit `kuber/config.yaml` with the values from the Panel:

```yaml
uuid: <from panel>
token_id: <from panel>
token: <from panel>
```

Then apply:

```bash
kubectl apply -k applications/gaming/base/pterodactyl/kuber/
kubectl rollout restart deploy/pterodactyl-kuber -n gaming
```

### 4. Import Game Eggs

1. Download eggs from https://github.com/pelican-eggs/eggs
2. In Panel: **Admin** → **Nests** → **Import Egg**
3. Upload the JSON file (e.g., `conan_exiles.json`)

## Components

| Component | Image | Purpose |
|-----------|-------|---------|
| Panel | ghcr.io/kubectyl/panel:v0.1.0-beta | Web UI for server management |
| Kuber | ghcr.io/kubectyl/kuber:v1.0.0-alpha.1 | K8s daemon that spawns game servers as pods |
| MariaDB | mariadb:10.11 | Database backend |
| Redis | redis:7-alpine | Cache and session storage |

## Creating Game Servers

Once Kuber is connected:

1. **Admin** → **Servers** → **Create New**
2. Select the game type (Nest/Egg)
3. Configure resources (CPU, RAM, disk)
4. Kuber will create a pod for the server

## Troubleshooting

### Check Panel logs
```bash
kubectl logs -n gaming deploy/pterodactyl-panel -f
```

### Check Kuber logs
```bash
kubectl logs -n gaming deploy/pterodactyl-kuber -f
```

### Recreate admin password
```bash
kubectl exec -it -n gaming deploy/pterodactyl-panel -- php artisan p:user:make
```

## Security Notes

- **TODO**: Move secrets to 1Password via External Secrets Operator
- Default passwords in secrets MUST be changed
- Panel should be behind HTTPS in production
