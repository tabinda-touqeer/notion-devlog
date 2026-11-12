# Engineering Task Reference Template

Use this template as the standard blueprint for any bug fix, feature, or optimization log.

---

### Callout
> 🗣️ **Overview**: [1-2 sentences summarizing the goal, the bug/feature, and the resolution].

---

### Heading 2: 1. System Context & The Bug / Requirement
*(Note: Write so any reviewer with zero prior knowledge of this repository understands what component this touches, what triggered the change, and never insert developer-to-agent chat instructions).*

* **System Context**: [Plain-English description of what this endpoint, background worker, database table, or module does].
* **End-User Query / Trigger**: `"[Exact product input, API payload, or engineering trigger]"`
* **Problem / Impact**: [Concrete issue encountered].

---

### Heading 2: 2. Behavioral Impact (Before vs. After)
* **Before (System Behavior With Issue)**: [How the system actually behaved beforehand — exact wrong output, error code, latency/query count, race condition, or security exposure].
* **After (System Behavior Now)**: [How the system behaves now across normal requests, invalid inputs, and edge cases].

---

### Heading 2: 3. Why Did This Happen? (Root Cause Analysis)
Tracing the execution flow in `[file_path]`, we discovered the following root causes:
* **Root Cause 1 - [Vocabulary / Mapping Gap]**: [Detailed explanation of why the input or component failed].
* **Root Cause 2 - [Logic / Lifecycle Gap]**: [Explanation of edge cases or missing constraints].

---

### Heading 2: 4. What Was Fixed & How It Was Implemented
We resolved this across multiple layers:
* **Layer 1 - [Data / Schema / State Change]**: In `[file_path]`, [exact implementation change].
* **Layer 2 - [Algorithm / Guardrail]**: [Added validation/caching/rate-limit logic with exact thresholds]:

```python
# Code guardrail snippet
```

* **Layer 3 - [Fallback / Audit Logging]**: [Updated fallback behavior and structured logging].

---

### Heading 2: 5. Why This Architectural Decision?
* **[Trade-off 1 - Latency / Security]**: [Why this design was chosen over alternatives].
* **[Trade-off 2 - Maintainability]**: [How future developers should understand and extend this behavior].

---

### Heading 2: 6. Verification & Testing
* **Automated / Unit Tests**: [Tests executed covering valid, invalid, and edge cases]. Result: [Observed pass rate / assertions].
* **End-to-End Verification**: [Confirmed exact HTTP statuses, DB query counts, or payloads].

---

### Heading 2: 7. Git & Effort Traceability
*(Must reference an actual committed Git SHA — NEVER 'Pending commit')*
* **[Main Branch]**: Commit `[short_sha]` on `[branch_name]`.
* **[Modified Files]**: `[file_list]`.
* **[Estimated Effort (Senior Engineer Benchmark)]**: `[X.XX] hrs ([Xh Ym])` — realistic end-to-end effort for a senior engineer familiar with the codebase (investigation, implementation, verification, and git sync).

