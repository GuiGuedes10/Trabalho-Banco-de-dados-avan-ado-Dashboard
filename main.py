import ast

import os
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import threading

from dash import Dash, Input, Output, dcc, html
from database.dataTratament import DETAILS_CSV, prepare_dashboard_dataframe
from database.getData import getAppDetails
from dotenv import load_dotenv

load_dotenv()

RATE_LIMIT = int(os.getenv("RATE_LIMIT", "100"))
FETCH_ON_START = os.getenv("FETCH_ON_START", "true").strip().lower() in (
    "1",
    "true",
    "yes",
)
DASH_REFRESH_MS = int(os.getenv("DASH_REFRESH_MS", "5000"))

STEAM_STORE_BASE_URL = "https://store.steampowered.com/app/"
METACRITIC_BASE_URL = "https://www.metacritic.com/game/"
STEAMDB_BASE_URL = "https://steamdb.info/app/"

_fetch_thread = None

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


def safe_load_data():
    if not os.path.exists(CSV_PATH):
        return pd.DataFrame()
    try:
        return load_data()
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def load_data():
    df = pd.read_csv(CSV_PATH)
    return prepare_dashboard_dataframe(df)


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


def _valid_header_image(url):
    return isinstance(url, str) and url.strip().startswith("http")


def compute_kpis(df):
    if df.empty:
        return {
            "games": 0,
            "downloads_total": 0,
            "income_total": 0,
            "reviews_total": 0,
            "avg_price": None,
            "with_dlc": 0,
            "avg_downloads": 0,
            "metacritic_avg": None,
            "top_downloads_name": "—",
            "top_downloads_val": 0,
            "top_downloads_img": None,
            "top_income_name": "—",
            "top_income_val": 0,
            "top_income_img": None,
        }

    top_dl = df.loc[df["estimated_downloads"].idxmax()]
    top_inc = df.loc[df["estimated_income"].idxmax()]
    meta = df["metacritic.score"].dropna()
    kpis = {
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
        "top_downloads_img": top_dl.get("header_image"),
        "top_income_name": top_inc["name"],
        "top_income_val": top_inc["estimated_income"],
        "top_income_img": top_inc.get("header_image"),
    }
    if "estimated_downloads_pessimistic" in df.columns:
        kpis["downloads_pessimistic_total"] = df["estimated_downloads_pessimistic"].sum()
        kpis["downloads_optimistic_total"] = df["estimated_downloads_optimistic"].sum()
    return kpis


def _has_download_scenarios(df):
    return (
        not df.empty
        and "estimated_downloads_pessimistic" in df.columns
        and "estimated_downloads_optimistic" in df.columns
    )


def _downloads_display(row):
    mid = row["estimated_downloads"]
    if (
        "estimated_downloads_pessimistic" not in row.index
        or "estimated_downloads_optimistic" not in row.index
    ):
        return fmt_compact(mid) + " vendas est."
    low = row["estimated_downloads_pessimistic"]
    high = row["estimated_downloads_optimistic"]
    return f"{fmt_compact(low)} – {fmt_compact(high)} vendas est."


