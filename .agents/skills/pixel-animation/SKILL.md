---
name: pixel-animation
description: >
  Create or improve pixel-art sprite animations using LibreSprite MCP with rough
  key poses, evidence-based motion review, and bounded autonomous revision loops.
  Use for character attacks, casting, walks, idle cycles, and requests to fix stiff,
  floaty, jittery, or unconvincing sprite animation. Human review is final-only by
  default; intermediate reviews are performed by the agent.
compatibility: Requires LibreSprite MCP and a model that can inspect image results. Reviewer subagents and video input are optional.
---

# Pixel animation

Animate the action before polishing the pixels. A valid export, more frames, or
more particles does not establish good motion. Own the intermediate creative
decisions; deliver the best reviewed result for the human's final review.

## Operating rules

- Default to autonomous iteration and **human final review only**. Do not ask for
  approval of the brief, key poses, rough pass, or routine corrections. Follow a
  user's explicit request for intermediate reviews instead when given.
- Make reasonable assumptions and state them briefly. Interrupt only for a real
  blocker: missing access/input essential to proceed, a manual pause, or permission
  needed for destructive changes to existing work. Do not stop merely because
  video-capable review or a subagent is unavailable.
- Use the actual LibreSprite MCP tool schemas, discovering tools as needed. Inspect
  existing artwork and the editor session before editing. Connect to an existing
  bridge when possible; do not launch duplicate editors unnecessarily.
- Use current document/layer IDs, revisions, and explicit zero-based frame indices.
  Reinspect after structural changes. Keep one writer. Preserve user edits, locks,
  unrelated layers, and originals; work on a new native copy for existing assets.
- Respect manual pauses. Never bypass guards or blindly replay mutations after a
  timeout/disconnect. Reconnect and inspect uncertain outcomes; replan on conflicts.
  A deferred operation is not queued. Ordinary waiting is not permission to resume
  a user-paused editor.
- Keep checkpoints and exports inside the configured asset root with unique names.
  Never overwrite originals or roll back across intervening manual work.

## 1. Establish the action and review capability

Inspect the appearance reference and existing sprite, if supplied. Write a compact
working brief before drawing:

- Action, facing, canvas size, style, and desired character/weight.
- Looping cycle or one-shot action; approximate duration and key event/contact.
- Main body part driving the movement, secondary motion, and recovery.
- Constraints: planted contacts, grip location, prop length, proportions, and
  reserved canvas space for extreme poses and effects.

Separate appearance references from motion references. Use a supplied motion
reference when available; otherwise choose a clear interpretation without
requiring the user to find one.

Identify what you can actually evaluate:

- **Image review:** rendered poses, contact sheets, onion skins, and frame diffs.
- **Timing inspection:** frame durations and playback-order diagnostics.
- **Temporal review:** actual playback supplied to a model with suitable video or
  animated-input support. Exporting a GIF alone does not provide this capability;
  opening a GIF as an image may expose only a single frame.

Record the available review mode. Never claim to have watched playback unless you
actually received and evaluated its motion. Still-image/timing review is useful
but cannot fully establish the feel of an animation; disclose that at handoff.

## 2. Block the action, not the decoration

Create roughly 4–6 readable key poses, adjusting the number to the action. Use
silhouettes or simple bones/joints and a prop before detailed shading or effects.
For an attack: rest, anticipation, maximum wind-up, contact, follow-through,
recovery. For a cycle: establish contacts, passing/extreme poses, and continuity.

- Make the important silhouettes meaningfully different. The body must act, not
  just a hand or prop translating while the torso stays unchanged.
- Plan shoulder/hip rotation, limb articulation, and weight shift appropriate to
  the character. Track a few explicit landmarks such as feet, shoulder, elbow,
  grip, prop tip, and hem; these are visual constraints, not automatic tracking.
- Maintain intentional hand/prop contact and prop length. Avoid whole-sprite bobbing
  or rigid part translation as a substitute for articulated motion.
- Reserve space at every extreme. Do not shrink a requested character or crop a
  spell to conceal a poor motion plan.

Render the extremes and review their silhouettes. This is an internal checkpoint,
not a request for human approval.

## 3. Build a rough timed animation

Add only the breakdowns/in-betweens needed to explain the movement. Choose timing
from the action, not an arbitrary frame-count target or uniformly spaced tween.

- Use anticipation and a readable wind-up; let a forceful strike accelerate into
  contact and stop there. Do not spread the same displacement evenly over time.
- Let the torso/limbs contribute to impact, then settle. Offset appropriate cloth,
  hair, or equipment follow-through rather than moving everything in lockstep.
- Preserve volume and controlled pixel clusters. Check both native size and a
  nearest-neighbor enlarged preview; avoid antialiased interpolation.
- Design a believable recovery. For cycles, review the last-to-first transition
  in actual playback order; identical endpoints are neither necessary nor proof
  of a good loop. Do not force a one-shot action to loop.
- Review the action without spell effects first. Effects reinforce contact; they
  cannot rescue unclear poses, weight, or timing.

