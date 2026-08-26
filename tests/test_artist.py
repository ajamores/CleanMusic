"""Direct unit tests for the artist-name normaliser (spec US#26, #47).

This is exactly the fiddly, branch-heavy logic the ticket says is worth cracking the
box open for: feature-credit unification and de-duplication, with a hard conservative
line — never merge two distinct artists, never touch the primary artist. So it is
tested directly, not only through the engine.
"""

from __future__ import annotations

import unicodedata

import pytest

from muzik.artist import normalise_artist, place_feature_credit

# Unicode fixtures written as explicit code points (pure-ASCII source), so the
# composed/decomposed distinction survives no matter how an editor stores this file.
_COMPOSED = "Beyoncé"  # pre-composed 'é'
_DECOMPOSED = "Beyoncé"  # 'e' + U+0301 combining acute accent
_ALL_CAPS = "BEYONCÉ"  # 'BEYONCÉ'
_NO_ACCENT = "Beyonce"

# The fixtures are exactly what the tests below claim they are.
assert _DECOMPOSED == unicodedata.normalize("NFD", _COMPOSED)
assert _COMPOSED == unicodedata.normalize("NFC", _DECOMPOSED)


class TestLeavesCleanNamesAlone:
    @pytest.mark.parametrize(
        "name",
        [
            "Michael Jackson",
            _COMPOSED,  # already NFC + accented: untouched
            "Simon & Garfunkel",  # an ampersand duo is not a feature credit
            "Above & Beyond",
            "Florence + the Machine",
            "Tyler, The Creator",  # a comma in the name is not a credit separator
            "Daft Punk",  # the "ft" inside "Daft" is not a feature marker
            "AC/DC",
        ],
    )
    def test_a_name_with_no_feature_marker_is_returned_unchanged(self, name):
        assert normalise_artist(name) == name


class TestSafeCanonicalisation:
    def test_collapses_internal_whitespace_and_trims(self):
        assert normalise_artist("  Michael   Jackson  ") == "Michael Jackson"

    def test_nfc_normalises_a_decomposed_accent_to_composed(self):
        assert _DECOMPOSED != _COMPOSED  # same glyph, different byte sequences
        assert normalise_artist(_DECOMPOSED) == _COMPOSED

    def test_does_not_strip_diacritics(self):
        # "Beyonce" (no accent) is a *different* spelling; choosing the accented form
        # needs a catalogue, so it is left alone (conservative bias).
        assert normalise_artist(_NO_ACCENT) == _NO_ACCENT

    def test_does_not_fold_case(self):
        assert normalise_artist(_ALL_CAPS) == _ALL_CAPS

    def test_empty_or_blank_becomes_empty(self):
        assert normalise_artist("") == ""
        assert normalise_artist("   ") == ""


class TestFeatureCreditForm:
    @pytest.mark.parametrize(
        "written",
        [
            "Drake feat. Rihanna",
            "Drake feat Rihanna",
            "Drake ft. Rihanna",
            "Drake ft Rihanna",
            "Drake featuring Rihanna",
            "Drake (feat. Rihanna)",
            "Drake (ft. Rihanna)",
            "Drake [feat. Rihanna]",
            "Drake [ft Rihanna]",
            "Drake FT. Rihanna",
            "Drake Featuring Rihanna",
            "Drake   feat.   Rihanna",
        ],
    )
    def test_every_feature_form_canonicalises_to_one(self, written):
        assert normalise_artist(written) == "Drake feat. Rihanna"

    def test_multiple_feature_markers_merge_into_one_credit_list(self):
        assert (
            normalise_artist("Drake feat. Rihanna feat. Future")
            == "Drake feat. Rihanna, Future"
        )

    def test_an_already_comma_joined_credit_is_kept_as_one_segment(self):
        assert (
            normalise_artist("Drake feat. Rihanna, Future")
            == "Drake feat. Rihanna, Future"
        )


