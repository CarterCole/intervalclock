# future/ — specified but not yet implemented

The FFT layer (PROTOCOL.md §9) and schedule inference (§10) now ship in
`python/src/intervalclock/dsp.py` and `infer.py`; type 0x8 and the text
form `f:` are claimed. The duration layer (§2.5) ships in `duration.py`,
claiming types 0xA–0xC and the text forms `d:` and `n:`.

What remains reserved:

- **Proleptic-UTC cron → PSet** (§11.2): under an idealized lens that
  ignores future leap seconds, any UTC cron is periodic with the 400-year
  Gregorian period of 12 622 780 800 s. Optional by design — it trades an
  honest "cron is symbolic" for a period a user may prefer to reason with.
- **Binary types 0xD–0xF** and the rest of the header nibble space.
- **Nominal steps below a day** — "next Tuesday", "the first business day
  after" and other named recurrences are cron's job today; whether they
  deserve a nominal-step spelling of their own is open.
