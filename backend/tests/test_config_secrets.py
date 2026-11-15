def test_credentials_have_no_source_default_and_are_not_serialized():
    from app.config import Settings
    for name in ['supabase_service_key','google_api_key','openrouter_api_key']:
        assert not Settings.model_fields[name].default
    config=Settings(_env_file=None,supabase_service_key='sentinel-service',google_api_key='sentinel-google',openrouter_api_key='sentinel-router')
    assert 'sentinel' not in repr(config)
    assert not {'supabase_service_key','google_api_key','openrouter_api_key'} & config.model_dump().keys()