def kpi_row(kpis):
    if kpis.get("downloads_pessimistic_total") is not None:
        sales_value = (
            f"{fmt_compact(kpis['downloads_pessimistic_total'])} – "
            f"{fmt_compact(kpis['downloads_optimistic_total'])}"
        )
        sales_hint = f"Mediana do catálogo: {fmt_compact(kpis['downloads_total'])}"
    else:
        sales_value = fmt_compact(kpis["downloads_total"])
        sales_hint = "Base + DLC ·"
    cards = [
        ("Jogos analisados", f"{kpis['games']:,}", "Catálogo pago · BRL"),
        ("Vendas estimadas", sales_value, sales_hint),
        ("Receita estimada", fmt_brl(kpis["income_total"]), "Vendas × preço efetivo"),
        ("Reviews na Steam", fmt_compact(kpis["reviews_total"]), "Soma do catálogo"),
        ("Ganhos da Steam", fmt_brl(kpis["income_total"] * 0.3), "Receita gerada para a Steam"),
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


def _highlight_card(label, name, metric, image_url, accent_class=""):
    img_block = (
        html.Img(src=image_url, className="highlight-img", alt=name)
        if _valid_header_image(image_url)
        else html.Div(className="highlight-img-placeholder", children="Sem capa")
    )
    return html.Div(
        className=f"highlight-item {accent_class}".strip(),
        children=[
            img_block,
            html.Div(
                className="highlight-body",
                children=[
                    html.Span(label, className="highlight-label"),
                    html.Strong(name, className="highlight-title"),
                    html.Span(metric, className="highlight-metric"),
                ],
            ),
        ],
    )


def highlight_strip(kpis):
    return html.Div(
        className="highlight-strip",
        children=[
            _highlight_card(
                "Maior alcance",
                kpis["top_downloads_name"],
                fmt_compact(kpis["top_downloads_val"]) + " Vendas estimadas.",
                kpis.get("top_downloads_img"),
            ),
            _highlight_card(
                "Maior receita est.",
                kpis["top_income_name"],
                fmt_brl(kpis["top_income_val"]),
                kpis.get("top_income_img"),
                accent_class="accent",
            ),
        ],
    )


def _game_card(row, rank_label):
    img_url = row.get("header_image")
    img = (
        html.Img(src=img_url, className="game-card-img", alt=row["name"])
        if _valid_header_image(img_url)
        else html.Div(className="game-card-img-placeholder", children="—")
    )
    return html.A(
        href=f"{STEAM_STORE_BASE_URL}{row['steam_appid']}/{row['name'].replace(' ', '_')}",
        target="_blank",
        rel="noopener noreferrer",
        className="game-card",
        children=[
            html.Span(rank_label, className="game-card-rank"),
            img,
            html.Div(
                className="game-card-info ",
                children=[
                    html.Strong(row["name_short"], className="game-card-title"),
                    html.A(
                        href=f"{STEAMDB_BASE_URL}{row['steam_appid']}/charts",
                        target="_blank",
                        rel="noopener noreferrer",
                        children=[fmt_compact(row["estimated_downloads"])],
                        className="game-card-stat game-card-sales",
                    ),
                    html.Span(
                        _downloads_display(row),
                        className="game-card-stat game-card-op-pess", 
                    ),
                    html.Span(
                        fmt_brl(row["estimated_income"]) if row["estimated_income"] > 0 else "—",
                        className="game-card-stat game-card-op-pess muted",
                    ),
                ],
            ),
        ],
    )


def _empty_chart(title):
    fig = go.Figure()
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text=title, x=0, font=dict(size=14)),
        annotations=[
            dict(
                text="Aguardando dados no CSV…",
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


def _genres_display(value):
    labels = _genre_labels_from_cell(value)
    return ", ".join(labels) if labels else "—"


def _metacritic_score_class(score):
    if score >= 75:
        return "meta-score-high"
    if score >= 50:
        return "meta-score-mid"
    return "meta-score-low"


def _metacritic_card(row, rank_label):
    score = float(row["metacritic.score"])
    img_url = row.get("header_image")
    hero = (
        html.Img(src=img_url, className="meta-card-header", alt=row["name"])
        if _valid_header_image(img_url)
        else html.Div(className="meta-card-header-placeholder", children="Sem capa")
    )
    income = row["estimated_income"]
    return html.A(
        className="meta-card",
        href=f"{STEAM_STORE_BASE_URL}{row['steam_appid']}/{row['name'].replace(' ', '_')}",
        target="_blank",
        rel="noopener noreferrer",
        children=[
            html.Div(
                className="meta-card-hero",
                children=[
                    hero,
                    html.Span(rank_label, className="meta-card-rank"),
                    html.A(
                        href=f"{METACRITIC_BASE_URL}{row['name'].replace(' ', '-').replace('™', '').lower()}",
                        target="_blank",
                        rel="noopener noreferrer",
                        children=
                        f"{score:.0f}",
                        className=f"meta-card-score {_metacritic_score_class(score)}",
                        title="Metacritic",
                    ),
                ],
            ),
            html.Div(
                className="meta-card-body",
                children=[
                    html.Strong(row["name"], className="meta-card-title"),
                    html.Span(_genres_display(row.get("genres")), className="meta-card-genre"),
                    html.A(
                        href=f"{STEAMDB_BASE_URL}{row['steam_appid']}/charts",
                        target="_blank",
                        rel="noopener noreferrer",
                        children=[fmt_compact(row["estimated_downloads"])],
                        className="meta-card-stat meta-card-sales",
                    ),
                    html.Span(
                        _downloads_display(row),
                        className="meta-card-stat meta-card-op-pess muted",
                    ),
                    html.Span(
                        fmt_brl(income) if income > 0 else "—",
                        className="meta-card-stat meta-card-income",
                    ),
                ],
            ),
        ],
    )


def top_metacritic_gallery(df, n=4):
    if df.empty or "metacritic.score" not in df.columns:
        return html.P("Sem notas Metacritic no catálogo ainda.", className="section-desc")

    rated = df.copy()
    rated["metacritic.score"] = pd.to_numeric(rated["metacritic.score"], errors="coerce")
    rated = rated[rated["metacritic.score"].notna()]
    if rated.empty:
        return html.P("Sem notas Metacritic no catálogo ainda.", className="section-desc")

    top = rated.nlargest(n, "metacritic.score").reset_index(drop=True)
    return html.Div(
        className="meta-gallery",
        children=[
            _metacritic_card(row, f"#{i + 1}")
            for i, row in top.iterrows()
        ],
    )


def top_games_gallery(df, n=8):
    if df.empty:
        return html.P("Aguardando coleta de dados…", className="section-desc")
    top = df.nlargest(n, "estimated_downloads").reset_index(drop=True)
    return html.Div(
        className="game-gallery",
        children=[
            _game_card(row, f"#{i + 1}")
            for i, row in top.iterrows()
        ],
    )


def chart_top_downloads(df):
    if df.empty:
        return _empty_chart("Top 10 — vendas estimadas")
    top = df.nlargest(TOP_N, "estimated_downloads").sort_values("estimated_downloads")
    base = top["estimated_downloads_base"].fillna(0)
    dlc = top["estimated_downloads_dlc"].fillna(0)
    fig = go.Figure(
        data=[
            go.Bar(
                name="Base",
                y=top["name_short"],
                x=base,
                orientation="h",
                marker=dict(color=THEME["accent"], line=dict(width=0)),
                hovertemplate="%{y}<br>Base: %{x:,.0f}<extra></extra>",
            ),
            go.Bar(
                name="DLC",
                y=top["name_short"],
                x=dlc,
                orientation="h",
                marker=dict(color=THEME["success"], line=dict(width=0)),
                hovertemplate="%{y}<br>DLC: %{x:,.0f}<extra></extra>",
            ),
        ]
    )
    fig.update_layout(
        **CHART_LAYOUT,
        barmode="stack",
        title=dict(text="Top 10 — vendas estimadas", x=0, font=dict(size=14)),
        xaxis=dict(showgrid=True, gridcolor=THEME["border"], title=""),
        yaxis=dict(showgrid=False),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            font=dict(size=11),
        ),
    )
    fig.update_traces(textposition="none")
    for i, row in top.iterrows():
        total = row["estimated_downloads"]
        fig.add_annotation(
            x=total,
            y=row["name_short"],
            text=fmt_compact(total),
            showarrow=False,
            xanchor="left",
            xshift=6,
            font=dict(size=11, color=THEME["text"]),
        )
    return fig


def chart_top_downloads_scenario(df):
    if df.empty:
        return _empty_chart("Top 10 — faixa de vendas (pess. / otim.)")
    if not _has_download_scenarios(df):
        fig = _empty_chart("Top 10 — faixa de vendas (pess. / otim.)")
        fig.update_layout(
            annotations=[
                dict(
                    text="Colunas pessimista/otimista ausentes no CSV.",
                    xref="paper",
                    yref="paper",
                    x=0.5,
                    y=0.5,
                    showarrow=False,
                    font=dict(size=13, color=THEME["muted"]),
                )
            ]
        )
        return fig

    top = df.nlargest(TOP_N, "estimated_downloads").sort_values("estimated_downloads")
    mid = top["estimated_downloads"]
    low = top["estimated_downloads_pessimistic"]
    high = top["estimated_downloads_optimistic"]
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
                "%{y}<br>Mediana: %{x:,.0f}<br>"
                "Pessimista: %{customdata[0]:,.0f}<br>"
                "Otimista: %{customdata[1]:,.0f}<extra></extra>"
            ),
            customdata=list(zip(low, high)),
        )
    )
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(
            text="Top 10 — faixa pessimista / mediana / otimista",
            x=0,
            font=dict(size=14),
        ),
        xaxis=dict(showgrid=True, gridcolor=THEME["border"], title=""),
        yaxis=dict(showgrid=False),
        showlegend=False,
    )
    return fig


