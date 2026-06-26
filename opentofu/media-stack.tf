# media-stack.tf — QEMU VM 105 on node02 (media services; iGPU transcode + virtiofs).
# Retrofitted via generate-config-out, hand-cleaned: dropped the experimental
# generator's invalid empty-string enums (cpu.architecture="", memory.hugepages="",
# vga.type="") and operation-timeout / default noise. Hardware blocks kept faithful.
#
# NOTE: hostpci0 = Intel iGPU passthrough for transcoding; virtiofs "media" mapping
# exposes the ZFS array share into the guest (see Storage runbook).

resource "proxmox_virtual_environment_vm" "media_stack" {
  node_name = "node02"
  vm_id     = 105
  name      = "media-stack"

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
    cores   = 4
    sockets = 1
    type    = "x86-64-v2-AES"
  }

  memory {
    dedicated = 10240
  }

  network_device {
    bridge      = "vmbr0"
    model       = "virtio"
    firewall    = true
    mac_address = "BC:24:11:00:00:09"
    queues      = 4
  }

  disk {
    datastore_id = "local-lvm"
    interface    = "scsi0"
    size         = 256
    file_format  = "raw"
    ssd          = false
    discard      = "on"
    iothread     = true
    cache        = "none"
    aio          = "io_uring"
  }

  efi_disk {
    datastore_id      = "local-lvm"
    file_format       = "raw"
    type              = "4m"
    pre_enrolled_keys = true
  }

  hostpci {
    device = "hostpci0"
    id     = "0000:00:02"
    pcie   = true
    rombar = true
  }

  virtiofs {
    mapping = "media"
    cache   = "auto"
  }

  operating_system {
    type = "l26"
  }

  # NOTE: the live VM has no vga config at all — leaving the block off and
  # ignoring it so the provider's "std" default isn't written to the guest.

  lifecycle {
    ignore_changes = [operating_system, vga]
  }
}
