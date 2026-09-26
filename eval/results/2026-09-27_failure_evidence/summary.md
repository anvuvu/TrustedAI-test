# Failure evidence (engine only, all ratings, frozen config)

## Case 1: "I liked Toy Story but I'm tired of animated movies" (seed 1, exclude Animation)

User 1, weights {'seed': 0.5, 'cf': 0.3, 'quality': 0.2}:

1. Gremlins (1984) — Comedy, Horror; contributions {'seed': 0.407, 'cf': 0.175, 'quality': 0.0}; 41 ratings, mean 3.38
2. Babe (1995) — Children, Drama; contributions {'seed': 0.275, 'cf': 0.237, 'quality': 0.0}; 128 ratings, mean 3.65
3. Snatch (2000) — Comedy, Crime, Thriller; contributions {'seed': 0.085, 'cf': 0.241, 'quality': 0.185}; 93 ratings, mean 4.16
4. The Santa Clause (1994) — Comedy, Drama, Fantasy; contributions {'seed': 0.415, 'cf': 0.089, 'quality': 0.0}; 81 ratings, mean 3.2
5. Santa Claus: The Movie (1985) — Adventure, Children, Fantasy; contributions {'seed': 0.5, 'cf': 0.0, 'quality': 0.0}; 4 ratings, mean 2.25

User 15, weights {'seed': 0.5, 'cf': 0.3, 'quality': 0.2}:

1. E.T. the Extra-Terrestrial (1982) — Children, Drama, Sci-Fi; contributions {'seed': 0.345, 'cf': 0.254, 'quality': 0.0}; 122 ratings, mean 3.77
2. Snatch (2000) — Comedy, Crime, Thriller; contributions {'seed': 0.068, 'cf': 0.263, 'quality': 0.18}; 93 ratings, mean 4.16
3. Toys (1992) — Comedy, Fantasy; contributions {'seed': 0.5, 'cf': 0.0, 'quality': 0.0}; 20 ratings, mean 2.38
4. Santa Claus: The Movie (1985) — Adventure, Children, Fantasy; contributions {'seed': 0.497, 'cf': 0.0, 'quality': 0.0}; 4 ratings, mean 2.25
5. Jingle All the Way (1996) — Children, Comedy; contributions {'seed': 0.495, 'cf': 0.0, 'quality': 0.0}; 18 ratings, mean 2.86

`why-not` for user 15 (same request):

```
RANKED_BELOW: The Princess Bride (1987)
  mode: seed
  n_ratings: 142
  genres: ['Action', 'Adventure', 'Comedy', 'Fantasy', 'Romance']
  rank: 31
  k: 5
  score: 0.454
  contributions: {'seed': 0.0, 'cf': 0.258, 'quality': 0.196}
  rank_k_movie: Jingle All the Way (1996)
  rank_k_score: 0.495
  rank_k_contributions: {'seed': 0.495, 'cf': 0.0, 'quality': 0.0}
  largest_gap_feature: seed
  no_cf_signal: False
```

```
RANKED_BELOW: Big (1988)
  mode: seed
  n_ratings: 91
  genres: ['Comedy', 'Drama', 'Fantasy', 'Romance']
  rank: 9
  k: 5
  score: 0.49
  contributions: {'seed': 0.482, 'cf': 0.008, 'quality': 0.0}
  rank_k_movie: Jingle All the Way (1996)
  rank_k_score: 0.495
  rank_k_contributions: {'seed': 0.495, 'cf': 0.0, 'quality': 0.0}
  largest_gap_feature: seed
  no_cf_signal: False
```

```
RANKED_BELOW: Home Alone (1990)
  mode: seed
  n_ratings: 116
  genres: ['Children', 'Comedy']
  rank: 144
  k: 5
  score: 0.271
  contributions: {'seed': 0.112, 'cf': 0.159, 'quality': 0.0}
  rank_k_movie: Jingle All the Way (1996)
  rank_k_score: 0.495
  rank_k_contributions: {'seed': 0.495, 'cf': 0.0, 'quality': 0.0}
  largest_gap_feature: seed
  no_cf_signal: False
```

```
RANKED_BELOW: Jumanji (1995)
  mode: seed
  n_ratings: 110
  genres: ['Adventure', 'Children', 'Fantasy']
  rank: 171
  k: 5
  score: 0.233
  contributions: {'seed': 0.015, 'cf': 0.217, 'quality': 0.0}
  rank_k_movie: Jingle All the Way (1996)
  rank_k_score: 0.495
  rank_k_contributions: {'seed': 0.495, 'cf': 0.0, 'quality': 0.0}
  largest_gap_feature: seed
  no_cf_signal: False
```

## Case 2: "I want a dark psychological thriller with a twist" (user 15)

1. Donnie Darko (2001) — 109 ratings, confidence high []; contributions {'query': 0.498, 'cf': 0.165, 'quality': 0.101}; matched passage: "Monnitoff  about time travel after Frank brings up the topic, and is given the book The Philosophy of Time Travel, written by Roberta Sparrow , a former science…"
2. Psycho (1960) — 83 ratings, confidence high []; contributions {'query': 0.546, 'cf': 0.0, 'quality': 0.133}; matched passage: "The plot revolves around a young man who prefers a lonely life. He begins to a stalk a television anchor named Pavana and starts interacting with her through hi…"
3. Twelve Monkeys (a.k.a. 12 Monkeys) (1995) — 177 ratings, confidence high []; contributions {'query': 0.303, 'cf': 0.183, 'quality': 0.118}; matched passage: "A Greek chorus narrates and comments -- and Oedipus, Jocasta, Tiresias, and Cassandra sometimes directly intervene -- in this modern fable. Sportswriter Lenny W…"
4. Darkness Falls (2003) — 4 ratings, confidence low ['few_ratings']; contributions {'query': 0.6, 'cf': 0.0, 'quality': 0.0}; matched passage: "He soon realizes that the story of Matilda Dixon is not just a fable when he sees her in his room. Realizing that light is her weakness, he shines a flashlight …"
5. Color of Night (1994) — 7 ratings, confidence high []; contributions {'query': 0.597, 'cf': 0.0, 'quality': 0.0}; matched passage: "* Sondra Dorio  is a nymphomaniac and kleptomaniac. She stabbed her father with a knife and fork and one of her husbands died of unnatural causes. * Buck  is a …"

## Case 3: "because you rated" includes low ratings (user 15, personal mode)

1. Blade Runner (1982) — because you rated: Alien (1979) (rated 5.0, EASE contribution 0.0219); Star Wars: Episode V - The Empire Strikes Back (1980) (rated 5.0, EASE contribution 0.0183)
2. The Silence of the Lambs (1991) — because you rated: Pulp Fiction (1994) (rated 4.0, EASE contribution 0.0521); The Shawshank Redemption (1994) (rated 5.0, EASE contribution 0.0509)
3. Braveheart (1995) — because you rated: Saving Private Ryan (1998) (rated 3.5, EASE contribution 0.0423); Terminator 2: Judgment Day (1991) (rated 5.0, EASE contribution 0.0422)
4. Inglourious Basterds (2009) — because you rated: Inception (2010) (rated 3.5, EASE contribution 0.035); Django Unchained (2012) (rated 1.0, EASE contribution 0.0326)
5. Good Will Hunting (1997) — because you rated: The Shawshank Redemption (1994) (rated 5.0, EASE contribution 0.0271); Fight Club (1999) (rated 2.5, EASE contribution 0.0202)
