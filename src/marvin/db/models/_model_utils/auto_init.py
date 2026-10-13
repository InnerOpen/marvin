"""
This module provides an `auto_init` decorator for SQLAlchemy models.

The decorator automates the initialization of model attributes from keyword
arguments passed to the `__init__` method. It intelligently handles simple
attributes (mapped columns) and relationships (one-to-many, many-to-one,
many-to-many), allowing for nested data initialization.

Configuration for the behavior of `auto_init` can be provided via a
`model_config` attribute on the SQLAlchemy model class, using fields
defined in `AutoInitConfig`.
"""

from collections.abc import Callable
from functools import wraps
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import MANYTOMANY, MANYTOONE, ONETOMANY, Session
from sqlalchemy.orm.mapper import Mapper
from sqlalchemy.orm.relationships import RelationshipProperty
from sqlalchemy.sql.base import ColumnCollection

from .. import SqlAlchemyBase
from .helpers import safe_call


def _default_exclusion() -> set[str]:
    """
    Returns the default set of attributes to exclude from auto-initialization.
    By default, excludes the 'id' attribute.
    """
    return {"id"}


class AutoInitConfig(BaseModel):
    """
    Configuration class for the `auto_init` decorator.

    This Pydantic model defines settings that can be specified in a SQLAlchemy
    model's `model_config` to customize the behavior of `auto_init`.

    Attributes:
        get_attr (str | None): The attribute name to use for looking up existing
            related instances. If None, the primary key of the related class is used.
            Defaults to None.
        exclude (set): A set of attribute names to exclude from automatic
            initialization. Defaults to `{"id"}`.
    """

    get_attr: str | None = None
    exclude: set = Field(default_factory=_default_exclusion)
    # auto_create: bool = False # Potential future feature


def _get_config(model_cls: type[SqlAlchemyBase]) -> AutoInitConfig:
    """
    Retrieves the `AutoInitConfig` for a given SQLAlchemy model class.

    It looks for a `model_config` attribute (expected to be a Pydantic ConfigDict)
    on the model class and merges its values with the default `AutoInitConfig`.

    Args:
        model_cls (type[SqlAlchemyBase]): The SQLAlchemy model class.

    Returns:
        AutoInitConfig: The resolved configuration for auto-initialization.
    """
    cfg = AutoInitConfig()
    cfg_keys = cfg.model_fields.keys()  # Use model_fields for Pydantic v2

    # Get the config from the class's model_config attribute
    try:
        # In Pydantic v2, model_config is a dict, not an attribute of the class itself.
        # Accessing it directly might be tricky if it's not a standard Pydantic model.
        # Assuming model_cls might have a Pydantic-style ConfigDict.
        class_model_config: ConfigDict | None = getattr(model_cls, "model_config", None)
        if class_model_config:
            for attr_name, value in class_model_config.items():
                if attr_name in cfg_keys:
                    setattr(cfg, attr_name, value)
    except AttributeError:
        # No model_config found on the class, use default AutoInitConfig
        pass

    return cfg


def get_lookup_attr(relation_cls: type[SqlAlchemyBase]) -> str:
    """
    Determines the attribute name to use for looking up instances of a related class.

    It first checks the `AutoInitConfig` for `get_attr`. If not specified,
    it defaults to the name of the first primary key column of the related class.
    If that also fails, it defaults to "id".

    Args:
        relation_cls (type[SqlAlchemyBase]): The SQLAlchemy model class of the related objects.

    Returns:
        str: The attribute name to use for lookups.
    """
    cfg = _get_config(relation_cls)

    try:
        lookup_attribute = cfg.get_attr
        if lookup_attribute is None:
            # Get the name of the first primary key column
            pk_columns = relation_cls.__table__.primary_key.columns
            lookup_attribute = pk_columns.keys()[0] if pk_columns else "id"
    except Exception:
        lookup_attribute = "id"  # Fallback
    return lookup_attribute


def handle_many_to_many(session: Session, get_attr: str, relation_cls: type[SqlAlchemyBase], all_elements: list[dict]) -> list[SqlAlchemyBase]:
    """
    Handles the initialization or update of objects in a many-to-many relationship.

    This function is essentially a proxy to `handle_one_to_many_list` as the logic
    for finding existing elements or preparing new ones is similar for list-based
    relationships.

    Args:
        session (Session): The active SQLAlchemy session.
        get_attr (str): The attribute name used to look up existing related instances.
        relation_cls (type[SqlAlchemyBase]): The class of the related objects.
        all_elements (list[dict]): A list of dictionaries, where each dictionary
            contains data for a related object.

    Returns:
        list[SqlAlchemyBase]: A list of initialized or updated SQLAlchemy model instances.
    """
    return handle_one_to_many_list(session, get_attr, relation_cls, all_elements)


