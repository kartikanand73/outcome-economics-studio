# Calculation validation: three hand-worked scenarios

Every number below was worked out by hand from the formulas, independently of the code.
`backend/tests/test_hand_calculated.py` builds the same three scenarios and asserts that the engine
returns exactly these values (exact `Decimal` equality unless noted). Run `pytest -q` to re-check.

Price convention: prices are per 1,000,000 tokens, so a call's cost is tokens × price ÷ 1,000,000.

---

## Scenario A: rules + one lightweight model

**Inputs**

| Item | Value |
|---|---|
| Volume | 1,000 tasks/day × 30 days = **30,000 tasks/month**, no growth |
| Model L | $1.00 in / $4.00 out per 1M; 1,000 input + 100 output tokens per call; 1 call; no retries, no cache, no reasoning |
| Tool / API | $0.001 per call |
| Human review | 3 min at $60/h = **$3.00 per review**; worst case 10 min |
| Evaluation | 10% of tasks sampled at $0.05 |
| Fixed | $300/month infrastructure |
| Route R1 (20%) | Deterministic rule, 1 API call, no review, 100% accurate |
| Route R2 (80%) | 1 API call → L, 10% reviewed, 95% accurate |

**Expected cost**

| Step | Working | Result |
|---|---|---|
| L call | 1,000 × 1 ÷ 1M + 100 × 4 ÷ 1M = 0.001 + 0.0004 | $0.0014 |
| Evaluation per task | 10% × $0.05 | $0.005 |
| R1 cost | $0.001 tool + $0.005 eval | $0.006 |
| R2 cost | $0.0014 + $0.001 + 10% × $3.00 + $0.005 | $0.3074 |
| Variable per task | 0.2 × 0.006 + 0.8 × 0.3074 = 0.0012 + 0.24592 | **$0.24712** |
| Allocated fixed | $300 ÷ 30,000 | $0.01 |
| Expected per task | 0.24712 + 0.01 | **$0.25712** |
| Daily (variable) | 0.24712 × 1,000 | **$247.12** |
| Monthly | 247.12 × 30 + 300 | **$7,713.60** |
| Annual | 7,713.60 × 12 | **$92,563.20** |
| Accuracy | 0.2 × 100% + 0.8 × 95% | **96%** |
| Correct outcomes / month | 30,000 × 0.96 | 28,800 |
| **Cost per correct outcome** | 7,713.60 ÷ 28,800 | **$0.2678333…** |
| Human reviews / month | 0.8 × 10% × 30,000 | 2,400 |
| Model cost per 1,000 decisions | 0.8 × 0.0014 × 1,000 | $1.12 |
| Expected tokens per task | 0.8 × 1,100 | 880 |

Cost by category per task: lightweight model $0.00112 · tools $0.001 · human $0.24 · evaluation $0.005 · infrastructure $0.01.

**Maximum (custom limits)**: L max input 500 system + 500 user = 1,000 tokens, max output 200, 1 call, no retries.

| Step | Working | Result |
|---|---|---|
| L worst call | 1,000 × 1 ÷ 1M + 200 × 4 ÷ 1M | $0.0018 (1,200 tokens) |
| R2 worst | 0.0018 + 0.001 tool + 10 min × $60/h ($10) + $0.05 eval | $10.0528 |
| R1 worst | $0.001 + $0.05 | $0.051 |
| Maximum variable per task | worst route = R2 | **$10.0528** |
| Maximum per task incl. allocated fixed | 10.0528 + 0.01 | **$10.0628** |
| Maximum tokens per task | | **1,200** |

**Latency**: R1 takes 5 ms; R2 has L at P50 = P95 = 200 ms. 20% of tasks finish at 5 ms and 80% at 200 ms, so
the median and P95 are both **200 ms**.

---

## Scenario B: cascade with retries, prompt cache, reasoning and a budget

**Inputs**

| Item | Value |
|---|---|
| Volume | 2,000 tasks/day × 20 days = **40,000 tasks/month** |
| Model L (lightweight) | $0.50 in / $2.00 out; 800 in + 50 out; retries on, 5% retry rate, max 1 retry |
| Model G (larger) | $5.00 in / $20.00 out / $0.50 cached; 2,000 in (50% cached) + 100 out + 200 reasoning (billed at output price); no retries |
| Human review | 4 min at $45/h = **$3.00 per review** (no separate worst case) |
| No tools, no evaluation, no fixed costs | |
| Route R1 (70%) | L only, no review, 96% accurate |
| Route R2 (30%) | L → G, 20% reviewed, 99% accurate; G changes the outcome on 40% of its calls |
| Budget | $0.01 per task, reject, checked before each call |

