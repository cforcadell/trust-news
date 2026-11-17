#!/usr/bin/env bash
# Shared on-disk contract for database backups made by the operator scripts.
# Callers keep the archive in a private directory and provide the database stream.

backup_artifact_prepare_output() {
  local output=$1 directory file
  [[ -n $output && $output != */ ]] || { echo 'Invalid backup output' >&2; return 2; }
  for file in "$output" "$output.manifest" "$output.sha256"; do
    [[ ! -e $file && ! -L $file ]] || { echo "Refusing to overwrite $file" >&2; return 1; }
  done
  directory=$(dirname -- "$output")
  [[ -d $directory ]] || { echo "Directory does not exist: $directory" >&2; return 1; }
  backup_artifact_temporary=$(mktemp "$directory/.database-backup.XXXXXXXX")
}

backup_artifact_finish_output() {
  local output=$1 engine=$2 database=$3 namespace=$4 pod=$5 checksum
  [[ -s $backup_artifact_temporary ]] || { echo 'Empty database archive' >&2; return 1; }
  gzip -t "$backup_artifact_temporary"
  checksum=$(sha256sum "$backup_artifact_temporary" | cut -d ' ' -f 1)
  printf 'engine=%s\ndatabase=%s\nnamespace=%s\npod=%s\ncreated_utc=%s\nsha256=%s\n' \
    "$engine" "$database" "$namespace" "$pod" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "$checksum" >"$output.manifest"
  printf '%s  %s\n' "$checksum" "$(basename -- "$output")" >"$output.sha256"
  mv -T -- "$backup_artifact_temporary" "$output"
}

backup_artifact_verify_input() {
  local input=$1 expected_engine=$2 manifest_engine expected actual
  [[ -f $input && -f $input.manifest ]] || { echo 'Backup or manifest not found' >&2; return 2; }
  backup_artifact_database=$(sed -n 's/^database=//p' "$input.manifest")
  expected=$(sed -n 's/^sha256=//p' "$input.manifest")
  manifest_engine=$(sed -n 's/^engine=//p' "$input.manifest")
  [[ -n $backup_artifact_database && $backup_artifact_database != *$'\n'* && \
     $expected =~ ^[0-9a-f]{64}$ ]] || { echo 'Invalid backup manifest' >&2; return 1; }
  # Existing MongoDB archives predate the engine field; only MongoDB accepts them.
  [[ $manifest_engine == "$expected_engine" || \
     ( -z $manifest_engine && $expected_engine == mongodb ) ]] || {
    echo 'Backup engine does not match restore engine' >&2; return 1;
  }
  actual=$(sha256sum "$input" | cut -d ' ' -f 1)
  [[ $actual == "$expected" ]] || { echo 'Backup checksum mismatch' >&2; return 1; }
  gzip -t "$input"
}
