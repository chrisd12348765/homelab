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

# --- DONE: every guest imported + adopted into state (import blocks removed after
#     adoption; each resource lives in its own <name>.tf):
#       node01 LXCs: vaultwarden/100, adguard/101, vpn-exit/102, obsidian/103,
#                           caddy/104, homarr/107, syncthing/108
#       node02:               media-stack/105 (qemu), agent/106 (qemu), immich/109 (lxc)
#     Whole cluster is now under IaC management — `tofu plan` == "No changes".
#
# Multi-line import form is mandatory (single-line import {to=..,id=..} is invalid HCL).
# To retrofit a future guest: add a multi-line import block here, run
#   ./scripts/tofu.sh plan -generate-config-out=generated.tf
# clean the output into <name>.tf, apply to adopt, then delete the import block.
