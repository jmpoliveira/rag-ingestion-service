# Contributing and releasing

## Repository rules

Set these up on GitHub when the repository is created (Settings -> Rules -> Rulesets), the
same as ai-agent-service:

| Rule | Effect |
|---|---|
| `main` changes only through a pull request | `git push origin main` is rejected; push a branch and open a PR |
| Required status checks | `Lint, types and tests` on Python 3.12, 3.13 and 3.14, and `Docker build` |
| Merge commits disabled | Merge with **squash** or **rebase** |
| Tags cannot be deleted (or moved) | A pushed tag is permanent: tag only commits already on `main` |

## Everyday change

```bash
git switch main && git pull
git switch -c <type>/<short-name>          # e.g. feat/markdown-chunking
# ... change, then:
make check
make test-live                             # when an adapter or the settings changed (needs docker-env)
git add <files> && git commit -m "<type>(<scope>): <summary>"
git push -u origin <type>/<short-name>
gh pr create --base main --fill
gh pr checks --watch
gh pr merge --squash --delete-branch       # or --rebase to keep every commit
git switch main && git pull
```

Commit messages follow Conventional Commits (`feat`, `fix`, `docs`, `test`, `refactor`,
`chore`), in English. Use `--rebase` when individual commits matter later (for example commits
referenced by `evals/EXPERIMENTS.md`).

## Releasing a version

**The tag comes last**, after the merge, because squash and rebase give commits new hashes.

1. On a branch, bump `version` in `pyproject.toml`, update the README and any ADRs, and merge
   it through a PR.
2. Tag the merged commit on `main` and publish the release:

   ```bash
   git switch main && git pull
   make check
   git tag -a vX.Y.Z -m "vX.Y.Z: <title>"
   git push origin vX.Y.Z
   gh release create vX.Y.Z --verify-tag --title "vX.Y.Z – <title>" --notes "<what changed>"
   ```

Never run `git push --follow-tags` or `git push --tags` from a branch. A fix after a pushed tag
is the next patch version.
