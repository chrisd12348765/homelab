# immich.tf — LXC 109 on node02 (Immich photo server).
# Retrofitted from the live container via `tofu plan -generate-config-out`,
# then hand-cleaned (generate-config-out is experimental and emits a few
# invalid defaults: cpu.units=0 and entrypoint="" were dropped; vm_id pinned).

resource "proxmox_virtual_environment_container" "immich" {
  node_name    = "nas"
  vm_id        = 109
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
    cores        = 4
  }

  memory {
    dedicated = 4096
    swap      = 1024
  }

  disk {
    datastore_id = "local-zfs"
    size         = 20
  }

  # Photo library bind-mount onto the ZFS array (see Storage runbook).
  mount_point {
    path      = "/data"
    volume    = "/mnt/storage/immich"
    replicate = true
  }

  features {
    keyctl  = true
    nesting = true
  }

  network_interface {
    name        = "eth0"
    bridge      = "vmbr0"
    firewall    = true
    mac_address = "BC:24:11:00:00:00"
  }

  initialization {
    hostname = "immich"
    ip_config {
      ipv4 {
        address = "dhcp"
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
