# Architecture

## Two repos, one source of truth ("left join")

```
PRIVATE (~/homelab)                         PUBLIC (~/homelab-public -> github, public)
  full config, real values                   subset: only .publish.allow paths
  secrets SOPS-encrypted          ──┐        domain/IPs placeholdered
                                    │        secrets never copied
        scripts/publish.sh  ────────┘
        allowlist → sanitize → gitleaks → rsync
```

The public repo is a **derived artifact**, regenerated deterministically. Its git
history is **independent** of the private repo, so a real secret can never appear
in public history even if it once existed privately.

## Three safety layers (a leak needs all three to fail)
1. **`.publish.allow`** — default-deny allowlist. Unlisted files are never public.
2. **`scripts/sanitize.map`** — literal rewrites of real domain/IPs/hostnames → placeholders.
3. **`.gitleaks.toml` gate** — publish aborts if any secret pattern is found in the staged public tree.

Plus a hard denylist inside `publish.sh` (`*.sops.*`, `*.enc.*`, `vault`, `*.tfstate`,
`*.tfvars`, keys) that blocks secret-shaped files even if the allowlist is wrong.

## Secret flow (SOPS + age)
- One age keypair; private key lives at `~/.config/sops/age/keys.txt`, **never in git**.
- `.sops.yaml` declares which files/fields are encrypted and to which age recipient.
- Encrypted `*.sops.yaml` files are committed to the **private** repo only.
- At apply time secrets are decrypted in-memory / to gitignored tfvars, never committed.

## Layer responsibilities
| Layer | Tool | Reverse-engineer existing? |
|-------|------|----------------------------|
| Provision (VMs/LXC) | OpenTofu + bpg/proxmox | semi-auto: `import` blocks + `-generate-config-out` |
| Configure (hosts)   | Ansible | manual (no reliable reverse tool) |
| Apps (containers)   | Docker Compose | auto: `docker-autocompose` |
