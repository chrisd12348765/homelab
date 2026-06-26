# vpn-exit.tf — LXC 102 on node01 (VPN exit node).
# Retrofitted via generate-config-out, hand-cleaned (dropped invalid entrypoint="",
# pinned vm_id, stripped provider-default noise).
#
# NOTE: PRIVILEGED (unprivileged = false) — needed for the VPN tunnel device.

resource "proxmox_virtual_environment_container" "vpn_exit" {
  node_name    = "node01"
  vm_id        = 102
  unprivileged = false

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
    size         = 8
  }

  features {
    keyctl  = true
    nesting = true
  }

  network_interface {
    name        = "eth0"
    bridge      = "vmbr0"
    firewall    = true
    mac_address = "BC:24:11:00:00:04"
  }

  initialization {
    hostname = "vpn-exit"
    ip_config {
      ipv4 {
        address = "10.0.0.7/24"
        gateway = "10.0.0.1"
      }
    }
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
