variable "pve_endpoint" {
  type        = string
  description = "Proxmox API endpoint URL"
}

variable "pve_api_token" {
  type        = string
  sensitive   = true
  description = "Proxmox API token id=secret (supplied via SOPS-decrypted tfvars)"
}

variable "pve_ssh_user" {
  type        = string
  default     = "root"
  description = "SSH user bpg uses for API-less actions"
}

variable "target_node" {
  type        = string
  default     = "node02"
  description = "Default Proxmox node to place resources on"
}

variable "tailscale_oauth_client_id" {
  type        = string
  sensitive   = true
  description = "Tailscale OAuth client ID, acl scope (supplied via SOPS-decrypted tfvars)"
}

variable "tailscale_oauth_client_secret" {
  type        = string
  sensitive   = true
  description = "Tailscale OAuth client secret, acl scope (supplied via SOPS-decrypted tfvars)"
}
