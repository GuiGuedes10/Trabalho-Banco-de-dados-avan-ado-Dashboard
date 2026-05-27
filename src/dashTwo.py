import ast
import os
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, Input, Output, dcc, html
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from dashboard_nav import dashboard_nav
from database.dataTratament import DETAILS_CSV, prepare_dashboard_dataframe

load_dotenv(ROOT_DIR / ".env")

APP_TITLE = "Steam Explorer"
TOP_N = 12
CHART_H = 360
CSV_PATH = ROOT_DIR / DETAILS_CSV

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
    "danger": "#ff7b72",
}

CHART_LAYOUT = dict(
    paper_bgcolor=THEME["surface"],
    plot_bgcolor=THEME["card"],
    font=dict(family="Segoe UI, system-ui, sans-serif", color=THEME["text"], size=12),
    margin=dict(l=40, r=20, t=48, b=40),
    height=CHART_H,
)

METRIC_OPTIONS = {
    "estimated_sales": "Vendas estimadas",
    "estimated_sales_base": "Vendas base (jogo)",
    "estimated_sales_dlc": "Vendas DLC",
    "estimated_income": "Receita estimada",
    "total_reviews": "Reviews na Steam",
    "price_brl": "Preco (BRL)",
    "metacritic.score": "Metacritic",
    "community_review_factor": "Fator da comunidade",
}

AXIS_OPTIONS = [
    {"label": "Vendas estimadas", "value": "estimated_sales"},
    {"label": "Receita estimada", "value": "estimated_income"},
    {"label": "Reviews na Steam", "value": "total_reviews"},
    {"label": "Preco (BRL)", "value": "price_brl"},
    {"label": "Metacritic", "value": "metacritic.score"},
    {"label": "Vendas base (jogo)", "value": "estimated_sales_base"},
    {"label": "Vendas DLC", "value": "estimated_sales_dlc"},
]

RANKING_OPTIONS = [
    {"label": label, "value": value}
    for value, label in METRIC_OPTIONS.items()
    if value in {"estimated_sales", "estimated_income", "total_reviews", "metacritic.score"}
]

DEFAULT_COMPARE_X = "price_brl"
DEFAULT_COMPARE_Y = "estimated_sales"
DEFAULT_RANKING_METRIC = "estimated_sales"


def resolve_metric(metric, default):
    if metric in METRIC_OPTIONS:
        return metric
    return default


def metric_label(metric, default=""):
    return METRIC_OPTIONS.get(resolve_metric(metric, default), "Metrica")


def numeric_column(df, column):
    if column not in df.columns:
        return pd.Series(0, index=df.index, dtype=float)
    return pd.to_numeric(df[column], errors="coerce")


def safe_load_data():
    if not CSV_PATH.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(CSV_PATH)
        return prepare_explorer_dataframe(df)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def prepare_explorer_dataframe(df):
    df = prepare_dashboard_dataframe(df)
    if df.empty:
        return df
    df = df.copy()
    df["genre_list"] = df["genres"].apply(parse_genres)
    df["primary_genre"] = df["genre_list"].apply(
        lambda items: items[0] if items else "Sem genero"
    )
    df["release_year"] = pd.to_datetime(
        df["release_date.date"], errors="coerce"
    ).dt.year.fillna(0).astype(int)
    df["is_windows"] = boolean_series(df, "platforms.windows")
    df["is_mac"] = boolean_series(df, "platforms.mac")
    df["is_linux"] = boolean_series(df, "platforms.linux")
    df["platform_bucket"] = df.apply(platform_bucket, axis=1)
    return df


def parse_genres(value):
    if pd.isna(value) or not str(value).strip():
        return []
    try:
        items = ast.literal_eval(str(value).strip())
    except (ValueError, SyntaxError):
        return []
    if not isinstance(items, list):
        return []
    labels = []
    for item in items:
        if isinstance(item, dict):
            desc = item.get("description")
            if desc:
                labels.append(str(desc).strip())
    return labels


def platform_bucket(row):
    labels = []
    if bool(row.get("is_windows")):
        labels.append("Windows")
    if bool(row.get("is_mac")):
        labels.append("Mac")
    if bool(row.get("is_linux")):
        labels.append("Linux")
    if not labels:
        return "Sem plataforma"
    return " / ".join(labels)


def boolean_series(df, column):
    if column in df.columns:
        return df[column].fillna(False).astype(bool)
    return pd.Series(False, index=df.index, dtype=bool)


def fmt_compact(value):
    value = float(value or 0)
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f} bi"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f} M"
    if value >= 1_000:
        return f"{value / 1_000:.0f} mil"
    return f"{value:.0f}"


def fmt_brl(value):
    value = float(value or 0)
    if value >= 1_000_000_000:
        return f"R$ {value / 1_000_000_000:.2f} bi"
    if value >= 1_000_000:
        return f"R$ {value / 1_000_000:.1f} M"
    return f"R$ {value:,.0f}"


