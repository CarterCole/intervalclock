"""Word aliases: what3words-style names for sharing and speech.

Derivation: BLAKE2b(canonical binary ID, digest_size=16, person="ic-alias-v1")
→ 128 bits → 11 words from the frozen BIP-39 English list (2048 words,
11 bits each; the top 121 bits are used). The full 11-word alias is the
identity; the *shareable* alias is its shortest prefix (≥ 4 words) unique in
a registry, git-short-hash style: on a later collision the newcomer takes a
longer prefix — existing aliases never change.

Aliases are one-way by design (a hash of an unbounded ID space into fixed
tuples cannot be injective); alias → ID resolution requires a registry
(v1: local SQLite). The structured math name remains the registry-free
ground truth.
"""

from __future__ import annotations

import hashlib
import sqlite3
from importlib import resources
from pathlib import Path

from .encode import encode, decode

__all__ = ["full_alias", "alias", "Registry", "WORDLIST_VERSION"]

WORDLIST_VERSION = "bip39-english-v1"
_PERSON = b"ic-alias-v1"
_MIN_WORDS = 4
_TOTAL_WORDS = 11


def _wordlist() -> list[str]:
    text = (
        resources.files("intervalclock").joinpath("_wordlist_v1.txt").read_text()
    )
    words = text.split()
    if len(words) != 2048:
        raise RuntimeError("corrupt wordlist: expected 2048 words")
    return words


_WORDS = _wordlist()
_WORD_INDEX = {w: i for i, w in enumerate(_WORDS)}


def full_alias(x) -> list[str]:
    """The full 11-word alias of a TimeSet (deterministic, registry-free)."""
    h = hashlib.blake2b(encode(x), digest_size=16, person=_PERSON).digest()
    n = int.from_bytes(h, "big") >> (128 - _TOTAL_WORDS * 11)
    out = []
    for i in range(_TOTAL_WORDS):
        shift = (_TOTAL_WORDS - 1 - i) * 11
        out.append(_WORDS[(n >> shift) & 0x7FF])
    return out


def alias(x, words: int = _MIN_WORDS) -> str:
    """A hyphen-joined alias prefix (no registry uniqueness check)."""
    if not _MIN_WORDS <= words <= _TOTAL_WORDS:
        raise ValueError(f"alias length must be {_MIN_WORDS}–{_TOTAL_WORDS} words")
    return "-".join(full_alias(x)[:words])


class Registry:
    """Local SQLite alias registry: mint shortest-unique prefixes, resolve.

    The registry format is deliberately simple so shared/federated
    registries can adopt it: one row per ID, storing the full alias and the
    prefix length handed out at mint time.
    """

    def __init__(self, path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(path))
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS aliases ("
            " full_alias TEXT PRIMARY KEY,"
            " id_bytes BLOB NOT NULL,"
            " prefix_len INTEGER NOT NULL,"
            " wordlist TEXT NOT NULL)"
        )

    def mint(self, x) -> str:
        """Register x and return its shareable alias.

        The prefix is the shortest (≥ 4 words) not shared by any *other*
        registered full alias. Existing entries keep their prefixes.
        """
        words = full_alias(x)
        full = "-".join(words)
        row = self.db.execute(
            "SELECT prefix_len FROM aliases WHERE full_alias = ?", (full,)
        ).fetchone()
        if row:
            return "-".join(words[: row[0]])
        n = _MIN_WORDS
        while n < _TOTAL_WORDS:
            prefix = "-".join(words[:n])
            clash = self.db.execute(
                "SELECT 1 FROM aliases WHERE full_alias LIKE ? AND full_alias != ?",
                (prefix + "-%", full),
            ).fetchone()
            if not clash:
                break
            n += 1
        self.db.execute(
            "INSERT INTO aliases VALUES (?, ?, ?, ?)",
            (full, encode(x), n, WORDLIST_VERSION),
        )
        self.db.commit()
        return "-".join(words[:n])

    def resolve(self, alias_text: str):
        """Alias (any prefix ≥ 4 words) → TimeSet, or raise."""
        words = alias_text.strip().lower().split("-")
        if len(words) < _MIN_WORDS:
            raise ValueError(f"aliases have at least {_MIN_WORDS} words")
        for w in words:
            if w not in _WORD_INDEX:
                raise KeyError(f"{w!r} is not in the wordlist")
        prefix = "-".join(words)
        rows = self.db.execute(
            "SELECT id_bytes, full_alias, prefix_len FROM aliases "
            "WHERE full_alias = ? OR full_alias LIKE ?",
            (prefix, prefix + "-%"),
        ).fetchall()
        if not rows:
            raise KeyError(f"alias {alias_text!r} not in registry")
        if len(rows) > 1:
            # Existing aliases never change: if the query is exactly the
            # alias minted for one entry, that entry wins over later
            # entries that merely share the prefix.
            minted = [
                r for r in rows
                if "-".join(r[1].split("-")[: r[2]]) == prefix
            ]
            if len(minted) == 1:
                return decode(minted[0][0])
            raise KeyError(f"alias {alias_text!r} is ambiguous; add words")
        return decode(rows[0][0])
