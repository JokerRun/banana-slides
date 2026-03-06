"""
Restyle 端到端集成测试

覆盖:
1. POST /api/projects/restyle — 上传PPT/PDF + 风格参考图创建项目
2. POST /api/projects/{id}/restyle/generate — 异步批量restyle
3. POST /api/projects/{id}/pages/{page_id}/restyle/generate — 单页restyle
4. 输入校验 & 边界条件
"""

import io
import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from conftest import assert_success_response, assert_error_response


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def sample_pdf_bytes():
    """创建一个真实的 2 页 PDF (in-memory)"""
    try:
        import fitz
    except ImportError:
        pytest.skip("PyMuPDF (fitz) not installed")

    doc = fitz.open()
    for i in range(2):
        page = doc.new_page(width=1920, height=1080)
        page.insert_text((100, 100), f"Slide {i+1}", fontsize=48)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.fixture
def sample_style_ref_bytes():
    """创建风格参考图片 (100x100 blue PNG)"""
    from PIL import Image
    img = Image.new('RGB', (100, 100), color='blue')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf.read()


@pytest.fixture
def sample_style_ref_bytes_2():
    """第二张风格参考图 (100x100 green PNG)"""
    from PIL import Image
    img = Image.new('RGB', (100, 100), color='green')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf.read()


# ============================================================
# POST /api/projects/restyle — 创建restyle项目
# ============================================================

class TestCreateRestyleProject:
    """创建 restyle 项目测试"""

    def test_create_with_pdf(self, client, sample_pdf_bytes, sample_style_ref_bytes):
        """PDF + 风格参考 → 成功创建项目"""
        data = {
            'source_file': (io.BytesIO(sample_pdf_bytes), 'slides.pdf'),
            'style_refs': (io.BytesIO(sample_style_ref_bytes), 'ref1.png'),
        }
        response = client.post(
            '/api/projects/restyle',
            data=data,
            content_type='multipart/form-data'
        )

        result = assert_success_response(response, 201)
        assert result['data']['creation_type'] == 'restyle'
        assert result['data']['total_pages'] == 2
        assert len(result['data']['pages']) == 2
        assert result['data']['status'] == 'SLIDES_EXTRACTED'

        # 每个 page 应有 original_slide_image_url
        for page in result['data']['pages']:
            assert page.get('original_slide_image_url') is not None

    def test_create_with_multiple_style_refs(self, client, sample_pdf_bytes,
                                              sample_style_ref_bytes, sample_style_ref_bytes_2):
        """多张风格参考图"""
        data = {
            'source_file': (io.BytesIO(sample_pdf_bytes), 'slides.pdf'),
            'style_refs': [
                (io.BytesIO(sample_style_ref_bytes), 'ref1.png'),
                (io.BytesIO(sample_style_ref_bytes_2), 'ref2.png'),
            ],
        }
        response = client.post(
            '/api/projects/restyle',
            data=data,
            content_type='multipart/form-data'
        )

        result = assert_success_response(response, 201)
        assert result['data']['total_pages'] == 2

    def test_create_without_restyle_prompt(self, client, sample_pdf_bytes, sample_style_ref_bytes):
        """restyle_prompt 可选"""
        data = {
            'source_file': (io.BytesIO(sample_pdf_bytes), 'slides.pdf'),
            'style_refs': (io.BytesIO(sample_style_ref_bytes), 'ref1.png'),
        }
        response = client.post(
            '/api/projects/restyle',
            data=data,
            content_type='multipart/form-data'
        )
        result = assert_success_response(response, 201)
        assert result['data']['creation_type'] == 'restyle'

    def test_create_with_restyle_prompt(self, client, sample_pdf_bytes, sample_style_ref_bytes):
        """restyle_prompt 可选并应持久化"""
        custom_prompt = "必须使用底版.png作为唯一页面基础"
        data = {
            'source_file': (io.BytesIO(sample_pdf_bytes), 'slides.pdf'),
            'style_refs': (io.BytesIO(sample_style_ref_bytes), 'ref1.png'),
            'restyle_prompt': custom_prompt,
        }
        response = client.post(
            '/api/projects/restyle',
            data=data,
            content_type='multipart/form-data'
        )
        result = assert_success_response(response, 201)
        project_id = result['data']['project_id']

        get_resp = client.get(f'/api/projects/{project_id}')
        get_result = assert_success_response(get_resp, 200)
        assert get_result['data']['restyle_prompt'] == custom_prompt

    def test_create_with_non_ascii_source_filename(self, client, sample_pdf_bytes, sample_style_ref_bytes):
        """中文文件名也应正确保留扩展名并成功创建"""
        data = {
            'source_file': (io.BytesIO(sample_pdf_bytes), '源文件.pdf'),
            'style_refs': (io.BytesIO(sample_style_ref_bytes), '参考图.png'),
        }
        response = client.post(
            '/api/projects/restyle',
            data=data,
            content_type='multipart/form-data'
        )

        result = assert_success_response(response, 201)
        assert result['data']['creation_type'] == 'restyle'
        assert result['data']['total_pages'] == 2

    def test_create_missing_source_file(self, client, sample_style_ref_bytes):
        """缺少源文件应返回 400"""
        data = {
            'style_refs': (io.BytesIO(sample_style_ref_bytes), 'ref1.png'),
        }
        response = client.post(
            '/api/projects/restyle',
            data=data,
            content_type='multipart/form-data'
        )
        assert response.status_code == 400

    def test_create_missing_style_refs(self, client, sample_pdf_bytes):
        """缺少风格参考图应返回 400"""
        data = {
            'source_file': (io.BytesIO(sample_pdf_bytes), 'slides.pdf'),
        }
        response = client.post(
            '/api/projects/restyle',
            data=data,
            content_type='multipart/form-data'
        )
        assert response.status_code == 400

    def test_create_invalid_source_format(self, client, sample_style_ref_bytes):
        """不支持的源文件格式应返回 400"""
        data = {
            'source_file': (io.BytesIO(b'dummy'), 'slides.docx'),
            'style_refs': (io.BytesIO(sample_style_ref_bytes), 'ref1.png'),
        }
        response = client.post(
            '/api/projects/restyle',
            data=data,
            content_type='multipart/form-data'
        )
        assert response.status_code == 400

    def test_create_invalid_style_ref_format(self, client, sample_pdf_bytes):
        """不支持的风格参考图格式应返回 400"""
        data = {
            'source_file': (io.BytesIO(sample_pdf_bytes), 'slides.pdf'),
            'style_refs': (io.BytesIO(b'dummy'), 'ref1.gif'),
        }
        response = client.post(
            '/api/projects/restyle',
            data=data,
            content_type='multipart/form-data'
        )
        assert response.status_code == 400

    def test_create_too_many_style_refs(self, client, sample_pdf_bytes, sample_style_ref_bytes):
        """超过5张风格参考图应返回 400"""
        refs = [(io.BytesIO(sample_style_ref_bytes), f'ref{i}.png') for i in range(6)]
        data = {
            'source_file': (io.BytesIO(sample_pdf_bytes), 'slides.pdf'),
            'style_refs': refs,
        }
        response = client.post(
            '/api/projects/restyle',
            data=data,
            content_type='multipart/form-data'
        )
        assert response.status_code == 400


