"""A collection's read shape says which package installed it, so the sidebar can give a package's collections a section."""

from marvin.schemas.platform.collections import CollectionRead


def test_a_collection_read_carries_its_package_slug_and_defaults_to_none():
    schema = CollectionRead.model_json_schema(by_alias=True)["properties"]
    assert "sourcePackage" in schema
    assert CollectionRead.model_fields["source_package"].default is None
