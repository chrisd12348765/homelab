# openwebui.tf — LXC 111 on server (Open WebUI + Kokoro TTS).
# Hosts the Open WebUI and Kokoro compose stacks, moved off the agent VM (106)
# in July 2026 to free RAM on nas. Built from scratch (not adopted) — like
# home-assistant.tf, there was no pre-existing live container to retrofit, so
# this specifies a real template_file_id instead of the adoption placeholder.
# The lone ignore_changes (device_passthrough) is for a block deliberately NOT
# declared below — see the network_interface comment.

resource "proxmox_virtual_environment_container" "openwebui" {
  node_name    = "server"
  vm_id        = 111
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
    dedicated = 3072
    swap      = 512
  }

  disk {
    datastore_id = "local-zfs"
    size         = 24
  }

  # NOTE: this API token isn't root@pam, so it can only set `nesting` (not
  # `keyctl` like the GUI-created/adopted containers) — nesting alone is
  # sufficient for Docker.
  features {
    nesting = true
  }

  # Tailscale needs /dev/net/tun for its TUN device (same passthrough as
  # adguard.tf/home-assistant.tf). Our API token isn't root@pam, so it can't
  # push this block itself (403) — applied live via `pct set 111 -dev0
  # /dev/net/tun,mode=0660,uid=0,gid=0` as true root on the node instead.
  #
  # Deliberately NOT declared as a `device_passthrough` block here: an
  # ignore_changes entry only suppresses diffs on UPDATE, not on CREATE — a
  # from-scratch apply (disaster recovery, or a forced replace) would still
  # submit the block on the create call and hit the same 403. Omitting it
  # entirely means tofu never submits it at all, on create or update;
  # ignore_changes below still exists to stop tofu proposing to *remove* the
  # live-set value it reads back on refresh.
  #
  # firewall = false: cluster-wide pve-firewall is disabled (see vaultwarden.tf),
  # so firewall=true here just builds an empty fwbr/fwpr bridge with no ruleset
  # loaded — which dropped ALL traffic (even gateway pings) instead of passing
  # it through. Confirmed by comparing veth100i0 (vaultwarden, firewall=false,
  # plugs straight into vmbr0) against this container's fwbr111i0 before the fix.
  network_interface {
    name        = "eth0"
    bridge      = "vmbr0"
    firewall    = false
    mac_address = "BC:24:11:D7:A3:22"
  }

  initialization {
    hostname = "openwebui"
    dns {
      servers = ["1.1.1.1"]
    }
    ip_config {
      ipv4 {
        address = "10.0.0.12/24"
        gateway = "10.0.0.1"
      }
    }
  }

  operating_system {
    type             = "debian"
    # 12.12-1: the 12.7-1 image home-assistant.tf used is no longer in the pveam
    # index, and server's template cache was emptied by the 2026-07-02 reinstall.
    template_file_id = "local:vztmpl/debian-12-standard_12.12-1_amd64.tar.zst"
  }

  lifecycle {
    # operating_system: template_file_id is create-only and doesn't read back from
    # the live container (same class of gotcha as media-stack.tf/agent.tf's vga
    # ignore) — without this, every plan proposes a destroy+recreate of a live CT.
    ignore_changes = [device_passthrough, operating_system]
  }
}
