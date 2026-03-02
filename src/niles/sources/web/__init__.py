"""Web GUI package — re-exports for backward compatibility.

All public names previously importable from ``niles.sources.web`` remain
available at the same path.  Sub-modules register their routes on the
shared ``router`` via side-effect imports below.
"""

from ._core import (  # noqa: F401 — public re-exports
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    _CHAT_PAGE_SIZE,
    _get_session_user,
    _require_admin,
    _require_auth_and_csrf,
    _verify_csrf,
    router,
    templates,
)

# Side-effect imports: each module registers @router routes on import.
from . import (  # noqa: F401, E402
    _admin,
    _auth,
    _briefing,
    _calendar,
    _chat,
    _contacts,
    _settings,
    _signal,
    _vikunja,
    _weather,
    _whatsapp,
)

# Re-export route functions and helpers used by tests.
from ._admin import (  # noqa: F401, E402
    admin_create_user,
    admin_delete_user,
    admin_reset_password,
    admin_users_page,
)
from ._auth import (  # noqa: F401, E402
    _login_attempts,
    callback_google,
    login_google,
    login_page,
    login_submit,
    logout,
)
from ._briefing import briefing_test  # noqa: F401, E402
from ._calendar import (  # noqa: F401, E402
    _GCAL_OAUTH_COOKIE,
    callback_google_calendar,
    caldav_calendars,
    calendar_source_add,
    calendar_source_remove,
    calendar_source_sync,
    calendar_sources_list,
    google_calendar_connect,
)
from ._chat import (  # noqa: F401, E402
    chat_clear,
    chat_history,
    chat_page,
    chat_send,
    chat_stream,
)
from ._contacts import (  # noqa: F401, E402
    contacts_connect,
    contacts_disconnect,
    contacts_status,
    contacts_sync,
)
from ._settings import (  # noqa: F401, E402
    ollama_models,
    settings_page,
    update_setting,
)
from ._signal import (  # noqa: F401, E402
    _ensure_signal_listener,
    signal_disconnect,
    signal_link,
    signal_qrcode,
    signal_status,
)
from ._vikunja import (  # noqa: F401, E402
    vikunja_connect,
    vikunja_disconnect,
    vikunja_status,
)
from ._weather import (  # noqa: F401, E402
    weather_location_remove,
    weather_location_search,
    weather_location_set,
)
from ._whatsapp import (  # noqa: F401, E402
    whatsapp_connect,
    whatsapp_disconnect,
    whatsapp_status,
)