def empty_figure(title, message):
    fig = go.Figure()
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text=title, x=0, font=dict(size=14)),
        annotations=[
            dict(
                text=message,
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=13, color=THEME["muted"]),
            )
        ],
    )
    return fig


def slider_marks(min_value, max_value, prefix="", suffix=""):
    min_value = int(min_value)
    max_value = int(max_value)
    if min_value == max_value:
        return {min_value: f"{prefix}{min_value}{suffix}"}
    step = max(1, (max_value - min_value) // 4)
    values = [min_value, min_value + step, min_value + 2 * step, min_value + 3 * step, max_value]
    return {
        int(v): f"{prefix}{int(v)}{suffix}"
        for v in sorted({min_value, max_value, *values})
    }


def initial_state(df):
    genres = sorted(
        {
            genre
            for items in df.get("genre_list", pd.Series(dtype=object))
            for genre in items
        }
    )
    max_price = int(df["price_brl"].fillna(0).max()) if not df.empty else 0
    valid_years = df.loc[df["release_year"] > 0, "release_year"] if not df.empty else pd.Series(dtype=int)
    min_year = int(valid_years.min()) if not valid_years.empty else 2000
    max_year = int(valid_years.max()) if not valid_years.empty else 2026
    return {
        "genres": genres,
        "price_range": [0, max(1, max_price)],
        "year_range": [min_year, max_year],
    }


def filter_dataframe(df, genres, platforms, price_range, year_range, dlc_mode):
    if df.empty:
        return df
    filtered = df.copy()

    if genres:
        selected = set(genres)
        filtered = filtered[
            filtered["genre_list"].apply(lambda items: bool(selected.intersection(items)))
        ]

    if platforms:
        platform_mask = pd.Series(False, index=filtered.index)
        platform_map = {
            "Windows": "is_windows",
            "Mac": "is_mac",
            "Linux": "is_linux",
        }
        for platform in platforms:
            column = platform_map.get(platform)
            if column in filtered.columns:
                platform_mask = platform_mask | filtered[column].fillna(False)
        filtered = filtered[platform_mask]

    if price_range:
        filtered = filtered[
            filtered["price_brl"].fillna(0).between(price_range[0], price_range[1])
        ]

    if year_range:
        filtered = filtered[
            filtered["release_year"].between(year_range[0], year_range[1])
        ]

    if dlc_mode == "with_dlc":
        filtered = filtered[filtered["has_dlc"]]
    elif dlc_mode == "without_dlc":
        filtered = filtered[~filtered["has_dlc"]]

    return filtered


def build_kpis(df):
    if df.empty:
        values = [
            ("Jogos filtrados", "0", "Nenhum titulo atende aos filtros"),
            ("Vendas estimadas", "0", "Base + DLC"),
            ("Receita estimada", "R$ 0", "Preco efetivo"),
            ("Preco medio", "R$ 0", "Somente catalogo filtrado"),
            ("Reviews", "0", "Soma do recorte"),
            ("Metacritic medio", "—", "Somente jogos com nota"),
        ]
    else:
        meta = df["metacritic.score"].dropna()
        avg_price = df["price_brl"].replace(0, pd.NA).mean()
        values = [
            ("Jogos filtrados", f"{len(df):,}", f"{df['primary_genre'].nunique():,} generos visiveis"),
            ("Vendas estimadas", fmt_compact(df["estimated_sales"].sum()), "Base + DLC"),
            ("Receita estimada", fmt_brl(df["estimated_income"].sum()), "Preco efetivo x vendas"),
            ("Preco medio", fmt_brl(avg_price if pd.notna(avg_price) else 0), "Jogos com preco em BRL"),
            ("Reviews", fmt_compact(df["total_reviews"].fillna(0).sum()), "Soma do recorte"),
            (
                "Metacritic medio",
                f"{meta.mean():.0f}" if len(meta) else "—",
                "Somente jogos com nota",
            ),
        ]
    return [
        html.Div(
            className="kpi-card",
            children=[
                html.Span(label, className="kpi-label"),
                html.Strong(value, className="kpi-value"),
                html.Span(hint, className="kpi-hint"),
            ],
        )
        for label, value, hint in values
    ]


def chart_top_games(df, metric):
    metric = resolve_metric(metric, DEFAULT_RANKING_METRIC)
    title = f"Top {TOP_N} - {metric_label(metric).lower()}"
    if df.empty:
        return empty_figure(title, "Sem dados para o recorte atual.")
    values = numeric_column(df, metric).fillna(0)
    top = df.assign(_sort=values).nlargest(TOP_N, "_sort").sort_values("_sort")
    colors = [THEME["success"] if has_dlc else THEME["accent"] for has_dlc in top["has_dlc"]]
    fig = go.Figure(
        go.Bar(
            y=top["name_short"],
            x=top["_sort"],
            orientation="h",
            marker=dict(color=colors, line=dict(width=0)),
            hovertemplate="%{y}<br>%{x:,.0f}<extra></extra>",
        )
    )
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text=title, x=0, font=dict(size=14)),
        xaxis=dict(showgrid=True, gridcolor=THEME["border"], title=""),
        yaxis=dict(showgrid=False),
        showlegend=False,
    )
    return fig


