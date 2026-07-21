ROLE_ADMIN = "admin"
ROLE_SUPERUSER = "superuser"
ROLE_USER = "user"

KNOWN_ROLES = {ROLE_ADMIN, ROLE_SUPERUSER, ROLE_USER}

ROLE_LABELS = {
    ROLE_ADMIN: "Администратор",
    ROLE_SUPERUSER: "Суперпользователь",
    ROLE_USER: "Пользователь",
}

ROLE_PERMISSIONS = {
    ROLE_ADMIN: {
        "view_all_sessions",
        "delete_any_session",
        "view_all_documents",
        "manage_documents",
        "manage_users",
        "view_services",
        "search_zup_data",
    },
    ROLE_SUPERUSER: {
        "view_own_sessions",
        "delete_own_sessions",
        "view_own_documents",
        "search_zup_data",
    },
    ROLE_USER: {
        "view_own_sessions",
        "delete_own_sessions",
        "view_own_documents",
    },
}
