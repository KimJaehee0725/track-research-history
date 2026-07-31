# Data repository format

The generated repository is intentionally separate from the public Research
Memory application source.

```text
research-history/
├── README.md
├── .gitignore
├── .research-memory/
│   └── schema.json
└── history/
    ├── CONTEXT.md
    ├── INDEX.md
    ├── daily/.gitkeep
    ├── changes/.gitkeep
    ├── decisions/.gitkeep
    ├── ideas/.gitkeep
    ├── experiments/.gitkeep
    ├── handoffs/.gitkeep
    ├── capsules/.gitkeep
    └── sessions/.gitkeep
```

`research-memory record` creates timestamped Markdown under `history/daily/`
and appends a relative link to `history/INDEX.md`.

The following must not be committed:

- application, server, client, deployment, or test source;
- GitHub tokens, passwords, SSH private keys, or `.env` files;
- SQLite indexes and sidecar files;
- caches, runtime lock files, and operation journals; and
- machine-specific credentials or raw private transcripts.

`.research-memory/schema.json` is tracked and identifies the data format.
Local indexes may be rebuilt and are ignored. The non-secret machine config
that selects the active repository lives outside the data repository, normally
at `~/.config/research-memory/config.json`, with owner-only permissions.
