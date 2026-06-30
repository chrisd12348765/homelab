# Tailnet ACL under IaC. The policy lives in tailscale-acl.hujson (versioned, reviewed
# via `tofu plan`); its embedded `tests`/`sshTests` are validated server-side on apply,
# so a policy that fails them is rejected before it goes live.
#
# Provider config + creds: see providers.tf (provider "tailscale", OAuth acl scope).
#
# ONE-TIME ADOPTION (the console already has a policy — adopt it, don't clobber):
#   scripts/tofu.sh init
#   scripts/tofu.sh import tailscale_acl.policy acl   # import id is literally "acl"
#   scripts/tofu.sh plan      # shows live-vs-file diff — review before applying
#   scripts/tofu.sh apply
# Thereafter: edit tailscale-acl.hujson → tofu.sh plan (review) → apply → hl.sh push.

resource "tailscale_acl" "policy" {
  acl = file("${path.module}/tailscale-acl.hujson")
}
