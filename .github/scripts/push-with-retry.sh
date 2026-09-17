#!/usr/bin/env bash
set -euo pipefail
# Caller has committed only its own state/history changes. Preserve other jobs.
target_branch="${GITHUB_REF_NAME:-master}"
for attempt in 1 2 3 4 5; do
  git fetch origin "$target_branch"
  git rebase "origin/$target_branch"
  if git push origin "HEAD:$target_branch"; then
    exit 0
  fi
  if ((attempt < 5)); then
    sleep $((attempt * 2))
  fi
done
echo "Failed to persist history after 5 attempts." >&2
exit 1
