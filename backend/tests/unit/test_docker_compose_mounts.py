from pathlib import Path

import yaml


def test_backend_service_mounts_data_directories():
    compose = yaml.safe_load(Path('docker-compose.yml').read_text())

    backend = compose['services']['backend']
    volumes = backend['volumes']

    assert './data/instance:/app/backend/instance' in volumes
    assert './data/uploads:/app/uploads' in volumes
    assert './data/debug:/app/debug' in volumes
