# imports.tf — RETROFIT existing guests into code (semi-automatic).
#
# Workflow:
#   1. Add an import block per existing guest (bpg id format = "<node>/<vmid>").
#   2. ../scripts/tofu.sh plan -generate-config-out=generated.tf
#        -> OpenTofu reads the live resource via bpg and writes matching HCL.
#   3. Review generated.tf, fold the good parts into main.tf, then apply
#        (first apply just adopts state into management — no real changes).
#
# Live inventory (pulled 2026-06-25):
#   node02:          105 media-stack(qemu) 106 agent(qemu) 109 immich(lxc)
#   node01: 100 vaultwarden 101 adguard 102 vpn-exit 103 obsidian
#                  104 caddy 107 homarr 108 syncthing  (all lxc)

# --- DONE: imported + adopted into state (import blocks removed after adoption;
#     resources live in their own <name>.tf files):
#       immich  (LXC 109 on node02)          2026-06-25  -> immich.tf
#       adguard (LXC 101 on node01) 2026-06-26  -> adguard.tf
#       caddy   (LXC 104 on node01) 2026-06-26  -> caddy.tf

# --- Backlog: import the rest using the proven Immich pattern -----------------
# import { to = proxmox_virtual_environment_container.vaultwarden, id = "node01/100" }
# import { to = proxmox_virtual_environment_container.homarr,      id = "node01/107" }
# import { to = proxmox_virtual_environment_container.syncthing,   id = "node01/108" }
# import { to = proxmox_virtual_environment_vm.media_stack,        id = "node02/105" }
# import { to = proxmox_virtual_environment_vm.agent,             id = "node02/106" }
