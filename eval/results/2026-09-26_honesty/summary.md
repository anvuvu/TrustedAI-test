# Honesty tests

## Explanation fidelity (engine drivers, train fit)

- pairs: 30, with a history-movie driver: 30
- faithful when the top driver is removed: 0.07 [0.00, 0.17]
- 'faithful' when a random history movie is removed (control): 0.00 [0.00, 0.00]
- driver signals: {'cf': 25, 'content': 5}

## Perturbation (peer question, ratings flipped to 5.5 - r)

- pairs: 3; data direction flipped in 3
- verifier first pass: 0.5
- stance and extra facts: graded by hand in `perturbation_sheet.csv`

## LLM attribution

- answers naming the engine's top driver movie: 0.7 (n = 10); match judged by hand in `attribution_sheet.csv`