def chart_compare(df, x_metric, y_metric):
    x_metric = resolve_metric(x_metric, DEFAULT_COMPARE_X)
    y_metric = resolve_metric(y_metric, DEFAULT_COMPARE_Y)
    x_label = metric_label(x_metric)
    y_label = metric_label(y_metric)
    title = f"Comparacao - {x_label} x {y_label}"
    if df.empty:
        return empty_figure(title, "Ajuste os filtros para gerar pontos.")

    plot = df.copy()
    plot["_x"] = numeric_column(plot, x_metric)
    plot["_y"] = numeric_column(plot, y_metric)
    plot["_size"] = numeric_column(plot, "total_reviews").fillna(0).clip(lower=0)
    plot = plot.dropna(subset=["_x", "_y"])
    if plot.empty:
        return empty_figure(title, "Nenhum jogo com valores validos nas duas metricas.")

    top_genres = plot["primary_genre"].value_counts().head(8).index
    plot["genre_group"] = plot["primary_genre"].where(plot["primary_genre"].isin(top_genres), "Outros")
    size_col = "_size" if plot["_size"].max() > 0 else None
    fig = px.scatter(
        plot,
        x="_x",
        y="_y",
        color="genre_group",
        size=size_col,
        size_max=28,
        hover_name="name",
        hover_data={
            "price_brl": ":.2f",
            "release_year": True,
            "genre_group": True,
            "total_reviews": ":,.0f",
        },
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig.update_traces(marker=dict(opacity=0.75, line=dict(width=0)))
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text=title, x=0, font=dict(size=14)),
        xaxis=dict(showgrid=True, gridcolor=THEME["border"], title=x_label),
        yaxis=dict(showgrid=True, gridcolor=THEME["border"], title=y_label),
        legend_title_text="Genero",
    )
    return fig


def has_sales_scenarios(df):
    return (
        not df.empty
        and "estimated_sales_pessimistic" in df.columns
        and "estimated_sales_optimistic" in df.columns
    )


def chart_top_sales_scenario(df):
    title = "Top 10 - faixa pessimista / estimativa / otimista"
    if df.empty:
        return empty_figure(title, "Sem dados para comparar cenarios.")
    if not has_sales_scenarios(df):
        return empty_figure(title, "Colunas pessimista/otimista ausentes no CSV.")

    top = df.nlargest(TOP_N, "estimated_sales").sort_values("estimated_sales")
    mid = top["estimated_sales"]
    low = top["estimated_sales_pessimistic"]
    high = top["estimated_sales_optimistic"]
    err_plus = (high - mid).clip(lower=0)
    err_minus = (mid - low).clip(lower=0)

    fig = go.Figure(
        go.Bar(
            y=top["name_short"],
            x=mid,
            orientation="h",
            marker=dict(color=THEME["accent"], line=dict(width=0)),
            error_x=dict(
                type="data",
                symmetric=False,
                array=err_plus,
                arrayminus=err_minus,
                color=THEME["warn"],
                thickness=1.5,
                width=4,
            ),
            hovertemplate=(
                "%{y}<br>Estimativa: %{x:,.0f}<br>"
                "Pessimista: %{customdata[0]:,.0f}<br>"
                "Otimista: %{customdata[1]:,.0f}<extra></extra>"
            ),
            customdata=list(zip(low, high)),
        )
    )
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text=title, x=0, font=dict(size=14)),
        xaxis=dict(showgrid=True, gridcolor=THEME["border"], title=""),
        yaxis=dict(showgrid=False),
        showlegend=False,
    )
    return fig


def chart_catalog_scenario_totals(df):
    title = "Catalogo inteiro - soma dos cenarios"
    if df.empty:
        return empty_figure(title, "Sem dados para resumir os cenarios.")
    if not has_sales_scenarios(df):
        return empty_figure(title, "Colunas pessimista/otimista ausentes no CSV.")

    labels = ["Pessimista", "Mediana", "Otimista"]
    values = [
        df["estimated_sales_pessimistic"].sum(),
        df["estimated_sales"].sum(),
        df["estimated_sales_optimistic"].sum(),
    ]
    colors = [THEME["border"], THEME["accent"], THEME["success"]]
    fig = go.Figure(
        go.Bar(
            x=labels,
            y=values,
            marker=dict(color=colors, line=dict(width=0)),
            text=[fmt_compact(v) for v in values],
            textposition="outside",
            textfont=dict(size=11, color=THEME["text"]),
            hovertemplate="%{x}<br>%{y:,.0f} vendas<extra></extra>",
        )
    )
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text=title, x=0, font=dict(size=14)),
        xaxis=dict(showgrid=False, title=""),
        yaxis=dict(showgrid=True, gridcolor=THEME["border"], title=""),
        showlegend=False,
    )
    return fig