def chart_catalog_scenario_totals(df):
    if df.empty:
        return _empty_chart("Catálogo — cenários de vendas")
    if not _has_download_scenarios(df):
        fig = _empty_chart("Catálogo — cenários de vendas")
        fig.update_layout(
            annotations=[
                dict(
                    text="Colunas pessimista/otimista ausentes no CSV.",
                    xref="paper",
                    yref="paper",
                    x=0.5,
                    y=0.5,
                    showarrow=False,
                    font=dict(size=13, color=THEME["muted"]),
                )
            ]
        )
        return fig

    labels = ["Pessimista", "Mediana", "Otimista"]
    values = [
        df["estimated_downloads_pessimistic"].sum(),
        df["estimated_downloads"].sum(),
        df["estimated_downloads_optimistic"].sum(),
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
        title=dict(text="Catálogo inteiro — soma dos cenários", x=0, font=dict(size=14)),
        xaxis=dict(showgrid=False, title=""),
        yaxis=dict(showgrid=True, gridcolor=THEME["border"], title=""),
        showlegend=False,
    )
    return fig


def chart_top_income(df):
    if df.empty:
        return _empty_chart("Top 10 — receita estimada (BRL)")
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
    if df.empty:
        return _empty_chart("Distribuição por faixa de vendas")
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
        title=dict(text="Distribuição por faixa de vendas", x=0, font=dict(size=14)),
        showlegend=False,
    )
    return fig

