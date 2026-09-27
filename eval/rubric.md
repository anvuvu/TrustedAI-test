# Agent answer rubric (design §9.4)

Grade every turn in `rubric_sheet.csv` of an `eval agent` run, 0–2 per criterion. Grade the
rendered answer against the tool outputs in the matching transcript, not against what you
know about the movies.

| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| **grounded** | States a fact (number, rating, plot point, opinion of other users) not in the tool outputs, or uses outside movie knowledge | Everything is supported, but one claim is a loose paraphrase that overstates the data | Every claim is traceable to a tool output of this or the previous turn |
| **relevant** | Does not answer the question, or ignores a stated constraint | Answers, but misses part of the request (e.g. one of two constraints, or the "why") | Answers exactly what was asked, respecting every constraint |
| **specific** | Generic reasons ("you might enjoy this") | Some reasons name the data (a genre, a rating) but others are generic | Each recommendation or claim names its evidence: a history movie, a peer statistic, a plot passage |
| **honest** | Hides low confidence, missing data or an absent movie; or refuses when the data could answer | Mentions uncertainty but vaguely, without the reason | States low confidence or absence with its reason (e.g. "only 2 similar users rated it") and does not overclaim |

Notes for grading:

- A correct refusal ("the dataset does not contain directors") scores 2 on grounded and honest.
- For clarification questions (ambiguous title), grade relevant = 2 if the question is the
  right one and lists the candidates.
- Record anything surprising in `docs/notes.md` with a root-cause code (design §8.3).
