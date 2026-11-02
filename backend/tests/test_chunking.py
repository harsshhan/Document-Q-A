"""Tests for services/chunking.py (pure function, no mocking needed)."""

import pytest

from services.chunking import chunk_text


def test_splits_text_into_expected_number_of_chunks():
    text = " ".join(str(i) for i in range(250))

    chunks = chunk_text(text, chunk_size=100, overlap=20)

    # step = chunk_size - overlap = 80 -> starts at 0, 80, 160, 240
    assert len(chunks) == 4
    assert len(chunks[0].split()) == 100
    assert len(chunks[-1].split()) == 10


def test_consecutive_chunks_overlap():
    text = " ".join(f"w{i}" for i in range(150))

    chunks = chunk_text(text, chunk_size=100, overlap=20)

    first = chunks[0].split()
    second = chunks[1].split()
    assert first[-20:] == second[:20]


def test_no_overlap_produces_disjoint_chunks():
    text = " ".join(str(i) for i in range(10))

    chunks = chunk_text(text, chunk_size=4, overlap=0)

    assert chunks == ["0 1 2 3", "4 5 6 7", "8 9"]


def test_text_shorter_than_chunk_size_returns_single_chunk():
    assert chunk_text("hello world") == ["hello world"]


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_blank_text_returns_no_chunks(text):
    assert chunk_text(text) == []


def test_chunks_always_contain_strings():
    chunks = chunk_text(" ".join(str(i) for i in range(120)))

    assert all(isinstance(chunk, str) for chunk in chunks)
