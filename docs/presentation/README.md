# Presentation (assembled by Habib Hasanov)

| File | Content |
|---|---|
| `group4_deck.pptx` | the shared 15-slide deck (20-minute slot); speaker pill on each slide, notes per slide |
| `build_deck.js` | generates the deck (`make deck`); chart numbers are read from `results/summary/*.csv` |
| `apply_theme.py`, `theme.json` | writes the group palette and fonts into the deck's theme |
| `p2_consistency_talk.md` | Person 2's slide contents, notes and demo commands |
| `hasanov_talk.md` | Habib Hasanov's notes, demo commands and Q&A answers |

Slides 3-4 Person 1, 5-7 Person 2, 8-10 Person 3, 11-15 Habib Hasanov. Each presenter owns
their slides: edit `build_deck.js` (or the .pptx) and replace "Person 1/2/3" with names before
the talk. Rebuild after `make figures` / `make exp2-report` so the charts use the latest data.
