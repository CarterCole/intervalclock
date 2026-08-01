# future/ — v2 modules, specified but not yet implemented

These are reserved by the protocol (PROTOCOL.md §9–§10) and by the encoding
(type 0x8, text form `f:`):

- **dsp.py** — `from_fft(X, fs, t0, phase_quantum_turns)` naming every bin as
  an eternal phase class (positive-half-cycle mapping), `nyquist(fs)`,
  `alias_freq`/`alias_class` (exact rational folding), windowed-class
  provenance.
- **infer.py** — `infer(timestamps, min_resolution, top_k)`: epoch folding
  over rational + calendar candidate periods, Rayleigh-test scoring,
  `to_cron()` on winners. The inverse operation: observed timestamps → named
  schedules ("this feed publishes every Tuesday ~09:00").
