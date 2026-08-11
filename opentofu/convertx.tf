# convertx.tf — LXC 113 on server (ConvertX — self-hosted file conversion web UI).
# Replaces ad-hoc use of online file-conversion sites: doc/tex/pdf/image/video via
# ffmpeg, LibreOffice, Pandoc, ImageMagick, Calibre, XeLaTeX and friends.
#
# Built from scratch (not adopted) — like openwebui.tf/home-assistant.tf there was no
# pre-existing live container to retrofit, so this specifies a real template_file_id
# instead of the adoption placeholder ("").
#
# Sizing notes:
#   disk 24G — the ConvertX image is ~1.55 GB compressed / ~4 GB on disk because it
#     bundles a full texlive (texlive-latex-extra, -xetex, latexmk) plus LibreOffice,
#     Calibre, ffmpeg and ImageMagick. The LaTeX support is most of that weight.
#     The rest is headroom for in-flight uploads (auto-deleted after 24h).
#   cores 2 / memory 2048 — server is a 4-core Celeron N5105; 2 cores leaves the other
#     two for the eight other LXCs on this node. MAX_CONVERT_PROCESS=2 in the compose
#     env keeps concurrent ffmpeg/LibreOffice runs from thrashing the box.

resource "proxmox_virtual_environment_container" "convertx" {
  node_name    = "server"
  vm_id        = 113
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

  # Same API-token limitation as openwebui.tf: the token isn't root@pam, so it can
  # only set `nesting` (not `keyctl`). nesting alone is sufficient for Docker.
  features {
    nesting = true
  }

  # Tailscale needs /dev/net/tun. Our API token can't push a device_passthrough block
  # (403), and ignore_changes only suppresses diffs on UPDATE — not CREATE — so a
  # from-scratch apply would still submit it and fail. Declared nowhere here; applied
  # live on the node as true root instead:
  #   pct set 113 -dev0 /dev/net/tun,mode=0660,uid=0,gid=0
  # The ignore_changes entry below exists only to stop tofu proposing to REMOVE the
  # live-set value it reads back on refresh. Same pattern as openwebui.tf.
  #
  # firewall = false: cluster-wide pve-firewall is disabled (see vaultwarden.tf), so
  # firewall=true here builds an empty fwbr bridge with no ruleset and drops ALL
  # traffic instead of passing it through.
  network_interface {
    name        = "eth0"
    bridge      = "vmbr0"
    firewall    = false
    mac_address = "BC:24:11:4A:2E:C7"
  }

  initialization {
    hostname = "convertx"
    dns {
      servers = ["1.1.1.1"]
    }
    ip_config {
      ipv4 {
        address = "10.0.0.13/24"
        gateway = "10.0.0.1"
      }
    }
  }

  operating_system {
    type             = "debian"
    template_file_id = "local:vztmpl/debian-12-standard_12.12-1_amd64.tar.zst"
  }

  lifecycle {
    # operating_system: template_file_id is create-only and doesn't read back from the
    # live container — without this, every plan proposes a destroy+recreate of a live CT.
    ignore_changes = [device_passthrough, operating_system]
  }
}
