import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, html, dcc

CSV_PATH = "database/data/steam_app_details.csv"
TOP_N = 10
CHART_H = 340

THEME = {
    "bg": "#0e1419",
    "surface": "#1b2838",
    "card": "#2a475e",
    "border": "#3d5a73",
    "text": "#c7d5e0",
    "muted": "#8f98a0",
    "accent": "#66c0f4",
    "success": "#a4d007",
    "warn": "#febc0d",
}

CHART_LAYOUT = dict(
    paper_bgcolor=THEME["surface"],
    plot_bgcolor=THEME["card"],
    font=dict(family="Segoe UI, system-ui, sans-serif", color=THEME["text"], size=12),
    margin=dict(l=40, r=20, t=48, b=40),
    height=CHART_H,
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
        df["estimated_downloads_base"].fillna(0) + df["estimated_downloads_dlc"].fillna(0)
    )
    df["estimated_income"] = df["estimated_income"].fillna(0)
    df["price_brl"] = df["price_overview.final"].fillna(0) / 100
    df["name_short"] = df["name"].astype(str).str.slice(0, 28)
    df["has_dlc"] = df["estimated_downloads_dlc"].fillna(0) > 0
    return df


def fmt_compact(value):
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


def compute_kpis(df):
    top_dl = df.loc[df["estimated_downloads"].idxmax()]
    top_inc = df.loc[df["estimated_income"].idxmax()]
    meta = df["metacritic.score"].dropna()
    return {
        "games": len(df),
        "downloads_total": df["estimated_downloads"].sum(),
        "income_total": df["estimated_income"].sum(),
        "reviews_total": int(df["total_reviews"].fillna(0).sum()),
        "avg_price": df["price_brl"].replace(0, pd.NA).mean(),
        "with_dlc": int(df["has_dlc"].sum()),
        "avg_downloads": df["estimated_downloads"].mean(),
        "metacritic_avg": meta.mean() if len(meta) else None,
        "top_downloads_name": top_dl["name"],
        "top_downloads_val": top_dl["estimated_downloads"],
        "top_income_name": top_inc["name"],
        "top_income_val": top_inc["estimated_income"],
    }


def kpi_row(kpis):
    cards = [
        ("Jogos analisados", f"{kpis['games']:,}", "Catálogo pago · BRL"),
        ("Downloads estimados", fmt_compact(kpis["downloads_total"]), "Base + DLC"),
        ("Receita estimada", fmt_brl(kpis["income_total"]), "Downloads × preço efetivo"),
        ("Reviews na Steam", fmt_compact(kpis["reviews_total"]), "Soma do catálogo"),
        ("Preço médio", fmt_brl(kpis["avg_price"]) if pd.notna(kpis["avg_price"]) else "—", "Loja BR"),
        ("Com DLC ativo", f"{kpis['with_dlc']:,}", f"{100 * kpis['with_dlc'] / max(kpis['games'], 1):.0f}% do catálogo"),
    ]
    return html.Div(
        className="kpi-grid",
        children=[
            html.Div(
                className="kpi-card",
                children=[
                    html.Span(label, className="kpi-label"),
                    html.Strong(value, className="kpi-value"),
                    html.Span(hint, className="kpi-hint"),
                ],
            )
            for label, value, hint in cards
        ],
    )


def highlight_strip(kpis):
    return html.Div(
        className="highlight-strip",
        children=[
            html.Div(
                className="highlight-item",
                children=[
                    html.Span("Maior alcance", className="highlight-label"),
                    html.Strong(kpis["top_downloads_name"], className="highlight-title"),
                    html.Span(
                        fmt_compact(kpis["top_downloads_val"]) + " downloads est.",
                        className="highlight-metric",
                    ),
                ],
            ),
            html.Div(
                className="highlight-item accent",
                children=[
                    html.Span("Maior receita est.", className="highlight-label"),
                    html.Strong(kpis["top_income_name"], className="highlight-title"),
                    html.Span(fmt_brl(kpis["top_income_val"]), className="highlight-metric"),
                ],
            ),
        ],
    )


