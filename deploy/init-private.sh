#!/bin/sh
# Run ONLY from the prepared private repository directory after obtaining createRepository permission.
# Creates new objects only; never deletes, force-pushes, or replaces an existing repository.
set -eu
repo='xyz1367487/hl-liqmap-private'
test -d state && test -f state/addresses.json && test -f state/accounts.json
test -f state/snapshot.json && test -f .github/workflows/collect.yml
if test -d .git; then
  echo 'Existing git metadata found; inspect it instead of initializing over it.' >&2
  exit 1
fi
# Stop if any repository with this name is already accessible. Inspect it manually first.
if gh repo view "$repo" --json name >/dev/null 2>&1; then
  echo 'Repository already exists; inspect visibility and contents before proceeding.' >&2
  exit 1
fi
gh repo create "$repo" --private --description 'Private hl-liqmap state and account snapshots'
visibility=$(gh api "repos/$repo" --jq '.private')
identity=$(gh api "repos/$repo" --jq '.full_name')
test "$visibility" = true && test "$identity" = "$repo"
git init -b main
git remote add origin "https://github.com/$repo.git"
git add -- .gitignore .github/workflows/collect.yml LICENSE README.md harvest.py aggregate.py private_export.py publish_aggregate.py state/ snapshots/
git -c user.name='hl-liqmap preparation' -c user.email='preparation@users.noreply.github.com' commit -m 'Initialize private collection state; collection enabled; publication requires secret'
# Recheck visibility immediately before sending any account data.
test "$(gh api "repos/$repo" --jq '.private')" = true
git push -u origin main
printf '%s\n' 'Private seed uploaded. Main initialization push starts collection; publication requires PUBLIC_AGGREGATE_TOKEN.'
