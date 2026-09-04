# receipt-wrangler.tf — LXC 114 on server (shared household expense tracking).
#
# Receipt Wrangler stores receipt images, split allocations, and its PostgreSQL
# database inside this guest.  The nightly cluster-wide PBS job backs up every
# guest, so keeping the whole stack on the root disk makes recovery atomic.
#
# Sizing:
#   2 cores / 2 GiB — OCR and vision inference run on the separate agent VM;
#     this guest only serves the web app, PostgreSQL, and Redis.
#   24 GiB disk — ample for container images, database growth, and years of
#     household receipt photos while remaining cheap to snapshot.
# First-create bootstrap: this stock template has no root authorized key. Before
# the first Ansible run, use `pct exec 114` on server to install the controller's
# public key at /root/.ssh/authorized_keys (0700 directory, 0600 file).

resource "proxmox_virtual_environment_container" "receipt_wrangler" {
  node_name    = "server"
  vm_id        = 114
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
    dedicated = 2048
    swap      = 512
  }

  disk {
    datastore_id = "local-zfs"
    size         = 24
  }

  # Docker-in-LXC needs nesting. The API token cannot set keyctl, but nesting
  # alone is sufficient for the Docker CE + Compose stack used here.
  features {
    nesting = true
  }

  # Cluster-wide pve-firewall is disabled. Enabling the per-guest firewall
  # would create an empty fwbr and drop traffic instead of filtering it.
  network_interface {
    name        = "eth0"
    bridge      = "vmbr0"
    firewall    = false
    mac_address = "BC:24:11:E1:F4:EE"
  }

  initialization {
    hostname = "receipt-wrangler"
    dns {
      servers = ["1.1.1.1"]
    }
    ip_config {
      ipv4 {
        address = "10.0.0.14/24"
        gateway = "10.0.0.1"
      }
    }
  }

  operating_system {
    type             = "debian"
    template_file_id = "local:vztmpl/debian-12-standard_12.12-1_amd64.tar.zst"
  }

  lifecycle {
    # template_file_id is create-only and does not read back from a running CT.
    ignore_changes = [operating_system]
  }
}
