# UX Principles for Interactable Software
### The Control & Input Layer — and How to Prove It Actually Works

*A practitioner's reference for building software a human can actually operate, and for forcing the
verification that it does. Sibling to `ux-principles-web-apps-v3.md` (the display layer); this document
governs the earlier layer — **make it work for a human before you make it ideal to read**. Sources are
attributed inline; the canon is listed at the end.*

## How to use this (operating procedure)

- **Step 0 — scope & paradigm gate.** Does a human (or another *program*) operate this at *runtime*? If it
  only runs by editing source, or is imported as a library, it has no control/input layer and this playbook
  does not apply. If it does, name the **paradigm** — it selects which sections bind: *discrete GUI flow*
  (forms, wizards, agent flows) → §3–§11; *real-time / continuous loop* (games, media) → §4 control-loop +
  §7 state machine; *ambient / monitor* (dashboards, widgets) → §5 liveness + §7; *streaming*
  (audio/video/sensor) → §5 liveness + §7; *single hardware/OS control* (a toggle) → §5 truthful +
  indeterminate state and §4 feedback-on-success-*and*-failure; *machine-operated CLI/API* (agent-consumed)
  → §10 structured-contract + §5 distinct-verdict, reading "the user" as "the calling code." A one-control
  app needs only its few binding sections.
- **Before building** a control/input flow, read §1 (the bar) plus the 2–3 sections your flow touches
  (execution §3, evaluation §4, status §5, handoffs §6, states §7, dialogs §10). Agent flows add §12–§13.
- **While building**, treat each section's **Test** as a live design check — it names the next defect to fix.
- **Before claiming done**, run the **Shippability Gate (§15)** and produce the human-path evidence ledger.
  No ledger → not done. Agent flows also clear §13's four-part action test.
- **The one inversion to internalize:** the failure this document exists to prevent is declaring a flow
  "working" off a green backend or a clicked *confirm*. **A 200 and an approval are not verification.**

---

## 1. The Central Problem: Built ≠ Works

The display playbook's central problem is *data ≠ information*. This one's is sharper and earlier: **a
thing that was built is not a thing that works.** A backend that returns the right value, a passing unit
test, a smooth demo, a feature that compiles — none is evidence that a human can pick up the product and
succeed. The discipline below closes the gap between "the system did something" and "the user accomplished
their goal."

Boehm's distinction is the spine: **verification** is "build the product right," **validation** is "build
the right product." The V&V standards make the failure concrete: a black-box test "can produce the correct
output despite internal errors" (NIST SP 500-165); 1.5–4 defects per 1,000 lines survive even after system
testing (ESA PSS-05-10). A green suite is not proof — the cheap defects are the ones tests catch; the
expensive ones leak past them to the user.

The usability tradition hits the same wall from the human side. Rubin & Chisnell: **"You can only measure
how unusable [something] is"** — the instrument counts *failures*, never goodness, so a single positive
"it worked" reading is not evidence; "test results do not prove that a product works." Norman's corollary:
**"It is easy to design devices that work well when everything goes as planned. The hard and necessary
part of design is to make things work well even when things do not go as planned."**

And the test runs whether you run it or not. Nielsen: **"your system will be tested for usability even if
you don't do so yourself. Your customers will do it for you."** Shipping unverified IS the test — Rubin &
Chisnell: "the true name for this type of testing has been 'product release.'" Field-discovered changes
cost ~100× the changes caught early (Nielsen).

**The canonical failure this playbook exists to prevent.** An agent-invocation flow was declared "working"
after minting an auth token and calling the API directly — without ever driving the human path (tray →
prompt → file picker → browser login → job). The flow was broken at nearly every visible step: a fabricated
"1 agent running" status with no job behind it, a dead-end browser hand-off, a file picker that appeared
*after* the prompt referencing files, a bare credentials dialog. The API call was confirmation via evidence
that *structurally could not reveal the failure* — the token bypassed the entire broken path. That is
verification-vs-validation confusion wearing the costume of an engineer's "it works."

**The cardinal rule.** *A flow is not done until a human-equivalent run produces the human-visible
outcome.* For a GUI that means driving the real entry point — the clicks, dialogs, browser, waits — and
capturing observable evidence at every step the user sees. Disqualifying as evidence: token-minting, direct
API calls, "it compiles," "the tests passed," any demo that skips the off-happy-path states.

**Test:** Can you produce a step-by-step *human-path evidence ledger* — screenshots or observed outcomes at
every user-visible step of a cold run by someone who is not you — ending in the intended real-world result?
If not, the flow is not done, whatever the backend returns. (Formalized in §15.)

---

## 2. You Are Not the User

The most reliable builder error is assuming the user is like you — the false-consensus effect (NN/g):
"people's tendency to assume that others share their beliefs and will behave similarly." The correction is
not more thinking; it is observation: test with real users, not colleagues, and watch them.

Your own ability to operate the product is zero-bit evidence. Krug: **"The only way to find out if it
really works is to watch other people try to use it."** Nielsen: "Users have infinite potential for making
unexpected misinterpretations" — and inspection can't substitute: unless you test real units on typical
tasks, *looking* straightforward is not evidence of *being* usable.

**The absence of complaints is not evidence of usability.** When an interface is hard, users blame
*themselves* — Norman: **"Because everyone perceives the fault to be his or her own, nobody wants to admit
to having trouble. This creates a conspiracy of silence."** Low bug-report counts are consistent with a
widespread defect — go observe; don't wait for tickets. Krug's corollary: the value proposition is the one
thing nobody inside the organization will notice is missing, because every insider already knows it.

**The remedies are observational, and cheap** (§14). Minimum viable: watch one real, audience-matched
person attempt the real task without your help — and **don't demonstrate what you want to find out**
(Norman/HIG): showing the user how, then watching them copy you, is a rigged test that forbids nothing.
Recruit loosely (Krug: "we're all beginners under the skin" — most serious problems are
demographic-agnostic), so "I couldn't get a representative user" is not an excuse to skip it.

**Test:** Name the last time you watched a person who did not build it, and was not coached, complete this
flow cold. If "never," your confidence is a fact about your model, not about the product.

---

## 3. Close the Gulf of Execution: The Next Action Is Discoverable; Flow Order Matches the Mental Model

Norman's action cycle has two gulfs. The **Gulf of Execution**: figuring out how to use it. The **Gulf of
Evaluation** (§4): figuring out what state it's in and whether you got there. "We bridge the Gulf of
Execution through the use of signifiers, constraints, mappings, and a conceptual model. We bridge the Gulf
of Evaluation through the use of feedback and a conceptual model."

**Possible is not discoverable.** Norman: **"Affordances define what actions are possible. Signifiers
specify how people discover those possibilities… Signifiers are of far more importance to designers than
are affordances."** A technically-available action with no perceptible signal *functionally does not
exist*. The smoking gun for a discoverability defect is a sign taped on to explain it ("whenever you see
hand-lettered signs pasted on doors, switches, or products… you are also looking at poor design"). A
tooltip or error-toast whose only job is to explain a confusing control is that taped sign — the defect,
not the fix.

**Flow order is a first-order property, not a layout detail.** Wroblewski's canonical case: a checkout that
lost ~75% of users, fixed for **+$300M/year** — "the problem wasn't as much about the form's layout as it
was about where the form lived… It came before they could actually enter the information." The identical
field is hostile early and natural late (street address demanded before browsing vs. asked at shipping).
Demanding input before the user's step justifies it breaks the mental model — a file picker that fires
*after* a prompt referencing files is the same bug. Enforce order with Norman's **interlock** ("forces
operations to take place in proper sequence") and its UI realization the **wizard** (enforce the sequence;
show the step list with the current step highlighted). When a task needs prerequisites the user may not
have on hand, use a **start page**: front-load *what to gather and how long it takes*.

**Defer everything the core task does not need.** Strictly better than front-loading: eBay saw higher
completion *and* ~40% more optional answers by asking optional questions *after* the core task completed.
Premature personal questions also corrupt the data — users maintain "a convenient false set of personal
answers" for questions they consider impertinent right now.

**Solve the right problem before ordering the steps of the wrong one.** Norman: "the problem I am asked to
solve is not the real, fundamental, root problem. It is usually a symptom" — pair with the Double Diamond
(diverge/converge twice: first to define the right problem, then to develop the right solution). A
brilliantly-ordered flow for the wrong task is still the wrong product.

