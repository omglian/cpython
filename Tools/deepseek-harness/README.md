# DeepSeek Harness (dsh)

[DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) is
DeepSeek's plugin-based agent framework ("Everything is a Plugin"),
distributed as the npm package `@deepseek-ai/dsh`. It is currently in
developer preview, so expect breaking changes between releases.

## Install

Run the script in this directory (no root required):

```sh
Tools/deepseek-harness/install.sh
```

It installs the package into a per-user npm prefix (default `~/.local`,
override with `DSH_PREFIX=/some/prefix`) and puts the `dsh` command at
`$PREFIX/bin/dsh`. Node.js 18+ with npm is the only prerequisite.

One-off alternative without installing anything:

```sh
npx -y @deepseek-ai/dsh web
```

## Verify

```sh
dsh --version   # e.g. 0.1.0-rc.6
dsh --help
```

## Use

```sh
dsh web                          # Web UI at http://127.0.0.1:3080
dsh --profile headless "task"    # answer one task, print result, exit
dsh plugin --profile web add <package>   # install a plugin into a profile
```

A DeepSeek API key (from your DeepSeek account's API keys page) is
required before the harness will run tasks. Profiles and overrides live
under `$DSH_HOME/profiles` (default `~/.dsh`).

Last verified: `dsh` 0.1.0-rc.6 on Linux with Node.js 22 — CLI runs and
`dsh web` serves the UI on 127.0.0.1:3080.
