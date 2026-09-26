# Agent scenarios: 24 scenarios, 29 turns

| Metric | Value |
|---|---|
| scenario_success | 0.708 |
| turn_success | 0.655 |
| tool_chain_accuracy | 1.000 |
| verifier_first_pass_rate | 0.862 |
| fallback_rate | 0.034 |
| constraint_satisfaction | 1.000 |
| state_persistence | 0.167 |
| mean_tool_calls | 1.586 |
| mean_tokens | 6468.448 |
| p50_latency_ms | 2601.600 |
| p95_latency_ms | 5820.620 |

| Scenario | Turn | tools | verifier_first_pass | no_fallback | no_title_echo | recommends | constraints | state |
|---|---|---|---|---|---|---|---|---|
| tonight_u1 | 1 | ok | ok | ok | ok | ok | ok |  |
| dark_thriller_u1 | 1 | ok | ok | ok | ok | ok | ok |  |
| peers_pulp_fiction_u1 | 1 | ok | ok | ok | ok | ok |  |  |
| why_that_u1 | 1 | ok | ok | ok | ok | ok | ok |  |
| why_that_u1 | 2 | ok | ok | ok | ok |  | ok |  |
| toy_story_no_animation_u1 | 1 | ok | ok | ok | ok | ok | ok | FAIL |
| blind_spot_u1 | 1 | ok | ok | ok | ok |  |  |  |
| tonight_u15 | 1 | ok | ok | ok | ok | ok | ok |  |
| dark_thriller_u15 | 1 | ok | ok | ok | ok | ok | ok |  |
| peers_pulp_fiction_u15 | 1 | ok | ok | ok | ok | ok |  |  |
| why_that_u15 | 1 | ok | ok | ok | ok | ok | ok |  |
| why_that_u15 | 2 | ok | ok | ok | FAIL |  | ok |  |
| toy_story_no_animation_u15 | 1 | ok | ok | ok | ok | ok | ok | FAIL |
| blind_spot_u15 | 1 | ok | ok | ok | ok |  |  |  |
| tonight_u30 | 1 | ok | FAIL | ok | ok | ok | ok |  |
| dark_thriller_u30 | 1 | ok | ok | ok | ok | ok | ok |  |
| peers_pulp_fiction_u30 | 1 | ok | ok | ok | ok | ok |  |  |
| why_that_u30 | 1 | ok | FAIL | FAIL | ok | ok | ok |  |
| why_that_u30 | 2 | ok | FAIL | ok | ok |  | ok |  |
| toy_story_no_animation_u30 | 1 | ok | ok | ok | ok | ok | ok | ok |
| blind_spot_u30 | 1 | ok | ok | ok | ok |  |  |  |
| matrix_absent_u15 | 1 | ok | ok | ok | ok | ok |  |  |
| ambiguous_psycho_u15 | 1 | ok | ok | ok | ok | ok |  |  |
| niche_peers_u30 | 1 | ok | FAIL | ok | ok | ok |  |  |
| own_knowledge_u1 | 1 | ok | ok | ok | ok | ok |  |  |
| no_animation_persists_u15 | 1 | ok | ok | ok | ok | ok | ok | FAIL |
| no_animation_persists_u15 | 2 | ok | ok | ok | ok | ok | ok | FAIL |
| no_animation_persists_u15 | 3 | ok | ok | ok | ok | ok | ok | FAIL |
| unknown_user | 1 | ok | ok | ok | ok | ok |  |  |

Manual rubric: fill `rubric_sheet.csv` (0–2 per criterion), then run `movie-agent report-tables`.
