---
name: labgrid
description: Use shared hardware through labgrid to flash firmware, reset readers, inspect serial logs, send commands, or capture device screens, including concurrent agent sessions.
---

Use the JappyJan/labgrid fork's `labgrid-client session` command to hold one
reader for a complete hardware operation. Build firmware before reserving.
Check `labgrid-client session --help` for availability and read the project's
hardware-lab documentation for its environment YAML, drivers and firmware format.

```sh
labgrid-client -x HOST:20408 session --filter board=BOARD \
  --purpose 'TASK: validation goal' --wait-timeout 300 -- COMMAND ARGUMENTS
```

Use `-p PLACE` before `session` when a specific reader is required. Otherwise,
filters let the coordinator allocate any matching reader. Each invocation gets
a unique identity, even for agents sharing one machine and SSH account.

The child inherits `LG_PLACE`, `LG_COORDINATOR`, `LG_USERNAME`, `LG_TOKEN`,
`LG_SESSION_ID`, `LG_SESSION_PURPOSE`, and `LG_ARTIFACTS`. Native labgrid commands
inside the child use that identity. Save logs and captures in `LG_ARTIFACTS`;
the session already writes `session.json` there. `python` and native labgrid
commands inside the child use the client's installed environment. Pass `-c ENV.yaml` before
`session` to supply `LG_ENV` to children. Shell expansion of those variables
must happen inside the child, for example with `sh -c '...'`.

Keep flash, reset, boot readiness, serial interaction and capture in one child
process or script. Use the project's session-aware helper or native labgrid
drivers; do not independently acquire/release, create another session, change
identity, or detach hardware work into background processes. The parent stops
the child process group before releasing the reader. Serial logs and images
are evidence; assert the expected responses or inspect the images before
reporting success.

Normal completion, command failure, SIGINT and SIGTERM clean up the claim and
reservation. Allocation timeout reports busy without taking another claim.
Lost claims or coordinator errors stop the command. SIGKILL of the session
parent or machine failure can leave an abandoned claim and child processes:
inspect `labgrid-client who`, the session metadata and process state, then
report the situation. Never automatically use `release --kick`; deliberate
recovery must stop the original hardware operation first.

Claims coordinate trusted participants. Shared SSH credentials and the native
force-release command are not an authorization boundary.

For Attractap, consult `apps/attractap-lab/README.md` in the current Attraccess
checkout. Its `attractap-lab` CLI reuses the session claim and defaults output
to `LG_ARTIFACTS`. Machines configured with the personal Nix profile supply
`LG_COORDINATOR` and `~/.config/attractap-lab/reader.yaml`; when present, use
that file with `attractap-lab --config`. A missing camera blocks real screen validation; do not count
placeholder frames as evidence. Flashing a fresh merged image at offset zero
may reset stored device configuration, so follow the firmware documentation.
