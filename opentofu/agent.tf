# agent.tf — QEMU VM 106 on node02 (Hermes agent host; GPU passthrough).
# Retrofitted via generate-config-out, hand-cleaned: dropped the experimental
# generator's invalid empty-string enums (cpu.architecture="", memory.hugepages="",
# vga.type="") and operation-timeout / default noise. Hardware blocks kept faithful.
#
# NOTE: hostpci0 = full GPU passthrough (xvga), so memory is a pinned/static host-RAM
# reservation (balloon can't reclaim it). Sized 8192 since 2026-07: Open WebUI moved to
# CT 111 (openwebui, on server); Kokoro (~1.1 GiB) stayed here after the N5105 failed
# its TTS benchmark (RTF ~2.8). LLM weights live in VRAM, not RAM (llama-server host
# RSS ~1 GiB with bonsai-27b loaded), so 8 GiB holds the stack with ~5 GiB page cache
# for the ggufs. A memory change needs a full VM stop/start (passthrough, balloon=0).

resource "proxmox_virtual_environment_vm" "agent" {
  node_name = "nas"
  vm_id     = 106
  name      = "agent"

  bios          = "ovmf"
  machine       = "q35"
  scsi_hardware = "virtio-scsi-single"
  boot_order    = ["scsi0", "net0"]
  on_boot       = true
  started       = true
  tablet_device = true

  agent {
    enabled = true
    timeout = "15m"
    type    = "virtio"
  }

  cpu {
    cores   = 8
    sockets = 1
    type    = "host"
    flags   = ["+pdpe1gb"]
    numa    = true
  }

  memory {
    dedicated = 8192
  }

  network_device {
    bridge      = "vmbr0"
    model       = "virtio"
    firewall    = true
    mac_address = "BC:24:11:00:00:08"
    queues      = 4
  }

  disk {
    datastore_id = "local-zfs"
    interface    = "scsi0"
    size         = 256
    file_format  = "raw"
    ssd          = true
    discard      = "on"
    iothread     = true
    cache        = "none"
    aio          = "io_uring"
  }

  efi_disk {
    datastore_id      = "local-zfs"
    file_format       = "raw"
    type              = "4m"
    pre_enrolled_keys = true
  }

  hostpci {
    device = "hostpci0"
    id     = "0000:03:00"
    pcie   = true
    xvga   = true
    rombar = true
  }

  operating_system {
    type = "l26"
  }

  vga {
    clipboard = "vnc"
    memory    = 16
  }

  lifecycle {
    # vga.type is unset on the live VM; the provider schema defaults it to "std"
    # (and "" is an invalid value), so ignore it rather than write to the GPU guest.
    ignore_changes = [operating_system, vga]
  }
}
