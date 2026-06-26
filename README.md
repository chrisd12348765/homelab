# HaC (Homelab as Code)

A reproducible, GitOps-style homelab on a Proxmox cluster — provisioning,
configuration, and app deployment all defined in code.

## Stack
- **OpenTofu** (`bpg/proxmox` provider) — declaratively provisions VMs and LXC containers.
- **Ansible** — configures hosts: installs Docker, lays down services, manages config.
- **Docker Compose** — defines the application stacks themselves.
- **SOPS + age** — secrets encrypted at rest; nothing sensitive in plaintext.

## Architecture
```
OpenTofu  ──provisions──▶  Proxmox VMs / LXC
Ansible   ──configures──▶  Docker hosts + services
Compose   ──runs──────▶    application stacks
```

## Highlights
- Three-layer IaC: infra → config → apps, each independently reproducible.
- Existing cluster retrofitted into code via OpenTofu config-driven import.
- Secret management with SOPS + age; CI secret-scanning gate before publish.

> Hostnames, domains, and addresses in this public repo are placeholders.
> It mirrors the structure of my real setup, not its actual topology.