def _genre_labels_from_cell(value):
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


def chart_top_genres(df):
    if df.empty or "genres" not in df.columns:
        return _empty_chart("Top 10 — gêneros no catálogo")

    genres = (
        df["genres"]
        .dropna()
        .map(_genre_labels_from_cell)
        .explode()
        .dropna()
    )
    top = genres.value_counts().head(TOP_N).reset_index()
    top.columns = ["genre", "count"]

    if top.empty:
        return _empty_chart("Top 10 — gêneros no catálogo")

    fig = go.Figure(
        go.Bar(
            x=top["genre"],
            y=top["count"],
            marker=dict(color=THEME["accent"], line=dict(width=0)),
            text=top["count"],
            textposition="outside",
            textfont=dict(size=11, color=THEME["text"]),
            hovertemplate="%{x}<br>%{y} jogos com o gênero<extra></extra>",
        )
    )
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text="Top 10 — gêneros no catálogo", x=0, font=dict(size=14)),
        xaxis=dict(showgrid=False, title=""),
        yaxis=dict(showgrid=True, gridcolor=THEME["border"], title=""),
        showlegend=False,
    )
    return fig

def _fetch_status_banner():
    global _fetch_thread
    if _fetch_thread is not None and _fetch_thread.is_alive():
        return html.P(
            f"Coleta Steam em andamento · painel atualiza a cada {DASH_REFRESH_MS // 1000}s",
            className="live-status",
        )
    return None


def build_dashboard_body(df):
    kpis = compute_kpis(df)
    graph_cfg = {"displayModeBar": False}
    return html.Div(
        className="exec-dashboard",
        children=[
            html.Header(
                className="exec-header",
                children=[
                    html.Div(
                        children=[
                            html.P("Dashboard de Jogos Pagos", className="eyebrow"),
                            html.H1("Steam · jogos pagos (BRL)", className="exec-title"),
                            html.P(
                                f"{kpis['games']:,} títulos pagos no Steam.",
                                className="exec-subtitle",
                            ),
                        ]
                    ),
                ],
            ),
            _fetch_status_banner(),
            kpi_row(kpis),
            highlight_strip(kpis),
            html.Section(
                className="section",
                children=[
                    html.H2("Melhores no Metacritic", className="section-title"),
                    html.P(
                        "Top 4 por nota · capa Steam · downloads, receita e gênero estimados.",
                        className="section-desc",
                    ),
                    top_metacritic_gallery(df, n=4),
                ],
            ),
            html.Section(
                className="section",
                children=[
                    html.H2("Top vendas estimadas", className="section-title"),
                    top_games_gallery(df, n=8),
                ],
            ),
            html.Section(
                className="section",
                children=[
                    html.H2("Visão de mercado", className="section-title"),
                    html.Div(
                        className="charts-2",
                        children=[
                            dcc.Graph(
                                figure=chart_top_downloads(df),
                                config=graph_cfg,
                            ),
                            dcc.Graph(
                                figure=chart_top_income(df),
                                config=graph_cfg,
                            ),
                        ],
                    ),
                ],
            ),
            html.Section(
                className="section",
                children=[
                    html.H2("Incerteza das estimativas", className="section-title"),
                    html.P(
                        "Faixa pessimista / otimista no Top 10 e no total do catálogo "
                        "(não exibe jogo a jogo).",
                        className="section-desc",
                    ),
                    html.Div(
                        className="charts-2",
                        children=[
                            dcc.Graph(
                                figure=chart_top_downloads_scenario(df),
                                config=graph_cfg,
                            ),
                            dcc.Graph(
                                figure=chart_catalog_scenario_totals(df),
                                config=graph_cfg,
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
                                config=graph_cfg,
                            ),
                            dcc.Graph(
                                figure=chart_top_genres(df),
                                config=graph_cfg,
                            ),
                        ],
                    ),
                ],
            ),
            html.Footer(
                className="exec-footer",
                children=(
                    "Fonte: steamWebApi · Exclui F2P lifeservice · "
                    "Preços e reviews via API pública Steam"
                ),
            ),
        ],
    )


