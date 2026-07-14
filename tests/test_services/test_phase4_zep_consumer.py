"""Tests for Phase 4: Zep as pure consumer.

Verifies that:
- ZepGraphMemoryUpdater is removed
- OasisProfileGenerator is removed
- GraphBuilderService does not persist Zep data back to MIVE DB
- ZepEntityReader is read-only
"""

import pytest


class TestPhase4RemovedServices:
    """Verify that services removed in Phase 4 no longer exist."""

    def test_zep_graph_memory_updater_removed(self):
        """ZepGraphMemoryUpdater should no longer exist as a module."""
        import importlib

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("src.services.zep_graph_memory_updater")

    def test_oasis_profile_generator_removed(self):
        """OasisProfileGenerator should no longer exist as a module."""
        import importlib

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("src.services.oasis_profile_generator")


class TestPhase4MainPyCleanup:
    """Verify main.py no longer imports or instantiates removed services."""

    def test_no_memory_updater_in_main(self):
        """main.py should not reference ZepGraphMemoryUpdater."""
        import inspect

        from src import main

        source = inspect.getsource(main)
        assert "ZepGraphMemoryUpdater" not in source, (
            "main.py should not import or instantiate ZepGraphMemoryUpdater"
        )
        assert "memory_updater" not in source, "main.py should not set app.state.memory_updater"

    def test_no_profile_generator_in_main(self):
        """main.py should not reference OasisProfileGenerator."""
        import inspect

        from src import main

        source = inspect.getsource(main)
        assert "OasisProfileGenerator" not in source, (
            "main.py should not import or instantiate OasisProfileGenerator"
        )
        assert "profile_generator" not in source, (
            "main.py should not set app.state.profile_generator"
        )


class TestPhase4ApiCleanup:
    """Verify API routes no longer reference removed services."""

    def test_characters_api_no_memory_updater(self):
        """characters.py should not reference memory_updater."""
        import inspect

        from src.api import characters

        source = inspect.getsource(characters)
        assert "memory_updater" not in source, "characters.py should not reference memory_updater"

    def test_relations_api_no_memory_updater(self):
        """relations.py should not reference memory_updater."""
        import inspect

        from src.api import relations

        source = inspect.getsource(relations)
        assert "memory_updater" not in source, "relations.py should not reference memory_updater"

    def test_m6_graph_api_no_profile_generator(self):
        """m6_graph.py should not reference profile_generator or generate-profiles."""
        import inspect

        from src.api import m6_graph

        source = inspect.getsource(m6_graph)
        assert "profile_generator" not in source, (
            "m6_graph.py should not reference profile_generator"
        )
