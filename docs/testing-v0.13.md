# v0.13 cooperative-editing draft PR checklist

**Source-only branch:** `feat/cooperative-editing`. Do not merge or release before
manual review. Approved v0.9/v0.12 app folders/ZIPs remain unchanged; this work
does not install an application or update personal MCP configuration.

## Build and automated checks

From the branch checkout with the existing prerequisites:

```sh
npm ci
npm test
python3 -m unittest discover -s tests -v
bash scripts/build-libresprite.sh
python3 scripts/smoke-test-libresprite.py
python3 scripts/test-live-bridge.py
node scripts/test-cooperative-mcp.mjs
```

Native GUI tests and the real-MCP test launch **new** generated-art editors with
private sockets, asset roots and profiles. Never run them on your personal editor
or use personal art as fixtures. Run GUI suites sequentially.

Optional OS gestures require an unused desktop and **existing** macOS Accessibility/
post-event permissions; no permissions are requested or changed automatically:

```sh
LIBRESPRITE_TEST_GUI_INPUT=1 python3 scripts/test-live-bridge.py --cooperative-only
LIBRESPRITE_TEST_GUI_INPUT=1 node scripts/test-cooperative-mcp.mjs
```

These checks bring only the disposable editor forward, verify ownership of the
frontmost window at the pointer before every mouse event, release held gestures
and restore the pointer. Keyboard input is process-targeted. Do not interact with
the desktop during an opted-in run; focus changes abort input rather than clicking
another app. Without opt-in/permissions, gesture checks explicitly report SKIP.

## Separate manual-review editor/server

Use a fresh private directory (example uses the ignored `.runtime/`):

```sh
mkdir -m 700 .runtime/v0.13-manual
mkdir .runtime/v0.13-manual/assets
LIBRESPRITE_SOCKET="$PWD/.runtime/v0.13-manual/b.sock" \
LIBRESPRITE_ASSET_ROOT="$PWD/.runtime/v0.13-manual/assets" \
LIBRESPRITE_USER_DIR="$PWD/.runtime/v0.13-manual/profile" \
node dist/index.js
```

The last command is an MCP stdio server, not a terminal REPL: use it as a **separate
test client's** server command/environment. No changes to your normal client
configuration are required. Run `libresprite_launch`, then `libresprite_connect`.
Verify bridge version `0.13.0` and a 70-tool catalog. Explicitly resume. Existing
running editors and packaged servers may still be v0.12 or earlier.

Create generated test artwork through the tools; do not open your master sprites.
Ask the test agent to follow [the cooperative result contract](cooperative-editing.md)
and use prepare/apply for the three supported corrections. A client/model that
ignores `deferred`/`conflict` cannot be expected to continue correctly.

## Manual acceptance cases

- [ ] **Held pan:** keep middle-button/Space pan held while inspecting/rendering
  and applying a prepared correction. The viewport/zoom/site/mask must not jump.
  Navigation/closing/Undo/canvas operations must wait/refuse, not disrupt the pan.
- [ ] **Held drawing:** start a stroke while an AI request is running. No partial
  artwork reads/writes. A short gesture allows continued work after revalidation;
  a >2-second hold returns deferred without pausing or leaving a native queued edit.
- [ ] **Disjoint edits:** prepare a correction, draw elsewhere, then apply.
  User work stays intact, `rebased:true`, user/AI Undo steps are separate.
- [ ] **Overlap:** paint a protected target/source before apply. Conflict returns
  `applied:false`, artwork/history remain unchanged, token cannot be reused.
- [ ] **Selection:** selection dragging waits; after completion an explicit
  correction may coexist and must preserve the new GUI mask.
- [ ] **Floating transform:** drag selected pixels and leave the transform pending.
  Even after mouse-up, reads/writes remain guarded until Return/Escape. Pan while
  pending must NOT be classified as view-only. Test other selection/cel transforms.
- [ ] **Cel dragging and multiple views:** hold the Move tool/timeline cel drag;
  test a cloned view with an unfinished gesture. All target views must be safe.
- [ ] **Strict tools:** a completed manual edit before an old-revision write must
  return a conflict. The agent must inspect/replan, not silently substitute revisions.
- [ ] **Pause:** click local Pause while the agent is waiting; no further AI write.
  Remote resume returns `USER_PAUSED`. Only your Resume button releases the latch.
- [ ] **Dialogs/playback:** do not bypass their safety guards; wait/defer sensibly.
- [ ] **Navigation:** changing active document during waiting must not silently
  switch back or apply an old plan. Prepared tokens remain document-specific.
- [ ] **Undo/Redo:** repeatedly undo/redo AI and user transactions; check pixels,
  selection, focus, modified/saved state and clean no-op/conflict history.
- [ ] **Disconnect/cancellation/closure:** cancelled waits/unsent requests send no
  later writes (already transmitted requests can complete; inspect their outcome);
  disconnect pauses and invalidates tickets. Unknown outcomes are inspected, not
  blindly retried. Closing the app must not silently launch a replacement.
- [ ] **Performance:** larger corrections/guard scans remain usable; atomic native
  transactions can briefly delay input. No promise of simultaneous writers.

Record review observations on the **draft PR**; request changes before merge.
New package rebuilding, binary publication and signing/notarization remain separate
decisions. Full Linux GUI validation remains deferred; no new native CI milestone.

## Automated verification recorded 2026-10-14

On Apple Silicon/macOS, with the source build and disposable generated-only profiles:

- Native editor build and four smoke checks: passed.
- TypeScript/MCP suite: **21 tests passed**.
- Native helper/privacy/metadata suite: **45 tests passed**.
- Complete native GUI suite with opted-in OS gestures: **68 PASS groups, no skips**.
- Focused cooperative suite: **8 PASS groups**, including held pan, pencil,
  selection/cel dragging, overlap/source conflicts, floating transforms and Undo.
- Real stdio MCP: verified 70 tools, guarded rebase/conflicts, held pan/Undo deferral,
  short/long drawing waits, no queued writes, actual MCP cancellation, continuing
  work and remote/local Pause behavior.

Earlier development runs exposed the existing 32-tab ceiling (fixed by saving/
closing only new fixtures) and a transient recovery reader lock (handled only at
proven pre-operation lock acquisition). No resource, capture or revision guard
was weakened. OS gesture runs also deliberately abort if another window takes
focus and can fail if the desktop is being used; the final isolated runs passed.
Multiple cloned-view interactions and broader real-user dialogs/playback/ergonomics
remain on the manual acceptance checklist above. Automated results are not manual
release approval.
