terraform {
  required_version = ">= 1.6" # OpenTofu 1.6+ / Terraform 1.5+
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.66" # bpg provider — manages VMs, LXC, SDN, ACLs, users...
    }
    tailscale = {
      source  = "tailscale/tailscale"
      version = "~> 0.17" # manages the tailnet ACL policy (see tailscale.tf)
    }
  }
}

provider "tailscale" {
  # OAuth client with the "Policy File: Write" scope (non-expiring, unlike a 90-day
  # API token). Values arrive via SOPS-decrypted tfvars, same path as the proxmox creds.
  # NOTE: do NOT set `scopes` here. Tailscale's granular-scope OAuth clients issue a
  # client-credentials token carrying exactly the scopes the client was granted;
  # explicitly requesting `scopes = ["acl"]` makes the token endpoint 403 with
  # "OAuth client cannot grant scopes \"acl\"". Omitting it uses the token's own scopes.
  oauth_client_id     = var.tailscale_oauth_client_id
  oauth_client_secret = var.tailscale_oauth_client_secret
  tailnet             = "-" # "-" = the OAuth client's own tailnet
}

provider "proxmox" {
  endpoint = var.pve_endpoint # e.g. https://node02.example.com:8006/
  # Auth via API token (create a dedicated user+token, not root@pam).
  api_token = var.pve_api_token # loaded from SOPS-decrypted tfvars — never hardcode
  insecure  = true              # node :8006 uses PVE's self-signed cert; skip TLS verify
                                # (set false only if you put a trusted cert on the node)

  # bpg uses SSH for a few API-less actions (disk import, snippet upload).
  ssh {
    agent    = true
    username = var.pve_ssh_user
  }
}
