# SPDX-License-Identifier: AGPL-3.0-only
"""FastAPI dependency providers for web routes.

Replaces the `request.app.state.*` service-locator pattern with declared
`Depends()` injection. Providers read from the typed StartupContext
(`app.state.ctx`), so handlers state their dependencies in their signature and
tests inject fakes directly instead of mocking a fat app.state.
"""

from fastapi import Request

from ...actions.vikunja_setup import VikunjaSetupAction


def get_vikunja_setup(request: Request) -> VikunjaSetupAction | None:
    """Provide the VikunjaSetupAction (or None if Vikunja is not configured)."""
    ctx = getattr(request.app.state, "ctx", None)
    if ctx is not None:
        return ctx.vikunja_setup_action
    return getattr(request.app.state, "vikunja_setup_action", None)
