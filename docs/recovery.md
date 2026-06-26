# Recovery & Redeploy Runbook

Disaster recovery and redeploy procedures for the homelab. Read this *before* you
need it.

## The one thing that matters most

> **This repo restores *configuration and infrastructure*. It does NOT restore your
> data.** Data (photos, databases, app state) comes back from **PBS** (Proxmox
> Backup Server) snapshots and per-app dumps. A guest redeployed from code is an
> *empty* guest until you restore its data.

Two independent recovery tracks, do not confuse them:

| Track | What it brings back | Source of truth |
|-------|---------------------|-----------------|
| **Config / infra** | VMs, LXCs, host setup, app definitions | this repo (OpenTofu + Ansible + Compose) |
| **Data** | photo library, DBs, volumes | PBS snapshots + app-level dumps |

## CRITICAL: the age key is a single point of failure

Every secret in this system is SOPS-encrypted to **one age key**
(`~/.config/sops/age/keys.txt`). It is deliberately **never in git**.

**If that key is lost, every encrypted secret is permanently unrecoverable** — the
Proxmox API token, DB passwords, app `.env` files, everything. No key = no
decryption = no automated redeploy.

So the key must live in **at least two places that don't fail together**:

1. The control-plane machine (`~/.config/sops/age/keys.txt`, mode `0600`).
2. An off-machine copy — your password manager (Vaultwarden), a hardware token,
   and/or printed paper in a safe. **Do not** store the only off-machine copy
   inside the homelab it unlocks (circular dependency).

**Restore it first.** Recreate `~/.config/sops/age/keys.txt` from your backup
(`mode 0600`) before anything else. SOPS auto-discovers it there; verify:

```bash
sops -d opentofu/secrets.sops.yaml >/dev/null && echo "age key OK — secrets decrypt"
```

## Prerequisites — the control plane

Recovery is driven from a workstation, **not** from inside the cluster (so a
cluster outage can't take out your recovery tooling). You need:

```bash
# tooling (Arch example)
yay -S opentofu ansible sops age gitleaks pre-commit

# this repo (the PRIVATE one — it has the encrypted secrets)
git clone <private-repo-url> ~/homelab && cd ~/homelab
pre-commit install            # per-clone, the gitleaks hook is not cloned

# the age key (see above) at ~/.config/sops/age/keys.txt, mode 0600

# Proxmox reachable: nodes up, API token valid (see opentofu/providers.tf).
# If the token was lost with the cluster, recreate it per the bpg token steps
# (dedicated tofu@pve user + token, privilege-separation OFF) and `sops set`
# it into opentofu/secrets.sops.yaml.
```

### OpenTofu state

State is **local** (`opentofu/terraform.tfstate`, gitignored). Back it up
alongside the age key. If it's lost, the resources still exist in Proxmox — you
rebuild state by re-running the **import** flow (see `opentofu/imports.tf`); the
config files (`opentofu/<name>.tf`) are already in the repo, so this is
adopt-only, not a rebuild.

## Procedure A — repair / redeploy a single guest

Use when one VM/LXC is broken but the cluster is healthy.

```bash
cd ~/homelab

# 1. Reconcile infra: does the live guest still match code?
./scripts/tofu.sh plan          # review; apply only if you intend the change
./scripts/tofu.sh apply

# 2. Re-apply host config + app (Ansible). Example: Immich.
cd ansible
ansible-playbook playbooks/immich.yml                 # full
ansible-playbook playbooks/immich.yml --check --diff  # dry run first if unsure

# 3. Restore data if the guest was wiped (NOT needed for a config-only fix):
#    - PBS: restore the guest's latest snapshot from the PBS UI, OR
#    - app-level: e.g. Immich DB from a pg_dump (see "Data restore").
```

> Only `immich` currently has the full Ansible + Compose layer. Other guests are
> provisioned by OpenTofu (Procedure A step 1) but configured manually for now —
> extend `ansible/playbooks/` to bring them under step 2.

## Procedure B — full cluster rebuild (bare nodes)

Use when you're rebuilding Proxmox nodes from scratch.

1. **Restore the control plane** — age key, repo clone, tooling, tofu state
   (Prerequisites above).
2. **Stand up Proxmox** on the node(s); restore cluster/node config from PBS or
   reconfigure (networking/bridges `vmbr0`, storage `local-lvm`, the ZFS array,
   PCI passthrough mappings for the GPU/iGPU and the `media` virtiofs share).
3. **Recreate guests from code.** With empty nodes there's nothing to import, so
   the `import {}` blocks aren't used — OpenTofu *creates* the guests:
   ```bash
   ./scripts/tofu.sh init
   ./scripts/tofu.sh apply
   ```
   (Provisioning fresh guests may need an OS template / cloud-init image present
   on the node — the running cluster's configs `ignore_changes` the template, so
   re-check those blocks when building truly from zero.)
4. **Configure + deploy apps** with Ansible, in dependency order (below).
5. **Restore data** per app from PBS + dumps.

### Bootstrap / dependency order

Bring services up in this order (it matches the `startup { order }` already
encoded in the resources):

1. **DNS first** — `adguard` (startup order 1). Until LAN DNS resolves, other
   services and `ansible_host` name lookups may fail.
2. **Reverse proxy** — `caddy` (startup order 2). TLS / external entry.
3. **Core services** — `vaultwarden` (so secrets/passwords are reachable),
   then the rest (`obsidian`, `syncthing`, `immich`, dashboards, media).

## Data restore

- **PBS (primary):** restore a guest snapshot from the Proxmox Backup Server
  datastore (whole-VM/CT rollback). This is the fastest path for a wiped guest.
- **Immich DB (app-level rollback point):** a pre-deploy dump is taken before
  risky changes, e.g.:
  ```bash
  # on the immich host
  gunzip -c immich-predeploy-<date>.sql.gz | docker exec -i immich_postgres \
    psql -U postgres -d immich
  ```
- **Photo library / large volumes:** live on the ZFS array (bind/virtiofs
  mounts) and are covered by PBS + the array's own redundancy/replication — they
  are *not* recreated by `tofu apply`.

## Verify after recovery

```bash
cd ~/homelab
./scripts/tofu.sh plan          # expect: "No changes." (infra matches code)
sops -d opentofu/secrets.sops.yaml >/dev/null && echo "secrets OK"
```

Then spot-check each service's own endpoint/health (DNS resolving, proxy
serving, Vaultwarden unlock, Immich timeline loads, etc.).

## DR action items (do these now, not during an outage)

- [ ] Back up the age key off-machine (≥2 locations, not inside the homelab).
- [ ] Back up `opentofu/terraform.tfstate` alongside the key.
- [ ] Confirm PBS is running and its last verify job passed (`0 errors`).
- [ ] Extend the Ansible/Compose layer beyond Immich so Procedure A step 2
      covers every guest.
