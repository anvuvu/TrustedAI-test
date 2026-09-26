# Offline ranking (test), K = 10, 590 users

Relevant: held-out rating >= 4.0. 95% bootstrap CIs over users.

| System | Recall@K | NDCG@K | Tail recall | Coverage | Pop. ratio | Sparse share |
|---|---|---|---|---|---|---|
| MostPopular | 0.065 [0.054, 0.076] | 0.084 [0.071, 0.096] | 0.000 [0.000, 0.000] | 0.018 | 3.43 | 0.000 |
| TopBayesian | 0.051 [0.041, 0.062] | 0.065 [0.055, 0.076] | 0.000 [0.000, 0.000] | 0.010 | 2.29 | 0.000 |
| UserKNN | 0.083 [0.072, 0.095] | 0.107 [0.094, 0.120] | 0.000 [0.000, 0.000] | 0.033 | 2.64 | 0.000 |
| EASE | 0.098 [0.085, 0.111] | 0.113 [0.100, 0.126] | 0.000 [0.000, 0.000] | 0.085 | 2.13 | 0.000 |
| ContentProfile | 0.008 [0.004, 0.011] | 0.009 [0.006, 0.013] | 0.008 [0.002, 0.017] | 0.084 | 0.18 | 0.558 |
| Blend | 0.097 [0.085, 0.111] | 0.113 [0.101, 0.127] | 0.003 [0.000, 0.009] | 0.074 | 2.27 | 0.000 |

Secondary relevance (rating - user mean >= 0.5):

| System | Recall@K | NDCG@K |
|---|---|---|
| MostPopular | 0.077 [0.062, 0.095] | 0.076 [0.064, 0.090] |
| TopBayesian | 0.060 [0.046, 0.074] | 0.057 [0.046, 0.067] |
| UserKNN | 0.096 [0.081, 0.112] | 0.099 [0.086, 0.113] |
| EASE | 0.104 [0.086, 0.121] | 0.097 [0.084, 0.112] |
| ContentProfile | 0.004 [0.002, 0.007] | 0.005 [0.003, 0.008] |
| Blend | 0.105 [0.087, 0.123] | 0.100 [0.087, 0.115] |

NDCG@K by train-history tercile (cut points [28.333333333333314, 79.0]):

| System | small | medium | large |
|---|---|---|---|
| MostPopular | 0.078 [0.057, 0.103] | 0.068 [0.052, 0.086] | 0.106 [0.086, 0.127] |
| TopBayesian | 0.056 [0.038, 0.077] | 0.049 [0.035, 0.065] | 0.090 [0.072, 0.111] |
| UserKNN | 0.080 [0.062, 0.099] | 0.094 [0.073, 0.114] | 0.148 [0.123, 0.175] |
| EASE | 0.109 [0.084, 0.135] | 0.087 [0.068, 0.107] | 0.142 [0.118, 0.169] |
| ContentProfile | 0.013 [0.005, 0.023] | 0.003 [0.001, 0.006] | 0.011 [0.006, 0.016] |
| Blend | 0.107 [0.084, 0.130] | 0.092 [0.072, 0.114] | 0.140 [0.114, 0.165] |

Paired differences:

| Comparison | Metric | Mean diff [CI] | Significant |
|---|---|---|---|
| Blend - EASE | recall | -0.001 [-0.011, 0.007] | False |
| Blend - EASE | ndcg | 0.000 [-0.008, 0.009] | False |
| EASE - MostPopular | recall | 0.034 [0.021, 0.047] | True |
| EASE - MostPopular | ndcg | 0.029 [0.016, 0.041] | True |

Qualitative:

**User 1** (152 ratings). Top rated: The Usual Suspects (1995): 5.0; Bottle Rocket (1996): 5.0; Billy Madison (1995): 5.0; Dumb & Dumber (Dumb and Dumber) (1994): 5.0; Star Wars: Episode IV - A New Hope (1977): 5.0

Blend top 5: Snatch (2000) (score 0.803, 72 ratings); The Silence of the Lambs (1991) (score 0.774, 251 ratings); The Godfather (1972) (score 0.768, 173 ratings); The Godfather: Part II (1974) (score 0.752, 111 ratings); Aliens (1986) (score 0.748, 102 ratings)

**User 15** (68 ratings). Top rated: Star Wars: Episode IV - A New Hope (1977): 5.0; The Shawshank Redemption (1994): 5.0; Forrest Gump (1994): 5.0; Schindler's List (1993): 5.0; Terminator 2: Judgment Day (1991): 5.0

Blend top 5: Blade Runner (1982) (score 0.84, 107 ratings); The Silence of the Lambs (1991) (score 0.795, 251 ratings); The Usual Suspects (1995) (score 0.788, 182 ratings); Inglourious Basterds (2009) (score 0.777, 73 ratings); Good Will Hunting (1997) (score 0.772, 118 ratings)

**User 30** (14 ratings). Top rated: Star Wars: Episode IV - A New Hope (1977): 5.0; The Shawshank Redemption (1994): 5.0; Star Wars: Episode V - The Empire Strikes Back (1980): 5.0; Raiders of the Lost Ark (Indiana Jones and the Raiders of the Lost Ark) (1981): 5.0; Star Wars: Episode VI - Return of the Jedi (1983): 5.0

Blend top 5: Blade Runner (1982) (score 0.889, 107 ratings); The Godfather (1972) (score 0.793, 173 ratings); The Silence of the Lambs (1991) (score 0.789, 251 ratings); Fight Club (1999) (score 0.789, 196 ratings); Saving Private Ryan (1998) (score 0.787, 173 ratings)
