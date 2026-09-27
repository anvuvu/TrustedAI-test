# Honesty tests

## Explanation fidelity (engine drivers, train fit)

- pairs: 30, with a history-movie driver: 30
- faithful when the top driver is removed: 0.27 [0.10, 0.43]
- 'faithful' when a random history movie is removed (control): 0.00 [0.00, 0.00]
- driver signals: {'cf': 30}
- mean score drop, driver removed: 0.091 [0.043, 0.151]; control: 0.007 [-0.001, 0.016]

## Perturbation (peer question, ratings flipped to 5.5 - r)

- pairs: 3; data direction flipped in 3
- verifier first pass: 0.6666666666666666
- stance and extra facts: graded by hand in `perturbation_sheet.csv`

## LLM attribution

- answers naming the engine's top driver movie: 1.0 (n = 10); match judged by hand in `attribution_sheet.csv`
