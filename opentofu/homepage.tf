# homepage.tf — LXC 107 on node01. Runs the Homepage (gethomepage.dev)
# dashboard served at dash.example.com; see roles/homepage.
# Retrofitted via generate-config-out, hand-cleaned (dropped invalid entrypoint="",
# cpu.units=0/limit=0; pinned vm_id; stripped provider-default noise).

# The guest was called "homarr" until 2026-07-12 (it once ran Homarr). Renamed in
# Proxmox with `pct set 107 --hostname homepage`. OpenTofu now owns initialization
# so bootstrap DNS is enforced across cold boots; the recorded hostname already
# matches live and remains stable.
moved {
  from = proxmox_virtual_environment_container.homarr
  to   = proxmox_virtual_environment_container.homepage
}

resource "proxmox_virtual_environment_container" "homepage" {
  node_name    = "server"
  vm_id        = 107
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
    size         = 8
  }

  features {
    nesting = true
  }

  network_interface {
    name        = "eth0"
    bridge      = "vmbr0"
    firewall    = true
    mac_address = "BC:24:11:00:00:06"
  }

  initialization {
    hostname = "homepage"
    # Bootstrap DNS must work before tailscaled can install the tailnet resolver.
    # The old 10.0.0.3 value survived the LAN renumber and stranded this CT
    # off-tailnet whenever it rebooted.
    dns {
      servers = ["1.1.1.1"]
    }
    ip_config {
      ipv4 {
        address = "10.0.0.8/24"
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
    ignore_changes = [operating_system]
  }
}
