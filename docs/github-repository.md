# Private GitHub data repository

`research-memory repo create` is intentionally narrower than a general GitHub
repository creator. It creates only private repositories for personal research
data.

## Creation contract

The command:

1. requires `git` and `gh`;
2. checks non-interactive `gh auth status`;
3. verifies global/environment Git author and committer identity outside the
   caller's repository context, without changing Git configuration;
4. refuses any existing target path, dangling symlink, config file, or config
   destination inside the data repository;
5. writes a minimal data-only structure and recovery journal;
6. initializes a new exact Git root and confirms that `origin` is absent;
7. creates the initial unsigned commit;
8. calls `gh repo create OWNER/NAME --private --source PATH --remote origin`;
9. queries the explicit repository and requires `visibility == PRIVATE`;
10. rejects Git URL rewrite configuration, then resolves every effective fetch
    and push URL and requires all of them to name that same owner/repository;
11. pushes the initial commit to the already verified URL;
12. creates non-secret config with mode `0600`; and
13. removes the operation journal only after every check succeeds.

It never calls `git remote set-url`, changes repository visibility, deletes an
existing directory, or automatically deletes a GitHub repository after a
partial failure.

The conservative URL-rewrite boundary applies to all configured
`url.*.insteadOf` and `url.*.pushInsteadOf` entries, including unrelated
rewrites. Diagnose `git_url_rewrite_unsupported` by listing config origins and
names:

```bash
git config --show-origin --name-only --get-regexp '^url\.'
```

## Organization repositories

Pass the organization explicitly:

```bash
research-memory repo create \
  --owner YOUR_ORGANIZATION \
  --name research-history \
  --private
```

The active GitHub account must have permission to create and inspect private
repositories for that owner.

## Automation

```bash
research-memory repo create \
  --owner YOUR_OWNER \
  --name research-history \
  --path /absolute/data/path \
  --private \
  --non-interactive \
  --json
```

GitHub, Git credential, SSH, and askpass prompts are disabled internally, and
automatic commits disable signing prompts. SSH uses strict host-key checking,
so its trusted GitHub key must already be present. JSON output includes
argument failures but never includes raw authentication output, tokens, or
command stderr.

External GitHub creation and push should be faked in unit tests through the
command-runner boundary. A real end-to-end smoke test creates billable/external
state and should use a deliberately named disposable private repository only
with explicit operator approval.
