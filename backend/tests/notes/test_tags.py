from app.notes.tags import derive_scope_tags, TOPIC_KEYWORDS


def test_derive_scope_tags_includes_profile_and_entities():
    profile = {"id": "u1"}
    accounts = [{"id": "a1"}, {"id": "a2"}]
    goals = [{"id": "g1"}]
    tags = derive_scope_tags(
        profile=profile, accounts=accounts, goals=goals,
        recurring_rules=[], last_user_message="how does my dining out look?",
    )
    assert "entity:profile:u1" in tags
    assert "entity:account:a1" in tags
    assert "entity:account:a2" in tags
    assert "entity:goal:g1" in tags
    assert "topic:dining" in tags


def test_derive_scope_tags_topic_keyword_match_is_case_insensitive():
    tags = derive_scope_tags(
        profile={"id": "u1"}, accounts=[], goals=[], recurring_rules=[],
        last_user_message="What about my Retirement plan?",
    )
    assert "topic:retirement" in tags


def test_derive_scope_tags_recurring_only_when_keyword_present():
    rules = [{"id": "r1"}]
    tags_no = derive_scope_tags(
        profile={"id": "u1"}, accounts=[], goals=[], recurring_rules=rules,
        last_user_message="what's my net worth?",
    )
    assert "entity:recurring:r1" not in tags_no

    tags_yes = derive_scope_tags(
        profile={"id": "u1"}, accounts=[], goals=[], recurring_rules=rules,
        last_user_message="any subscription i can cancel?",
    )
    assert "entity:recurring:r1" in tags_yes


def test_topic_keywords_allow_list_is_documented():
    for slug, kws in TOPIC_KEYWORDS.items():
        assert slug == slug.lower()
        assert kws, f"empty keywords for {slug}"


def test_derive_scope_tags_new_slugs():
    tags = derive_scope_tags(
        profile={}, accounts=[], goals=[], recurring_rules=[],
        last_user_message="I want to build an emergency fund and save more",
    )
    assert "topic:emergency" in tags
    assert "topic:savings" in tags


def test_derive_scope_tags_career():
    tags = derive_scope_tags(
        profile={}, accounts=[], goals=[], recurring_rules=[],
        last_user_message="I just got a raise at work",
    )
    assert "topic:career" in tags
