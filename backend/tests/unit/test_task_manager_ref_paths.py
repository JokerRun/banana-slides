"""Unit tests for generation ref manifest and ref path normalization."""

from services.task_manager import (
    _build_generation_ref_manifest,
    _normalize_ref_paths,
    _selected_manifest_paths,
)


class _FakeFileService:
    upload_folder = "/tmp/uploads"


class TestBuildGenerationRefManifest:
    def test_includes_style_and_material_refs(self):
        manifest = _build_generation_ref_manifest(
            primary_ref_path="/tmp/template.png",
            additional_ref_paths=[
                "/tmp/style1.png",
                "https://cdn.example.com/material.png",
                "/files/materials/abc.png",
            ],
        )
        paths = [item["path"] for item in manifest]
        assert paths == [
            "/tmp/template.png",
            "/tmp/style1.png",
            "https://cdn.example.com/material.png",
            "/files/materials/abc.png",
        ]
        assert all(item.get("selected") is True for item in manifest)


class TestNormalizeRefPaths:
    def test_passes_through_http_urls(self):
        urls = [
            "https://example.com/a.png",
            "http://example.com/b.jpg",
        ]
        assert _normalize_ref_paths(urls, _FakeFileService()) == urls

    def test_selected_manifest_paths_round_trip(self):
        manifest = _build_generation_ref_manifest(
            additional_ref_paths=["https://example.com/m.png"],
        )
        assert _selected_manifest_paths(manifest) == ["https://example.com/m.png"]
