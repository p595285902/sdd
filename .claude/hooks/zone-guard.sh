#!/usr/bin/env bash
# Specs/code isolation guard for PreToolUse on Edit/Write/NotebookEdit:
# a unit of work touches either openspec/ (specs) or the rest of the repo (code) — never both.
# The active zone is derived from pending git changes (staged, unstaged, and untracked):
# uncommitted code changes block spec edits and vice versa. Committing (or stashing)
# releases the zone. tasks.md files are always exempt. Files outside the repo are ignored.
set -euo pipefail

input="$(cat)"
file_path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')"

if [ -z "$file_path" ]; then
  exit 0
fi

if [ "$(basename "$file_path")" = "tasks.md" ]; then
  exit 0
fi

# Determine repo root (directory containing .claude) to resolve relative paths.
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"

case "$file_path" in
  /*) abs_path="$file_path" ;;
  *) abs_path="$repo_root/$file_path" ;;
esac

case "$abs_path" in
  "$repo_root/"*) ;;
  *) exit 0 ;;
esac

case "$abs_path" in
  "$repo_root/openspec/"*) target_zone="specs" ;;
  *) target_zone="code" ;;
esac

specs_count=0
code_count=0
specs_examples=""
code_examples=""

while IFS= read -r line; do
  [ -n "$line" ] || continue
  entry="${line:3}"
  # A rename line is "old -> new"; both sides count as pending changes.
  if [[ "$entry" == *" -> "* ]]; then
    candidates="${entry%% -> *}"$'\n'"${entry##* -> }"
  else
    candidates="$entry"
  fi
  while IFS= read -r p; do
    p="${p%\"}"; p="${p#\"}"
    [ -n "$p" ] || continue
    [ "$(basename "$p")" = "tasks.md" ] && continue
    case "$p" in
      openspec/*)
        specs_count=$((specs_count + 1))
        [ "$specs_count" -le 3 ] && specs_examples="${specs_examples:+$specs_examples, }$p"
        ;;
      *)
        code_count=$((code_count + 1))
        [ "$code_count" -le 3 ] && code_examples="${code_examples:+$code_examples, }$p"
        ;;
    esac
  done <<<"$candidates"
done < <(git -C "$repo_root" status --porcelain)

deny() {
  jq -cn --arg r "$1" '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":$r}}'
  exit 0
}

if [ "$specs_count" -gt 0 ] && [ "$code_count" -gt 0 ]; then
  deny "Specs/code isolation rule: the working tree already mixes zones (specs: $specs_examples; code: $code_examples). Commit or stash one side before editing anything. tasks.md files are exempt from this rule."
fi

if [ "$target_zone" = "specs" ] && [ "$code_count" -gt 0 ]; then
  deny "Specs/code isolation rule: uncommitted code changes exist (e.g. $code_examples), so '$file_path' in the specs zone cannot be edited. Commit or stash the code changes first. tasks.md files are exempt from this rule."
fi

if [ "$target_zone" = "code" ] && [ "$specs_count" -gt 0 ]; then
  deny "Specs/code isolation rule: uncommitted spec changes exist (e.g. $specs_examples), so '$file_path' in the code zone cannot be edited. Commit or stash the spec changes first. tasks.md files are exempt from this rule."
fi

exit 0
