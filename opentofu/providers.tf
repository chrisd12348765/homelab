terraform {
  required_version = ">= 1.6" # OpenTofu 1.6+ / Terraform 1.5+
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.66" # bpg provider — manages VMs, LXC, SDN, ACLs, users...
    }
  }
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
