# adguard.tf — LXC 101 on node01 (AdGuard Home — network-wide DNS).
# Retrofitted from the live container via `tofu plan -generate-config-out`,
# then hand-cleaned (dropped the experimental generator's invalid entrypoint="",
# pinned vm_id, stripped provider-default noise).
#
# NOTE: this container is PRIVILEGED (unprivileged = false) and passes through
# /dev/net/tun — do not flip those without understanding the DNS/VPN setup.

resource "proxmox_virtual_environment_container" "adguard" {
  node_name    = "server"
  vm_id        = 101
  unprivileged = false

  start_on_boot = true
  started       = true

  console {
    enabled   = true
    tty_count = 2
    type      = "tty"
  }

  memory {
    dedicated = 1024
    swap      = 256
  }

  disk {
    datastore_id = "local-zfs"
    size         = 16
  }

  features {
    keyctl  = true
    nesting = true
  }

  device_passthrough {
    path = "/dev/net/tun"
    mode = "0660"
    uid  = 0
    gid  = 0
  }

  network_interface {
    name        = "eth0"
    bridge      = "vmbr0"
    firewall    = true
    mac_address = "BC:24:11:00:00:02"
  }

  initialization {
    hostname = "adguard"
    ip_config {
      ipv4 {
        address = "10.0.0.3/24"
        gateway = "10.0.0.1"
      }
    }
  }

  # First up — the rest of the LAN depends on it for DNS.
  startup {
    order      = 1
    up_delay   = -1
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
