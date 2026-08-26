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
    split = _split_credit(cleaned)
    if split is None:
        return cleaned  # no clear feature clause — leave the name alone
    primary, features = split
    if not features:
        return primary  # a dangling credit ("Artist feat.") — drop the empty marker
    return f"{primary} feat. {', '.join(features)}"


def place_feature_credit(title: str, artist: str) -> tuple[str, str]:
    """Move a featured-artist clause out of the artist field into the title (#56).

    The artist field should hold the **primary** artist only; a featured credit
    belongs in the title as ``(feat. X)`` — the convention every reference tagger
    (MusicBrainz/Picard, Apple Music, streaming) follows, and the one this repo
    already trusts through its Authority. #47 tidied the credit's *form* in place;
    this decides its *home* (ADR-0007). Operates on the ``(title, artist)`` pair and
    returns the rewritten pair.

    The artist is always #47-normalised first, so its in-place tidy still applies on
    every path. Then, when the artist carries a *clear* featured clause (a real
    primary before the marker):

    * If the title already names every one of those featured artists — Shazam
      sometimes supplies ``(feat. X)`` in the title itself — the credit is only
      **stripped** from the artist; never a second copy appended.
    * If the title carries no feature clause, the credit **moves** in as one
      ``(feat. X)`` and the artist is reduced to the primary.
    * If the title carries a *different* feature clause (naming someone the artist
      field does not), it is left untouched and the artist keeps its normalised
      credit — combining them would only guess, and a move is riskier than #47's
      tidy, so an untidy pair beats a wrong cross-field edit (the same bias as #47).
    """
    canonical = normalise_artist(artist)
    split = _split_credit(canonical)
    if split is None:
        return title, canonical  # no clear clause to move (bar the tidy already done)
    primary, features = split
    if not features:
        return title, primary  # defensive: a canonical artist never actually dangles
    if not title.strip():
        return title, canonical  # no title to place the credit in — leave both alone
    existing = _title_credit_names(title)
    if existing is None:
        return f"{title.rstrip()} (feat. {', '.join(features)})", primary
    if all(name.casefold() in existing for name in features):
        return title, primary  # title already carries the credit — just strip the artist
    return title, canonical  # the title names a different credit — leave both alone


def _tidy(text: str) -> str:
    """NFC-normalise and collapse whitespace — the always-safe canonicalisation."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def _split_credit(cleaned: str) -> tuple[str, list[str]] | None:
    """Split a tidied name into ``(primary, [featured...])``, or ``None`` when there
    is no *clear* feature clause to act on.

    ``None`` means "leave the name exactly as written": either it carries no feature
    marker, or the marker has no primary artist before it to anchor on ("feat. X"),
    where restructuring could only guess. Otherwise the primary (everything before
    the first marker) is returned verbatim — never split — with the de-duplicated
    featured segments; an empty featured list is a dangling marker ("Artist feat.").
    """
    parts = _FEATURE_RE.split(cleaned)
    if len(parts) == 1:
        return None  # no feature marker
    primary = _tidy(parts[0])
    if not primary:
        return None  # a marker but no primary artist to anchor on
    return primary, _unique_features(parts[1:], primary)


def _title_credit_names(title: str) -> set[str] | None:
    """The featured names a title already carries, case-folded — or ``None`` when the
    title has no clear feature clause of its own. Used to avoid writing a second copy
    of a credit Shazam already placed in the title. Parsed through the same
    ``_split_credit`` as the artist field, so both sides read a credit the same way."""
    split = _split_credit(_tidy(title))
    if split is None:
        return None
    _, features = split
    return {name.casefold() for name in features}


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
