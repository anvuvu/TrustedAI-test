# Offline ranking (val), K = 10, 535 users

Relevant: held-out rating >= 4.0. 95% bootstrap CIs over users.

| System | Recall@K | NDCG@K | Tail recall | Coverage | Pop. ratio | Sparse share |
|---|---|---|---|---|---|---|
| MostPopular | 0.090 [0.072, 0.107] | 0.064 [0.052, 0.077] | 0.000 [0.000, 0.000] | 0.015 | 3.49 | 0.000 |
| TopBayesian | 0.052 [0.039, 0.066] | 0.040 [0.031, 0.051] | 0.000 [0.000, 0.000] | 0.009 | 2.29 | 0.000 |
| UserKNN | 0.098 [0.081, 0.117] | 0.081 [0.066, 0.096] | 0.000 [0.000, 0.000] | 0.030 | 2.63 | 0.000 |
| EASE | 0.147 [0.125, 0.171] | 0.102 [0.088, 0.118] | 0.000 [0.000, 0.000] | 0.078 | 2.18 | 0.000 |
| ContentProfile | 0.008 [0.003, 0.014] | 0.006 [0.002, 0.011] | 0.011 [0.001, 0.026] | 0.084 | 0.17 | 0.595 |
| Blend | 0.141 [0.120, 0.164] | 0.099 [0.084, 0.114] | 0.000 [0.000, 0.000] | 0.066 | 2.33 | 0.000 |

Secondary relevance (rating - user mean >= 0.5):

| System | Recall@K | NDCG@K |
|---|---|---|
| MostPopular | 0.100 [0.077, 0.124] | 0.065 [0.050, 0.083] |
| TopBayesian | 0.057 [0.040, 0.076] | 0.042 [0.030, 0.056] |
| UserKNN | 0.119 [0.093, 0.143] | 0.088 [0.069, 0.107] |
| EASE | 0.158 [0.129, 0.185] | 0.099 [0.080, 0.116] |
| ContentProfile | 0.012 [0.004, 0.023] | 0.008 [0.003, 0.014] |
| Blend | 0.159 [0.130, 0.191] | 0.097 [0.080, 0.115] |

NDCG@K by train-history tercile (cut points [28.0, 76.0]):

| System | small | medium | large |
|---|---|---|---|
| MostPopular | 0.076 [0.051, 0.105] | 0.060 [0.038, 0.084] | 0.056 [0.041, 0.074] |
| TopBayesian | 0.053 [0.032, 0.076] | 0.024 [0.012, 0.039] | 0.043 [0.029, 0.057] |
| UserKNN | 0.098 [0.070, 0.128] | 0.073 [0.050, 0.099] | 0.070 [0.052, 0.089] |
| EASE | 0.133 [0.101, 0.167] | 0.094 [0.070, 0.118] | 0.079 [0.061, 0.098] |
| ContentProfile | 0.010 [0.000, 0.024] | 0.002 [0.000, 0.004] | 0.005 [0.002, 0.009] |
| Blend | 0.137 [0.105, 0.174] | 0.088 [0.062, 0.112] | 0.070 [0.053, 0.087] |

Paired differences:

| Comparison | Metric | Mean diff [CI] | Significant |
|---|---|---|---|
| Blend - EASE | recall | -0.006 [-0.025, 0.012] | False |
| Blend - EASE | ndcg | -0.003 [-0.016, 0.009] | False |
| EASE - MostPopular | recall | 0.057 [0.036, 0.078] | True |
| EASE - MostPopular | ndcg | 0.038 [0.024, 0.054] | True |

EASE lambda (NDCG@K):

- 100.0: 0.092 [0.078, 0.107]
- 300.0: 0.098 [0.084, 0.112]
- 500.0: 0.102 [0.088, 0.117]
- 1000.0: 0.101 [0.087, 0.116]

Personal-mode cf weight (NDCG@K overall / users under the sparse threshold):

- cf 0.5 {'cf': 0.5, 'content': 0.3999999999999999, 'quality': 0.1}: 0.080 [0.067, 0.095] / 0.103 [0.071, 0.134]
- cf 0.6 {'cf': 0.6, 'content': 0.29999999999999993, 'quality': 0.1}: 0.093 [0.079, 0.109] / 0.124 [0.096, 0.157]
- cf 0.7 {'cf': 0.7, 'content': 0.19999999999999996, 'quality': 0.1}: 0.099 [0.084, 0.114] / 0.139 [0.106, 0.174]
- cf 0.8 {'cf': 0.8, 'content': 0.09999999999999987, 'quality': 0.1}: 0.100 [0.086, 0.116] / 0.135 [0.103, 0.171]
- cf 0.9 {'cf': 0.9, 'content': 0.0, 'quality': 0.1}: 0.103 [0.088, 0.119] / 0.133 [0.100, 0.165]

Qualitative:

**User 1** (136 ratings). Top rated: The Usual Suspects (1995): 5.0; Bottle Rocket (1996): 5.0; Billy Madison (1995): 5.0; Dumb & Dumber (Dumb and Dumber) (1994): 5.0; Star Wars: Episode IV - A New Hope (1977): 5.0

Blend top 5: Pulp Fiction (1994) (score 0.943, 258 ratings); Back to the Future (1985) (score 0.748, 141 ratings); Terminator 2: Judgment Day (1991) (score 0.746, 187 ratings); The Silence of the Lambs (1991) (score 0.741, 240 ratings); Groundhog Day (1993) (score 0.731, 112 ratings)

**User 15** (61 ratings). Top rated: Star Wars: Episode IV - A New Hope (1977): 5.0; The Shawshank Redemption (1994): 5.0; Forrest Gump (1994): 5.0; Schindler's List (1993): 5.0; Terminator 2: Judgment Day (1991): 5.0

Blend top 5: Blade Runner (1982) (score 0.844, 96 ratings); The Silence of the Lambs (1991) (score 0.795, 240 ratings); The Usual Suspects (1995) (score 0.787, 173 ratings); Good Will Hunting (1997) (score 0.776, 111 ratings); Inglourious Basterds (2009) (score 0.77, 60 ratings)

**User 30** (12 ratings). Top rated: Star Wars: Episode IV - A New Hope (1977): 5.0; The Shawshank Redemption (1994): 5.0; Star Wars: Episode V - The Empire Strikes Back (1980): 5.0; Raiders of the Lost Ark (Indiana Jones and the Raiders of the Lost Ark) (1981): 5.0; Star Wars: Episode VI - Return of the Jedi (1983): 5.0

Blend top 5: Blade Runner (1982) (score 0.892, 96 ratings); The Godfather (1972) (score 0.797, 164 ratings); The Silence of the Lambs (1991) (score 0.792, 240 ratings); Fight Club (1999) (score 0.792, 184 ratings); Forrest Gump (1994) (score 0.782, 286 ratings)