Save a native rough checkpoint and generate review evidence before polishing.

## 4. Evaluate and revise autonomously

Use **at most three correction passes total per requested action**, not three per
stage or reviewer. An initial build and final inspection do not consume a pass;
any subsequent creative correction does. Reserve a pass for polish regressions
when possible. Stop early when the applicable checks pass; do not invent changes
just to exhaust the budget.

For each review, inspect a contact sheet with an explicit frame-index/duration
mapping. Inspect onion skins or differences around questionable transitions, and
playback if supported. Use `libresprite_analyze_animation` for timing/order facts,
not an artistic verdict: occupancy centroids are not joints or centers of mass,
large differences can be intentional, and zero loop-boundary change is not proof
of seamless motion.

Check these against the brief:

| Check | Look for |
| --- | --- |
| Readability | Distinct anticipation, extreme, contact, and recovery silhouettes |
| Weight/body mechanics | Body participation, balance, compression, believable force |
| Timing/spacing | Deliberate holds, acceleration, impact stop, and settling |
| Contacts/arcs | Sliding planted feet, detached grip, implausible elbow/prop paths |
| Consistency | Unintended volume, anatomy, prop-length, or pixel-cluster changes |
| Secondary motion | Appropriate lag and follow-through without distracting noise |
| Recovery/loop | Intentional return or continuous cycle without an accidental hitch |
| Presentation | No unintended clipping; effects do not hide the main action |

Record a short review ledger in working notes or an agent-owned sidecar:

> Pass | checkpoint | evidence/review mode | affected frames | visible defect |
> proposed fix | observed before/after result | remaining uncertainty

Do not write generic praise or fabricated quality scores. A useful finding is:
"Frames 5–7: staff drops but shoulders stay level; lower shoulders and compress
the torso at contact, then delay the cloak's settling."

For each correction pass:

1. Choose the one or two highest-impact supported defects: action/contacts first,
   then weight/timing, then consistency and decoration.
2. Preserve the current best native checkpoint. Make targeted pose or timing edits
   using explicit native operations; dry-run multi-frame corrections when useful.
3. Render the changed frames and adjacent transitions again. Compare old and new
   candidates using the same scale, sequence, and preview conditions; preserve and
   report deliberate timing changes.
4. Keep the revision only when evidence supports improvement without a worse
   regression. Otherwise retain/restore the best checkpoint safely. Do not blindly
   Undo across manual edits; inspect before any rollback or document switch.
5. Update the ledger. If progress stalls or the budget is exhausted, keep the best
   candidate and report unresolved issues at final handoff. Do not restart the
   budget, add endless frames, or summon more reviewers to manufacture approval.

### Optional independent reviewer

Use a reviewer subagent only when a suitable tool/model is actually available;
a skill cannot create subagent capability. Prefer one review at the rough stage
and another at final inspection, rather than a reviewer for every edit.

Give the reviewer the brief, reference, frame-indexed images, durations, and actual
playback when supported. Require a short ranked defect report with frame ranges,
visible evidence, proposed fixes, and limitations. Let it inspect before seeing
the creator's self-assessment to reduce agreement bias.

The reviewer is **read-only**: no editor writes, navigation, resume, save, or Undo.
The main agent remains the sole writer and judges recommendations against visible
evidence. A reviewer without temporal input must not claim temporal verification.
Without subagents, perform the same checklist as a separate self-review pass; do
not impersonate an independent reviewer or interrupt the human for approval.

## 5. Polish the best motion, then inspect again

Polish only after the rough motion passes the available checks. If the correction
budget is exhausted with unresolved motion defects, keep polish minimal and do not
label the motion approved. Preserve pose silhouettes while adding the requested
palette, shading, character details, and restrained effects on separate layers
where useful. Retain editable cels and intentional transparency.

Recheck the complete sequence for jitter, contacts, silhouette changes, clipping,
impact alignment, and secondary motion introduced by cleanup. Spend any remaining
correction pass on an actual regression; otherwise deliver the best checkpoint
with the limitation noted. Technical export success is not artistic approval.

## 6. Final-only human handoff

Save the editable `.ase`/`.aseprite` and export an animated preview plus a native-
resolution transparent sprite sheet (and standalone sprite if requested). Preserve
requested one-shot/loop semantics; label a repeating review preview separately.
Persist returned sheet/timing metadata as a sidecar when possible; sheet export
writes a PNG, not an automatic JSON file. Include event timing for attacks/casts.

Verify exported dimensions, frame order/count, transparency, durations, and relevant
loop settings. Check GIF's color/alpha and 10 ms timing limitations; use APNG when
exact RGBA/timing matters. Native saves and exports can require different current
revisions; use actual tool results rather than assuming counters remain unchanged.

Present the playable preview or its path, editable source, sheet/metadata paths,
a short description of the action, and any remaining concerns. State the review
mode honestly (for example, "pose/timing review; playback not assessed by a
video-capable model"). Summarize meaningful corrections briefly, not the entire
internal ledger. This is the normal point for the human to review and request
changes; do not claim engine integration or human approval that did not occur.
