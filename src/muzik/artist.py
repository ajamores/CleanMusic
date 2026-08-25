"""Artist-name normalisation for the artist Tag written into a Track (spec US#26, #47).

A conservative canonicalisation applied to the artist name just before it is
written, so a library doesn't accumulate ``Artist ft. X`` / ``Artist feat. X`` /
``Artist (feat. X)`` variants of one artist. The guiding rule from the ticket: a
wrong "normalisation" that merges two *distinct* artists is worse than an
untidy-but-correct name — so this makes only the changes it can make **safely**,
and leaves a name alone when unsure.

What it does, and deliberately does **not** do:

* **Whitespace** — collapse internal runs and trim. Always safe.
* **Unicode form** — NFC-normalise, so the same visible name typed with a combining
  accent vs a pre-composed one is written identically ("Beyoncé" either way). It
  does **not** *strip* diacritics or fold case: ``Beyonce`` (no accent) and
  ``BEYONCÉ`` are left as they are, because deciding which spelling is "right" needs
  a known-artist catalogue — guessing risks merging two spellings a human entered
  deliberately. That aggressive case/diacritic folding, and romanisation of
  native-script names, are deferred (see ``docs/adr/0007``).
* **Feature credits** — the one structural change. Unify every ``ft`` / ``ft.`` /
  ``feat`` / ``feat.`` / ``featuring`` marker (bracketed or not, any case) to a
  single ``feat.`` form, and de-duplicate repeated whole credits
  (``A ft. X feat. X`` → ``A feat. X``). The **primary** artist — everything before
  the first feature marker — is never split or reordered, so a duo like
  "Simon & Garfunkel" is untouched; only the featured tail is restructured, and even
  there a featured segment is never split on its own internal commas, so
  "Tyler, The Creator" survives as one credit.
"""

from __future__ import annotations

import re
import unicodedata

#: A feature marker — feat / feat. / ft / ft. / featuring — as a standalone word,
#: optionally wrapped by an opening bracket, with surrounding whitespace. Splitting a
#: name on this yields the primary artist (before the first marker) then each
#: featured segment. Word boundaries keep it off the "ft" *inside* "Daft Punk".
_FEATURE_RE = re.compile(r"\s*[\(\[\{]?\s*\b(?:feat|ft|featuring)\b\.?\s*", re.IGNORECASE)

#: Bracket characters left clinging to a featured segment once the marker that
#: introduced it is split away ("… feat. X)" → "X)"); stripped from each end.
_BRACKET_CHARS = "()[]{}"


def normalise_artist(name: str) -> str:
    """Canonicalise an artist name for writing (spec US#26, #47).

    Conservative: unifies feature-credit form and de-duplicates repeated credits,
    NFC-normalises, and collapses whitespace — but never folds case or strips
    diacritics, and never splits or reorders the primary artist. A name with no
    feature marker comes back unchanged bar whitespace/NFC.
    """
    cleaned = _tidy(name)
    if not cleaned:
        return cleaned
    parts = _FEATURE_RE.split(cleaned)
    if len(parts) == 1:
        return cleaned  # no feature marker — leave the name alone
    primary = _tidy(parts[0])
    if not primary:
        return cleaned  # a marker but no primary artist ("feat. X") — don't restructure
    features = _unique_features(parts[1:], primary)
    if not features:
        return primary  # a dangling credit ("Artist feat.") — drop the empty marker
    return f"{primary} feat. {', '.join(features)}"


def _tidy(text: str) -> str:
    """NFC-normalise and collapse whitespace — the always-safe canonicalisation."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def _unique_features(segments: list[str], primary: str) -> list[str]:
    """The featured artists — trimmed of stray brackets, de-duplicated case-insensitively.

    Each segment is one featured credit as written (possibly several names joined by
    the artist's own commas/``&``); it is kept whole — never split on internal
    punctuation — so "Tyler, The Creator" survives. A segment equal (case-fold) to
    one already kept, or to the primary artist, is dropped: that is how a duplicated
    ``feat. X feat. X`` collapses, and how ``Drake feat. Drake`` falls back to
    ``Drake``.
    """
    seen = {primary.casefold()}
    unique: list[str] = []
    for segment in segments:
        credit = _tidy(segment).strip(_BRACKET_CHARS).strip()
        key = credit.casefold()
        if credit and key not in seen:
            seen.add(key)
            unique.append(credit)
    return unique
