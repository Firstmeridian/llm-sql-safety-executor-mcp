"""One explicitly reset catalog fixture for pre-packaging loader regressions."""

from sql_safety_executor.skills.catalog import *

_catalog = SkillCatalog()


def discover(*args, **kwargs):
    return _catalog.discover(*args, **kwargs)


def load_query(*args, **kwargs):
    return _catalog.load_query(*args, **kwargs)


def load_mutation(*args, **kwargs):
    return _catalog.load_mutation(*args, **kwargs)


def get_skills_cache():
    return _catalog.get_skills_cache()


def reset():
    global _catalog
    _catalog = SkillCatalog()

from sql_safety_executor.skills.catalog import _load_mutation_class as _load_mutation_class
from sql_safety_executor.skills.catalog import _CONNECTION_ID_PATTERN as _CONNECTION_ID_PATTERN