def chart_platform_donut(df, selected_platforms):
    title = "Plataformas no recorte"
    platform_map = {
        "Windows": "is_windows",
        "Mac": "is_mac",
        "Linux": "is_linux",
    }
    if not selected_platforms:
        return empty_figure(title, "Selecione ao menos uma plataforma.")
    if df.empty:
        return empty_figure(title, "Sem jogos para distribuir entre plataformas.")
    counts = {
        label: int(df[column].sum())
        for label, column in platform_map.items()
        if label in selected_platforms
    }
    values = [value for value in counts.values() if value > 0]
    labels = [label for label, value in counts.items() if value > 0]
    if not values:
        return empty_figure(title, "Nenhum jogo com as plataformas selecionadas.")
    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.58,
            marker=dict(colors=[THEME["accent"], THEME["success"], THEME["warn"]]),
            textinfo="label+percent",
            hovertemplate="%{label}<br>%{value} jogos<extra></extra>",
        )
    )
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text=title, x=0, font=dict(size=14)),
        showlegend=False,
    )
    return fig


def chart_price_histogram(df):
    title = "Distribuicao de preco (BRL)"
    if df.empty:
        return empty_figure(title, "Sem preco para analisar.")
    plot = df[df["price_brl"] > 0].copy()
    if plot.empty:
        return empty_figure(title, "Os jogos filtrados nao possuem preco em BRL.")
    fig = px.histogram(
        plot,
        x="price_brl",
        nbins=20,
        color="has_dlc",
        color_discrete_map={True: THEME["success"], False: THEME["accent"]},
    )
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text=title, x=0, font=dict(size=14)),
        xaxis=dict(showgrid=False, title="Preco (BRL)"),
        yaxis=dict(showgrid=True, gridcolor=THEME["border"], title="Jogos"),
        legend_title_text="Tem DLC",
        bargap=0.08,
    )
    return fig


def chart_genre_treemap(df, metric):
    metric = resolve_metric(metric, DEFAULT_RANKING_METRIC)
    title = f"Genero x {metric_label(metric).lower()}"
    if df.empty:
        return empty_figure(title, "Sem dados para organizar por genero.")
    plot = df.copy()
    plot["_value"] = numeric_column(plot, metric)
    exploded = plot[["genre_list", "_value"]].explode("genre_list").rename(columns={"genre_list": "genre"})
    exploded = exploded.dropna(subset=["genre"])
    if exploded.empty:
        return empty_figure(title, "Os jogos filtrados nao possuem genero estruturado.")
    grouped = (
        exploded.groupby("genre", as_index=False)["_value"]
        .sum()
        .sort_values("_value", ascending=False)
        .head(12)
    )
    fig = px.treemap(
        grouped,
        path=["genre"],
        values="_value",
        color="_value",
        color_continuous_scale=["#2a475e", "#66c0f4", "#a4d007"],
    )
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text=title, x=0, font=dict(size=14)),
        coloraxis_showscale=False,
    )
    return fig


def genre_boxplot_outliers(df, value_col, group_col, factor=1.5):
    parts = []
    for _, group in df.groupby(group_col):
        values = group[value_col]
        q1, q3 = values.quantile(0.25), values.quantile(0.75)
        iqr = q3 - q1
        if iqr <= 0:
            continue
        low = q1 - factor * iqr
        high = q3 + factor * iqr
        parts.append(group[(values < low) | (values > high)])
    if not parts:
        return df.iloc[0:0]
    return pd.concat(parts)


def chart_genre_boxplot(df, metric):
    metric = resolve_metric(metric, DEFAULT_RANKING_METRIC)
    title = f"Dispersao por genero - {metric_label(metric).lower()}"
    if df.empty:
        return empty_figure(title, "Sem dados para dispersao por genero.")
    plot_df = df.copy()
    plot_df["_value"] = numeric_column(plot_df, metric)
    exploded = plot_df[["name", "genre_list", "_value"]].explode("genre_list").rename(columns={"genre_list": "genre"})
    exploded = exploded.dropna(subset=["genre", "_value"])
    if exploded.empty:
        return empty_figure(title, "Os jogos filtrados nao possuem genero estruturado.")
    top_genres = exploded["genre"].value_counts().head(8).index
    plot = exploded[exploded["genre"].isin(top_genres)].copy()
    plot["label"] = plot["name"].astype(str).str.slice(0, 24)
    fig = px.box(
        plot,
        x="genre",
        y="_value",
        color="genre",
        color_discrete_sequence=px.colors.qualitative.Set2,
        points=False,
    )
    outliers = genre_boxplot_outliers(plot, "_value", "genre")
    if not outliers.empty:
        fig.add_trace(
            go.Scatter(
                x=outliers["genre"],
                y=outliers["_value"],
                mode="markers+text",
                text=outliers["label"],
                textposition="top center",
                textfont=dict(size=9, color=THEME["text"]),
                marker=dict(
                    size=8,
                    color=THEME["danger"],
                    line=dict(width=1, color="#ffffff"),
                ),
                hovertext=outliers["name"],
                hoverinfo="text",
                showlegend=False,
            )
        )
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text=title, x=0, font=dict(size=14)),
        xaxis=dict(showgrid=False, title="Genero"),
        yaxis=dict(showgrid=True, gridcolor=THEME["border"], title=metric_label(metric)),
        showlegend=False,
    )
    return fig


