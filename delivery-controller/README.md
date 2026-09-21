# Aineko Delivery Controller

A local, model-agnostic control plane for durable software-delivery jobs.

## Why this exists

The scarce resource it targets is **continuous engineering supervision**: remembering that a PR is waiting, noticing CI completion, preserving state across interruptions, and keeping a delivery objective alive until a terminal outcome.

The controller is deliberately not a coding agent. It owns durable transaction state and delegates cognition through an adapter. This keeps model choice replaceable and lets deterministic systems remain authoritative for Git, CI, review and deployment state.

## v0.1 scope

v0.1 is **observe-only by design**:

- durable SQLite job/event state;
- GOMS branch + checkpoint projection;
- GitHub PR/check/review observation through `gh`;
- explicit delivery state machine;
- model-provider boundary (`none` or the existing local dispatcher);
- macOS `launchd` example for periodic ticks;
- no automatic edits, pushes, merges, deployments or production actions.

This is enough to validate whether persistent completion orchestration removes attention load before granting it authority.

## Commands

```bash
cd ~/Documents/aineko-infrastructure/delivery-controller
python3 delivery.py doctor
python3 delivery.py init

# Create a dormant job
python3 delivery.py submit --repo OWNER/REPO --goal "Implement X"

# Or attach an existing PR, making the job immediately observable
python3 delivery.py submit --repo OWNER/REPO --goal "Shepherd PR to merge gate" --pr 123

python3 delivery.py tick
python3 delivery.py status --active
```

A green PR stops at `MERGE_GATE`; v0.1 never merges it. Failed CI becomes `WAIT_CI` with the failing check names as the next remediation target.

## Model independence

The controller does not import Gemini or ADK. `Provider` is an interface. The current local adapter calls `../local-ai/dispatch.py`, which means the existing model router can evolve independently. An ADK, Claude, OpenAI, local Ollama, MCP/A2A or other provider can later implement the same boundary.

Google ADK can therefore be used as one cognition runtime without becoming architecture.

## State and provenance

Operational state is in `delivery.sqlite3`. Each job also creates a GOMS branch when GOMS is available and writes checkpoints as external conditions change. GOMS remains the cross-capability coordination/provenance layer; the delivery database contains execution-specific state.

## launchd

The example plist in `launchd/` runs `tick` every five minutes. Do **not** install it until there is at least one real job worth observing. A scheduler with no useful work is just a tiny electric metronome.

## Next authority tranche

Only after observation shows value:

1. add isolated git worktrees;
2. add typed test/build tools;
3. let a provider diagnose CI failures;
4. allow patch + push under `authority=pr`;
5. keep merge/deploy as explicit policy gates;
6. promote autonomy only from measured failure/rollback evidence.

## PR autopilot

Repository policies may opt into autopilot. Authenticated GitHub events wake the controller to discover open PRs, distinguishes pending, code/review/reconciliation, and zero-step infrastructure failures, and may merge a clean PR only when repository policy explicitly grants it. Ambiguous or consequential repairs remain escalation points.

### Event ingress

webhook.py accepts signed GitHub events at /github, validates X-Hub-Signature-256, deduplicates X-GitHub-Delivery, and immediately runs the repository autopilot. Configure GITHUB_WEBHOOK_SECRET outside source control. The scheduled tick is retained only as reconciliation/watchdog fallback.
