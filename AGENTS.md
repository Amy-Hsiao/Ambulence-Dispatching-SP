# AGENTS.md

## Project goal
Implement a pure two-stage stochastic programming extensive-form model for post-disaster casualty evacuation using gurobipy.

## Scope for V1
- Implement only the plain two-stage SP extensive form.
- Do NOT implement DRO, Benders, L-shaped method, heuristics, warm-start, or custom algorithm.
- Objective uses scenario-probability-weighted expected second-stage cost.
- Use gurobipy directly.

## Modeling rules
- Sets: I, J, H, L, L_Amb, T, S.
- First-stage variables: X[j], V[j], U[j], Y[h,j].
- Second-stage variables are scenario-dependent.
- Treat t carefully. Use explicit period list and helper functions for t-1 and t-tau_l boundary cases.
- Minor casualties do not need hospital transfer variables.
- Add validation checks after solve: mass balance, nonnegative state variables, capacity constraints, and objective decomposition.

## Code quality
- Keep model building modular.
- Separate data generation, model construction, solving, and result validation.
- Add unit tests for tiny deterministic cases before scaling up.
- Every task must end with: tests run, summary of changes, known limitations.