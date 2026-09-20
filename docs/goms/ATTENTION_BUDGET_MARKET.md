# Attention Budget Market

## Purpose

Machine cognition is abundant relative to human attention. The Exocortex therefore treats a prospective interruption as a demand on a scarce control channel rather than as a notification with a severity label.

The market is deliberately small. It does not attempt monetary economics. It asks whether a candidate deserves the human boundary.

## Classes

| Class | Default machine behaviour |
| --- | --- |
| A0 | Execute or resolve autonomously; do not surface routinely |
| A1 | Preserve for the next digest |
| A2 | Bundle with related decisions at the next natural human interaction |
| A3 | Interrupt now |

A3 is exceptional. Importance or severity alone cannot create A3.

The classifier must be able to state both:

1. **What specifically can the human decide now that the machinery cannot?**
2. **What is the cost of waiting?**

If either answer is missing, the candidate cannot be A3.

## Bid

The initial bid is intentionally simple:

\`expected_value × urgency × human_irreplaceability ÷ attention_cost\`

All value factors are normalized to \`[0,1]\`. Attention cost is estimated in human minutes and normalized relative to ten minutes.

The scalar bid does **not** decide A3 by itself. A3 also requires high human irreducibility, a concrete human decision, and an explicit material delay-cost reason.

## Questions about ends

The market must not optimize away the human's role in choosing ends.

Explicit questions about objectives, acceptable risk, personal commitments, irreversible actions, values, or other protected end-questions are never classified below A2. They may become A3 only when delay is materially costly and that cost is stated.

No measurable proxy may silently replace such judgment.

## Machine-first escalation

Before consuming human attention, an agent should prefer available machine routes such as:

- stronger or alternative models;
- evidence retrieval;
- simulation;
- adversarial review;
- reversible experiments;
- delegation;
- recovery through alternate authorised capabilities;
- safe deferral.

This does not widen machine authority. Existing HUMAN_ONLY and authority boundaries remain independent constraints.

## Placement in the architecture

The market sits on the shared GOMS attention path:

\`producer → attention_item → control_intent → attention market → alert/digest/bundle\`

This is important. Hermes, research machinery, Nemosyne workers and infrastructure controllers should not compete for attention using separate urgency schemes.

\`goms-v2/attention_market.py\` owns classification and experiment state.

\`goms-v2/alerts.py\` invokes the market before alert creation.

## Rollout modes

\`GOMS_ATTENTION_MARKET_MODE\` supports:

- \`shadow\` — record classification; preserve current delivery behaviour.
- \`suppress_a0\` — suppress immediate A0 alerts.
- \`suppress_a0_a1\` — suppress A0 and immediate A1 alerts; A1 remains durable for digest surfaces.

The default is **shadow**.

No rollout stage changes HUMAN_ONLY authority semantics.

## Shadow experiment

The first experiment is \`attention-market-shadow-v1\`, target **50 real candidate interruptions**.

The system records:

- A0–A3 class;
- computed bid;
- expected value;
- urgency;
- human irreplaceability;
- estimated attention minutes;
- delay cost;
- concrete human decision text;
- delay-cost reason;
- protected-end flag;
- whether machine resolution is expected;
- producer family;
- recommended behaviour.

The sampler attempts coverage across:

- Hermes / GSV Aineko;
- Nemosyne / Moneta workers;
- research machinery;
- infrastructure;
- other producers when the canonical corpus lacks enough candidates.

It never invents candidates to satisfy the quota.

## Revealed-value review

Outcomes can record:

- whether the interruption proved useful;
- whether human intervention materially changed the outcome;
- minutes to decision;
- whether the machinery resolved it later anyway;
- whether it was bundled;
- a short outcome note.

The primary review surface is **disagreement**, not every classification:

- A0/A1 that later proved useful or outcome-changing;
- A2/A3 that proved useless;
- A2/A3 that machinery resolved later without needing the human.

## Metrics

The experiment reports:

- interruptions;
- actionable interruptions;
- minutes to decision;
- interruptions resolved by machine later;
- bundling ratio;
- human interventions that materially changed outcomes;
- class distribution;
- producer-family coverage.

The experiment becomes \`READY_FOR_REVIEW\` after at least 50 classified candidates. That state does not itself interrupt the human.

## Expansion rule

Autonomy expands only from evidence.

1. Run shadow mode.
2. Review disagreements after 50 real candidates.
3. If A0 performance is acceptable, enable \`suppress_a0\`.
4. Accumulate more revealed-value evidence.
5. Only then consider \`suppress_a0_a1\`.

A2 and A3 remain visible during these initial rollout stages.

## Success condition

Adding agents or compute should eventually reduce, not increase, human interruption pressure.

The long-run objective is not the smallest number of alerts. It is the highest worthwhile human impact per unit attention while preserving human control over ends.