# ============================================================
# POST /api/projects/{id}/restyle/generate — 批量restyle
# ============================================================

class TestRestyleGenerate:
    """批量 restyle 测试"""

    def _create_restyle_project(self, client, sample_pdf_bytes, sample_style_ref_bytes):
        """辅助: 创建一个 restyle 项目"""
        data = {
            'source_file': (io.BytesIO(sample_pdf_bytes), 'slides.pdf'),
            'style_refs': (io.BytesIO(sample_style_ref_bytes), 'ref1.png'),
        }
        response = client.post(
            '/api/projects/restyle',
            data=data,
            content_type='multipart/form-data'
        )
        return response.get_json()['data']

    def test_restyle_generate_starts_task(self, client, sample_pdf_bytes, sample_style_ref_bytes):
        """批量 restyle 应返回 task_id (202)"""
        project_data = self._create_restyle_project(client, sample_pdf_bytes, sample_style_ref_bytes)
        project_id = project_data['project_id']

        response = client.post(f'/api/projects/{project_id}/restyle/generate',
                               json={})

        assert response.status_code == 202
        data = response.get_json()
        assert data['success'] is True
        assert 'task_id' in data['data']
        assert data['data']['total_pages'] == 2

    def test_restyle_generate_specific_pages(self, client, sample_pdf_bytes, sample_style_ref_bytes):
        """指定 page_ids 只转换部分页面"""
        project_data = self._create_restyle_project(client, sample_pdf_bytes, sample_style_ref_bytes)
        project_id = project_data['project_id']
        page_id = project_data['pages'][0]['page_id']

        response = client.post(f'/api/projects/{project_id}/restyle/generate',
                               json={'page_ids': [page_id]})

        assert response.status_code == 202

    def test_restyle_generate_not_found(self, client):
        """项目不存在返回 404"""
        response = client.post('/api/projects/nonexistent/restyle/generate', json={})
        assert response.status_code == 404

    def test_restyle_generate_wrong_type(self, client):
        """非 restyle 类型项目应返回 400"""
        # 先创建一个 idea 类型项目
        create_resp = client.post('/api/projects', json={
            'creation_type': 'idea',
            'idea_prompt': 'test'
        })
        project_id = create_resp.get_json()['data']['project_id']

        response = client.post(f'/api/projects/{project_id}/restyle/generate', json={})
        assert response.status_code == 400