def chart_top_downloads(df):
    top = df.nlargest(TOP_N, "estimated_downloads").sort_values("estimated_downloads")
    fig = go.Figure(
        go.Bar(
            y=top["name_short"],
            x=top["estimated_downloads"],
            orientation="h",
            marker=dict(color=THEME["accent"], line=dict(width=0)),
            text=[fmt_compact(v) for v in top["estimated_downloads"]],
            textposition="outside",
            textfont=dict(size=11, color=THEME["text"]),
            hovertemplate="%{y}<br>%{x:,.0f} downloads<extra></extra>",
        )
    )
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text="Top 10 — downloads estimados", x=0, font=dict(size=14)),
        xaxis=dict(showgrid=True, gridcolor=THEME["border"], title=""),
        yaxis=dict(showgrid=False),
        showlegend=False,
    )
    return fig


def chart_top_income(df):
    top = df[df["estimated_income"] > 0].nlargest(TOP_N, "estimated_income")
    top = top.sort_values("estimated_income")
    fig = go.Figure(
        go.Bar(
            y=top["name_short"],
            x=top["estimated_income"],
            orientation="h",
            marker=dict(color=THEME["success"], line=dict(width=0)),
            text=[fmt_brl(v) for v in top["estimated_income"]],
            textposition="outside",
            textfont=dict(size=11, color=THEME["text"]),
            hovertemplate="%{y}<br>%{x:,.0f}<extra></extra>",
        )
    )
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text="Top 10 — receita estimada (BRL)", x=0, font=dict(size=14)),
        xaxis=dict(showgrid=True, gridcolor=THEME["border"], title=""),
        yaxis=dict(showgrid=False),
        showlegend=False,
    )
    return fig


def chart_download_tiers(df):
    bins = [0, 50_000, 200_000, 1_000_000, float("inf")]
    labels = ["< 50 mil", "50k – 200k", "200k – 1M", "> 1M"]
    tier = pd.cut(df["estimated_downloads"], bins=bins, labels=labels, right=False)
    counts = tier.value_counts().reindex(labels)
    fig = go.Figure(
        go.Pie(
            labels=counts.index.astype(str),
            values=counts.values,
            hole=0.55,
            marker=dict(colors=[THEME["border"], THEME["accent"], THEME["success"], THEME["warn"]]),
            textinfo="label+percent",
            textfont=dict(size=11),
            hovertemplate="%{label}<br>%{value} jogos (%{percent})<extra></extra>",
        )
    )
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text="Distribuição por faixa de downloads", x=0, font=dict(size=14)),
        showlegend=False,
    )
    return fig


def chart_reviews_efficiency(df):
    plot = df[(df["total_reviews"] > 0) & (df["estimated_downloads_base"] > 0)].copy()
    fig = px.scatter(
        plot,
        x="total_reviews",
        y="estimated_downloads_base",
        size="price_brl",
        size_max=22,
        opacity=0.65,
        color_discrete_sequence=[THEME["accent"]],
        hover_name="name",
        labels={
            "total_reviews": "Reviews",
            "estimated_downloads_base": "Downloads base",
        },
    )
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text="Reviews vs downloads (escala log)", x=0, font=dict(size=14)),
        xaxis=dict(type="log", gridcolor=THEME["border"]),
        yaxis=dict(type="log", gridcolor=THEME["border"]),
    )
    fig.update_traces(marker=dict(line=dict(width=0)))
    return fig


df = load_data()
kpis = compute_kpis(df)

app = Dash(__name__)
app.title = "Steam — Painel Executivo"

app.layout = html.Div(
    className="exec-dashboard",
    children=[
        html.Header(
            className="exec-header",
            children=[
                html.Div(
                    children=[
                        html.P("Painel executivo", className="eyebrow"),
                        html.H1("Steam · jogos pagos (BRL)", className="exec-title"),
                        html.P(
                            f"{kpis['games']:,} títulos · método Boxleiter (reviews × multiplicador) · "
                            "estimativas, não dados oficiais de vendas",
                            className="exec-subtitle",
                        ),
                    ]
                ),
            ],
        ),
        kpi_row(kpis),
        highlight_strip(kpis),
        html.Section(
            className="section",
            children=[
                html.H2("Visão de mercado", className="section-title"),
                html.Div(
                    className="charts-2",
                    children=[
                        dcc.Graph(
                            figure=chart_top_downloads(df),
                            config={"displayModeBar": False},
                        ),
                        dcc.Graph(
                            figure=chart_top_income(df),
                            config={"displayModeBar": False},
                        ),
                    ],
                ),
            ],
        ),
        html.Section(
            className="section",
            children=[
                html.H2("Síntese do catálogo", className="section-title"),
                html.Div(
                    className="charts-2",
                    children=[
                        dcc.Graph(
                            figure=chart_download_tiers(df),
                            config={"displayModeBar": False},
                        ),
                        dcc.Graph(
                            figure=chart_reviews_efficiency(df),
                            config={"displayModeBar": False},
                        ),
                    ],
                ),
            ],
        ),
        html.Footer(
            className="exec-footer",
            children="Fonte: steam_app_details.csv · Exclui F2P · Preços e reviews via API pública Steam",
        ),
    ],
)

