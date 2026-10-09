# Step 1 / v0.6.0 manual review

This milestone adds visible bridge control and everyday navigation. **Stop after
this review; do not proceed to animation/batch-editing features without approval.**

## Safe test setup

Build both components and launch the separate review demo:

```sh
npm run build
bash scripts/build-libresprite.sh
node scripts/demo-navigation.mjs
```

This uses the actual MCP stdio protocol and launches **one new editor**, not any
existing window. Its generated 32×32 test sprites A and B are saved under the
printed `.runtime/nav-…/assets/` directory, with two frames each. The script
verifies switching/focusing and the safe-close refusal, then stops making sprite
edits and remains connected only to monitor button status. It never opens your
working `assets/` collection. Like other development windows it still uses the
ordinary LibreSprite preferences/recovery locations.

## Test checklist

1. **Status:** look at the bottom-right status bar: `AI: Paused | Resume`.
   Hovering the canvas or changing tools should not erase the AI control.
2. **Resume:** finish any playback/drawing, then click Resume. Expect
   `AI: Enabled | Pause`. This grants permission; the demo does not make edits.
3. **Local pause:** click Pause. Expect `AI: Paused | Resume`. The demo should
   report `PASS: remote resume refused (USER_PAUSED)` in its output. The agent
   cannot override that pause. Click Resume again only when ready.
4. **Manual review:** pause, switch A/B tabs, scrub the two frames, and paint a
   small test mark. Native undo/redo and saving should still behave normally.
5. **Disconnect:** Ctrl+C in the demo terminal. The script disconnects but leaves
   the GUI and your test edits open. Expect `AI: Waiting (paused)`, disabled
   until a client connects. It does not quit/close the window or discard work.

## MCP navigation checks

Refreshing the chat client's MCP tools and launching a new bridge-enabled window
is required to use the three new tools. Already-running servers/editors retain
their old catalogs/bridge. Do not close unsaved originals just to upgrade.
The review demo has its own socket/root and does not change your personal config;
it owns the sole client connection until stopped. Its `review.json` records
the socket, process, root, and test document IDs if you want to configure a
separate review connection after disconnecting the monitor.

With a client connected to a **test** editor:

- List/inspect both sprites, then activate A using B's ID as
  `expectedActiveDocumentId` and A's current revision. It should restore A's view.
- Focus a layer/frame with `set_active_site`; pixels and undo history should not
  change. A request with an invalid frame plus a valid layer must change neither.
- Modify A; `close_document(confirm: true)` should return `UNSAVED_CHANGES` and
  leave it open without a dialog. Save first, inspect again, then close: only
  A and its cloned views should disappear, and the saved file should remain.
- A never-saved blank sprite must also refuse closing. No force/discard option
  is provided.
- For clone coverage, duplicate a saved test sprite's view with the native
  workspace UI, then close that document via MCP: all its views should close,
  while other sprites stay open.

The automated disposable-GUI suite checks the request guards, pixel/mask/history
preservation, file hashes, and close/reopen behavior. This review is primarily
about the visible controls and whether the workflow feels comfortable.

For the focused step 1 regression run, including closing the last sprite:

```sh
python3 scripts/test-live-bridge.py --navigation-only
```