**Controls must be discoverable without memorization or documentation.** Keyboard, gesture, and
direct-manipulation controls carry no inherent signifier — a 3D canvas doesn't announce "drag to rotate,"
and a hotkey announces nothing at all. The test is recognition-over-recall (Nielsen #6): a first-run user
must *find* every control on screen, not recall it. Remedies are cheap and standard: an always-available
help/legend overlay (`?` key, collapsible cheatsheet, first-run hint), tooltips, visible affordances for
spatial controls (grab cursor; "drag to rotate" shown once). The anti-pattern is documenting controls in
the README or source — the taped sign hidden in the one place no user looks. Dense expert controls are
fine *if* something on screen taught them the first time. (Don't over-correct: an *absent* control is not
automatically a defect — read §8 before adding one.)

**Test:** Walk the flow as a first-time user asking Norman's seven questions at every step — especially
"What can I do now?" and "How do I do it?" If any action is not *perceptible* (not merely present), if the
system demands an input the user has no reason to have ready, or if any control is discoverable only via
docs or source, that step has a Gulf-of-Execution defect. (Acid version: hand the running app to someone
who has never seen it or its README, and watch what they can and cannot find.)

---

## 4. Close the Gulf of Evaluation: Every Action Yields a Perceivable, Interpretable Result

After every action the user must be able to perceive *that* something happened and interpret *what* it
means. Norman: the gulf is small "when the device provides information about its state in a form that is
easy to get, is easy to interpret, and matches the way the person thinks about the system."

**A working-but-imperceptible system fails exactly like a broken one.** Norman's silent electric car "can
kill"; the software analogue is exact: a browser hand-off that opens login and then leaves *nothing
perceivable* on the app side strands the user unable to evaluate what happened or what to do next. Status
that is technically *retrievable* (in a log, behind a click) but not *perceivable* at the point of action
is, to the user, absent.

**Mode and state must be continuously visible, not remembered.** Norman: "Mode errors are especially likely
where the equipment does not make the mode visible, so the user is expected to remember what mode has been
established, sometimes hours earlier." The Royal Majesty grounding — a critical dead-reckoning mode shown
only as tiny "dr" letters — was *technically displayed* and still missed, because a long flawless history
had trained the crew to stop checking (a trust failure; §12). Perceivable means salient-when-it-matters,
not present-in-principle.

**Continuous control loops: feedback is the whole world moving; the HUD must be glanceable.** Real-time
loops (a game polling input at 240 fps, time-based media) have no discrete actions: feedback is *control
feel* and status is an always-on HUD. Three requirements the discrete model omits: input-to-render latency
under one frame with frame-rate-independent (dt-scaled) physics, so the control feels attached to the hand;
a *persistent, glanceable* status surface (health/ammo/cooldown — visible at the point of action, not on a
pause screen); and *content-temporal* status (elapsed recording time, clip duration, playhead) as its own
always-visible category, distinct from a system-latency spinner.

**When one surface serves multiple modes, the mode signifier lives on that surface.** A recorder whose
"recording" and "stopped-with-audio" screens are near-identical (same waveform), distinguished only by a
label and an 8 px dot absent half the blink cycle, is a mode-error trap. Put a *continuously salient*
badge, border, or color on or adjacent to the surface — not a flash, not a corner dot.

**A direct-manipulation gesture must land where the input occurred.** §3 covers whether a control is
findable; this covers whether its *effect lands*. The canonical canvas bug: click coordinates captured in
displayed-pixel space but applied in natural-pixel space, placing the marker up-and-left of the click.
Input-coordinate space ≠ render-coordinate space across display scaling, zoom, rotation, and
HiDPI/`devicePixelRatio` — store and convert in one canonical space, and verify the effect lands at the
input locus under each transform.

**Test:** Trigger each state on the real path and confirm a user can *perceive and name* what just happened
without consulting a log, a console, or you. Continuous apps: confirm the HUD is glanceable *during* play,
not only on pause. Direct manipulation: confirm the effect lands at the click locus under
zoom/scaling/HiDPI.

---

## 5. Status Must Be True

A fabricated "1 agent running" indicator — shown with no job and no workspace behind it — is the cardinal
sin of this layer, worse than a missing status. Nielsen #1 (Visibility of System Status): **"The design
should always keep users informed about what is going on, through appropriate feedback within a reasonable
amount of time."** Understanding state creates control and trust; "a lack of information often equates to a
lack of control."

**Derive status from the work, not from intent.** The defect: an indicator wired to *intent* ("I spawned a
worker") rather than *truth* ("a job exists server-side"). Rule: derive every status from the authoritative
state of the work itself; if you cannot confirm the work exists, say "starting…" or "couldn't start," never
"running." A status asserting work that isn't happening destroys the user's trust model and violates the
no-fake-data rule that should already govern the codebase.

**A false conceptual model is worse than none.** Misleading information beats absent information at
*producing* errors (Nielsen). Norman's two-knob refrigerator fails not because information is missing but
because the visible controls imply a mechanism the system lacks. A lying "running" badge is the software
version — it builds a confident, wrong model on which the user then acts.

**Liveness is its own status axis: "am I receiving *now*, and is this *current*?"** A muted or unplugged
microphone still showing a blinking "recording" (because `isRecording` was set from the *intent* to start,
not from samples actually arriving) is the lying-status sin in real time; a dead collector leaves a
dashboard frozen on last-good values that *look* live. Derive the live indicator from the live input itself
(a level meter/waveform from real samples; a data-age chip), distinguish *armed-but-silent* from
*not-capturing*, and when the source dies, degrade visibly (stale / age / blank) rather than freezing on
the last frame.

**An unknown is not an "off": a read/verify failure maps to a distinct *indeterminate* verdict — on the
structured channel, not just the prose.** Two converse lies hide where the positive-lie test doesn't look.
(1) Failure collapsing into the safe-looking pole: a webcam toggle that can't read its status node and
renders a confident "Disabled" is lying as much as a fake "running." (2) Honest prose with a success-coded
verdict: a command that prints "could not verify" yet returns exit 0 / `success=true` lies on the channel a
machine — or a glancing human — actually reads. "I couldn't confirm" is neither "it worked" nor "it's off";
the *exit code / status field / icon*, not only the message, must carry the distinct state.

**Wire to the right resource *instance*, not just the right *type*.** Reading the correct *kind* of
authoritative source doesn't help if you address the wrong one. A hardcoded path/handle/ID (a fixed port, a
pinned PID, `usb…/1-8`) silently points at nothing — or the wrong target — after a re-plug, a kernel
re-enumeration, a different host, or a second device. Resolve the instance dynamically; if it can't be
found, show an explicit "target not found" state.

**Test (the falsifiability check):** *Can you make the indicator lie?* Force the underlying work to fail or
never start, and confirm the status reflects that — not a hopeful default. Independently corroborate a
positive status against the backing system (the job/workspace actually exists). Then three more forces:
(1) *mid-stream* — mute or kill the source while it claims to capture, and confirm the indicator admits it
instead of freezing; (2) *the converse* — induce a read/verify failure and confirm a distinct *unknown*
(not a confident safe pole) on the structured channel as well as in prose; (3) *the instance* — re-plug or
move the resource and confirm the indicator follows it or says "not found."

---

## 6. Handoffs Preserve Continuity

A hand-off is a Gulf-of-Evaluation gap stretched across a context switch — a browser round-trip, an OAuth
redirect, a shell-out, an async job — and it is where flows most often strand the user.

**Never roll your own credential surface; hand off to the platform's.** A bare URL/email/password dialog is
not just ugly, it is *unsafe by construction* — RFC 8252: "Embedded user-agents are unsafe… the app that
hosts the embedded user-agent can access the user's full authentication credential… can record every
keystroke entered in the login form." Use the external browser with a loopback-IP redirect. General
principle: for any capability the platform provides a trusted surface for (auth, file selection,
permissions), invoke that surface — don't reimplement it inside your own dialog.

**The user must be able to perceive the return.** When control comes back, the originating surface must
visibly reflect the new state (§4), or the user is left asking "did that work? what now?" For long-running
agents the danger is sharper — the *paradox of automation*: automation "tends to give up" exactly when the
task gets hard, "failing without warning" and dumping an out-of-the-loop human back in with no situational
awareness. Over-communicate at the seams: hand-off acknowledged → work in progress (truthfully; §5) →
needs-input → done.

**The link itself is a status surface, not a per-command afterthought.** For remote-control, teleoperation,
and networked-device software, the connection is a stateful, continuously-visible entity. Model it
explicitly — **never-connected / connecting / up / degraded / lost / reconnecting** — make each state
perceivable *and* a designed recoverable surface (§7), and wire the indicator to the transport *actually
opening* and data *actually arriving*, never to the intent of constructing a socket. Recurrent failures: a
remote shell that handles "link absent" in 2 of 12 commands (the rest throw raw transport tracebacks — a
§10 violation); a "connected" dot lit when the `EventSource` is *constructed* rather than on `onopen` /
first message. "Link down" is a state every command shares, not one each rediscovers.

**Test:** Drive the hand-off on the real path — click through the browser, complete the external step,
return — and confirm the app visibly acknowledges each transition (left, working, returned, result). For a
persistent link, drop it mid-session (pull the cable, kill the far end) and confirm lost→reconnecting shows
and *every* command degrades to a designed "link down," not a traceback.

---

## 7. Every State Is Designed — Especially the Ones That Aren't the Happy Path

Norman's error taxonomy forces you to design for *both* kinds of error. A **slip**: right intention, wrong
execution. A **mistake**: the plan itself is wrong. They demand different defenses: slips want undo,
soft-delete/grace windows, sensible defaults, visible mode (§4); mistakes want a good conceptual model and
feedback that surfaces a wrong plan early. The thesis is his chapter title — **"Human Error? No, Bad
Design"** — and its operational form: "Assume that every possible mishap will happen… Make actions
reversible; make errors less costly."

**Undo is the default for destructive actions; confirmation is the rare exception.** A confirmation taxes
*every* correct invocation to maybe catch a *rare* slip, and habituation defeats it: "our hands have
memorized close-and-click as a single continuous gesture" (Raskin, *Never Use a Warning When You Mean
Undo*), and fMRI shows "a dramatic drop in the visual processing centers of the brain after only the second
exposure to a warning" (Anderson et al., CHI 2015). NN/g: "if you cry wolf too many times, people will stop
paying attention." Undo inverts the asymmetry — it taxes *only* the error, on the recovery path.
Tognazzini: "The unavoidable result of not supporting undo is that you must then support a bunch of dialogs
that say the equivalent of, 'Are you really, really sure?'" — confirmation is the *failure mode of missing
undo*, not its peer. (The confirmation-first lean of the 1980s–90s canon reflects a vanished constraint:
multi-level undo was genuinely expensive then. With cheap storage, soft-delete tombstones, version history,
and event sourcing, the cost-benefit has inverted — the hedge is a memory-era artifact.)

