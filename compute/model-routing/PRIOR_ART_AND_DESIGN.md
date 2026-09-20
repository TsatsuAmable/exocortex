# Aineko Model Routing: Prior Art and Design

Date: 2026-09-10
Status: active research/design
GOMS branch: `model-routing`

## Problem
Route each task, and eventually each agent step, to the cheapest trustworthy substrate that is likely to succeed while respecting privacy, capability, latency, local resource pressure and human-attention constraints.

The fleet is heterogeneous: local Ollama/MLX/llama.cpp models, rotating free cloud models, subscription-entitled capacity, paid APIs, and specialist workers. A router must treat model choice, provider choice, reasoning mode and escalation as separate decisions.

## Prior-art families
1. **Cost-aware cascades.** FrugalGPT (Chen, Zaharia, Zou; arXiv:2305.05176, TMLR 2024) learns cascades across LLM APIs. It established the central result that heterogeneous models can reduce cost dramatically while maintaining or improving quality.
2. **Post-answer verification cascades.** AutoMix (arXiv:2310.12963) runs a cheaper model first, estimates answer correctness by self-verification, then uses a POMDP policy to decide escalation.
3. **Pre-query learned routing.** RouteLLM (arXiv:2406.18665, ICLR 2025) learns strong-vs-weak routing from preference data. Hybrid LLM (arXiv:2404.14618) predicts query difficulty and routes between small and large models under a configurable quality target.
4. **Benchmark-derived routing.** Shnitzer et al. (arXiv:2309.15789) repurpose benchmark data to learn model selectors. RouterBench (arXiv:2403.12031) standardized evaluation with hundreds of thousands of recorded model outcomes.
5. **Simple non-parametric routing.** Li, `Rethinking Predictive Modeling for LLM Routing` (arXiv:2505.12601) finds tuned kNN competitive with or better than substantially more complex learned routers across multiple routing settings.
6. **Large-scale router re-evaluation.** LLMRouterBench (arXiv:2601.07206) evaluates 10 routing baselines across >400K instances, 21 datasets and 33 models. It reports strong model complementarity, but also that many sophisticated/commercial routers do not reliably beat simple baselines and that larger ensembles show diminishing returns.
7. **Calibrated cascade routing.** UCCI (arXiv:2605.18796) treats uncalibrated confidence as a core failure mode and uses calibrated uncertainty plus constrained cost minimization for escalation.
8. **Preference-aware routing.** MetaRouter (arXiv:2606.06178) frames user-specific cost-performance preferences as a contextual-bandit/meta-learning problem.
9. **Provider routing/gateways.** OpenRouter routes provider endpoints using reliability, price, latency and throughput, with explicit privacy controls such as data-collection and zero-data-retention filters. LiteLLM provides a unified gateway, budgets, retry/fallback, load balancing and observability across 100+ model providers.
10. **Commercial learned routing.** Not Diamond exposes pre-trained and custom routers over candidate models with quality/cost/latency trade-offs and feedback loops.
11. **Privacy-aware edge/cloud routing.** PRISM (arXiv:2511.22788) explicitly routes between edge, cloud and collaborative modes based on sensitivity and privacy/utility trade-offs.
12. **Reasoning-paradigm routing.** Select-then-Solve (arXiv:2604.06753) shows that Direct, CoT, ReAct, Plan-Execute, Reflection and ReCode have task-dependent strengths, and that routing the reasoning paradigm can matter independently of model choice.
13. **Step-wise agent routing.** ProgRouter (arXiv:2608.25992) argues that one-shot query routing is insufficient for long-running agents and routes dynamically by workflow progress, remaining difficulty, time and cost.

