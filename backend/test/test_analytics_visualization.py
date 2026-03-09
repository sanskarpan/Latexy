from datetime import datetime, timezone, timedelta
from uuid import uuid4

import jwt as pyjwt
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Compilation, Optimization, Resume, UsageAnalytics, User


def make_jwt(user_id: str, is_admin: bool = False) -> str:
    payload = {
        'sub': user_id,
        'exp': datetime.now(timezone.utc) + timedelta(hours=1),
    }
    if is_admin:
        payload['role'] = 'admin'
    return pyjwt.encode(payload, 'test_jwt_secret_32chars_minimum_!', algorithm='HS256')


@pytest.mark.asyncio
async def test_me_timeseries_returns_series_data(client: AsyncClient, db_session: AsyncSession):
    user_id = str(uuid4())
    resume_id = str(uuid4())
    now = datetime.now(timezone.utc)

    db_session.add(
        User(
            id=user_id,
            email=f'test_{user_id[:8]}@example.com',
            name='Analytics User',
            email_verified=True,
            subscription_plan='free',
            subscription_status='active',
            trial_used=False,
        )
    )
    db_session.add(
        Resume(
            id=resume_id,
            user_id=user_id,
            title='Test Resume',
            latex_content='\\\\documentclass{article}\\\\begin{document}x\\\\end{document}',
            is_template=False,
        )
    )

    db_session.add_all([
        Compilation(
            user_id=user_id,
            resume_id=None,
            device_fingerprint=None,
            job_id=f'job_{uuid4().hex[:8]}',
            status='completed',
            compilation_time=3.2,
            created_at=now - timedelta(days=1),
        ),
        Compilation(
            user_id=user_id,
            resume_id=None,
            device_fingerprint=None,
            job_id=f'job_{uuid4().hex[:8]}',
            status='failed',
            compilation_time=6.0,
            created_at=now,
        ),
        Optimization(
            user_id=user_id,
            resume_id=resume_id,
            job_description='JD',
            original_latex='orig',
            optimized_latex='opt',
            provider='openai',
            model='gpt-4o-mini',
            tokens_used=420,
            optimization_time=1.8,
            ats_score={'overall_score': 81},
            created_at=now,
        ),
        UsageAnalytics(
            user_id=user_id,
            device_fingerprint=None,
            action='compile',
            resource_type='resume',
            event_metadata={'feature': 'compile'},
            created_at=now,
        ),
        UsageAnalytics(
            user_id=user_id,
            device_fingerprint=None,
            action='feature_usage',
            resource_type='resume',
            event_metadata={'feature': 'optimize'},
            created_at=now,
        ),
    ])
    await db_session.commit()

    token = make_jwt(user_id)
    response = await client.get('/analytics/me/timeseries?days=7', headers={'Authorization': f'Bearer {token}'})

    assert response.status_code == 200
    body = response.json()
    assert body['user_id'] == user_id
    assert body['period_days'] == 7
    assert len(body['activity_series']) == 7
    assert len(body['compilation_series']) == 7
    assert len(body['optimization_series']) == 7
    assert body['status_distribution']['completed'] >= 1
    assert body['status_distribution']['failed'] >= 1
    assert any(point['count'] >= 1 for point in body['feature_series'])


@pytest.mark.asyncio
async def test_admin_analytics_routes_require_admin(client: AsyncClient):
    no_auth = await client.get('/analytics/system?days=7')
    assert no_auth.status_code == 401

    non_admin_token = make_jwt(str(uuid4()), is_admin=False)
    forbidden = await client.get('/analytics/system?days=7', headers={'Authorization': f'Bearer {non_admin_token}'})
    assert forbidden.status_code == 403

    admin_token = make_jwt(str(uuid4()), is_admin=True)
    allowed = await client.get('/analytics/system?days=7', headers={'Authorization': f'Bearer {admin_token}'})
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_conversion_funnel_uses_event_metadata_page(client: AsyncClient, db_session: AsyncSession):
    now = datetime.now(timezone.utc)

    db_session.add_all([
        UsageAnalytics(
            user_id=None,
            device_fingerprint='dev_a',
            action='page_view',
            resource_type='page',
            event_metadata={'page': 'landing'},
            created_at=now,
        ),
        UsageAnalytics(
            user_id=None,
            device_fingerprint='dev_b',
            action='page_view',
            resource_type='page',
            event_metadata={'page': 'landing'},
            created_at=now,
        ),
        UsageAnalytics(
            user_id=None,
            device_fingerprint='dev_c',
            action='page_view',
            resource_type='page',
            event_metadata={'page': 'pricing'},
            created_at=now,
        ),
    ])
    await db_session.commit()

    admin_token = make_jwt(str(uuid4()), is_admin=True)
    response = await client.get('/analytics/conversion-funnel?days=7', headers={'Authorization': f'Bearer {admin_token}'})

    assert response.status_code == 200
    data = response.json()
    assert data['funnel_steps']['landing_visits'] >= 2