*Rule.* Make the destructive action recoverable, then perform it immediately — no prompt. Reach for, in
order: (1) **acknowledgement-with-undo** — do it, show a non-blocking snackbar with an UNDO affordance;
(2) **soft-delete / trash with a retention window** — delete is a state transition (active→trashed→purged),
so undo is a flag flip; (3) **action-delay / grace window** for ops that look terminal — Gmail's Undo Send
doesn't recall, it *defers* 5–30 s, converting a one-shot send/publish into a reversible one with zero
happy-path clicks; (4) **version history / event log** as the durable undo of record. Do *not* confirm
trivial reversible actions — over-confirmation trains the click-through reflex that disarms the genuine
warning, and can *net-increase* errors as users start rushing (NN/g). Confirmation's residual role is the
*irreversible-and-consequential tail only* — gated on reversibility, not destructiveness (GOV.UK: "Only use
warning buttons for actions with serious destructive consequences that cannot be easily undone by a user…
Most services should not need one"). In that tail, prefer in order: make the bad state unreachable (§8);
add a delay+undo window to drag it back out of the tail; sequence the irreversible step *last, after all
validation*; and only then a *non-habituated* gate — type-to-confirm ("have people do something they would
normally not do," e.g. GitHub's type-the-exact-`owner/repo`) rather than a reflexive OK the brain has
stopped reading. Reconciled with §13's gate: reversibility first — a reversible action drops off the
confirm trigger entirely; only what genuinely *cannot* be made reversible escalates to mandatory approval.

**Test:** For every destructive action, name its recovery layer (undo / trash+retention / delay window /
version history / compensating transaction). If one exists, ship it and drop the prompt. If none does,
you've found the only place a confirmation is earned — and even there, prefer making the state unreachable
or adding a delay window; if you still gate, type-to-confirm.

**Design the empty, loading, partial, and degraded states explicitly.** Intentionally-designed empty states
"communicate system status, increase learnability, and provide direct pathways for getting started" (NN/g).
Nielsen's thresholds set when a designed waiting state is mandatory: 0.1 s feels instant; 1 s keeps flow;
10 s is the limit of attention — anything over ~1 s needs a progress indicator, over ~10 s a *determinate*
(percent-done) one, and the progress shown must track real work ("changes in speed will be noticed" —
honest progress is §5 applied to time). A state left undesigned is a state the user meets raw.

**Defaults are the highest-leverage input you ship.** Most users never change a default, so the default
*is* the decision for the median user — organ-donor participation flips ~15%→~90% on the default alone
(Johnson & Goldstein 2003). Set it to the safe, reversible, right-for-most option, and never use a *fake*
placeholder default that submits wrong data (Wroblewski's Jan-1-1975 birthday) — require an explicit choice
when there is no true majority answer. A default chosen to benefit you at the user's expense is a dark
pattern, not a convenience.

**The state list is a starting point — every domain has its own non-negotiable state machine.** The
empty/loading/partial/error/degraded/offline set is web-app-shaped; name *your* domain's states or you will
ship only the happy one. A real-time game has menu / playing / paused / death-respawn / win / transition; a
networked or teleoperation tool has §6's connection lifecycle; a recorder has idle / armed / recording /
paused / saving / error. Enumerate the machine and design every node.

**Undo's *correctness* is the test, not its existence.** A present-but-*wrong* undo is a lying affordance
(§5), worse than none: a history entry that captures `{image, annotations}` but omits rotation/flip, or a
stale closure that stores `{image: null}` so undoing to the first step *destroys the image*. Treat undo as
a state-restoration **contract**: every user-mutable field captured, each undo an exact inverse of its
operation, undo never loses data. Verify by mutating every field, undoing, and diffing back to the prior
state.

**Test:** Force each off-happy-path state on the real path — empty, slow, partial, failed, offline,
mid-mode, and every node of your domain's state machine — and confirm each is a designed, recoverable
surface, not a blank screen, a spinner that never resolves, or a stack trace. A flow verified only on the
happy path is not verified.

---

## 8. A Missing Control Is Not a Defect — Design for Intent, and Make "Always-On" Resilient

*The trigger this section prevents: an agent saw an always-on chat reader with no Start/Stop button, judged
the absence a gap, and proposed adding the control — for a user who never wants the reading to stop. The
absence was correct; the addition is the defect.*

**The reflex to add a control is a bias, not a fix — the bar for a new control is an observed need, never a
pattern.** People "systematically default to searching for additive transformations, and consequently
overlook subtractive transformations" (Adams et al., Nature 2021); the UI form is the gut reaction to slap
a screen/control on every problem (Golden Krishna). Absence is the default-correct state until a *real*
need overrides it (Saint-Exupéry: perfection is "when there is nothing more to take away"; Rams: "as little
design as possible"). The need must be observed, not hypothesized: a symmetry ("there's a start, so there
should be a stop"), a familiar pattern from other apps, or "someone might want to" is not evidence. For
that last and most seductive case apply the Mom Test (Fitzpatrick: "anything involving the future is an
over-optimistic lie") — demand a concrete *past* instance where this user actually did the thing.

**Design to the user's intent, not the mechanism's state machine.** A Start/Stop button is usually the
provider's internal run/stop state leaking into the UI — Cooper: "user interfaces should avoid
implementation models in favor of user mental models"; "a goal is an end condition, whereas a task is an
intermediate process… the goal is a steady thing, the tasks are transient." The user's model is steady ("my
chat is read aloud"); the engine's on/off is transient plumbing. Weiser's test: the best tool "disappears"
— a control that drags attention back onto the mechanism fails it. Cooper's allocation rule sets
prominence: "design for the probable, provide for the possible" — a near-never activity earns at most a
buried path, and often nothing.

**A control the user will never use is clutter at best and a footgun at worst.** Every control carries a
standing cost even unused: "every time you provide an option, you're asking the user to make a decision"
(Spolsky; the nine-way Vista shutdown menu); "using preferences as a band-aid is the root of much UI evil"
(Pennington); YAGNI cost-of-carry (Fowler). Now weigh the asymmetry: a Stop button on an always-on reader
has *no* upside (the user never wants to stop) and one irreversible downside (accidental silence
mid-stream). Norman's forcing-function vocabulary makes the inversion exact: the real requirement — reading
must never stop — is a *lock-in* (prevent premature termination); a Stop button is a *lock-out aimed at the
user's own goal*. When a control's only possible effect defeats the product's core promise, design the bad
state unreachable — don't add the button, and don't merely guard it with a confirmation.

**When the intent is continuous, the requirement is RESILIENCE, not an off-switch.** "I never want it to
stop" is a reliability requirement, and the threat is *silent death*, not a missing button. Watchdog
practice: "the most dangerous failures are not complete crashes, but situations where the software
continues running while no longer behaving correctly… the system may appear alive while silently failing to
perform its function." Vogels: "everything fails all the time" — the reader *will* stop (crash, audio
glitch, API hiccup); the answer is automated detection and recovery, not manual input where no human
judgment is needed. The idiom is a supervisor/watchdog that owns recovery (Erlang "let it crash" +
supervisor restart; systemd `Restart=always` + `WatchdogSec`), never the user. The positive spec to build
*instead of* the button: never silently stop; emit a heartbeat; auto-recover to a clean state; surface any
stop the system cannot fix *loudly* — not a silent off-state the user must happen to notice.

**But restraint is the *right amount* of change — not reflexively "less."** The same additive-bias
discipline can collude with sunk-cost and status-quo bias to keep patching a frame that should be scrapped —
a patch on a wrong design is as much a failure of restraint as a needless control. When the structure
itself is wrong, the restraint-correct move is the **overhaul (§9)**. Restraint sizes the intervention to
the diagnosis, in *both* directions.

**Test:** Before adding any control, name the concrete, observed scenario in which *this* user reaches for
it — a past instance, not a hypothesis or a symmetry. If you cannot, do not add it. Then: if mis-touched,
could this control defeat the product's core promise? If yes, make the bad state unreachable instead of
guarding it. And if the stated intent is "never stop," have you shipped a watchdog/auto-restart that makes
stopping self-correcting and any unrecoverable stop loud — rather than a manual switch that manufactures
the exact silence they fear?

---

## 9. Patch vs. Overhaul: Sizing the Intervention to the Diagnosis

A section-by-section defect audit can only ever return patches; it is structurally blind to the verdict
"scrap the frame." This gate supplies it. Restraint (§8) means the *right amount* of change — sometimes a
total rethink; a patch on a wrong frame and a rewrite of a sound one are both failures of restraint.

**A defect audit is greedy hill-climbing on one design — it reaches the peak of the current idea and stops,
even when a taller hill stands across the valley.** Buxton: the best design of an idea is that hill's peak;
"if the idea is not a good one, then the 'best' design solution will only be so-so." Refining the one
design in front of you is *getting the design right* — a different activity from *getting the right design*
(divergent generation), and only the latter changes hills.
**Rule:** When fixes hit diminishing returns while the experience is still bad, you are at a local maximum —
patching is structurally incapable of fixing it. Stop tweaking; reimagine.
**Test:** Are my last three fixes each true improvements, yet the whole still misses the user's goal? Then
I'm measuring the height of one hill, not choosing the hill.

**Diagnose defect *depth* before sizing the fix — surface defects get patches; a wrong conceptual model or
information architecture gets a new frame.** The bright line is Norman's: his two-dial refrigerator (dials
that *seem* to control freezer and fresh-food independently but actually set compressor and air-split)
shows that when the conceptual model is wrong, relabeling the dials cannot help. The IA analog is
measurable — NN/g: "When users go to the wrong section most of the time, your site obviously has an IA
problem," and renaming won't fix sections "inherently too similar for a single label."
**Rule:** If the user's repeated error comes from a mismatched mental model or an incoherent structure,
every surface remedy (a hint, a status color, a reconnect button) treats a symptom of the wrong frame.
**Test:** Does the user land in the wrong place / form the wrong expectation more than ~half the time? That
is the organizing scheme failing, not the pixels — no label/color patch will close it.

**Escalate from patch to overhaul only on named structural triggers — but escalate decisively when they
fire.** The default is conservative (NN/g: "Never make radical changes when minimal adjustments will
suffice… only resort to a complete redesign if the data tells you to do so"). The five triggers:
(1) **diminishing returns** — years of gradual fixes and not much more you can do; (2) **tech ceiling** —
the backend can't support critical user journeys; (3) **incoherent IA / patchwork** — after years of
patches the product "is incohesive and people can't accomplish what they need" (the stacking-patches case:
a grudging local fix preserving a broken design means you should have thrown the design out one patch ago);
(4) **debt so tangled** no incremental fix reaches acceptable; (5) **competitors do the job better.**
Guardrail against false triggers: "Don't let panic or boredom lead you astray."
**Rule:** Run this gate once over the **whole** artifact, not section-by-section — a section-local loop
passes each part's Test while the whole stays incoherent.
**Test:** Do two or more triggers fire (esp. diminishing-returns + architectural incoherence)? Then the
deliverable is "propose an overhaul," not the Nth small fix.

**Overhaul from the user's goals/jobs, generate alternatives in parallel, and reframe the problem — do not
iterate the screens you already have.** Redesign backward from goals/jobs (JTBD: people want the
quarter-inch hole, not the drill; Norman: "organize according to usage… not according to topic"), not
forward from the current menu. And generate *several* candidates, because a single artifact corrupts
judgment: presented one design, users rate higher and criticize less than presented three (Tohidi &
Buxton); parallel prototyping "significantly outperformed" serial and diverged more, because serial
iteration fixates — critique of your only option reads as rebuke (Dow et al. 2010). A defect-audit loop
*is* serial single-design refinement — the canonical fixation trap.
**Rule:** Produce ≥3 divergent whole-UI concepts (one anchored to each plausible framing of the job) before
committing; converge by elimination, never by polishing the incumbent.
**Test:** Is the existing UI a fixed substrate, or one candidate in the set? If it's the substrate, you've
silently pre-committed.

**Overhaul the *design*, not the working *implementation* — a from-scratch rewrite is the catastrophic
failure mode on the other side.** Spolsky: rewriting from scratch is "the single worst strategic mistake" —
"you are throwing away all that knowledge. All those collected bug fixes" (Netscape lost ~3 years). Brooks:
"the second is the most dangerous system a man ever designs" — freed from the first's restraint, the
architect over-engineers. Gall: "A complex system designed from scratch never works."
**Rule:** A UI overhaul re-derives the *interaction model* from goals while **preserving the validated
behaviors** already won — carry prior fixes in as known jobs the new design must still do; the new frame
inherits §8's additive-bias discipline, it does not escape it.
**Test:** Does the overhaul discard accumulated edge-case knowledge, or re-home it? Discarding it is the
rewrite trap wearing a redesign's clothes.

**Replace incrementally behind a stable surface — never a big-bang cut-over.** The strangler fig (Fowler):
grow the new system around the edges of the old, run both in parallel, migrate flows one at a time. Big-bang
concentrates all risk on one launch; "rewrites succeed when they are incremental, not heroic." But pure
incrementalism is *also* a failure mode when a breakthrough is the point — so: revolutionary in vision,
evolutionary in delivery.
**Rule:** Stage the overhaul flow-by-flow behind a facade; keep the old path live and shippable until each
new piece is proven; never couple the redesign to an immovable launch date.
**Test:** If a migrated section regresses, can I roll it back today without taking the product down? No
rollback path = big-bang, regardless of intent.

**Do NOT overhaul a UI the user has already internalized without validating the gain — the inverse
footgun.** A mastered design has become *invisible*, so an inspection cannot see the asset it is about to
destroy. Spool: "People hate change because they don't like to suddenly become stupid." Chesterton's fence:
an odd affordance or redundant indicator is usually a past bug fix. Case bank: Digg v4 (~50% traffic loss),
Sonos 2024 (clean-slate rewrite without feature parity or rollback: ~$500M market value and the CEO's job),
Snapchat 2018 (1.2M-signature revert petition, first DAU decline), Windows 8. Distinguish change-aversion
(recovers to baseline) from regression (plateaus lower): measure the recovery curve; don't label complaints
"change aversion" to dismiss them.
**Rule:** With an entrenched user base, an overhaul must (a) hold mental models / affordance placement
constant even during a heavy visual refresh, (b) ship opt-in / staged with a "switch back to classic"
escape, (c) gate cut-over on feature parity. With **no** incumbent users (a half-baked, user-less app — the
common agent case) this asymmetry inverts: there is no asset to protect, and restraint becomes the active
failure mode.
**Test:** Who has mastered this, and what does the overhaul make them re-learn? If I can't name the user
relying on an element, that's a STOP on deleting it, not a green light.

**Size the intervention to the diagnosis: do-nothing / patch / refactor / overhaul — and watch for the bias
that keeps a broken frame alive.** Sunk cost and status-quo bias collude with restraint to make "patch" the
default that never gets questioned. The forcing function strips the sunk cost out: evaluate the current
frame as if adopting it fresh today.
**Test:** "Would I build this UI this way starting from scratch today?" If no — and a structural trigger
has fired — the restraint-correct move is the overhaul, delivered incrementally.

---

## 10. Prompts, Dialogs, and Messages Are Real UI — Not Debug Output

A bare credentials prompt is a debug artifact shipped as a user surface. The rules for the words and the
boxes:

**Error messages: human, specific, blameless, constructive.** NN/g: plainspoken, no jargon; describe the
exact problem; offer remedies; never blame the user ("invalid, illegal, incorrect"). Nielsen #5: the best
designs prevent the problem in the first place; #9: "plain language (no error codes), precisely indicate
the problem, constructively suggest a solution." Wroblewski's discipline keeps a message system from
sprawling: there are only **two legitimate reasons** to show an error — the user entered something the
system can't accept, or something very bad happened to the system; a third type is "edging into
complexity," four+ "means start over." Marketing dressed as an error makes you "a bad person."

**Validate at the right time, in the right place.** Keep the message next to the field in error
(working-memory load), and don't error a field mid-type — wait until the user finishes and moves on. The
counter-rule prevents over-validation (Wroblewski: "I know my name") — don't validate fields the user
already knows are right.

**Dialogs are a UI surface with a contract.** Apple HIG: an alert says what went wrong, why, and what the
user can do about it, in the user's vocabulary. Buttons are named by their **verb** ("Save, Quit, Erase
Disk… more clear and precise than OK, Yes, and No"). **Cancel** means "dismiss the operation I started,
with no side effects" — if side effects are already committed, the button is **Stop**, not Cancel. Norman's
save-on-quit prompt is the dialog done right — the desired operation can be taken right from the message:
"what was once created as an error message has become an efficient shortcut."

**When the operator is *code*, the structured channel is the UI — and it must hold on every path.** A CLI,
API, or tool consumed by a program or agent has no human to read prose; "legible" means *machine-parseable*:
a typed error class, a stable exit code, a guaranteed JSON shape — a contract that must hold especially on
the failure paths. A tool whose docs promise `RuntimeError` but whose disconnected path leaks a raw
`SerialException` traceback on stderr with nothing parseable on stdout is shipping a debug dump as its
dialog. Pair with §5's distinct-verdict rule: the exit code / status field must also tell the truth, not
just the message.

**Test:** Read every message and button label in the flow aloud as a first-time user. Does each error say
what happened, why, and what to do, without blame or codes? Does each button name its action rather than
acknowledge the dialog? Can the user tell, from the words alone, what each choice will do?

---

## 11. First-Run Empathy and Activation

The first run is where self-blame is manufactured and where users decide whether the product is for them.
Norman's conspiracy of silence (§2) begins here: a few early failures generalize to "I can't use this at
all," and the user leaves without reporting. The defense is walk-up usability plus §3's gradual-engagement
and start-page patterns — never strand a newcomer in front of an empty, prerequisite-hungry form.

**Endowed progress is a real, measurable activation lever — distinct from honest progress.** Goal-gradient
research (Kivetz, Urminsky & Zheng): effort rises with proximity to the goal, and "the illusion of progress
toward the goal induces purchase acceleration" — a 12-stamp card with 2 pre-existing bonus stamps is
completed faster than a 10-stamp card from zero. Applied to a setup flow: start the progress bar non-empty
and show proximity-to-done. The boundary with §5/§7 is sharp and must be held: the progress *displayed*
must still be true — a step genuinely done, or a genuinely-granted head start, never a fabricated count.

**Test:** Have a fresh user reach first value (the product's "aha") cold, and measure where they stall or
quit. A from-zero checklist that strands the newcomer before any value is an activation defect no later
polish will fix.

---

## 12. Trust Calibration: The Theory Behind the "1 Agent Running" Lie

§5 and §6 are applications of Lee & See's theory of trust in automation — the right lens for an agentic
product whose user cannot watch the work directly. Trust is "the attitude that an agent will help achieve
an individual's goals in a situation characterized by uncertainty and vulnerability," and it "guides
reliance when the complexity of the automation makes a complete understanding impractical" — the user does
not verify; they rely. The design goal is **calibration**, not maximization: "Overtrust is poor calibration
in which trust exceeds system capabilities; with distrust, trust falls short."

**Make trust track capability, with resolution and specificity.** **Resolution**: "poor resolution occurs
when a large range of automation capability maps onto a small range of trust" — a UI that looks identical
whether the system performs well or badly has zero resolution. **Specificity** (functional and temporal):
trust should attach to a *particular component at a particular time*, not a global "trust this system";
stale capability indicators destabilize reliance. **The three bases**: expose not just **performance**
(what it did) but **process** (whether its method fits the situation) and **purpose** (whether it's used
within design intent) — single-basis trust is volatile and fragile. A checkmark backed only by "it passed
last time" is single-basis.

**Two traps run in opposite directions, and both are silent.** A distrusted system doesn't get used, so
trust does *not* self-correct upward after a fix — you must actively re-expose capability. Conversely,
highly trusted automation is monitored less, so trust keeps growing through occasional faults — the
complacency trap, likelier with highly reliable systems and observed in experts and novices alike. This is
the Royal Majesty mechanism (§4) in theoretical form, and why honest, high-resolution status (§5) is the
load-bearing trust instrument, not a nicety.

**Polish is a confound — do not let it stand in for capability.** Trust often rides on "surface features of
the interface that have no obvious link to the true capabilities of the system," and realism can make users
"blindly follow." A beautiful UI manufactures unearned trust; the verification discipline (§14) keeps you
honest about whether the trust is calibrated.

**Know which trust you are moving.** Hoff & Bashir: *dispositional* (general propensity), *situational*
(this task, this moment), and *learned* (this system's track record) trust move on different timescales — a
UI change that repairs situational trust does nothing for the learned distrust a past failure created. On
the agent's side, SAT transparency prescribes three levels: L1 the agent's actions/plan, L2 its reasoning
and constraints, L3 its projected outcomes *and their uncertainty*. Most agent UIs stop at L1 ("running…");
L2–L3 are what let the user calibrate.

**The two calibration failures are not symmetric, and both are real.** Over-trust is the headline risk;
**algorithm aversion** is its mirror: "people erroneously avoid algorithms after seeing them err"
(Dietvorst), and users are more observant and less forgiving of automation errors than human ones, so one
visible error costs disproportionately. The levers cut both ways: letting users adjust the algorithm
restores adoption, and the trust ramp (§13) lets learned trust recover rather than collapse.

**Explanations calibrate worse than you think.** Bansal et al.: explanations "increased the chance that
humans will accept the AI's recommendation, regardless of whether it was correct" — they boost *agreement*,
not team accuracy; an explanation that merely makes the agent more persuasive moves trust the wrong way.
Google PAIR: withhold a confidence number that won't change the user's decision, and accept that surfacing
genuine uncertainty "may temporarily reduce trust but yields long-term benefits." Measure complementary
performance (does human+agent beat either alone?), never acceptance rate.

**Test:** Degrade the agent's actual capability (inject a fault, a partial result, a stale state) and
confirm the interface *visibly loses confidence* in proportion — a different surface, not the same green
checkmark. If the UI looks identical whether the agent succeeded or failed, its trust resolution is zero
and it will train either complacency or abandonment.

---

## 13. Human–Agent Interaction: Delegation, Authority, and Reversibility

When the software *acts on the user's behalf*, the user is **delegating**, and the failures are about
authority, trust, and reversibility — territory studied rigorously decades before LLMs (the modern HAX/PAIR
corpus largely rediscovers it; grounding in the originals makes the principles sharper).

**Intermediate autonomy is the worst zone.** Bainbridge's *Ironies of Automation*: automating the easy part
deskills the human and dumps the residual hard cases on someone no longer prepared for them — a "confirm
everything" checkbox confers no real oversight if the user rubber-stamps. Norman (1990): a *mid-capable*
agent that acts but can't give continual feedback is more dangerous than either a dumb tool or a fully
capable one. Onnasch et al.'s **Lumberjack effect**: higher automation improves nominal performance but
degrades failure recovery *more*, mediated by lost situation awareness; Endsley & Kaber found
*intermediate* automation (agent generates/recommends, human selects) best protects failure-recovery. The
design default for any consequential task is a middle rung, not full autonomy.

**Gate action on confidence × irreversibility — not a single slider.** Maes & Kozierok (1993): two
per-action thresholds — a low *tell-me* (suggest) and a higher *do-it* (act without asking) — user-set and
action-specific ("higher do-it thresholds for actions which are harder to reverse"), with a mandatory log
of autonomous activity. The modern practitioner form is a four-tier action-risk ladder (T1 read-only → T4
irreversible: deploys, deletes, payments, external comms = "mandatory human approval, no exceptions"), and
it *rejects raw model confidence as the gate* ("90% claimed ≈ 75% actual"). Two further decompositions:
bound **pro-activeness** (self-generated goals) separately from action-taking (Wooldridge & Jennings — an
agent can be reactive-only by design), and set the autonomy level *independently per stage* — sense /
analyze / decide / act (Parasuraman, Sheridan & Wickens). An agent may analyze autonomously yet require
approval to act.

**Declarative guardrails sit beneath every autonomy level — and override instructions.** Weld & Etzioni's
"First Law of Robotics": *dont-disturb* invariants that "override direct human orders," plus a
no-regression baseline (no new harm relative to the start state); Norman's 1994 rule is the same — never
jeopardize the owner's physical, mental, or monetary well-being. Make them an editable
permission/obligation policy layer enforced *outside* the agent's reasoning. **Input-trust is part of the
guardrail:** an agent's instructions can be adversarial (prompt injection), so treat it as a capability
budget, not a content filter — the Rule of Two (≤ 2 of {untrusted input, sensitive access, external comms}
per session; all three → drop to human-in-the-loop or a new session; Willison's *lethal trifecta* is the
same kill-chain). Operationalize with provenance tagging, deterministic data/control-flow separation
(CaMeL), and integrity labels surfaced *in the UI* ("this argument is untrusted-derived, so this send is
blocked"). Never certify an injection defense on a fixed corpus — the attacker moves second; require
adaptive red-team evaluation (a §14 mandate).

**Make actions reversible so the gate has room to work.** The confidence×irreversibility gate collapses if
everything is irreversible, so reversibility is a design target, not a given. **Sagas** (Garcia-Molina &
Salem): decompose a long action into steps each paired with a *compensating* transaction, so a mid-way
failure semantically undoes already-committed external effects — the model for shipping an inverse with
every irreversible tool call. Add dry-run / preview / simulation before commit, and persist an
**idempotency key *before* the human interrupt** so resume is exactly-once, not double-executed.
Reversibility is what *earns* more autonomy: Maes's lower do-it bar for reversible acts is the same insight.

**Reversibility comes first; approval is the last resort, not a co-equal.** The gate's order: *first* make
the action reversible (compensating transaction / soft-delete / delay-plus-undo window / dry-run) — a
reversible action drops *out* of T4 and off the confirm trigger entirely. This is §7's undo-default at the
system layer: Gmail's Undo-Send grace window *is* a saga timeout, the same mechanism at UI and backend.
Only what genuinely *cannot* be made reversible escalates to T4 mandatory approval — and even then prefer
making the bad state unreachable (§8) or a non-habituated type-to-confirm over a reflexive "are you sure?"
the operator has been trained to click through.

**Authority transfer: who shifts the level, and the cost of taking control back.** Inagaki distinguishes
*sharing* control (joint) from *trading* it (clean handoff), and licenses a narrow, pre-declared rule where
final authority goes to automation in time-critical situations — then trades back. The cheapest deployable
trigger is a *critical-event* rule (on an irreversible / financial / external step → drop to confirm),
needing no human-state sensing. But taking control back is not free: takeover-request research (a
129-study meta-analysis) finds a disengaged human needs ~7 seconds of lead time to re-acquire control at
manual-equivalent quality — never demand *instant* takeover from an out-of-the-loop overseer; budget lead
time and escalate modality as it shrinks. Honesty check on any "confirm" affordance: ResQu (Douer & Meyer)
quantifies the operator's *exclusive causal contribution* — a confirm button that doesn't change the
outcome is *theater*, exactly what regulators mean by "a rubber-stamp review does not count" (GDPR 22).

**Engineer the joint activity, not the autonomy.** Dekker & Woods's *substitution myth*: you cannot hand a
function to the machine and leave the rest unchanged — adding an agent reshapes the whole workflow, so
design the *joint* activity. The testable form is Coactive Design's three properties — **Observability,
Predictability, Directability** — which double as acceptance criteria: can the user see what the agent is
doing and about to do, predict it, and redirect it mid-task? Cohen & Levesque add a hard communication
obligation: a team member who comes to believe the joint goal is achieved, impossible, or irrelevant must
make that mutually known — **the agent proactively reports the moment a delegated goal becomes done /
impossible / moot**, never silently retries or silently stops. COLLAGEN (Rich & Sidner) shows the
mechanism: surface the agent's task model as a *shared, inspectable* goal/subgoal stack so "what is it
doing and why" is answerable by construction — distinct from, and better than, post-hoc explanation.

**The input/authoring side: teach the agent, and confirm what it learned.** Programming-by-demonstration
solved much of agent specification before LLMs. Eager (Cypher 1991) ghosts the next predicted action so
that *proceeding is consent and diverging is veto* — zero-friction confirmation. CoScripter/Inky display a
ranked list of possible interpretations as concise textual sentences with inline provenance, and render the
learned behavior as a human-readable, **editable artifact** rather than opaque inference. Lau's
version-space rule gives the calibration: the *size of the still-consistent hypothesis set* **is** the
agent's uncertainty — query the maximally discriminating example; never collapse to one interpretation
prematurely. And mine the user's **takeovers and corrections as implicit negative examples** (Lieberman &
Maulsby), keeping their mental model of what the agent knows in sync.

**Infer intent, then confirm it — never act on a bare guess.** Cohen, Perrault & Allen distinguish
*intended* recognition (the user deliberately signals the goal) from *keyhole* recognition (inferring from
incomplete observations) — engineer cheap explicit channels for the user to state goals, and
confidence-gate anything inferred passively. While multiple goals still cover the observations, *hold the
disjunction and ask one targeted clarification* rather than commit (Kautz & Allen). After inferring a goal,
validate the plan and, on a belief mismatch, **surface the misconception** instead of silently "fixing" or
executing a buggy plan (Pollack). And type your acknowledgements (Allwood): "received" ≠ "understood" ≠
"will comply" — conflating them produces false grounding, the conversational form of lying status (§5).

**Anthropomorphism manufactures trust you did not earn.** CASA (Reeves & Nass): social responses to
computers are automatic — "simply having a computer use a human voice is sufficient to cause people to
apply social rules" — and users apply those rules *while denying* the machine warrants it, so
**self-reported trust is unreliable; measure behavior** (Nass & Moon). Luger & Sellen: conversational
fluency inflates capability expectations that collapse on first failure — *sounds capable ≠ is capable*.
Norman: "personification suggests promises of performance that cannot be met"; Erickson's fix is to
deliberately *under*-portray capability. The cues are concrete and controllable — first-person pronouns,
claims of feeling, agentive phrasing — and turning them against the user's perceptual weaknesses is
dishonest anthropomorphism, a checkable ship constraint.

**Build trust as a ramp, with feedback that decays as it's earned.** Muir & Moray: trust develops in stages
(predictability → dependability → faith), and mistrust *persists after the automation recovers* from a
fault — so error-*recovery* UX matters as much as error rate. Maes: earn autonomy incrementally "so the
user and agent can gradually build up a trust relationship," not a day-one full-autonomy grant; Norman's
matching rule is feedback "dialed down as reliability increases." Early runs over-communicate and ask;
later runs, on earned trust, do more silently — but the *floor* (honest status §5, the guardrails,
reversibility) never moves.

**The false-agency verification trap — the tie back to §1.** A confident-but-wrong agent *captures* the
user. Horvitz's Lumiere study found even off-target advice "was typically examined carefully and often
taken seriously… giving experts false confirmation of successful goal recognition." Microsoft's Magentic-UI
study, 28 years later: agent summaries "hide execution errors," producing an "illusion of accountability,"
and surfacing the agent's assumptions raised users' *confidence* without raising *accuracy* ("criteria
drift"). This is the cardinal rule in agent form: **approval is not verification.** A user clicking
"confirm" on a plausible-looking plan they did not — often *could* not — check is the human-path equivalent
of the API-returned-200 trap. Show a **diff, not a JSON blob**; offer **reject-with-edits**, not just
approve/deny; the Gate's rungs 6 (calibrated) and 7 (evidenced) exist precisely because consent ≠
correctness.

**Oversight is an auditable acceptance requirement, not a vibe.** EU AI Act Article 14's testable
ship-requirements: overseers must be able to monitor and detect anomalies, stay aware of automation bias,
"disregard, override or reverse the output," interrupt via a stop control to a safe state, and (high-stakes
biometric actions) confirm by two persons. GDPR 22 adds: request a human, submit your side, contest — with
the bar that the reviewer "must be able to actually change the outcome." Meaningful Human Control (Santoni
de Sio & van den Hoven) gives the deeper pair: **tracking** (the system responds to the relevant human's
reasons, not just outcomes) and **tracing** (every outcome traces to an informed human). Treat override and
escalation events as logged acceptance artifacts — they connect the control layer to the verification half.

**When the agent raises a flag, treat it as signal detection (the cry-wolf problem).** Meyer separates
**compliance** (acting on a raised flag — driven by the false-alarm rate) from **reliance** (relaxing your
own monitoring while the agent is silent — driven by the miss rate); the agent's *silence* is itself a
trust-bearing signal. Dixon & Wickens: false alarms damage *both* compliance and reliance (misses degrade
only reliance) — so bias agent flags *away* from false positives, and don't ship a diagnostic flag below
~60% precision, where net benefit stops. Prefer a **graded likelihood display** (tiered by computed
confidence) over a binary fire/not (Sorkin), and *attach the cause/evidence* to every flag — a
comprehensible "unnecessary" alarm can even support trust; an incomprehensible false one destroys it.
Reserve confirm/explain friction for high-consequence flags.

**Test:** For each consequential action your agent can take, can you name (a) its reversibility class and
the matching gate (auto / veto-window / confirm / two-person); (b) the declarative guardrail that overrides
instructions even when the model "wants" to proceed; (c) the evidence the user actually saw before
approving — a diff, not a blob; and (d) the instrument showing the user's confirmation *changed* the
outcome (ResQu, not a rubber stamp)? If "the user clicked confirm" is the whole answer, you have approval,
not verification.

---

## 14. The Verification Methods: How to Prove It

Each section ends with a **Test**; this is the toolbox those tests draw on. None requires a lab, a budget,
or a statistician.

**Watch a real user attempt the real task (the irreplaceable method).** The discipline that makes it valid
(Rubin & Chisnell): attribute every failure to the design, not the user; don't rescue a frustrated user
(the struggle "can be more revealing than at any other time"); don't telegraph success (a note, a nod, a
tone leaks); recruit the **Least Competent User** rather than a ringer, because a ringer "provides a false
sense of confidence." Test the **integrated whole**, not components: "it matters little if each component
is usable within itself… from the user's viewpoint, it is all one product."

**Test small, iterate often — the real math, not the slogan.** Nielsen: "the best results come from testing
no more than 5 users and running as many small tests as you can afford… 3 studies with 5 users each
[beats] a single monster study with 15." The model behind it (Nielsen & Landauer): N(1−(1−λ)^i), λ≈0.33 —
with the honest caveat the slogan drops: "5 users finds ~85%" is a cost/benefit peak, not a coverage
guarantee (maximum net benefit ≈16 evaluations). Two iron rules: a test that surfaces *no* difficulty
taught you nothing ("Learning occurs when there are difficulties" — a green run with no change extracted is
zero-bit), and discovery is sequence-independent, so the only failure mode is not iterating.

**Verify without users when you must: the Cognitive Walkthrough** (Wharton et al.). For each step of the
real task, ask the four questions: will the user try the right action? notice it's available? recognize it
as the right one? see progress after it? Its unit of evidence is a *missing* success story plus the named
knowledge gap — confirmations carry zero bits.

**Test the interaction before you build the backend: Wizard-of-Oz.** A human secretly simulating the system
"can be used to mimic a huge, powerful system long before it can be built" and reveals that real user
language/behavior diverges from your design assumptions — run it *before* committing engineering,
especially for conversational/agent UIs where the failure is usually in the interaction, not the model.

**Close the loop with a shipped, measured fix.** Krug: a test that ends in a report is not done — fix a
known, quickly-fixable problem and prove the fix with a real before/after signal. Instrument the path so a
defect can't hide: Wroblewski's $300M failure "was invisible to its own designers" until they read drop-off
data — measure completion rate *and where users abandon* (absence of complaints ≠ absence of problems, §2).
One honesty guard: a method's one-off success may owe as much to team skill and excitement as to the
method — re-run on a real path.

**Fault injection is the verification method for controls whose resource the user can't see.** The
human-centric methods above are nearly useless for a hardware, OS-resource, serial, sensor, or network
control surface — there the highest-value method is **perturbing the world** and watching the indicator:
unplug the device, point at a missing path, deny the permission, kill the data source, corrupt a frame,
drop the link. §5's lie-test and §12's resolution test depend on it — a first-class method, not an
afterthought.

**Synthetic-device harnesses let you drive the loop without the hardware — but a grant-everything harness
is structurally blind.** A fake input device (fake-media-stream, a headless boot) is a legitimate
substitute, but a harness that always grants and always connects exercises only the happy path — blind to
the denied / absent / unplugged / mid-stream-death states, precisely the ones that matter (§1's "evidence
that cannot reveal the failure"). Pair every synthetic harness with fault injection; the off-happy-path
states reachable *without* hardware (permission denied, device absent, wrong port, corrupted frame,
timeout) are the cheap, mandatory minimum.

**Test:** Which of these methods produced the evidence in your human-path ledger? "None — I reasoned about
it" is the answer this section exists to make unacceptable. For a hardware/resource/network control: did
you *perturb the world* (unplug / deny / kill the source) and watch the indicator and the structured
channel both tell the truth?

---

## 15. The Shippability Gate: The Forcing Function

Principles do not self-apply — a rigorous *display* playbook already existed when the agent flow shipped
broken. The control/input layer needs an *enforcement* layer: a hard definition-of-done you cannot satisfy
by reasoning. The gate is a **guiding ladder**, not a pass/fail punishment — from wherever you are, it
names the lowest unmet rung and the next action, and you loop until the top rung holds, *with evidence*.

```
0. Builds?     — The shippable artifact compiles/builds with NO errors silently suppressed by the dev or
                 watch harness (a dev server that strips type errors is a "green" that hides a
                 non-shippable build). ✗ → build the production artifact; fix what it surfaces. (§1)
1. Completes?  — A cold run by a non-builder reaches the intended real-world outcome at all.
       ✗ → drive the real entry point; find the first step that dead-ends; fix that. (§1, §3)
2. Honest?     — Every status/message reflects reality; no fabricated progress or state.
       ✗ → trace each indicator to its source of truth; rewire the one that can lie. (§5, §12)
3. Operable?   — At each step the user can form and take the right action; inputs asked in order.
       ✗ → reorder/relabel/signify the step the user couldn't act on. (§3, §10)
4. Legible?    — After each action the user perceives and understands what happened, incl. handoffs.
       ✗ → add the missing feedback / continuity at that seam. (§4, §6)
5. Robust?     — Empty / loading / partial / error / degraded / offline states are designed.
       ✗ → force the missing state on the real path and design it. (§7)
6. Calibrated? — The UI's confidence tracks the system's actual capability (loses face on failure).
       ✗ → add resolution: make success and failure look different. (§12)
7. Evidenced?  — A human-path ledger exists: screenshots + observed outcome at every user-visible
                 step of a cold run, ending in the real result.
       ✗ → NOT DONE. Produce the ledger. ← the rung that would have caught the original disaster.
```

**Three mechanisms make the gate bite:** (1) a **trigger** — any change to a user-facing flow loads this
playbook; (2) a **hard definition-of-done** — you may not claim a user workflow works without the rung-7
ledger; no ledger → not done, full stop; (3) a **UX red-team pass** — before calling a flow usable, run a
"first-run user with no context" adversarial walkthrough, the human-path analogue of security red-teaming.

**Make the safe path the efficient path, or the gate gets gamed.** Verification gets skipped rationally,
not carelessly: if producing the evidence is slower than shipping without it, builders will ship without
it. The ledger must be cheap — a screen-recording of the cold run is often enough — and §14's methods must
be the *fast* path, not a bureaucratic one. A gate that costs more than the bug it prevents will be
efficiency-thoroughness-traded around.

**The ledger's *form* follows the paradigm.** Screenshots-per-step fits a discrete GUI flow. For other
paradigms the evidence differs but the bar (observable proof of the real path) is the same: a timestamped
**screen-recording** of a cold session — entry → core loop → each state — for real-time and media apps; the
**data-state × rendered-response** cross-product for ambient monitors (force each data/degraded state,
capture the render); **rendered-pixel** verification (`readPixels` / `toDataURL`, dev-harness error
overlays neutralized first) for canvas/WebGL/video surfaces a DOM snapshot can't judge; a **terminal
transcript plus far-end-state evidence** (the remote actually changed) for headless/CLI/hardware-in-the-loop
tools.

**Test (the meta-test):** Could you, right now, hand someone the rung-7 ledger for this flow? If producing
it would require you to actually run the human path you've been claiming works — that gap is the whole
reason this document exists.

---

## Summary: One Pass

1. **Built ≠ works.** Green backend / passing tests / smooth demo ≠ a human can succeed. Done = a
   human-equivalent cold run produces the human-visible outcome.
2. **You are not the user.** Your success is zero-bit; absent complaints ≠ absent problems (the conspiracy
   of silence). Watch a real, uncoached, fresh user.
3. **Gulf of Execution.** Signifiers over affordances (possible ≠ discoverable); flow order matches the
   mental model; interlocks/wizards/start pages; defer non-essential inputs; solve the right problem.
4. **Gulf of Evaluation.** Imperceptible success fails like failure; mode/state perceivable at the point of
   action, not retrievable in a log; effects land at the input locus; real-time needs a glanceable HUD.
5. **Status must be true.** Derive from the work, not intent; liveness from data actually arriving; unknown
   is its own verdict on the structured channel; right instance, not just right type. Test: can you make
   the indicator lie?
6. **Handoffs preserve continuity.** Platform credential surfaces (RFC 8252); perceivable return;
   over-communicate at seams; the connection is a modeled state machine every command shares.
7. **Every state is designed.** Slips vs mistakes; undo over confirmation (confirm only the genuinely
   irreversible tail, type-to-confirm); undo is a correctness contract; empty/loading/partial/degraded +
   your domain's machine; honest progress at the 0.1/1/10 s thresholds; safe true defaults.
8. **A missing control is not a defect.** The bar is an observed past need, not a symmetry. Design for
   intent, not mechanism. Never-used controls are clutter; core-promise-destroying ones are footguns — make
   the bad state unreachable. Continuous intent → resilience (watchdog, heartbeat, loud unrecoverable
   stops), not an off-switch.
9. **Patch vs. overhaul.** Defect audits are hill-climbing one design; a wrong conceptual model/IA needs a
   new frame; escalate on structural triggers judged over the whole artifact; ≥3 parallel alternatives from
   goals/jobs; overhaul the design, never rewrite from scratch; strangler-fig delivery; don't churn a
   mastered UI unvalidated — but for a user-less app, restraint is the active failure. Ask: would I build
   it this way from scratch today?
10. **Dialogs are real UI.** Errors: human, specific, blameless, constructive, ≤2 types; validate at the
    right time and place; buttons are verbs; Cancel has a contract; for machine operators the structured
    channel is the UI and must hold on failure paths.
11. **First-run empathy.** Walk-up usability; endowed progress accelerates — but shown progress must be true.
12. **Trust calibration.** Calibrate, don't maximize; resolution + specificity + three bases
    (performance/process/purpose); dispositional/situational/learned layers; SAT levels L1–L3; both failure
    directions (complacency *and* algorithm aversion); explanations boost agreement, not accuracy; polish
    is a confound.
13. **Human–agent.** Middle-rung autonomy; gate on confidence × irreversibility, per stage and action
    class; declarative guardrails above instructions (Rule of Two); reversibility first (sagas, dry-run,
    idempotency keys), approval last; budget takeover lead time; Observable/Predictable/Directable; report
    done/impossible/moot; teach by demonstration with editable artifacts; infer-then-confirm intent;
    anthropomorphism = unearned trust; trust ramps with decaying feedback; **approval ≠ verification**
    (diff, not blob); auditable oversight; flags as two-knob signal detection.
14. **Verification methods.** Watch real users (LCU, integrated whole, don't rescue/telegraph); test 5 and
    iterate; cognitive walkthrough; Wizard-of-Oz before building; close the loop with a measured fix;
    fault injection; no grant-everything harnesses.
15. **The Shippability Gate.** The 0–7 ladder ending in a human-path evidence ledger; trigger + hard DoD +
    UX red-team; make the safe path the efficient path.

---

## Sources

Attributed inline throughout. Core canon: Norman *The Design of Everyday Things* (+ 1990/1994 agent
papers); Nielsen *Usability Engineering* + the NN/g corpus; Nielsen & Landauer 1993 (problem-discovery
model); Krug *Don't Make Me Think*; Wroblewski *Web Form Design*; Rubin & Chisnell *Handbook of Usability
Testing*; Wharton et al. (Cognitive Walkthrough); Boehm 1984 (verification vs. validation); ESA PSS-05-10;
NIST SP 500-165; Apple *Macintosh HIG* 1992; RFC 8252; Kivetz, Urminsky & Zheng 2006 (goal gradient);
Raskin 2007 (undo, not warnings); Anderson et al. CHI 2015 (warning habituation, fMRI); Johnson & Goldstein
2003 (defaults); Adams et al. 2021 (additive bias); Cooper (mental vs. implementation models); Spolsky;
Fowler (YAGNI, strangler fig); Buxton *Sketching User Experiences*; Tohidi & Buxton 2006; Dow et al. 2010
(parallel prototyping); Brooks; Gall.

Human–agent & automation: Lee & See 2004 (trust in automation); Muir & Moray 1996; Hoff & Bashir 2015;
Bainbridge 1983 (ironies of automation); Sheridan & Verplank 1978 (levels of automation);
Parasuraman/Sheridan/Wickens 2000; Maes 1994 / Maes & Kozierok 1993; Shneiderman & Maes 1997; Weld &
Etzioni 1994; Endsley & Kaber 1999; Onnasch et al. 2014; Inagaki 2003; Johnson, Bradshaw et al. 2014
(Coactive Design); Cohen & Levesque 1991; Rich & Sidner 1998 (COLLAGEN); Cypher 1993 / Lieberman 2001
(programming by demonstration); Lau et al. 2003 (version spaces); Reeves & Nass 1996 (CASA); Nass & Moon
2000; Luger & Sellen 2016; Horvitz 1998–99 (Lumiere, mixed-initiative); Amershi et al. 2019 (Microsoft
HAX); Google PAIR 2019; Bansal et al. 2021; Dietvorst et al. 2015 (algorithm aversion); Garcia-Molina &
Salem 1987 (sagas); Willison (lethal trifecta); Meta (Agents Rule of Two); Debenedetti et al. 2025 (CaMeL);
EU AI Act Art. 14/50; GDPR Art. 22; Santoni de Sio & van den Hoven 2018 (meaningful human control); Meyer
2001/2004 (compliance vs. reliance); Sorkin et al. 1988 (likelihood alarms); Dixon & Wickens 2006; Douer &
Meyer (ResQu).