class TestDeduplication:
    def test_a_repeated_featured_artist_collapses(self):
        assert normalise_artist("Drake ft. Rihanna feat. Rihanna") == "Drake feat. Rihanna"

    def test_dedup_is_case_insensitive(self):
        # The first-seen casing is kept; a later case-variant duplicate is dropped.
        assert normalise_artist("Drake ft. rihanna feat. RIHANNA") == "Drake feat. rihanna"

    def test_a_featured_artist_equal_to_the_primary_is_dropped(self):
        assert normalise_artist("Drake feat. Drake") == "Drake"


class TestPrimaryArtistIsNeverSplit:
    def test_an_ampersand_primary_survives_a_feature_tail(self):
        assert (
            normalise_artist("Simon & Garfunkel ft. Someone")
            == "Simon & Garfunkel feat. Someone"
        )

    def test_a_comma_primary_survives_a_feature_tail(self):
        assert (
            normalise_artist("Tyler, The Creator ft. Kali Uchis")
            == "Tyler, The Creator feat. Kali Uchis"
        )

    def test_a_comma_featured_name_is_kept_whole(self):
        assert (
            normalise_artist("Kanye West feat. Tyler, The Creator")
            == "Kanye West feat. Tyler, The Creator"
        )

    def test_a_primary_ending_in_ft_letters_is_not_split(self):
        assert normalise_artist("Daft Punk feat. Pharrell") == "Daft Punk feat. Pharrell"


class TestDegenerateCredits:
    def test_a_dangling_marker_with_no_featured_name_is_dropped(self):
        assert normalise_artist("Drake feat.") == "Drake"

    def test_a_bare_credit_with_no_primary_is_left_alone(self):
        # No primary artist to anchor on — restructuring "feat. X" could only guess,
        # so leave it exactly as written.
        assert normalise_artist("feat. Rihanna") == "feat. Rihanna"


class TestIdempotency:
    @pytest.mark.parametrize(
        "name",
        [
            "Drake ft. Rihanna",
            "Drake feat. Rihanna feat. Future",
            "Tyler, The Creator ft. Kali Uchis",
            _COMPOSED,
            "Simon & Garfunkel",
        ],
    )
    def test_normalising_twice_changes_nothing_the_second_time(self, name):
        once = normalise_artist(name)
        assert normalise_artist(once) == once


class TestPlaceFeatureCredit:
    """The credit belongs in the title, not the artist field (spec US#26, #56).

    ``place_feature_credit`` operates on the ``(title, artist)`` pair: it moves a
    clear featured-artist clause out of the artist field and into the title as one
    ``(feat. X)``, leaving the artist primary-only — the standard every reference
    tagger uses. It reuses the #47 parser, so it inherits the same conservative
    guarantees (primary never split, a featured segment never split on its own
    commas) and the same bias: when unsure, leave both fields alone.
    """

    def test_a_feature_clause_moves_from_artist_into_the_title(self):
        assert place_feature_credit("Take Care", "Drake feat. Rihanna") == (
            "Take Care (feat. Rihanna)",
            "Drake",
        )

    def test_multiple_featured_artists_move_as_one_credit(self):
        assert place_feature_credit(
            "Take Care", "Drake feat. Rihanna feat. Future"
        ) == ("Take Care (feat. Rihanna, Future)", "Drake")

    @pytest.mark.parametrize(
        "artist",
        [
            "Drake ft. Rihanna",
            "Drake (ft. Rihanna)",
            "Drake featuring Rihanna",
            "Drake [feat. Rihanna]",
        ],
    )
    def test_any_feature_form_is_canonicalised_as_it_moves(self, artist):
        assert place_feature_credit("Take Care", artist) == (
            "Take Care (feat. Rihanna)",
            "Drake",
        )

    def test_a_repeated_credit_is_deduped_before_it_moves(self):
        assert place_feature_credit(
            "Take Care", "Drake ft. Rihanna feat. Rihanna"
        ) == ("Take Care (feat. Rihanna)", "Drake")

    def test_an_artist_with_no_feature_clause_leaves_the_title_alone(self):
        assert place_feature_credit("Take Care", "Drake") == ("Take Care", "Drake")

    def test_the_artist_is_still_normalised_when_there_is_nothing_to_move(self):
        # No feature clause, but #47's in-place tidy (whitespace/NFC) still applies.
        assert place_feature_credit("Take Care", "  Drake  ") == ("Take Care", "Drake")

    def test_a_primary_with_an_ampersand_is_never_split(self):
        assert place_feature_credit("Song", "Simon & Garfunkel ft. Someone") == (
            "Song (feat. Someone)",
            "Simon & Garfunkel",
        )

    def test_a_featured_name_with_a_comma_is_kept_whole(self):
        assert place_feature_credit(
            "Song", "Kanye West feat. Tyler, The Creator"
        ) == ("Song (feat. Tyler, The Creator)", "Kanye West")

    def test_trailing_whitespace_on_the_title_is_not_doubled(self):
        assert place_feature_credit("Take Care  ", "Drake feat. Rihanna") == (
            "Take Care (feat. Rihanna)",
            "Drake",
        )


