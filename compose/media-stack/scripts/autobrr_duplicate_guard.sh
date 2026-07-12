#!/bin/sh
# Conservative duplicate guard for Autobrr. Exit 0 = allow, 1 = reject.
set -eu

release="$*"
[ -n "$release" ] || { echo "duplicate-guard: no release supplied; allow"; exit 0; }

norm_key() {
  # NOTE: do NOT strip a trailing short token here. It was added to drop scene-group
  # suffixes, but it ran on BOTH sides and mangled untagged library folder names
  # (e.g. "Better Call Saul" -> "better call", "Mad Max" -> "mad"), causing the title to
  # stop matching its own release -> duplicate re-downloaded. The awk year/season `break`
  # below already drops the group suffix for properly tagged releases.
  printf '%s' "$1" \
    | sed 's/[._\[\](){}-]/ /g' \
    | sed -E 's/[^A-Za-z0-9 ]+/ /g' \
    | awk '{
        out="";
        for (i=1; i<=NF; i++) {
          w=tolower($i);
          if (w ~ /^(1080p|720p|2160p|480p|4k|uhd|hdr|hdr10|dv|web|webdl|webrip|bluray|bdrip|brrip|remux|x264|x265|h264|h265|hevc|avc|av1|aac|ac3|eac3|ddp|dts|truehd|atmos|proper|repack|limited|internal|extended|unrated|multi|dual|audio|subs|complete|season)$/) continue;
          # Year / season mark the END of the title -- but only once we already have title
          # words. A LEADING year/season is part of the title itself (e.g.
          # 2001 - A Space Odyssey, 1917, 1984), so do not break on it or the key is empty.
          if (out != "" && w ~ /^(19[0-9][0-9]|20[0-9][0-9])$/) break;
          if (out != "" && w ~ /^s[0-9][0-9](e[0-9][0-9][0-9]?)?$/) break;
          out = out " " w;
        }
        gsub(/^ +| +$/, "", out);
        print out;
      }'
}

year_of() {
  printf '%s' "$1" | grep -Eo '(^|[^0-9])(19[0-9]{2}|20[0-9]{2})([^0-9]|$)' | head -1 | tr -dc '0-9' || true
}

rel_key=$(norm_key "$release")
rel_year=$(year_of "$release")
[ ${#rel_key} -ge 4 ] || { echo "duplicate-guard: weak key '$rel_key'; allow"; exit 0; }

for root in /mnt/media/movies /mnt/media/tv; do
  # Skip a root we can't list within 10s — missing, or a HUNG virtiofs mount (a known risk on
  # this NAS). Without this guard a hung /mnt/media makes `find` block until autobrr's exec
  # times out, and on_error=REJECT then drops EVERY freeleech grab. Failing open (skip the
  # root -> eventually allow) beats silently rejecting everything.
  timeout 10 ls -d "$root" >/dev/null 2>&1 || continue
  timeout 30 find "$root" -mindepth 1 -maxdepth 1 -print | while IFS= read -r path; do
    name=$(basename "$path")
    ent_key=$(norm_key "$name")
    [ -n "$ent_key" ] || continue
    ent_year=$(year_of "$name")
    year_ok=0
    [ -z "$rel_year" ] && year_ok=1
    [ -z "$ent_year" ] && year_ok=1
    [ "$rel_year" = "$ent_year" ] && year_ok=1
    if [ "$year_ok" -eq 1 ]; then
      case "$rel_key:$ent_key" in
        "$ent_key:"*|*":$rel_key")
          echo "duplicate-guard: reject likely duplicate: '$release' matches '$name'"
          exit 1
          ;;
      esac
      if [ "$rel_key" = "$ent_key" ]; then
        echo "duplicate-guard: reject likely duplicate: '$release' matches '$name'"
        exit 1
      fi
    fi
  done || exit 1
done

echo "duplicate-guard: allow '$release'"
exit 0
