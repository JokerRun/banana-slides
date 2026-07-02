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

    def test_preserves_role_aware_order_for_generate_refs(self):
        manifest = _build_generation_ref_manifest(
            primary_ref_path="/tmp/template.png",
            style_ref_paths=["/tmp/style-extra.png"],
            content_ref_paths=[
                "https://cdn.example.com/logo.png",
                "/files/materials/chart.png",
            ],
        )

        assert [
            (item["kind"], item["bucket"], item["path"], item["selection_reason"])
            for item in manifest
        ] == [
            (
                "style_ref",
                "style",
                "/tmp/template.png",
                "generate_style_reference",
            ),
            (
                "style_ref",
                "style",
                "/tmp/style-extra.png",
                "generate_style_reference",
            ),
            (
                "content_ref",
                "content",
                "https://cdn.example.com/logo.png",
                "generate_content_reference",
            ),
            (
                "content_ref",
                "content",
                "/files/materials/chart.png",
                "generate_content_reference",
            ),
        ]
        assert _selected_manifest_paths(manifest) == [
            "/tmp/template.png",
            "/tmp/style-extra.png",
            "https://cdn.example.com/logo.png",
            "/files/materials/chart.png",
        ]


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
