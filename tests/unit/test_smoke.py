import workplace_agent


def test_version_is_string() -> None:
    assert isinstance(workplace_agent.__version__, str)
