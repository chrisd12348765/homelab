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

## PBS host recovery — the backup appliance itself

**PBS runs on its own dedicated appliance host, entirely outside OpenTofu and
Ansible's scope** — it's hand-provisioned (custom kernel, hand-built OS package),
not a guest this repo can redeploy. Procedure B's "restore from PBS" steps have
nothing to restore *from* until PBS itself exists again, so treat this as a
prerequisite of Procedure B, not part of it.

There is no automated path here — rebuild by hand:

1. Reimage the appliance (fresh OS install) and reinstall PBS.
2. Reattach the backup drive; re-import (or recreate) the datastore(s) pointing
   at its existing mount so historical snapshots on the drive are recovered, not
   lost — **the drive holds the actual backup history; the appliance's own OS
   disk does not.**
3. Recreate the PVE↔PBS API tokens and re-add the datastore to each Proxmox
   node's storage config (`pvesm add pbs ...`).
4. Re-add the Caddy vhost + zero-click SSO entry and the Homepage tile by
   replicating the existing pattern for the other reverse-proxied services
   (`ansible/roles/caddy/files/Caddyfile`, `services.enc.json`).

The backup drive is the real single point of failure here, not the appliance
itself — losing the appliance with the drive intact is a few hours of manual
rebuild; losing the drive loses the backup history.

## PVE host config recovery — the nodes' own OS config

**PBS's guest-level `vzdump` job (all VMs/CTs, nightly 02:30) does not cover the
hypervisor hosts themselves.** A separate job, `pbs-host-backup.sh` (hand-installed
to `/usr/local/sbin` on both `node01` and `node02`/`nas`, cron `/etc/cron.d/
pbs-host-backup`, daily 02:00, alongside the guest vzdump job — repo copy + the full design rationale in
`ansible/roles/proxmox_hosts/files/`), backs up each node's own OS-level config
into PBS under a dedicated **`host-configs` namespace** on datastore `main`, one
group per node (`host/node01`, `host/node02`), each written by its own
least-privilege token (`DatastoreBackup` only, scoped to that namespace — a
compromised host-backup token can't touch the guest backups or the other node's
group). Retention: server-side `host-configs-prune` job, 7d/4w/3m (matches the
guest policy). Archives per snapshot: `etc.pxar` (`/etc`, minus `/etc/pve` — see
below), `pve-cluster.pxar` (see below), `root.pxar`, `usr-local.pxar`, `opt.pxar`,
`tailscale.pxar` (`/var/lib/tailscale` — Tailscale's machine identity; without it
a rebuilt node needs interactive `tailscale up` re-auth). **Encrypted** with a
shared key (`/etc/pbs-host-backup/encryption.key` on both nodes, `--kdf none` —
unattended cron can't supply a passphrase) since these snapshots contain root's
SSH private key and both nodes' SSH host keys.

**⚠ Second SPOF, same doctrine as the age key (see top of this doc):** losing
`/etc/pbs-host-backup/encryption.key` (identical on both nodes) makes every
host-config snapshot permanently undecryptable. A copy lives SOPS-encrypted in
`ansible/roles/proxmox_hosts/files/pbs-host-backup-secrets.enc.json` alongside
both PBS token secrets — that repo copy **is** the off-machine copy; don't treat
it as optional.

**`/etc/pve` is deliberately excluded from `etc.pxar`** — it's a FUSE view
(pmxcfs), not real files; its actual backing store,
`/var/lib/pve-cluster/config.db`, is a live SQLite file pmxcfs holds open, so the
script takes a clean `sqlite3 .backup` snapshot first and archives that (plus
`pvecm status` + a timestamp for context) as `pve-cluster.pxar`.

**Restore is a reference, not a drop-in.** Do **not** stop a rebuilt node's
cluster services and overwrite a fresh `config.db` with the restored one — on a
live quorate corosync cluster this can conflict on generation/version state. The
real rebuild path: reinstall PVE → rejoin the cluster normally (`pvecm add`) →
open the restored `config.db` **read-only** (`sqlite3 -readonly
<restored-path>`) and manually re-enter `storage.cfg`/`datacenter.cfg`/
`jobs.cfg` entries via the live cluster's own tools, using the restored copy as
your reference for exactly what those entries were.

**Not captured by this job — re-derive by hand:**
- **`nas`'s `vendor-reset` DKMS module** (`/root/vendor-reset`, excluded from
  `root.pxar` — 177MB, re-clonable, no value archived as bytes). Needed for the
  RX 6600 GPU-passthrough reset workaround. Post-reinstall: `git clone
  https://github.com/gnif/vendor-reset && dkms install` for the running kernel.
  Currently installed: `vendor-reset/0.1.1, 6.8.12-20-pve, x86_64: installed`
  (`dkms status`, checked 2026-07-01 — re-check after any kernel upgrade).
- **`nas`'s ext4 project quotas** (`/mnt/storage`, projects 10=media/20=immich) —
  the `chattr -p`/`setquota` bindings exist only as live xattrs on the array, not
  in any config file (`/etc/projid`/`/etc/projects` are empty). If the array
  itself survives a host rebuild this doesn't matter; if it's ever rebuilt from
  scratch, re-run (current caps confirmed via `repquota -P /mnt/storage`,
  2026-07-01): project 10 (media) soft/hard 0 / **8200G**; project 20 (immich)
  soft/hard 0 / **2700G**. Full `chattr`/`setquota` commands in
  `Systems/Homelab/Storage.md`.
- **Tailscale re-auth is best-effort even with `tailscaled.state` restored** — if
  the tailnet key expired or was revoked while the node was down, `tailscale up`
  will still prompt for interactive re-auth; the restored state just means it
  *might* resume silently, not that it's guaranteed to.

**Known CLI gap on the Pi's PBS build:** `proxmox-backup-manager` (the arm64
`pipbs` build) has no `namespace` subcommand, even though the underlying feature
works fine — the namespace was created via a direct `POST
/api2/json/admin/datastore/main/namespace` call (param name is `name`, not
`ns`) using a temporary self-granted admin token, deleted immediately after. If
you ever need to create another namespace on this PBS instance, use the same
approach (or `proxmox-backup-client namespace create`, which the *client* binary
does support, from a PVE node once it can reach the datastore admin API — not
yet verified whether the client-side command implies datastore-admin
permissions the write-only tokens above don't have).

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
- [ ] Document/rehearse rebuilding the PBS appliance itself — it's outside
      OpenTofu/Ansible so there's no automated path (see "PBS host recovery").
- [x] Host-config backup (`pbs-host-backup.sh`) verified end-to-end 2026-07-01:
      manual run on both nodes succeeded, snapshots landed under the
      `host-configs` namespace with correct per-node ownership, `config.db`
      restored clean (`PRAGMA integrity_check` → `ok`), `/etc/pve` and (on
      `nas`) `vendor-reset` confirmed absent from their respective archives.
      Still open: confirm the first *cron-triggered* (not manual) run on both
      nodes at 02:00, and confirm the encryption key's off-host copy
      (`pbs-host-backup-secrets.enc.json`) actually decrypts on a second
      machine.
- [ ] Extend the Ansible/Compose layer beyond Immich so Procedure A step 2
      covers every guest.