**Expected cost**

| Step | Working | Result |
|---|---|---|
| L call | 800 × 0.5 ÷ 1M + 50 × 2 ÷ 1M | $0.0005 |
| L per task with retries | 0.0005 × 1.05 | $0.000525 |
| G input | 2,000 × 5 ÷ 1M | $0.01 |
| G cache credit | 1,000 cached × (5 − 0.5) ÷ 1M | −$0.0045 |
| G output + reasoning | 100 × 20 ÷ 1M + 200 × 20 ÷ 1M | $0.006 |
| G call | 0.01 − 0.0045 + 0.006 | $0.0115 |
| R1 cost | | $0.000525 |
| R2 cost | 0.000525 + 0.0115 + 20% × $3.00 | $0.612025 |
| Expected per task | 0.7 × 0.000525 + 0.3 × 0.612025 = 0.0003675 + 0.1836075 | **$0.183975** |
| Daily | 0.183975 × 2,000 | **$367.95** |
| Monthly | 367.95 × 20 | **$7,359.00** |
| Annual | × 12 | **$88,308.00** |
| Accuracy | 0.7 × 96% + 0.3 × 99% | **96.9%** |
| Correct outcomes / month | 40,000 × 0.969 | 38,760 |
| **Cost per correct outcome** | 7,359 ÷ 38,760 | **$0.1898606…** |
| Human reviews / month | 0.3 × 20% × 40,000 | 2,400 |
| Larger-model calls / month | 0.3 × 40,000 | 12,000 |
| Model cost per 1,000 decisions | (0.000525 + 0.3 × 0.0115) × 1,000 | $3.975 |

**Decision value**

| Metric | Working | Result |
|---|---|---|
| Escalation rate | share of tasks that reach G | 30% |
| Larger-model cost per task | 0.3 × 0.0115 | $0.00345 |
| Changed decisions per task | 0.3 × 40% | 0.12 |
| Cost per changed decision | 0.00345 ÷ 0.12 | **$0.02875** |
| Avoidable model spend / month | 0.3 × 0.0115 × 60% unchanged × 40,000 | **$82.80** |
| Tokens on unchanged decisions / month | 0.3 × 2,300 × 60% × 40,000 | **16,560,000** |
| Larger calls avoided / month | (100% eligible − 30%) × 40,000 | 28,000 |

**Maximum and budget**

| Step | Working | Result |
|---|---|---|
| L worst call | 800 in (300 system + 500 user) + 100 out: 0.0004 + 0.0002 | $0.0006 (900 tokens) |
| L attempts | 1 call × (1 + 1 retry) | 2 → $0.0012, 1,800 tokens |
| G worst call (no cache credit) | 2,000 × 5 ÷ 1M + 200 out × 20 ÷ 1M + 500 reasoning × 20 ÷ 1M | $0.024 (2,700 tokens) |
| R2 automated worst | 0.0012 + 0.024 | $0.0252 |
| R2 review worst | 4 min × $45/h | $3.00 |
| Calculated maximum | 0.0252 + 3.00 | **$3.0252** |
| Budget (hard bound: pre-call reject, single call bounded) | min(0.0252, 0.01) + 3.00 | **Effective maximum $3.01** |
| Maximum tokens per task | 1,800 + 2,700 | **4,500** |

---

## Scenario C: larger-model-only baseline, compared with B

Same volume, review cost and model G as B. One route: 100% of tasks go to G, 20% reviewed, 99% accurate.

| Step | Working | Result |
|---|---|---|
| Cost per task | 0.0115 + 20% × $3.00 | $0.6115 |
| Monthly | 0.6115 × 2,000 × 20 | **$24,460.00** |
| Correct outcomes / month | 40,000 × 0.99 | 39,600 |
| Human reviews / month | 20% × 40,000 | 8,000 |
| Larger-model calls / month | | 40,000 |

**Compare, with C as the baseline and B as the alternative**

| Headline | Working | Result |
|---|---|---|
| Monthly savings | 24,460 − 7,359 | **$17,101.00** |
| Accuracy difference | 96.9% − 99% | **−2.1 points** |
| Human reviews avoided | 8,000 − 2,400 | **5,600 / month** |
| Larger-model calls avoided | 40,000 − 12,000 | **28,000 / month** |
| Correct outcomes difference | 38,760 − 39,600 | −840 / month |
| Cost per correct outcome given up | 17,101 ÷ 840 | **$20.358…** (B is cheaper but gets 840 fewer decisions right) |

With B as the baseline instead, C costs **$20.358… per additional correct outcome**.
