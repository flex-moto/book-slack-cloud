#!/usr/bin/env bash
set -euo pipefail

state_files=(sunrise_state.json)

if [[ -z "$(git status --porcelain -- "${state_files[@]}")" ]]; then
  echo "No sunrise state changes to persist."
  exit 0
fi

git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
git add -- "${state_files[@]}"
git commit -m "chore: update sunrise slot state [skip ci]"

target_branch="${GITHUB_REF_NAME:-master}"
max_attempts=5

for ((attempt = 1; attempt <= max_attempts; attempt++)); do
  # Replay only this run's state commit on the latest branch tip. This keeps
  # concurrent commits (for example posted.log updates) instead of replacing them.
  git fetch origin "$target_branch"
  git rebase "origin/$target_branch"

  if git push origin "HEAD:$target_branch"; then
    exit 0
  fi

  if ((attempt < max_attempts)); then
    echo "Push raced with another commit; retrying ($attempt/$max_attempts)."
    sleep $((attempt * 2))
  fi
done

echo "Failed to persist sunrise state after $max_attempts attempts." >&2
exit 1