## Strong conclusions from the literature
- **Model complementarity is real.** No single model dominates every task, so routing is worth doing.
- **Routing overhead must stay small.** Simple kNN and linear baselines are unusually competitive. Complexity is not evidence of intelligence.
- **Candidate curation matters.** More models are not automatically better; large ensembles show diminishing returns.
- **Generic benchmarks are insufficient.** Routers must be evaluated on the real workload distribution they will serve.
- **Self-confidence is dangerous when uncalibrated.** Escalation should rely on externally measurable verification where possible, or calibrated uncertainty rather than a model saying it feels confident.
- **Verification changes the economics.** Code/tests, structured-output validation and deterministic checks make cheap-first cascades much safer than they are for open-ended judgement tasks.
- **Provider routing and model routing are different layers.** We should reuse gateways for endpoint reliability/price where possible rather than relearn that layer ourselves.
- **Agent routing is stateful.** For multi-step work, the right model can change after each observation or failed attempt.

## What is still missing for Aineko
Existing work generally optimises some subset of quality, token cost and latency. Our control plane needs additional hard and soft constraints:
- privacy class and provider retention/training policy;
- local RAM/VRAM pressure, model residency and cold-start cost;
- tool-calling and structured-output fidelity;
- context-window requirement;
- online/free-tier availability and quota volatility;
- task verifiability and availability of an oracle/test;
- long-horizon progress rather than one-shot answer quality;
- provenance and reproducibility of routing decisions;
- human repair/validation attention as a first-class cost;
- strategic reuse: whether a run creates reusable capability, data or evidence.
## Recommended architecture: gated utility router

### Stage 0: hard eligibility filter
Before any learned decision, eliminate candidates that violate constraints: sensitivity/privacy, required tools or modality, minimum context, offline requirement, local memory budget, provider trust policy, or explicit monetary cap.

### Stage 1: simple pre-router
Represent the task with a cheap embedding plus explicit features: task family, expected context size, tool requirements, verification type, privacy class and interaction mode. Use kNN over historical Aineko task outcomes to estimate success probability, latency, total cost and repair burden for each eligible candidate.

A first utility score should be transparent rather than magical:
`U = P(success) * task_value - money - latency_penalty - resource_penalty - privacy_risk - expected_human_repair_cost`
with hard constraints applied before utility scoring. We should report the Pareto frontier rather than hide trade-offs in one permanent scalar.

### Stage 2: verification and escalation
For verifiable tasks, try the cheapest candidate predicted to clear a success threshold, run the verifier, and escalate only on failure. Verifiers include tests, type-checking, schema validation, exact-answer checks, citation/source checks, replay/determinism checks and bounded adversarial review.

For weakly verifiable tasks, use calibrated historical error rates and conservative escalation. Never substitute uncalibrated self-confidence for evidence.

### Stage 3: online learning
Every run emits a routing outcome to GOMS: task fingerprint, candidate/model/provider, privacy class, context, tools, latency, tokens, monetary cost, local resource pressure, verifier outcome, retries, final success, human repair minutes and any escalation path. The kNN support set updates online. Later, contextual bandits or learned routers must beat this baseline before promotion.

### Stage 4: workflow routing
Only after one-shot routing is reliable, route individual agent steps based on current progress. A planning step, web search, code edit, verifier and synthesis step may each deserve a different substrate or reasoning paradigm.

## Initial benchmark: AinekoRouterBench
Start with 30-50 real tasks, not synthetic model trivia. Classes should include: conversational control-plane turns; extraction/classification; structured output; GOMS tool use; web research; summarisation; code generation; code repair with tests; code review; statistical/scientific reasoning; long-context synthesis; security/privacy judgement; and source-grounded research.

Candidate pool v0: `gsvaineko-core:v1` / Qwen3.5-4B local, Qwen3.5-9B local, Bonsai-27B local where compatible, current OpenCode anonymous free models, temporary subscription-entitled models when available, and one frontier reference model used sparingly as an upper-bound comparator.

Promotion metrics: task success, verifier pass, tool-call success, TTFT, end-to-end latency, input/output tokens, actual monetary cost, peak local memory/swap delta, cold/warm state, provider failure rate, privacy eligibility, retries, and estimated human repair minutes.

## V0 decision
Do **not** train a neural router yet. Implement: capability/privacy gates + curated candidate set + measured outcomes + kNN baseline + verification cascade. Compare against three baselines: fixed local model, fixed strongest model, and simple cheapest-first cascade. A learned router earns promotion only if it improves the real workload Pareto frontier with held-out tasks.
