# Semantic Promotion Throughput

## Principle

Raw knowledge arrival is a proxy for the speed at which the human is working.

The Exocortex must not treat that rate as something to suppress merely because downstream semantic machinery is slower. The machinery exists to extend the human, so the default response to sustained semantic backlog is to **increase promotion capacity**, not to slow human input.

Lossless ingestion and semantic promotion are separate concerns:

```text
human work-rate
  -> lossless ingestion
  -> durable raw/evidence queue
  -> semantic extraction
  -> validation
  -> reconciliation
  -> evidence sufficiency / review
  -> graph-shape review / repair
  -> promotion
  -> canonical current world model
```

The ingestion edge should remain fast, durable, and non-blocking. Downstream stages may apply bounded internal backpressure to protect databases/providers, but must not turn that backpressure into human attention cost.

## Throughput objective

For a stable system over a meaningful window:

```text
semantic promotion capacity >= durable semantic arrival rate
```

This does not mean every message becomes knowledge. It means the pipeline must be able to classify, reject, quarantine, repair, or promote candidates at least as quickly as durable candidates arrive.

## Current bottleneck discovered 2026-09-20

The live corpus contained:
- 108,440 distillation segments;
- 2,084 semantic candidates;
- 1,338 validator-accepted/reclassified candidates;
- 334 promoted distillation assertions;
- 464 low-confidence HOLD candidates;
- 177 graph-shape REWRITE candidates.

The semantic daemon previously processed one stage per round-robin turn, exposed review backlog as a boolean rather than a count, reviewed only 12 graph-shape candidates per invocation, and treated HOLD/REWRITE as effectively terminal.

That made the semantic pipeline appear idle while approximately one thousand potentially useful candidates were stranded after extraction.

## Throughput architecture

### Adaptive scheduler

The semantic daemon now supports backlog-pressure scheduling.

Each stage has an approximate per-pass capacity. When a backlog exceeds one pass, the scheduler prioritizes the stage with the largest normalized pressure:

```text
pressure(stage) = backlog(stage) / nominal_capacity(stage)
```

Below capacity, ordinary round-robin fairness remains.

### Larger batches

Default safe batch sizes are increased for:
- validation;
- reconciliation;
- graph-shape review.

All remain environment-configurable so measured model/context limits can tune capacity without code changes.

### Evidence-review lane

Low composite confidence is no longer a permanent parking state.

Candidates held **only** for `LOW_COMPOSITE_CONFIDENCE` can enter an independent evidence-sufficiency committee.

The committee:
- uses the shared model router;
- requires distinct qualified reviewer models;
- reviews cited evidence, not plausibility;
- requires unanimous ACCEPT and minimum reviewer confidence;
- cannot waive identity ambiguity, contradiction, temporal uncertainty, malformed graph shape, or other hard-review reasons;
- records reviewer decisions with the exact gate fingerprint;
- deterministically persists the override across re-gating.

A reviewer disagreement, REJECT, insufficient qualified reviewers, or sub-threshold confidence leaves the candidate non-authorized.

### Rewrite-repair lane

Graph-shape REWRITE is also no longer terminal.

Automatic rewrite is deliberately narrow:
- current gate only;
- consensus REWRITE;
- at least two independent reviewers;
- identical proposed replacement shape;
- no mutation of an existing canonical entity identity.

Safe rewrites update the proposal, invalidate the old gate/review through existing triggers, and re-enter normal gating.

Non-identical or disputed rewrites remain non-authorizing for stronger adjudication.

## Metrics

The pipeline should expose at least:
- candidate arrivals/hour;
- assertions promoted/hour;
- promotion-to-arrival ratio;
- accepted-to-promoted conversion ratio;
- validation backlog;
- reconciliation backlog;
- review backlog;
- evidence-review backlog;
- graph-shape backlog;
- rewrite backlog;
- promotable backlog;
- oldest-item age by stage.

The governing operational metric is not database size. It is whether the semantic system can metabolize the human's durable work stream while preserving epistemic quality.

## Scaling order

When promotion throughput is below durable arrival rate:

1. remove deterministic waste and terminal parking states;
2. increase safe batch size;
3. prioritize overloaded stages;
4. parallelize independent model review where provider/runtime supports it;
5. use additional qualified subscription/free/local compute through the shared router;
6. distribute independent stage workers across available machines;
7. only apply ingestion throttling to protect hard resource integrity, never as the normal solution to human productivity.

## Safety invariant

Throughput improvements must not weaken semantic authority.

Faster promotion is acceptable only when provenance, evidence sufficiency, temporal authority, graph shape, contradiction checks, and HUMAN_ONLY boundaries remain at least as strong as before.
