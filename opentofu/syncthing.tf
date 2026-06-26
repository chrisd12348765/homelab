# syncthing.tf — LXC 108 on node01 (Syncthing hub — hub-and-spoke topology).
# Retrofitted via generate-config-out, hand-cleaned (dropped invalid entrypoint="",
# pinned vm_id, stripped provider-default noise).

resource "proxmox_virtual_environment_container" "syncthing" {
  node_name    = "node01"
  vm_id        = 108
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
    size         = 4
  }

  features {
    nesting = true
  }

  network_interface {
    name        = "eth0"
    bridge      = "vmbr0"
    firewall    = false
    mac_address = "BC:24:11:00:00:07"
  }

  initialization {
    hostname = "syncthing"
    ip_config {
      ipv4 {
        address = "10.0.0.9/24"
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
