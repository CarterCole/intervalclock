from fractions import Fraction as F
from unittest import mock

import pytest

from intervalclock import Registry, alias, from_cron, full_alias, phase
from intervalclock import words as words_mod


def test_alias_deterministic():
    c = phase(F(1, 3), 3, k=2)
    assert alias(c) == alias(c)
    assert len(alias(c).split("-")) == 4
    assert len(alias(c, words=6).split("-")) == 6
    assert full_alias(c)[:4] == alias(c).split("-")


def test_alias_words_are_in_wordlist():
    for w in full_alias(from_cron("*/5 * * * *")):
        assert w in words_mod._WORD_INDEX


def test_registry_mint_and_resolve():
    reg = Registry()
    c = phase(F(1, 3), 3, k=2)
    a = reg.mint(c)
    assert reg.resolve(a) == c
    assert reg.mint(c) == a  # idempotent


def test_registry_prefix_resolution():
    reg = Registry()
    c = phase(F(1, 7), 2)
    reg.mint(c)
    assert reg.resolve(alias(c, words=5)) == c  # longer prefix still resolves


def test_forced_collision_mints_longer_prefix():
    reg = Registry()
    a = phase(F(1, 3), 3, k=0)
    b = phase(F(1, 3), 3, k=1)
    fake_a = ["apple", "banana", "cherry", "dragon", "eagle", "fabric",
              "gadget", "habit", "icon", "jacket", "kangaroo"]
    fake_b = ["apple", "banana", "cherry", "dragon", "else", "fame",
              "gap", "hair", "ice", "jazz", "keen"]
    with mock.patch.object(words_mod, "full_alias",
                           side_effect=lambda x: fake_a if x == a else fake_b):
        first = reg.mint(a)
        second = reg.mint(b)
    assert first == "apple-banana-cherry-dragon"
    assert second == "apple-banana-cherry-dragon-else"  # newcomer takes 5 words
    # existing aliases never change: the short alias still resolves to a,
    # and the newcomer's longer alias resolves to b
    assert reg.resolve(first) == a
    assert reg.resolve(second) == b
    assert reg.resolve("-".join(fake_a[:5])) == a  # longer prefix of a works too


def test_unknown_and_short_aliases_rejected():
    reg = Registry()
    with pytest.raises(ValueError):
        reg.resolve("only-three-words")
    with pytest.raises(KeyError):
        reg.resolve("zzzz-not-a-word-nope")