class TestPlaceFeatureCreditNeverDuplicates:
    """When the title already carries the credit, strip the artist — don't append."""

    def test_a_title_that_already_names_the_credit_is_not_appended_to(self):
        assert place_feature_credit(
            "Take Care (feat. Rihanna)", "Drake feat. Rihanna"
        ) == ("Take Care (feat. Rihanna)", "Drake")

    def test_the_title_credit_is_matched_across_feature_forms(self):
        assert place_feature_credit(
            "Take Care (ft. Rihanna)", "Drake feat. Rihanna"
        ) == ("Take Care (ft. Rihanna)", "Drake")

    def test_the_title_credit_is_matched_case_insensitively(self):
        assert place_feature_credit(
            "Take Care (feat. RIHANNA)", "Drake feat. rihanna"
        ) == ("Take Care (feat. RIHANNA)", "Drake")


class TestPlaceFeatureCreditLeavesTheUnsureCaseAlone:
    """A move is riskier than #47's tidy; only a *clear* clause is moved."""

    def test_a_bare_credit_with_no_primary_moves_nothing(self):
        # No primary artist to anchor on — #47 leaves the artist as-is, and there
        # is nothing safe to move into the title either.
        assert place_feature_credit("Song", "feat. Rihanna") == (
            "Song",
            "feat. Rihanna",
        )

    def test_a_title_naming_a_different_credit_leaves_both_fields_alone(self):
        # The title already features someone the artist field does not — combining
        # them would guess. Leave both (the artist stays #47-normalised, not stripped).
        assert place_feature_credit(
            "Take Care (feat. Alice)", "Drake feat. Bob"
        ) == ("Take Care (feat. Alice)", "Drake feat. Bob")

    def test_a_partially_covered_credit_leaves_both_fields_alone(self):
        assert place_feature_credit(
            "Take Care (feat. Rihanna)", "Drake feat. Rihanna, Future"
        ) == ("Take Care (feat. Rihanna)", "Drake feat. Rihanna, Future")


class TestPlaceFeatureCreditIsIdempotent:
    @pytest.mark.parametrize(
        ("title", "artist"),
        [
            ("Take Care", "Drake feat. Rihanna"),
            ("Take Care (feat. Rihanna)", "Drake feat. Rihanna"),
            ("Take Care (feat. Alice)", "Drake feat. Bob"),
            ("Song", "Kanye West feat. Tyler, The Creator"),
            ("Song", "Drake"),
        ],
    )
    def test_placing_twice_changes_nothing_the_second_time(self, title, artist):
        once = place_feature_credit(title, artist)
        assert place_feature_credit(*once) == once
