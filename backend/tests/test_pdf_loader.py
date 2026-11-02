"""Tests for services/pdf_loader.py.

PyPDF2's reader is replaced with a fake so the tests do not depend on real PDF
files, but the page iteration / concatenation logic is exercised for real.
"""

import types

import pytest

from services import pdf_loader


class _FakePage:
    def __init__(self, text):
        self._text = text

    def extract_text(self):
        return self._text


def _patch_reader(monkeypatch, pages):
    monkeypatch.setattr(
        pdf_loader,
        "PdfReader",
        lambda file: types.SimpleNamespace(pages=pages),
    )


def test_extract_text_concatenates_all_pages(monkeypatch):
    _patch_reader(monkeypatch, [_FakePage("Page one."), _FakePage("Page two.")])

    assert pdf_loader.extract_text(b"fake-file") == "Page one.Page two."


def test_extract_text_ignores_pages_without_text(monkeypatch):
    _patch_reader(monkeypatch, [_FakePage(None), _FakePage("only text")])

    assert pdf_loader.extract_text(b"fake-file") == "only text"


def test_extract_text_returns_empty_string_for_pdf_without_pages(monkeypatch):
    _patch_reader(monkeypatch, [])

    assert pdf_loader.extract_text(b"fake-file") == ""


def test_extract_text_passes_file_object_to_reader(monkeypatch):
    received = {}

    def fake_reader(file):
        received["file"] = file
        return types.SimpleNamespace(pages=[_FakePage("x")])

    monkeypatch.setattr(pdf_loader, "PdfReader", fake_reader)

    sentinel = object()
    pdf_loader.extract_text(sentinel)

    assert received["file"] is sentinel


@pytest.mark.parametrize("text", [0, ""])
def test_extract_text_handles_falsy_page_text(monkeypatch, text):
    _patch_reader(monkeypatch, [_FakePage(text), _FakePage("ok")])

    assert pdf_loader.extract_text(b"fake-file") == "ok"