def handle_one_to_many_list(
    session: Session,
    get_attr: str,
    relation_cls: type[SqlAlchemyBase],
    all_elements: list[dict] | list[str] | list[UUID],  # Added list[UUID]
) -> list[SqlAlchemyBase]:
    """
    Handles initialization or update of a list of related objects (one-to-many or many-to-many).

    For each element in `all_elements`:
    - If the element is a dictionary and an existing related object is found using `get_attr`,
      the existing object is updated with the dictionary's values (excluding configured exclusions).
    - If the element is a dictionary and no existing object is found, it's prepared for creation.
    - If the element is a string or UUID (assumed to be an ID), it attempts to fetch the existing object.

    Args:
        session (Session): The active SQLAlchemy session.
        get_attr (str): The attribute name used to look up existing related instances.
        relation_cls (type[SqlAlchemyBase]): The class of the related objects.
        all_elements (list[dict] | list[str] | list[UUID]): A list of dictionaries (data for new/updated objects)
            or strings/UUIDs (IDs of existing objects).

    Returns:
        list[SqlAlchemyBase]: A list of new or updated SQLAlchemy model instances.
    """
    elems_to_create_data: list[dict] = []
    final_elements_list: list[SqlAlchemyBase] = []
    cfg = _get_config(relation_cls)

    for elem_data in all_elements:
        existing_elem: SqlAlchemyBase | None = None
        elem_id = None

        if isinstance(elem_data, dict):
            elem_id = elem_data.get(get_attr)
        elif isinstance(elem_data, (str | UUID)):  # Handle direct IDs
            elem_id = elem_data

        if elem_id is not None:
            stmt = select(relation_cls).filter_by(**{get_attr: elem_id})
            existing_elem = session.execute(stmt).scalars().one_or_none()

        if existing_elem:
            if isinstance(elem_data, dict):  # Update if full data provided
                for key, value in elem_data.items():
                    if key not in cfg.exclude:  # Respect exclusions
                        setattr(existing_elem, key, value)
            final_elements_list.append(existing_elem)
        elif isinstance(elem_data, dict):  # Prepare for creation if not found and data is dict
            elems_to_create_data.append(elem_data)
        # If elem_data is just an ID and not found, it's skipped (could add logging or error)

    # Create new elements if any data was provided for them
    newly_created_elems = [safe_call(relation_cls, data.copy(), session=session) for data in elems_to_create_data]
    final_elements_list.extend(filter(None, newly_created_elems))  # Add successfully created items

    return final_elements_list


def auto_init():  # sourcery no-metrics
    """
    A decorator that wraps the `__init__` method of a SQLAlchemy model class
    to automatically set attributes from keyword arguments.

    It handles simple column attributes and relationships (one-to-many,
    many-to-one, many-to-many), allowing for nested initialization of related
    objects.

    The behavior can be customized via `AutoInitConfig` settings in the model's
    `model_config`. A `session` keyword argument is required during model
    instantiation when using this decorator.

    Example:
        ```python
        from sqlalchemy.orm import Session
        from .base import SqlAlchemyBase # Assuming your Base is here
        from .auto_init import auto_init

        class User(SqlAlchemyBase):
            __tablename__ = "users"
            id = Column(Integer, primary_key=True)
            name = Column(String)
            # ... other columns and relationships

            @auto_init()
            def __init__(self, *, session: Session, **kwargs):
                # The 'session' kwarg is captured by auto_init
                # Original __init__ can be empty or have pre/post logic
                pass
        ```
    """

    def decorator(init_method: Callable):
        @wraps(init_method)
        def wrapper(self: SqlAlchemyBase, *args, **kwargs):
            """
            Custom initializer that processes keyword arguments to set model attributes.

            It iterates through `kwargs`:
            - If a key matches a model column, the attribute is set.
            - If a key matches a mapped relationship, it processes the related data:
                - For one-to-many list relationships, it calls `handle_one_to_many_list`.
                - For simple one-to-many (non-list), it initializes the related object.
                - For many-to-one, it fetches or initializes the related object based on provided ID or data.
                - For many-to-many, it calls `handle_many_to_many`.
            - Requires a `session` keyword argument for database operations.
            - Attributes listed in `exclude` (from `AutoInitConfig`) are skipped.

            Inspired by a solution for nested Pydantic models in FastAPI:
            Ref: https://github.com/tiangolo/fastapi/issues/2194
            """
            cls = self.__class__
            current_config = _get_config(cls)
            exclude = current_config.exclude

            alchemy_mapper: Mapper = self.__mapper__
            model_columns: ColumnCollection = alchemy_mapper.columns
            relationships = alchemy_mapper.relationships

            session: Session = kwargs.get("session", None)

            if session is None:
                raise ValueError("Session is required to initialize the model with `auto_init`")

            for key, val in kwargs.items():
                if key in exclude:
                    continue

                if not hasattr(cls, key):
                    continue
                    # raise TypeError(f"Invalid keyword argument: {key}")

                if key in model_columns:
                    setattr(self, key, val)
                    continue

                if key in relationships:
                    prop: RelationshipProperty = relationships[key]

                    # Identifies the type of relationship (ONETOMANY, MANYTOONE, many-to-one, many-to-many)
                    relation_dir = prop.direction

                    # Identifies the parent class of the related object.
                    relation_cls: type[SqlAlchemyBase] = prop.mapper.entity

                    # Identifies if the relationship was declared with use_list=True
                    use_list: bool = prop.uselist

                    get_attr = get_lookup_attr(relation_cls)

                    if relation_dir == ONETOMANY and use_list:
                        instances = handle_one_to_many_list(session, get_attr, relation_cls, val)
                        setattr(self, key, instances)

                    elif relation_dir == ONETOMANY:
                        instance = safe_call(relation_cls, val.copy() if val else None, session=session)
                        setattr(self, key, instance)

                    elif relation_dir == MANYTOONE and not use_list:
                        if isinstance(val, dict):
                            val = val.get(get_attr)

                            if val is None:
                                raise ValueError(f"Expected 'id' to be provided for {key}")

                        if isinstance(val, str | int | UUID):
                            stmt = select(relation_cls).filter_by(**{get_attr: val})
                            instance = session.execute(stmt).scalars().one_or_none()
                            setattr(self, key, instance)
                        else:
                            # If the value is not of the type defined above we assume that it isn't a valid id
                            # and try a different approach.
                            pass

                    elif relation_dir == MANYTOMANY:
                        instances = handle_many_to_many(session, get_attr, relation_cls, val)
                        setattr(self, key, instances)

            return init_method(self, *args, **kwargs)

        return wrapper

    return decorator
