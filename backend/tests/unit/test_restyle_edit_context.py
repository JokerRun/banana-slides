"""
Restyle edit context — unit tests (Task 1: schema & config baseline)
"""
import pytest


class TestPageRestyleSnapshot:
    """Page model restyle_base_prompt_snapshot field tests"""

    def test_page_has_restyle_base_prompt_snapshot_field(self, db_session):
        from models import Page
        page = Page(project_id='p1', order_index=0, restyle_base_prompt_snapshot='BASE PROMPT')
        assert page.restyle_base_prompt_snapshot == 'BASE PROMPT'

    def test_page_to_dict_includes_snapshot(self, db_session):
        from models import Page
        page = Page(project_id='p1', order_index=0, restyle_base_prompt_snapshot='SNAP')
        data = page.to_dict()
        assert 'restyle_base_prompt_snapshot' in data
        assert data['restyle_base_prompt_snapshot'] == 'SNAP'


class TestRestyleEditConfig:
    """Config defaults for restyle edit caps"""

    def test_restyle_edit_caps_default_from_config(self):
        from config import Config
        assert Config.RESTYLE_EDIT_MAX_PRUNABLE_IMAGES == 6
        assert Config.RESTYLE_EDIT_MAX_TOTAL_IMAGES == 8