INITIAL_DF = safe_load_data()
STATE = initial_state(INITIAL_DF)

app = Dash(__name__)
app.title = APP_TITLE

app.layout = html.Div(
    className="explorer-app",
    children=[
        html.Div(
            className="page-shell",
            children=[
                html.Header(
                    className="page-header",
                    children=[
                        html.Div(
                            children=[
                                html.P("Dashboard exploratorio", className="eyebrow"),
                                html.H1("Steam Explorer", className="page-title"),
                                html.P(
                                    "Explore o catalogo pago com filtros, comparacoes entre variaveis e visoes mais detalhadas do dataset.",
                                    className="page-subtitle",
                                ),
                            ]
                        ),
                        dashboard_nav("explorer"),
                    ],
                ),
                html.Section(
                    className="filter-panel",
                    children=[
                        html.Div(
                            className="section-header",
                            children=[
                                html.H2("Filtros globais", className="section-title"),
                                html.P(
                                    "Esses filtros afetam todo o recorte do dashboard. Controles especificos ficam acima dos graficos relacionados.",
                                    className="section-desc",
                                ),
                            ],
                        ),
                        html.Div(
                            className="filter-grid",
                            children=[
                                html.Div(
                                    className="filter-card filter-card-primary",
                                    children=[
                                        html.Label("Categorias / generos", className="filter-label"),
                                        dcc.Dropdown(
                                            id="genre-filter",
                                            options=[{"label": genre, "value": genre} for genre in STATE["genres"]],
                                            multi=True,
                                            placeholder="Selecione um ou mais generos",
                                        ),
                                    ],
                                ),
                                html.Div(
                                    className="filter-card filter-card-compact",
                                    children=[
                                        html.Label("Plataformas", className="filter-label"),
                                        dcc.Checklist(
                                            id="platform-filter",
                                            options=[
                                                {"label": "Windows", "value": "Windows"},
                                                {"label": "Mac", "value": "Mac"},
                                                {"label": "Linux", "value": "Linux"},
                                            ],
                                            value=["Windows", "Mac", "Linux"],
                                            className="chip-list",
                                            inline=True,
                                        ),
                                    ],
                                ),
                                html.Div(
                                    className="filter-card filter-card-compact",
                                    children=[
                                        html.Label("Somente jogos com DLC?", className="filter-label"),
                                        dcc.RadioItems(
                                            id="dlc-filter",
                                            options=[
                                                {"label": "Todos", "value": "all"},
                                                {"label": "Com DLC", "value": "with_dlc"},
                                                {"label": "Sem DLC", "value": "without_dlc"},
                                            ],
                                            value="all",
                                            className="chip-list",
                                            inline=True,
                                        ),
                                    ],
                                ),
                                html.Div(
                                    className="filter-card filter-card-half",
                                    children=[
                                        html.Label("Faixa de preco (BRL)", className="filter-label"),
                                        dcc.RangeSlider(
                                            id="price-filter",
                                            min=STATE["price_range"][0],
                                            max=STATE["price_range"][1],
                                            value=STATE["price_range"],
                                            marks=slider_marks(
                                                STATE["price_range"][0],
                                                STATE["price_range"][1],
                                                prefix="R$ ",
                                            ),
                                            tooltip={"placement": "bottom", "always_visible": False},
                                        ),
                                    ],
                                ),
                                html.Div(
                                    className="filter-card filter-card-half",
                                    children=[
                                        html.Label("Ano de lancamento", className="filter-label"),
                                        dcc.RangeSlider(
                                            id="year-filter",
                                            min=STATE["year_range"][0],
                                            max=STATE["year_range"][1],
                                            value=STATE["year_range"],
                                            marks=slider_marks(
                                                STATE["year_range"][0],
                                                STATE["year_range"][1],
                                            ),
                                            tooltip={"placement": "bottom", "always_visible": False},
                                        ),
                                    ],
                                ),
                            ],
                        )
                    ],
                ),
                html.Div(id="explorer-summary", className="summary-text"),
                html.Div(id="kpi-row", className="kpi-grid"),
                html.Section(
                    className="chart-section",
                    children=[
                        html.Div(
                            className="charts-2",
                            children=[
                                html.Div(
                                    className="chart-card",
                                    children=[
                                        html.Div(
                                            className="chart-card-head",
                                            children=[
                                                html.Div(
                                                    children=[
                                                        html.H3("Ranking principal", className="chart-title"),
                                                        html.P(
                                                            "Top jogos no recorte filtrado.",
                                                            className="chart-desc",
                                                        ),
                                                    ]
                                                ),
                                                html.Div(
                                                    className="chart-controls chart-controls-single",
                                                    children=[
                                                        html.Label("Ordenar por", className="chart-control-label"),
                                                        dcc.Dropdown(
                                                            id="ranking-metric",
                                                            options=RANKING_OPTIONS,
                                                            value="estimated_sales",
                                                            clearable=False,
                                                        ),
                                                    ],
                                                ),
                                            ],
                                        ),
                                        dcc.Graph(id="top-games-chart", config={"displayModeBar": False}),
                                    ],
                                ),
                                html.Div(
                                    className="chart-card",
                                    children=[
                                        html.Div(
                                            className="chart-card-head",
                                            children=[
                                                html.Div(
                                                    children=[
                                                        html.H3("Comparacao entre variaveis", className="chart-title"),
                                                        html.P(
                                                            "Cruze duas metricas para encontrar relacoes e outliers.",
                                                            className="chart-desc",
                                                        ),
                                                    ]
                                                ),
                                                html.Div(
                                                    className="chart-controls",
                                                    children=[
                                                        html.Div(
                                                            className="chart-control",
                                                            children=[
                                                                html.Label("Eixo X", className="chart-control-label"),
                                                                dcc.Dropdown(
                                                                    id="x-metric",
                                                                    options=AXIS_OPTIONS,
                                                                    value="price_brl",
                                                                    clearable=False,
                                                                ),
                                                            ],
                                                        ),
                                                        html.Div(
                                                            className="chart-control",
                                                            children=[
                                                                html.Label("Eixo Y", className="chart-control-label"),
                                                                dcc.Dropdown(
                                                                    id="y-metric",
                                                                    options=AXIS_OPTIONS,
                                                                    value="estimated_sales",
                                                                    clearable=False,
                                                                ),
                                                            ],
                                                        ),
                                                    ],
                                                ),
                                            ],
                                        ),
                                        dcc.Graph(id="scatter-chart", config={"displayModeBar": False}),
                                    ],
                                ),
                            ],
                        ),
                        html.Div(
                            className="charts-2",
                            children=[
                                html.Div(
                                    className="chart-card",
                                    children=[
                                        html.Div(
                                            className="chart-card-head",
                                            children=[
                                                html.Div(
                                                    children=[
                                                        html.H3("Composicao por genero", className="chart-title"),
                                                        html.P(
                                                            "Distribuicao agregada do recorte por genero.",
                                                            className="chart-desc",
                                                        ),
                                                    ]
                                                ),
                                                html.Div(
                                                    className="chart-controls chart-controls-single",
                                                    children=[
                                                        html.Label("Metrica do genero", className="chart-control-label"),
                                                        dcc.Dropdown(
                                                            id="genre-metric",
                                                            options=RANKING_OPTIONS,
                                                            value="estimated_sales",
                                                            clearable=False,
                                                        ),
                                                    ],
                                                ),
                                            ],
                                        ),
                                        dcc.Graph(id="treemap-chart", config={"displayModeBar": False}),
                                    ],
                                ),
                                html.Div(
                                    className="chart-card",
                                    children=[
                                        html.Div(
                                            className="chart-card-head",
                                            children=[
                                                html.Div(
                                                    children=[
                                                        html.H3("Plataformas no recorte", className="chart-title"),
                                                        html.P(
                                                            "Mostra apenas as plataformas marcadas no filtro global.",
                                                            className="chart-desc",
                                                        ),
                                                    ]
                                                ),
                                            ],
                                        ),
                                        dcc.Graph(id="platform-chart", config={"displayModeBar": False}),
                                    ],
                                ),
                            ],
                        ),
                        html.Div(
                            className="charts-2",
                            children=[
                                html.Div(
                                    className="chart-card",
                                    children=[
                                        html.Div(
                                            className="chart-card-head",
                                            children=[
                                                html.Div(
                                                    children=[
                                                        html.H3("Distribuicao de preco", className="chart-title"),
                                                        html.P(
                                                            "Histograma do preco em BRL para o recorte atual.",
                                                            className="chart-desc",
                                                        ),
                                                    ]
                                                ),
                                            ],
                                        ),
                                        dcc.Graph(id="histogram-chart", config={"displayModeBar": False}),
                                    ],
                                ),
                                html.Div(
                                    className="chart-card",
                                    children=[
                                        html.Div(
                                            className="chart-card-head",
                                            children=[
                                                html.Div(
                                                    children=[
                                                        html.H3("Dispersao por genero", className="chart-title"),
                                                        html.P(
                                                            "Variacao da metrica escolhida entre os generos dominantes.",
                                                            className="chart-desc",
                                                        ),
                                                    ]
                                                ),
                                            ],
                                        ),
                                        dcc.Graph(id="boxplot-chart", config={"displayModeBar": False}),
                                    ],
                                ),
                            ],
                        ),
                        html.Div(
                            className="charts-2",
                            children=[
                                html.Div(
                                    className="chart-card",
                                    children=[
                                        html.Div(
                                            className="chart-card-head",
                                            children=[
                                                html.Div(
                                                    children=[
                                                        html.H3("Faixa de estimativas", className="chart-title"),
                                                        html.P(
                                                            "Comparacao entre cenario pessimista, estimativa e otimista no Top 10.",
                                                            className="chart-desc",
                                                        ),
                                                    ]
                                                ),
                                            ],
                                        ),
                                        dcc.Graph(id="scenario-top-chart", config={"displayModeBar": False}),
                                    ],
                                ),
                                html.Div(
                                    className="chart-card",
                                    children=[
                                        html.Div(
                                            className="chart-card-head",
                                            children=[
                                                html.Div(
                                                    children=[
                                                        html.H3("Soma dos cenarios", className="chart-title"),
                                                        html.P(
                                                            "Impacto dos cenarios no catalogo inteiro filtrado.",
                                                            className="chart-desc",
                                                        ),
                                                    ]
                                                ),
                                            ],
                                        ),
                                        dcc.Graph(id="scenario-total-chart", config={"displayModeBar": False}),
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )
    ],
)


@app.callback(
    Output("explorer-summary", "children"),
    Output("kpi-row", "children"),
    Output("top-games-chart", "figure"),
    Output("scatter-chart", "figure"),
    Output("treemap-chart", "figure"),
    Output("platform-chart", "figure"),
    Output("histogram-chart", "figure"),
    Output("boxplot-chart", "figure"),
    Output("scenario-top-chart", "figure"),
    Output("scenario-total-chart", "figure"),
    Input("genre-filter", "value"),
    Input("platform-filter", "value"),
    Input("price-filter", "value"),
    Input("year-filter", "value"),
    Input("dlc-filter", "value"),
    Input("ranking-metric", "value"),
    Input("genre-metric", "value"),
    Input("x-metric", "value"),
    Input("y-metric", "value"),
)
def update_dashboard(
    genres,
    platforms,
    price_range,
    year_range,
    dlc_mode,
    ranking_metric,
    genre_metric,
    x_metric,
    y_metric,
):
    df = safe_load_data()
    filtered = filter_dataframe(df, genres, platforms, price_range, year_range, dlc_mode)
    summary = (
        f"{len(filtered):,} jogos encontrados no recorte atual."
        if not filtered.empty
        else "Nenhum jogo encontrado com os filtros atuais."
    )
    return (
        summary,
        build_kpis(filtered),
        chart_top_games(filtered, ranking_metric),
        chart_compare(filtered, x_metric, y_metric),
        chart_genre_treemap(filtered, genre_metric),
        chart_platform_donut(filtered, platforms),
        chart_price_histogram(filtered),
        chart_genre_boxplot(filtered, genre_metric),
        chart_top_sales_scenario(filtered),
        chart_catalog_scenario_totals(filtered),
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
            * { box-sizing: border-box; text-decoration: none; }
            body { margin: 0; background: #0e1419; color: #c7d5e0; font-family: Segoe UI, system-ui, sans-serif; }
            .explorer-app { min-height: 100vh; background: linear-gradient(180deg, #0e1419 0%, #13202c 100%); }
            .page-shell { max-width: 1440px; margin: 0 auto; padding: 28px 32px 40px; }
            .page-header {
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                gap: 20px;
                flex-wrap: wrap;
                margin-bottom: 20px;
            }
            .dashboard-nav { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
            .dashboard-nav-link {
                color: #c7d5e0;
                font-size: 0.85rem;
                font-weight: 600;
                padding: 8px 14px;
                border: 1px solid #3d5a73;
                border-radius: 999px;
                background: rgba(42, 71, 94, 0.5);
            }
            .dashboard-nav-link:hover { border-color: #66c0f4; color: #fff; }
            .dashboard-nav-link.is-active {
                background: rgba(102, 192, 244, 0.18);
                border-color: #66c0f4;
                color: #66c0f4;
            }
            .eyebrow { color: #66c0f4; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.12em; margin: 0 0 8px 0; font-weight: 700; }
            .page-title { margin: 0; font-size: clamp(2rem, 3vw, 3.1rem); line-height: 1.05; }
            .page-subtitle { margin: 10px 0 0; color: #8f98a0; font-size: 1rem; max-width: 880px; }
            .filter-panel, .chart-section { margin-top: 22px; }
            .section-header { margin-bottom: 14px; }
            .section-title { margin: 0; font-size: 1.05rem; }
            .section-desc { margin: 6px 0 0; color: #8f98a0; font-size: 0.92rem; }
            .filter-grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 16px; }
            .filter-card { background: linear-gradient(180deg, rgba(27, 40, 56, 0.98) 0%, rgba(18, 31, 44, 0.98) 100%); border: 1px solid rgba(102, 192, 244, 0.26); border-radius: 18px; padding: 18px; box-shadow: 0 14px 34px rgba(0, 0, 0, 0.22); }
            .filter-card-primary { grid-column: span 6; }
            .filter-card-compact { grid-column: span 3; }
            .filter-card-half { grid-column: span 6; }
            .filter-label { display: block; margin-bottom: 12px; font-size: 0.84rem; font-weight: 700; color: #c7d5e0; }
            .filter-card:hover { border-color: rgba(102, 192, 244, 0.42); }
            .summary-text { margin-top: 18px; color: #8f98a0; font-size: 0.96rem; }
            .kpi-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 14px; margin-top: 18px; }
            .kpi-card { background: rgba(27, 40, 56, 0.88); border: 1px solid #3d5a73; border-radius: 16px; padding: 16px 18px; min-height: 112px; display: flex; flex-direction: column; justify-content: space-between; box-shadow: 0 10px 25px rgba(0, 0, 0, 0.18); }
            .kpi-label { color: #8f98a0; font-size: 0.82rem; }
            .kpi-value { font-size: 1.5rem; line-height: 1.1; }
            .kpi-hint { color: #8f98a0; font-size: 0.8rem; }
            .charts-2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; margin-top: 18px; }
            .chart-card { background: rgba(27, 40, 56, 0.88); border: 1px solid #3d5a73; border-radius: 18px; padding: 14px 14px 8px; box-shadow: 0 14px 34px rgba(0, 0, 0, 0.2); }
            .chart-card-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; padding: 4px 8px 0; }
            .chart-title { margin: 0; font-size: 1rem; }
            .chart-desc { margin: 6px 0 0; color: #8f98a0; font-size: 0.86rem; max-width: 420px; }
            .chart-controls { display: flex; gap: 12px; min-width: 280px; }
            .chart-controls-single { min-width: 220px; max-width: 260px; }
            .chart-control { flex: 1; }
            .chart-control-label { display: block; margin-bottom: 8px; color: #8f98a0; font-size: 0.77rem; font-weight: 700; }
            .chip-list { color: #dbe6ee; }
            .chip-list label { display: inline-flex; align-items: center; gap: 8px; margin-right: 14px; color: #dbe6ee !important; font-weight: 600; }
            .chip-list label, .chip-list label * { color: #dbe6ee !important; }
            .chip-list input[type="checkbox"], .chip-list input[type="radio"] { accent-color: #b47cff; }
            .dash-dropdown .Select-control, .Select-control, .Select-menu-outer {
                background-color: #23384d !important;
                color: #dbe6ee !important;
                border-color: #4c6b86 !important;
            }
            .Select-control {
                min-height: 42px !important;
                border-radius: 12px !important;
                box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.03) !important;
            }
            .Select-placeholder,
            .Select--single > .Select-control .Select-value,
            .Select-value-label,
            .Select-input > input,
            .Select-arrow-zone,
            .Select-clear-zone,
            .Select-menu-outer,
            .Select-option,
            .Select-noresults {
                color: #dbe6ee !important;
            }
            .Select-placeholder { color: #a9bdd0 !important; }
            .is-focused:not(.is-open) > .Select-control,
            .Select-control:hover {
                border-color: #66c0f4 !important;
                box-shadow: 0 0 0 1px rgba(102, 192, 244, 0.22) !important;
            }
            .Select--multi .Select-value { background-color: #162434 !important; border-color: #4c6b86 !important; color: #dbe6ee !important; border-radius: 10px !important; }
            .VirtualizedSelectOption { background-color: #2a475e !important; color: #c7d5e0 !important; }
            .VirtualizedSelectFocusedOption { background-color: #3d5a73 !important; color: #ffffff !important; }
            .rc-slider-track { background: linear-gradient(90deg, #8b5cf6 0%, #66c0f4 100%); }
            .rc-slider-handle {
                border: 2px solid #d8b4fe;
                background-color: #8b5cf6;
                box-shadow: 0 0 0 4px rgba(180, 124, 255, 0.18);
                opacity: 1;
            }
            .rc-slider-handle:hover,
            .rc-slider-handle:active,
            .rc-slider-handle:focus {
                border-color: #f0abfc;
                box-shadow: 0 0 0 6px rgba(180, 124, 255, 0.22);
            }
            .rc-slider-rail { background-color: #425d74; }
            .rc-slider-mark-text { color: #9fb3c7; font-size: 0.74rem; }
            .rc-slider-mark-text-active { color: #dbe6ee; }
            .rc-slider-dot { border-color: #516b83; background-color: #23384d; }
            .rc-slider-tooltip-inner {
                background-color: #162434;
                color: #dbe6ee;
                border: 1px solid #4c6b86;
            }
            @media (max-width: 1200px) {
                .filter-card-primary, .filter-card-half, .filter-card-compact { grid-column: span 6; }
                .kpi-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
                .chart-card-head { flex-direction: column; }
                .chart-controls, .chart-controls-single { width: 100%; max-width: none; min-width: 0; }
            }
            @media (max-width: 860px) {
                .page-shell { padding: 20px 16px 32px; }
                .filter-card-primary, .filter-card-half, .filter-card-compact { grid-column: span 12; }
                .charts-2 { grid-template-columns: 1fr; }
                .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
                .chart-controls { flex-direction: column; }
            }
            @media (max-width: 560px) {
                .kpi-grid { grid-template-columns: 1fr; }
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
    port = int(os.getenv("EXPLORER_DASH_PORT", "8050"))
    app.run(debug=True, port=port, use_reloader=False)
