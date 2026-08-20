# Quickstart Professional Agent Experience Design

## Objective

Turn desktop Quickstart from a six-step resource wizard into a coherent agent-production workflow that:

1. recommends an immediately usable runtime when possible;
2. produces a professional, reviewable agent blueprint;
3. explains generation progress and recovery actions;
4. distinguishes platform capability from controls actually enforced for this launch;
5. proves the first run with an explicit acceptance scenario instead of treating any reply as success.

## Product Model

The user should perceive four outcomes rather than six configuration chores:

1. **Understand** — JoySafeter restates the goal and chooses the best usable runtime.
2. **Design** — JoySafeter generates a professional Agent Blueprint and exposes assumptions.
3. **Protect** — JoySafeter shows which controls are enforced, recommended, optional, or absent.
4. **Prove** — JoySafeter launches an acceptance run and shows observable evidence.

The existing six backend/resource steps remain valid implementation milestones, but the UI must group them into these four outcomes.

## Desktop Information Architecture

### Landing

- Keep the current two-column landing and established JoySafeter visual language.
- Make the natural-language goal the primary action; templates remain a secondary accelerator.
- Runtime choices must be ranked by both intent fit and immediate usability.
- Each runtime option displays one of:
  - `Ready now` — an active compatible Model Connection exists;
  - `Setup required` — no compatible Model Connection exists;
  - `Unavailable` — runtime is disabled or unhealthy.
- The recommended runtime must prefer `Ready now` over a marginally better semantic match that blocks the next step.

### Build Workspace

- Preserve the left conversation and right work surface.
- Replace the default raw YAML surface with `Agent Blueprint`.
- Keep YAML and JSON under an `Advanced config` tab.
- The blueprint must show:
  - mission;
  - responsibilities;
  - operating workflow;
  - boundaries and non-goals;
  - tools and authorization assumptions;
  - escalation conditions;
  - output contract;
  - success criteria;
  - acceptance test.
- Every section must have an explicit empty/generating state rather than disappearing.

### Generation Progress

Generation exposes semantic phases:

1. Understanding the goal
2. Designing responsibilities
3. Defining safety boundaries
4. Planning tools and permissions
5. Writing the operating instructions
6. Preparing the acceptance test

The UI must:

- show the current phase;
- show elapsed time after five seconds;
- expose `Cancel generation` while streaming;
- expose `Try again` after an error or cancelled run;
- preserve partial generated configuration for inspection;
- never leave only a generic `Thinking...` indicator.

### Safety Plan

Each launch control has an explicit state:

- **Enforced** — attached to the launch and verified in the request;
- **Ready** — configured and eligible for attachment;
- **Recommended** — omitted, but JoySafeter recommends it;
- **Not authorized** — external tool credentials are not attached;
- **Automatic** — audit capture is platform-managed.

The UI must not describe a recommended environment as already protected. Launch remains possible without an environment, but the CTA and summary must state that the session will run without custom egress controls.

### Acceptance Run

- The generated blueprint includes one short user message and observable checks.
- Session creation pre-fills that message.
- A reply returning to idle means `Response received`, not automatic goal success.
- The completion area displays the acceptance checks and links to transcript/debug evidence.
- Runtime errors, scheduling timeout, and rejected access remain distinct states.

## Agent Blueprint Contract

Generated agent configuration adds an optional `blueprint` object:

```ts
interface QuickstartAgentBlueprint {
  mission: string;
  responsibilities: string[];
  workflow: string[];
  boundaries: string[];
  toolPlan: string[];
  escalationConditions: string[];
  outputContract: string[];
  successCriteria: string[];
  acceptanceTest: {
    message: string;
    checks: string[];
  };
}
```

The authoritative runtime behavior remains the generated `system` prompt. Blueprint fields are review metadata and must be compiled into string metadata on agent creation so the professional design artifact survives creation without changing the backend agent schema.

Malformed or partial model output must be normalized into a safe blueprint rather than forwarded raw.

## Runtime Recommendation Contract

Recommendation consumes:

- enabled runtime capabilities;
- user intent;
- active compatible Model Connections per runtime.

Ranking order:

1. usable intent-matched runtime;
2. any usable runtime;
3. intent-matched runtime requiring setup;
4. any enabled runtime requiring setup.

The UI still allows selecting any enabled runtime.

## Template Contract

Templates must no longer claim that safety defaults are already applied when they only provide an agent prompt. Each template supplies:

- agent configuration;
- professional blueprint;
- declared runtime intent;
- recommended safety posture;
- acceptance test.

Environment and credential resources are still confirmed separately and are not silently created.

## Architecture

- Keep resource orchestration in `useQuickstartChat` initially, but extract pure state/normalization logic.
- Add focused helpers for runtime recommendation and blueprint normalization/persistence.
- Add focused presentation components for generation status and blueprint review.
- Keep `page.tsx` as composition during the first increment; later extraction may move environment, credential, and launch panels without changing behavior.

## Verification

- Pure recommendation and blueprint normalization tests.
- Hook tests for cancel/retry and acceptance-message behavior.
- Page tests for usable runtime recommendation, Blueprint default tab, truthful safety labels, and generation progress.
- Backend prompt/tool-schema tests.
- Desktop Playwright checks at 1440×900 for landing, recommendation, generating, blueprint review, safety review, and acceptance-run states.

## Constraints

- No new frontend dependency.
- Preserve current project scoping, read-only handling, typed IDs, resource creation contracts, and credential isolation.
- Do not create resources before explicit user confirmation.
- Do not overwrite unrelated credential-domain work already present in the worktree.