# ============================================================
# POST /api/projects/{id}/pages/{page_id}/restyle/generate — 单页restyle
# ============================================================

class TestRestyleSinglePage:
    """单页 restyle 测试"""

    def _create_restyle_project(self, client, sample_pdf_bytes, sample_style_ref_bytes):
        """辅助: 创建 restyle 项目"""
        data = {
            'source_file': (io.BytesIO(sample_pdf_bytes), 'slides.pdf'),
            'style_refs': (io.BytesIO(sample_style_ref_bytes), 'ref1.png'),
        }
        response = client.post(
            '/api/projects/restyle',
            data=data,
            content_type='multipart/form-data'
        )
        return response.get_json()['data']

    def test_single_page_restyle(self, client, sample_pdf_bytes, sample_style_ref_bytes):
        """单页 restyle 应返回 task_id"""
        project_data = self._create_restyle_project(client, sample_pdf_bytes, sample_style_ref_bytes)
        project_id = project_data['project_id']
        page_id = project_data['pages'][0]['page_id']

        response = client.post(
            f'/api/projects/{project_id}/pages/{page_id}/restyle/generate'
        )

        assert response.status_code == 202
        data = response.get_json()
        assert 'task_id' in data['data']

    def test_single_page_not_found(self, client, sample_pdf_bytes, sample_style_ref_bytes):
        """page 不存在返回 404"""
        project_data = self._create_restyle_project(client, sample_pdf_bytes, sample_style_ref_bytes)
        project_id = project_data['project_id']

        response = client.post(
            f'/api/projects/{project_id}/pages/nonexistent/restyle/generate'
        )
        assert response.status_code == 404

    def test_single_page_wrong_project_type(self, client):
        """非 restyle 项目返回 400"""
        create_resp = client.post('/api/projects', json={
            'creation_type': 'idea',
            'idea_prompt': 'test'
        })
        project_id = create_resp.get_json()['data']['project_id']

        response = client.post(
            f'/api/projects/{project_id}/pages/someid/restyle/generate'
        )
        assert response.status_code == 400


# ============================================================
# 项目查询和验证
# ============================================================

class TestRestyleProjectGet:
    """restyle 项目查询测试"""

    def test_get_restyle_project(self, client, sample_pdf_bytes, sample_style_ref_bytes):
        """创建后应能通过 GET /api/projects/{id} 查询"""
        data = {
            'source_file': (io.BytesIO(sample_pdf_bytes), 'slides.pdf'),
            'style_refs': (io.BytesIO(sample_style_ref_bytes), 'ref1.png'),
        }
        create_resp = client.post(
            '/api/projects/restyle',
            data=data,
            content_type='multipart/form-data'
        )
        project_id = create_resp.get_json()['data']['project_id']

        get_resp = client.get(f'/api/projects/{project_id}')
        result = assert_success_response(get_resp)

        assert result['data']['creation_type'] == 'restyle'
        assert result['data']['source_file_path'] is not None

    def test_delete_restyle_project(self, client, sample_pdf_bytes, sample_style_ref_bytes):
        """restyle 项目应能正常删除"""
        data = {
            'source_file': (io.BytesIO(sample_pdf_bytes), 'slides.pdf'),
            'style_refs': (io.BytesIO(sample_style_ref_bytes), 'ref1.png'),
        }
        create_resp = client.post(
            '/api/projects/restyle',
            data=data,
            content_type='multipart/form-data'
        )
        project_id = create_resp.get_json()['data']['project_id']

        del_resp = client.delete(f'/api/projects/{project_id}')
        assert_success_response(del_resp)

        # 确认已删除
        get_resp = client.get(f'/api/projects/{project_id}')
        assert get_resp.status_code == 404