app.index_string = """
<!DOCTYPE html>
<html lang="pt-BR">
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
            * { box-sizing: border-box; }
            body { margin: 0; background: #0e1419; }
            .exec-dashboard {
                min-height: 100vh;
                padding: 28px 32px 40px;
                max-width: 1400px;
                margin: 0 auto;
            }
            .exec-header { margin-bottom: 24px; }
            .eyebrow {
                color: #66c0f4;
                font-size: 0.75rem;
                text-transform: uppercase;
                letter-spacing: 0.12em;
                margin: 0 0 6px 0;
                font-weight: 600;
            }
            .exec-title {
                color: #fff;
                font-size: 1.85rem;
                font-weight: 600;
                margin: 0 0 8px 0;
            }
            .exec-subtitle {
                color: #8f98a0;
                margin: 0;
                font-size: 0.9rem;
                max-width: 720px;
                line-height: 1.45;
            }
            .kpi-grid {
                display: grid;
                grid-template-columns: repeat(6, 1fr);
                gap: 12px;
                margin-bottom: 16px;
            }
            .kpi-card {
                background: #1b2838;
                border: 1px solid #3d5a73;
                border-radius: 10px;
                padding: 16px;
            }
            .kpi-label {
                display: block;
                color: #8f98a0;
                font-size: 0.72rem;
                text-transform: uppercase;
                letter-spacing: 0.04em;
                margin-bottom: 6px;
            }
            .kpi-value {
                display: block;
                color: #fff;
                font-size: 1.25rem;
                font-weight: 600;
                line-height: 1.2;
                margin-bottom: 4px;
            }
            .kpi-hint {
                color: #66c0f4;
                font-size: 0.7rem;
            }
            .highlight-strip {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 12px;
                margin-bottom: 28px;
            }
            .highlight-item {
                background: linear-gradient(135deg, #1b2838 0%, #2a475e 100%);
                border: 1px solid #3d5a73;
                border-radius: 10px;
                padding: 18px 20px;
            }
            .highlight-item.accent { border-left: 4px solid #a4d007; }
            .highlight-item:first-child { border-left: 4px solid #66c0f4; }
            .highlight-label {
                display: block;
                color: #8f98a0;
                font-size: 0.72rem;
                text-transform: uppercase;
                margin-bottom: 4px;
            }
            .highlight-title {
                display: block;
                color: #fff;
                font-size: 1.1rem;
                margin-bottom: 4px;
            }
            .highlight-metric { color: #c7d5e0; font-size: 0.95rem; }
            .section { margin-bottom: 28px; }
            .section-title {
                color: #c7d5e0;
                font-size: 1rem;
                font-weight: 600;
                margin: 0 0 12px 0;
                padding-bottom: 8px;
                border-bottom: 1px solid #3d5a73;
            }
            .charts-2 {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 16px;
            }
            .exec-footer {
                color: #5c6e7e;
                font-size: 0.75rem;
                text-align: center;
                padding-top: 16px;
            }
            @media (max-width: 1200px) {
                .kpi-grid { grid-template-columns: repeat(3, 1fr); }
            }
            @media (max-width: 900px) {
                .kpi-grid { grid-template-columns: repeat(2, 1fr); }
                .charts-2, .highlight-strip { grid-template-columns: 1fr; }
                .exec-dashboard { padding: 16px; }
            }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>{%config%}{%scripts%}{%renderer%}</footer>
    </body>
</html>
"""

if __name__ == "__main__":
    app.run(debug=True, port=8080)
