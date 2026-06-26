# caddy.tf — LXC 104 on node01 (Caddy reverse proxy / TLS terminator).
# Retrofitted from the live container via `tofu plan -generate-config-out`,
# then hand-cleaned (dropped the experimental generator's invalid entrypoint="",
# pinned vm_id, stripped provider-default noise).

resource "proxmox_virtual_environment_container" "caddy" {
  node_name    = "node01"
  vm_id        = 104
  unprivileged = true

  start_on_boot = true
  started       = true

  console {
    enabled   = true
    tty_count = 2
    type      = "tty"
  }

  memory {
    dedicated = 512
    swap      = 512
  }

  disk {
    datastore_id = "local-lvm"
    size         = 6
  }

  features {
    keyctl  = true
    nesting = true
  }

  network_interface {
    name        = "eth0"
    bridge      = "vmbr0"
    firewall    = true
    mac_address = "BC:24:11:00:00:01"
  }

  initialization {
    hostname = "caddy"
    ip_config {
      ipv4 {
        address = "10.0.0.6/24"
        gateway = "10.0.0.1"
      }
    }
  }

  # Boot after AdGuard (order 1) so DNS is up before the proxy.
  startup {
    order     = 2
    up_delay  = 15
    down_delay = -1
  }

  operating_system {
    type = "debian"
    # template_file_id is unknowable from a running container; ignore it so
    # adoption doesn't try to recreate the LXC.
    template_file_id = ""
  }

  lifecycle {
    ignore_changes = [operating_system, initialization]
  }
}
