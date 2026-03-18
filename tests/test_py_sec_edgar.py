import pytest


pytestmark = pytest.mark.skip(
    reason="Legacy CLI/runtime test depends on deprecated entrypoint and pre-refactor behavior."
)
