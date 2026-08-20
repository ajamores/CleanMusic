"""Shared fixtures for the real-I/O ('bench') tests."""

import shutil
import subprocess

import pytest

# Smallest valid PNG (1x1 transparent), so cover-art format detection has real bytes.
_PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d4944415478da6360000002000154a24f5f0000000049454e44ae426082"
)


@pytest.fixture
def png_1px() -> bytes:
    return _PNG_1PX


@pytest.fixture
def silent_m4a(tmp_path):
    """A throwaway 1-second silent M4A, minted with ffmpeg."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    path = tmp_path / "track.m4a"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
         "-t", "1", "-c:a", "aac", str(path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return path


@pytest.fixture
def silent_mp3(tmp_path):
    """A throwaway 1-second silent MP3, minted with ffmpeg."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    path = tmp_path / "track.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
         "-t", "1", "-c:a", "libmp3lame", "-b:a", "320k", str(path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return path
