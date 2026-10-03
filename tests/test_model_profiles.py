import os
import tempfile
import uuid

os.environ.setdefault('REVIEW_DATA_DIR', tempfile.mkdtemp(prefix='review-model-test-'))

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app import app
from backend.db import DATA, Session, UserModelProfile, ModelService
from backend.model_profiles import profile_snapshot, profile_is_current


def _login(client, username, password):
    response = client.post('/api/login', json={'username': username, 'password': password})
    assert response.status_code == 200, response.text
    return {'X-CSRF-Token': response.json()['csrf']}


def test_two_users_cannot_read_or_select_each_others_profile():
    with TestClient(app) as admin_client, TestClient(app) as first, TestClient(app) as second:
        password = (DATA / 'bootstrap-admin.txt').read_text(encoding='utf-8').split('初始密码：')[1].splitlines()[0]
        admin_headers = _login(admin_client, 'admin', password)
        service = admin_client.post('/api/model-services', headers=admin_headers,
                                    json={'name': '本地测试', 'base_url': 'http://127.0.0.1:9999/v1',
                                          'models': ['synthetic-model'], 'enabled': True}).json()
        names = [f'test-{uuid.uuid4().hex[:8]}' for _ in range(2)]
        for name in names:
            result = admin_client.post('/api/users', headers=admin_headers,
                                       json={'username': name, 'display_name': name,
                                             'password': 'Example-password-12345'})
            assert result.status_code == 200, result.text
        first_headers = _login(first, names[0], 'Example-password-12345')
        second_headers = _login(second, names[1], 'Example-password-12345')
        created = first.post('/api/me/model-profiles', headers=first_headers,
                             json={'service_id': service['id'], 'model': 'synthetic-model',
                                   'api_key': 'synthetic-private-key'}).json()
        assert created['has_key'] is True and 'synthetic-private-key' not in str(created)
        assert second.get('/api/me/model-profiles').json() == []
        assert second.patch(f'/api/me/model-profiles/{created["id"]}', headers=second_headers,
                            json={'model': 'synthetic-model'}).status_code == 404
        with Session() as db:
            row = db.scalar(select(UserModelProfile).where(UserModelProfile.id == created['id']))
            assert row.key_encrypted != 'synthetic-private-key'


def test_unapproved_endpoint_and_model_cannot_be_saved():
    with TestClient(app) as client:
        password = (DATA / 'bootstrap-admin.txt').read_text(encoding='utf-8').split('初始密码：')[1].splitlines()[0]
        headers = _login(client, 'admin', password)
        direct = client.post('/api/me/model-profiles', headers=headers,
                             json={'base_url': 'https://unapproved.example/v1', 'model': 'unknown',
                                   'api_key': 'synthetic-key'})
        assert direct.status_code == 422
        service = client.post('/api/model-services', headers=headers,
                              json={'name': '本地测试', 'base_url': 'http://127.0.0.1:9998/v1',
                                    'models': ['approved'], 'enabled': True}).json()
        unknown = client.post('/api/me/model-profiles', headers=headers,
                              json={'service_id': service['id'], 'model': 'unknown', 'api_key': 'synthetic-key'})
        assert unknown.status_code == 422


def test_profile_rotation_changes_version_and_never_returns_key():
    with TestClient(app) as client:
        password = (DATA / 'bootstrap-admin.txt').read_text(encoding='utf-8').split('初始密码：')[1].splitlines()[0]
        headers = _login(client, 'admin', password)
        service = client.post('/api/model-services', headers=headers,
                              json={'name': '本地测试', 'base_url': 'http://127.0.0.1:9997/v1',
                                    'models': ['approved'], 'enabled': True}).json()
        created = client.post('/api/me/model-profiles', headers=headers,
                              json={'service_id': service['id'], 'model': 'approved',
                                    'api_key': 'synthetic-key-v1'}).json()
        with Session() as db:
            before=db.get(UserModelProfile,created['id'])
            target=db.get(ModelService,service['id'])
            snapshot=profile_snapshot(before,target)
            assert profile_is_current(snapshot,before,target)
        updated = client.patch(f'/api/me/model-profiles/{created["id"]}', headers=headers,
                               json={'api_key': 'synthetic-key-v2'}).json()
        assert updated['version'] == created['version'] + 1
        assert 'synthetic-key-v2' not in str(updated)
        assert client.get('/api/me/model-profiles').json()[0]['has_key'] is True
        with Session() as db:
            assert not profile_is_current(snapshot,db.get(UserModelProfile,created['id']),
                                          db.get(ModelService,service['id']))
