# obsidian.tf — LXC 103 on node01 (Obsidian LiveSync / CouchDB).
# Retrofitted via generate-config-out, hand-cleaned (dropped invalid entrypoint="",
# cpu.units=0/limit=0; pinned vm_id; stripped provider-default noise).

resource "proxmox_virtual_environment_container" "obsidian" {
  node_name    = "server"
  vm_id        = 103
  unprivileged = true

  start_on_boot = true
  started       = true

  console {
    enabled   = true
    tty_count = 2
    type      = "tty"
  }

  cpu {
    architecture = "amd64"
    cores        = 2
  }

  memory {
    dedicated = 1536
    swap      = 512
  }

  disk {
    datastore_id = "local-zfs"
    size         = 20
  }

  features {
    keyctl  = true
    nesting = true
  }

  network_interface {
    name        = "eth0"
    bridge      = "vmbr0"
    firewall    = true
    mac_address = "BC:24:11:00:00:05"
  }

  initialization {
    hostname = "obsidian"
    ip_config {
      ipv4 {
        address = "10.0.0.5/24"
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
