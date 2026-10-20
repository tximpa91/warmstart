# Mobile acceptance and evidence

Every development task records its mobile impact before implementation and reports the
result after review. This policy applies to the local console, public demonstration and
authenticated pilot. It defines acceptance requirements; it does not establish that the
current interface passes them.

## Required behavior

- Build from the smallest layout upward. At 320 CSS px the page has no horizontal overflow;
  long source IDs, answers and errors wrap without hiding content or controls.
- Make primary touch targets at least 44 by 44 CSS px, with usable spacing and visible labels.
- Reflow in portrait and landscape. Respect safe-area insets; browser chrome and the software
  keyboard must not cover the focused field, submit control or essential status.
- Provide visible keyboard focus, logical focus order, and operable controls. Check 200% text
  enlargement without clipping, lost actions or unreadable source references.
- Keep loading, cache state, policy edition, sources, errors and recovery actions readable.
  An error must not erase the question or selected profile; retry remains an explicit action.
- Preserve selected profile, question, displayed answer and in-flight request state through
  resize, rotation and fold/unfold. A layout transition must not submit a second request,
  change its authorized context, or attach the response to a different profile/question.

For backend-only changes, explain mobile API compatibility, error presentation, payload and
latency/retry implications. An explicit `N/A` is acceptable only with a task-specific reason;
for example, an instruction-only change has no runtime API or presentation impact.

## Matrix and claim boundaries

| Check | Coverage | Evidence requirement |
|---|---|---|
| Generic phone layouts | 320, 390 and 430 CSS px widths; portrait and landscape | Record both CSS width and height, browser/version and orientation |
| Generic wide layouts | 768 and 1024 CSS px widths; 1280 CSS px desktop | Verify reflow and state-preserving transitions from/to phone widths |
| Browser interaction | Touch, software keyboard, focus, text enlargement, loading/error/source states | Record actual checks and screenshots or reproducible steps |
| iPhone Duo Safari | Folded outer display and unfolded inner display; portrait and landscape | Identify OS/browser and actual Simulator model/runtime or hardware |
| Duo transitions | Fold/unfold and rotation while idle, editing, loading, displaying an answer and recovering from error | Preserve state and verify no duplicate request or context switch |

The generic widths are **layout probes, not Apple's official Duo CSS viewports**. Apple
documents separate outer and inner displays in its [iPhone Duo technical specifications](https://www.apple.com/iphone-duo/specs/).
Hardware-pixel resolutions do not establish Safari's CSS viewport dimensions. Measure and
record the viewport in the tested browser rather than deriving it from those resolutions.

Desktop WebKit or a resized browser establishes responsive behavior only. Simulator checks
must name the available model/runtime and any unsupported posture transitions. Do not call
a generic tablet preset a Duo Simulator. If the relevant Simulator or hardware is unavailable,
record the device gate as unverified. Claim device compatibility only with the corresponding
evidence; complete hardware coverage is required before claiming Duo support in the pilot.

## Development, review and release gates

1. Principal: record mobile impact, applicable scenarios and acceptance criteria in the task.
2. Developer: implement the applicable behavior and provide actual verification evidence.
3. Reviewer: check design and evidence; reject unsupported device or automation claims.
4. Technical QA: independently verify applicable scenarios and record limitations.
5. A failed mobile criterion follows the existing repair loop. Missing required evidence is
   `INCONCLUSIVE` for that gate; the two-repair cap and owner escalation remain unchanged.

Before merging future UI changes, add and require deterministic WebKit responsive regression
for the generic matrix and state preservation. Keep paid inference out of browser CI; use
synthetic deterministic responses. Real Safari keyboard/safe-area and Duo hardware checks
remain separate pilot gates. **These browser tests and CI gates are not implemented by this
documentation change, and no mobile/device result is asserted here.**

## Evidence template

Use the workflow's existing evidence format. Include the following in task criteria and
findings/artifacts without inventing new recorder fields or claiming automatic enforcement:

```text
Mobile impact: UI | backend/API | justified N/A, with reason
Revision/source digest:
Browser and version; OS and version:
Environment: desktop emulation | named Simulator/runtime | physical device
CSS viewport width x height; orientation; folded/unfolded posture if applicable:
Scenarios and commands/steps actually run:
Touch/overflow/safe-area/keyboard/enlargement/source/error results:
Profile/question/answer/in-flight preservation and duplicate-request result:
Evidence artifact paths:
Verdict, limitations and unverified coverage:
```

Never store credentials, tester identities, real questions or raw sensitive logs in screenshots
or public artifacts. A passing generic viewport check cannot fill an unverified device row.