def start_background_fetch():
    global _fetch_thread
    if _fetch_thread is not None and _fetch_thread.is_alive():
        return

    def _run():
        try:
            getAppDetails(limit=RATE_LIMIT)
        except Exception as exc:
            print(f"Coleta encerrada com erro: {exc}")

    _fetch_thread = threading.Thread(target=_run, daemon=True, name="steam-fetch")
    _fetch_thread.start()
    print("Coleta Steam iniciada em segundo plano.")


app = Dash(__name__)
app.title = "Steam — Dashboard de Jogos Pagos"

app.layout = html.Div(
    children=[
        dcc.Interval(
            id="refresh-interval",
            interval=DASH_REFRESH_MS,
            n_intervals=0,
        ),
        html.Div(id="dashboard-root"),
    ],
)


@app.callback(
    Output("dashboard-root", "children"),
    Input("refresh-interval", "n_intervals"),
)
def refresh_dashboard(_n):
    return build_dashboard_body(safe_load_data())

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
            .live-status {
                color: #a4d007;
                font-size: 0.85rem;
                margin: 12px 0 16px 0;
                padding: 8px 12px;
                background: rgba(164, 208, 7, 0.08);
                border: 1px solid rgba(164, 208, 7, 0.25);
                border-radius: 6px;
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
                transition: transform 0.15s ease, border-color 0.15s ease;
                cursor: pointer;
            }
            .kpi-card:hover {
                transform: scale(1.02);
                border-color: #66c0f4;
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
                cursor: pointer;
                transition: transform 0.15s ease, border-color 0.15s ease;
            }
            .highlight-strip:hover {
                transform: scale(1.02);
                border-color: #66c0f4;
            }
            .highlight-item {
                display: flex;
                gap: 16px;
                align-items: stretch;
                background: linear-gradient(135deg, #1b2838 0%, #2a475e 100%);
                border: 1px solid #3d5a73;
                border-radius: 10px;
                padding: 14px;
                overflow: hidden;
            }
            .highlight-item.accent { border-left: 4px solid #a4d007; }
            .highlight-item:not(.accent) { border-left: 4px solid #66c0f4; }
            .highlight-img {
                width: 200px;
                min-width: 200px;
                height: 94px;
                object-fit: cover;
                border-radius: 6px;
                border: 1px solid #3d5a73;
            }
            .highlight-img-placeholder {
                width: 200px;
                min-width: 200px;
                height: 94px;
                display: flex;
                align-items: center;
                justify-content: center;
                background: #1b2838;
                color: #8f98a0;
                font-size: 0.75rem;
                border-radius: 6px;
            }
            .highlight-body { flex: 1; display: flex; flex-direction: column; justify-content: center; }
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
            .section-desc {
                color: #8f98a0;
                font-size: 0.85rem;
                margin: -4px 0 14px 0;
            }
            .meta-gallery {
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 14px;
            }
            .meta-card {
                background: #1b2838;
                border: 1px solid #3d5a73;
                border-radius: 10px;
                overflow: hidden;
                transition: transform 0.15s ease, border-color 0.15s ease;
            }
            .meta-card:hover {
                transform: translateY(-2px);
                border-color: #66c0f4;
            }
            .meta-card-hero {
                position: relative;
            }
            .meta-card-header {
                width: 100%;
                height: 132px;
                object-fit: cover;
                display: block;
            }
            .meta-card-header-placeholder {
                width: 100%;
                height: 132px;
                display: flex;
                align-items: center;
                justify-content: center;
                background: #2a475e;
                color: #8f98a0;
                font-size: 0.8rem;
            }
            .meta-card-rank {
                position: absolute;
                top: 8px;
                left: 8px;
                z-index: 1;
                background: rgba(14, 20, 25, 0.88);
                color: #66c0f4;
                font-size: 0.7rem;
                font-weight: 700;
                padding: 2px 8px;
                border-radius: 4px;
            }

            .meta-card-score {
                position: absolute;
                bottom: 8px;
                right: 8px;
                z-index: 1;
                min-width: 44px;
                text-align: center;
                font-size: 1.35rem;
                font-weight: 800;
                line-height: 1;
                padding: 6px 10px;
                border-radius: 6px;
                border: 2px solid rgba(0, 0, 0, 0.35);
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.45);
                cursor: pointer;
                transition: transform 0.15s ease, border-color 0.15s ease;
            }
            .meta-card-score:hover {
                transform: scale(1.08);
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.75);
            }
            .meta-score-high {
                background: #4c6b22;
                color: #e8ffb0;
            }
            .meta-score-mid {
                background: #8b6914;
                color: #fff3c4;
            }
            .meta-score-low {
                background: #6b3a22;
                color: #ffd4c4;
            }
            .meta-card-body {
                padding: 12px 12px 14px;
            }
            .meta-card-title {
                display: block;
                color: #fff;
                font-size: 0.9rem;
                line-height: 1.3;
                margin-bottom: 6px;
            }
            .meta-card-genre {
                display: block;
                color: #8f98a0;
                font-size: 0.75rem;
                margin-bottom: 8px;
                line-height: 1.35;
            }
            .meta-card-stat {
                display: block;
                color: #66c0f4;
                font-size: 0.78rem;
            }
            .meta-card-stat.meta-card-sales {
                cursor: pointer;
                transition: transform 0.15s ease, border-color 0.15s ease;
            }
            .meta-card-stat.meta-card-sales:hover {
                text-decoration: underline;
                transform: scale(1.02);
            }
            .meta-card-stat.meta-card-op-pess.muted {
                color: #FFAC1C;
                margin-top: 2px;
                font-size: 10px;
            }
            .meta-card-income {
                color: #a4d007;
                margin-top: 3px;
            }
            .game-gallery {
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 14px;
            }
            .game-card {
                position: relative;
                background: #1b2838;
                border: 1px solid #3d5a73;
                border-radius: 10px;
                overflow: hidden;
                transition: transform 0.15s ease, border-color 0.15s ease;
            }
            .game-card:hover {
                transform: translateY(-2px);
                border-color: #66c0f4;
            }
            .game-card-rank {
                position: absolute;
                top: 8px;
                left: 8px;
                z-index: 1;
                background: rgba(14, 20, 25, 0.85);
                color: #66c0f4;
                font-size: 0.7rem;
                font-weight: 700;
                padding: 2px 8px;
                border-radius: 4px;
            }
            .game-card-img {
                width: 100%;
                height: 118px;
                object-fit: cover;
                display: block;
            }
            .game-card-img-placeholder {
                width: 100%;
                height: 118px;
                display: flex;
                align-items: center;
                justify-content: center;
                background: #2a475e;
                color: #8f98a0;
                font-size: 1.25rem;
            }
            .game-card-info {
                padding: 10px 12px 12px;
            }
            .game-card-title {
                display: block;
                color: #fff;
                font-size: 0.88rem;
                margin-bottom: 6px;
                line-height: 1.25;
            }
            .game-card-stat {
                display: block;
                color: #66c0f4;
                font-size: 0.78rem;
            }
            .game-card-stat.game-card-sales {
                cursor: pointer;
                transition: transform 0.15s ease, border-color 0.15s ease;
            }
            .game-card-stat.game-card-sales:hover {
                text-decoration: underline;
                transform: scale(1.02);
            }
            .game-card-stat.muted { color: #a4d007; margin-top: 2px; }
            .section { margin-bottom: 28px; }
            .section-title {
                color: #c7d5e0;
                font-size: 1rem;
                font-weight: 600;
                margin: 0 0 12px 0;
                padding-bottom: 8px;
                border-bottom: 1px solid #3d5a73;
            }
            .game-card-op-pess {
                font-size: 10px;
                color: #FFAC1C;
                margin-top: 2px;
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
                .meta-gallery, .game-gallery { grid-template-columns: repeat(2, 1fr); }
                .highlight-item { flex-direction: column; }
                .highlight-img, .highlight-img-placeholder {
                    width: 100%;
                    min-width: unset;
                }
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
    if FETCH_ON_START:
        start_background_fetch()
    app.run(port=8080, use_reloader=False)
