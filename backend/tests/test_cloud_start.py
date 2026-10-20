import pytest
from scripts.start_cloud import configure


def test_cloud_defaults_do_not_overwrite_explicit_config_or_seed():
    env={'RAILWAY_PUBLIC_DOMAIN':'rc.example.test','RAILWAY_GIT_COMMIT_SHA':'a'*40}
    assert configure(env)==(8080,2)
    assert env['CORS_ORIGINS']=='https://rc.example.test'
    assert env['APP_COMMIT']=='a'*40
    assert env['SECURE_COOKIES']=='true'
    env['CORS_ORIGINS']='https://approved.example.test'
    env['WEB_CONCURRENCY']='4'
    assert configure(env)==(8080,4)
    assert env['CORS_ORIGINS']=='https://approved.example.test'
    assert not any('SEED' in k for k in env)


@pytest.mark.parametrize('field,value',[('PORT','8000'),('PORT','80'),('PORT','65536'),('PORT','abc'),('WEB_CONCURRENCY','0'),('RAILWAY_PUBLIC_DOMAIN','host\nInjected')])
def test_invalid_cloud_config_fails_before_starting_children(field,value):
    with pytest.raises(ValueError):configure({field:value})
