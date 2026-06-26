# vaultwarden.tf — LXC 100 on node01 (Vaultwarden password manager).
# Retrofitted via generate-config-out, hand-cleaned (dropped invalid entrypoint="",
# pinned vm_id, stripped provider-default noise).

resource "proxmox_virtual_environment_container" "vaultwarden" {
  node_name    = "node01"
  vm_id        = 100
  unprivileged = true

  start_on_boot = true
  started       = true

  console {
    enabled   = true
    tty_count = 2
    type      = "tty"
  }

  memory {
    dedicated = 1024
    swap      = 512
  }

  disk {
    datastore_id = "local-lvm"
    size         = 12
  }

  features {
    keyctl  = true
    nesting = true
  }

  network_interface {
    name        = "eth0"
    bridge      = "vmbr0"
    firewall    = false
    mac_address = "BC:24:11:00:00:03"
  }

  initialization {
    hostname = "vaultwarden"
    dns {
      servers = ["1.1.1.1"]
    }
    ip_config {
      ipv4 {
        address = "10.0.0.4/24"
        gateway = "10.0.0.1"
      }
    }
  }

  startup {
    order      = -1
    up_delay   = 60
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
