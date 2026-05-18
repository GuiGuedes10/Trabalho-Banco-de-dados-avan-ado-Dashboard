import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, html, dcc

CSV_PATH = "database/data/steam_app_details.csv"
TOP_N = 15
CHART_HEIGHT = 420

STEAM_COLORS = {
    "bg": "#1b2838",
    "panel": "#2a475e",
    "accent": "#66c0f4",
    "accent2": "#c7d5e0",
    "green": "#a4d007",
    "orange": "#febc0d",
    "grid": "#3d5a73",
}

LAYOUT_BASE = dict(
    paper_bgcolor=STEAM_COLORS["bg"],
    plot_bgcolor=STEAM_COLORS["panel"],
    font=dict(family="Segoe UI, Arial, sans-serif", color=STEAM_COLORS["accent2"]),
    margin=dict(l=48, r=24, t=56, b=48),
    height=CHART_HEIGHT,
)


def load_data():
    df = pd.read_csv(CSV_PATH)
    if "is_free" in df.columns:
        df = df[
            ~df["is_free"].apply(
                lambda v: v is True or str(v).strip().lower() in ("true", "1", "yes")
            )
        ].copy()
    df["estimated_downloads"] = (
        df["estimated_downloads_base"].fillna(0)
        + df["estimated_downloads_dlc"].fillna(0)
    )
    df["estimated_income"] = df["estimated_income"].fillna(0)
    df["price_brl"] = df["price_overview.final"].fillna(0) / 100
    df["is_free"] = df["is_free"].map({True: "Grátis", False: "Pago"})
    df["name_short"] = df["name"].str.slice(0, 32)
    return df


def fmt_number(value):
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f} bi"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f} M"
    if value >= 1_000:
        return f"{value / 1_000:.0f} mil"
    return f"{value:.0f}"


def fmt_brl(value):
    if value >= 1_000_000_000:
        return f"R$ {value / 1_000_000_000:.2f} bi"
    if value >= 1_000_000:
        return f"R$ {value / 1_000_000:.1f} M"
    return f"R$ {value:,.0f}"


def chart_top_downloads(df):
    top = df.nlargest(TOP_N, "estimated_downloads").sort_values(
        "estimated_downloads", ascending=True
    )
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=top["name_short"],
            x=top["estimated_downloads_base"],
            name="Jogo base",
            orientation="h",
            marker=dict(color=STEAM_COLORS["accent"], line=dict(width=0)),
            hovertemplate="%{y}<br>Base: %{x:,.0f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            y=top["name_short"],
            x=top["estimated_downloads_dlc"],
            name="DLC",
            orientation="h",
            marker=dict(color=STEAM_COLORS["green"], line=dict(width=0)),
            hovertemplate="%{y}<br>DLC: %{x:,.0f}<extra></extra>",
        )
    )
    fig.update_layout(
        **LAYOUT_BASE,
        title=dict(text="Top downloads estimados (base + DLC)", x=0.02, xanchor="left"),
        barmode="stack",
        xaxis=dict(title="Downloads estimados", gridcolor=STEAM_COLORS["grid"]),
        yaxis=dict(gridcolor=STEAM_COLORS["grid"]),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    return fig


def chart_reviews_vs_downloads(df):
    plot_df = df[df["total_reviews"].fillna(0) > 0].copy()
    fig = px.scatter(
        plot_df,
        x="total_reviews",
        y="estimated_downloads_base",
        color="is_free",
        size="price_brl",
        size_max=28,
        hover_name="name",
        log_x=True,
        log_y=True,
        color_discrete_map={"Pago": STEAM_COLORS["accent"], "Grátis": STEAM_COLORS["orange"]},
        labels={
            "total_reviews": "Reviews (log)",
            "estimated_downloads_base": "Downloads base (log)",
            "is_free": "Modelo",
            "price_brl": "Preço BRL",
        },
    )
    fig.update_layout(
        **LAYOUT_BASE,
        title=dict(text="Reviews × downloads — o modelo escala?", x=0.02, xanchor="left"),
        xaxis=dict(gridcolor=STEAM_COLORS["grid"]),
        yaxis=dict(gridcolor=STEAM_COLORS["grid"]),
        legend=dict(title=""),
    )
    fig.update_traces(marker=dict(opacity=0.75, line=dict(width=0)))
    return fig


def chart_top_income(df):
    paid = df[df["estimated_income"] > 0].nlargest(TOP_N, "estimated_income")
    paid = paid.sort_values("estimated_income", ascending=True)
    fig = go.Figure(
        go.Bar(
            y=paid["name_short"],
            x=paid["estimated_income"],
            orientation="h",
            marker=dict(
                color=paid["estimated_income"],
                colorscale=[[0, "#2a475e"], [0.5, "#66c0f4"], [1, "#a4d007"]],
                line=dict(width=0),
            ),
            text=[fmt_brl(v) for v in paid["estimated_income"]],
            textposition="outside",
            hovertemplate="%{y}<br>Receita est.: %{x:,.0f}<extra></extra>",
        )
    )
    fig.update_layout(
        **LAYOUT_BASE,
        title=dict(text="Top receita estimada (downloads × preço)", x=0.02, xanchor="left"),
        xaxis=dict(title="BRL (estimativa bruta)", gridcolor=STEAM_COLORS["grid"]),
        yaxis=dict(gridcolor=STEAM_COLORS["grid"]),
        showlegend=False,
    )
    return fig


def chart_dlc_impact(df):
    with_dlc = df[df["estimated_downloads_dlc"].fillna(0) > 0].copy()
    with_dlc = with_dlc.nlargest(TOP_N, "estimated_downloads_dlc").sort_values(
        "estimated_downloads_dlc", ascending=True
    )
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name="% DLC nos downloads",
            y=with_dlc["name_short"],
            x=(
                100
                * with_dlc["estimated_downloads_dlc"]
                / with_dlc["estimated_downloads"].replace(0, 1)
            ),
            orientation="h",
            marker=dict(color=STEAM_COLORS["green"], line=dict(width=0)),
            hovertemplate=(
                "%{y}<br>DLC: %{customdata[0]:,.0f} (%{x:.1f}%)<extra></extra>"
            ),
            customdata=with_dlc[["estimated_downloads_dlc"]].values,
        )
    )
    fig.update_layout(
        **LAYOUT_BASE,
        title=dict(text="Peso do DLC no total de downloads", x=0.02, xanchor="left"),
        xaxis=dict(title="% downloads vindos de DLC", gridcolor=STEAM_COLORS["grid"]),
        yaxis=dict(gridcolor=STEAM_COLORS["grid"]),
    )
    return fig


