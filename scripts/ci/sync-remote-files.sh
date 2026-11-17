#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: sync-remote-files.sh --host HOST --user USER --identity FILE
                            --known-hosts FILE --target-dir DIRECTORY [--port PORT]
                            [--mode OCTAL] [--directory-only | -- FILE [FILE ...]]

Installs regular files on a remote host through SSH and verifies their
SHA-256 hashes. Source basenames must be unique. The target directory must be
an absolute path containing only letters, numbers, '.', '_', '-' and '/'.
EOF
}

host=
user=
identity=
known_hosts=
target_dir=
port=22
mode=0750
directory_only=false

while (($#)); do
  case "$1" in
    --host|--user|--identity|--known-hosts|--target-dir|--port|--mode)
      (($# >= 2)) || { usage >&2; exit 2; }
      case "$1" in
        --host) host=$2 ;;
        --user) user=$2 ;;
        --identity) identity=$2 ;;
        --known-hosts) known_hosts=$2 ;;
        --target-dir) target_dir=$2 ;;
        --port) port=$2 ;;
        --mode) mode=$2 ;;
      esac
      shift 2
      ;;
    --)
      shift
      break
      ;;
    --directory-only)
      directory_only=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

sources=("$@")
[[ -n $host && -n $user && -f $identity && -f $known_hosts && -n $target_dir ]] || {
  usage >&2
  exit 2
}
if [[ $directory_only == true ]]; then
  [[ ${#sources[@]} -eq 0 ]] || { usage >&2; exit 2; }
else
  [[ ${#sources[@]} -gt 0 ]] || { usage >&2; exit 2; }
fi
[[ $host =~ ^[A-Za-z0-9._:-]+$ && $user =~ ^[A-Za-z0-9._-]+$ ]] || {
  echo "Invalid SSH host or user" >&2
  exit 2
}
[[ $port =~ ^[0-9]+$ && $port -ge 1 && $port -le 65535 ]] || {
  echo "Invalid SSH port: $port" >&2
  exit 2
}
[[ $target_dir =~ ^/[A-Za-z0-9._/-]+$ && $target_dir != */../* && $target_dir != */.. ]] || {
  echo "Invalid target directory: $target_dir" >&2
  exit 2
}
[[ $mode =~ ^0?[0-7]{3}$ ]] || { echo "Invalid file mode: $mode" >&2; exit 2; }

declare -A basenames=()
for source in "${sources[@]}"; do
  [[ -f $source && ! -L $source ]] || { echo "Source is not a regular file: $source" >&2; exit 2; }
  name=$(basename -- "$source")
  [[ $name =~ ^[A-Za-z0-9._-]+$ && $name != . && $name != .. ]] || {
    echo "Unsafe source basename: $name" >&2
    exit 2
  }
  [[ -z ${basenames[$name]+x} ]] || { echo "Duplicate source basename: $name" >&2; exit 2; }
  basenames[$name]=1
done

ssh_options=(
  -F /dev/null
  -i "$identity"
  -p "$port"
  -o BatchMode=yes
  -o IdentitiesOnly=yes
  -o PreferredAuthentications=publickey
  -o PasswordAuthentication=no
  -o KbdInteractiveAuthentication=no
  -o ForwardAgent=no
  -o StrictHostKeyChecking=yes
  -o UserKnownHostsFile="$known_hosts"
  -o GlobalKnownHostsFile=/dev/null
  -o UpdateHostKeys=no
)
scp_options=(
  -F /dev/null
  -i "$identity"
  -P "$port"
  -o BatchMode=yes
  -o IdentitiesOnly=yes
  -o PreferredAuthentications=publickey
  -o PasswordAuthentication=no
  -o KbdInteractiveAuthentication=no
  -o ForwardAgent=no
  -o StrictHostKeyChecking=yes
  -o UserKnownHostsFile="$known_hosts"
  -o GlobalKnownHostsFile=/dev/null
  -o UpdateHostKeys=no
)
remote="$user@$host"
scp_remote=$remote
if [[ $host == *:* ]]; then
  scp_remote="$user@[$host]"
fi
if [[ $directory_only == true ]]; then
  ssh "${ssh_options[@]}" "$remote" "install -d -m '$mode' -- '$target_dir'"
  echo "Directory ready: $target_dir"
  exit 0
fi
remote_stage=$(ssh "${ssh_options[@]}" "$remote" 'mktemp -d /tmp/remote-file-sync.XXXXXXXX')
[[ $remote_stage =~ ^/tmp/remote-file-sync\.[A-Za-z0-9]+$ ]] || {
  echo "Remote host returned an invalid staging path" >&2
  exit 1
}

cleanup() {
  ssh "${ssh_options[@]}" "$remote" "rm -rf -- '$remote_stage'" >/dev/null 2>&1 || true
}
trap cleanup EXIT

scp "${scp_options[@]}" -- "${sources[@]}" "$scp_remote:$remote_stage/"
ssh "${ssh_options[@]}" "$remote" sh -s -- "$remote_stage" "$target_dir" "$mode" <<'REMOTE'
set -eu
stage=$1
target=$2
mode=$3
install -d -m 0750 -- "$target"
found=false
for source in "$stage"/*; do
  [ -f "$source" ] || continue
  found=true
  name=$(basename -- "$source")
  temporary=$(mktemp "$target/.$name.XXXXXXXX")
  trap 'rm -f -- "$temporary"' EXIT HUP INT TERM
  install -m "$mode" -- "$source" "$temporary"
  mv -f -- "$temporary" "$target/$name"
  trap - EXIT HUP INT TERM
done
[ "$found" = true ]
REMOTE

for source in "${sources[@]}"; do
  name=$(basename -- "$source")
  local_hash=$(sha256sum "$source" | cut -d ' ' -f 1)
  remote_hash=$(ssh "${ssh_options[@]}" "$remote" "sha256sum -- '$target_dir/$name'" | cut -d ' ' -f 1)
  [[ $remote_hash == "$local_hash" ]] || {
    echo "Checksum mismatch after installing $name" >&2
    exit 1
  }
  echo "Installed $target_dir/$name (sha256=$local_hash)"
done

