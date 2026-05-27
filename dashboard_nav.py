import os

from dash import html

MAIN_DASH_URL = os.getenv("MAIN_DASH_URL", "http://127.0.0.1:8080/")
EXPLORER_DASH_URL = os.getenv("EXPLORER_DASH_URL", "http://127.0.0.1:8050/")


def dashboard_nav(active):
    links = [
        ("main", "Visao executiva", MAIN_DASH_URL),
        ("explorer", "Explorar dados", EXPLORER_DASH_URL),
    ]
    return html.Nav(
        className="dashboard-nav",
        children=[
            html.A(
                label,
                href=url,
                className="dashboard-nav-link"
                + (" is-active" if key == active else ""),
            )
            for key, label, url in links
        ],
    )