def summary_cards(df):
    total_dl = df["estimated_downloads"].sum()
    total_inc = df["estimated_income"].sum()
    with_dlc = (df["dlc_reviews"].fillna(0) > 0).sum()
    return html.Div(
        className="stats-row",
        children=[
            _stat_card("Jogos no CSV", f"{len(df):,}"),
            _stat_card("Downloads (soma)", fmt_number(total_dl)),
            _stat_card("Receita est. total", fmt_brl(total_inc)),
            _stat_card("Com reviews em DLC", f"{with_dlc:,}"),
        ],
    )


def _stat_card(label, value):
    return html.Div(
        className="stat-card",
        children=[
            html.Span(label, className="stat-label"),
            html.Strong(value, className="stat-value"),
        ],
    )


df = load_data()

app = Dash(__name__)
app.title = "Steam Dashboard"

app.layout = html.Div(
    className="dashboard",
    style={"backgroundColor": STEAM_COLORS["bg"], "minHeight": "100vh", "padding": "24px"},
    children=[
        html.Header(
            children=[
                html.H1("Steam — visão dos dados", className="title"),
                html.P(
                    f"{len(df)} títulos · estimativas a partir de reviews e preços da loja",
                    className="subtitle",
                ),
                summary_cards(df),
            ]
        ),
        html.Div(
            className="charts-grid",
            children=[
                dcc.Graph(figure=chart_top_downloads(df), config={"displayModeBar": False}),
                dcc.Graph(figure=chart_top_income(df), config={"displayModeBar": False}),
                dcc.Graph(figure=chart_reviews_vs_downloads(df), config={"displayModeBar": False}),
                dcc.Graph(figure=chart_dlc_impact(df), config={"displayModeBar": False}),
            ],
        ),
    ],
)

app.index_string = """
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
            body { margin: 0; }
            .title {
                color: #c7d5e0;
                font-size: 1.75rem;
                font-weight: 600;
                margin: 0 0 4px 0;
            }
            .subtitle {
                color: #8f98a0;
                margin: 0 0 20px 0;
                font-size: 0.95rem;
            }
            .stats-row {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
                gap: 12px;
                margin-bottom: 24px;
            }
            .stat-card {
                background: #2a475e;
                border-radius: 8px;
                padding: 14px 18px;
                border-left: 3px solid #66c0f4;
            }
            .stat-label {
                display: block;
                color: #8f98a0;
                font-size: 0.8rem;
                margin-bottom: 4px;
            }
            .stat-value {
                color: #fff;
                font-size: 1.35rem;
            }
            .charts-grid {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 16px;
            }
            @media (max-width: 1100px) {
                .charts-grid { grid-template-columns: 1fr; }
            }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
"""

if __name__ == "__main__":
    app.run(debug=True, port=8080)
