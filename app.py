# ============================================
# app.py — Backend & Intelligent Data/Chart Engine
# Lumina Insights (3-File Architecture)
# ============================================

import os
import io
import uuid
import re
import urllib.request
import sqlite3
from collections import Counter
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_file, session
from werkzeug.utils import secure_filename
import pandas as pd
import numpy as np
from scipy import stats
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

import database

app = Flask(__name__, template_folder=".", static_folder=".")
app.secret_key = os.getenv("SECRET_KEY", "lumina-neutral-light-key-2026")
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024
app.config["UPLOAD_FOLDER"] = os.path.join(os.path.dirname(__file__), "uploads")

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
database.init_db()

_active_datasets = {}
ALLOWED_EXTENSIONS = {"csv", "xlsx", "xls", "sqlite", "db"}

STOPWORDS = {
    "the", "and", "to", "of", "a", "in", "for", "is", "on", "that", "by", "this",
    "with", "i", "you", "it", "not", "or", "be", "are", "from", "at", "as", "your",
    "all", "have", "new", "more", "an", "was", "we", "will", "my", "has", "would",
    "can", "if", "dear", "sir", "mr", "mrs", "please", "me", "am", "us", "our",
    "any", "so", "but", "there", "what", "which", "who", "when", "one", "their", "they"
}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# ----------------------------------------------------
# INTELLIGENT DATA ENGINE
# ----------------------------------------------------
class DataEngine:
    @staticmethod
    def load_and_clean(filepath):
        ext = os.path.splitext(filepath)[1].lower()
        if ext == ".csv":
            df = pd.read_csv(filepath, encoding="utf-8", on_bad_lines="skip")
        elif ext in [".xlsx", ".xls"]:
            df = pd.read_excel(filepath)
        else:
            raise ValueError("Unsupported file format.")

        return DataEngine.clean_dataframe(df)

    @staticmethod
    def clean_dataframe(df):
        clean_cols = []
        for i, c in enumerate(df.columns):
            c_str = str(c).strip()
            if not c_str or c_str.lower().startswith("unnamed") or c_str.lower() in ["nan", "null"]:
                clean_cols.append(f"field_{i+1}")
            else:
                clean_cols.append(c_str.lower().replace(" ", "_").replace("-", "_").replace(":", "_"))
        df.columns = clean_cols
        df.drop_duplicates(inplace=True)

        for col in df.columns:
            if df[col].dtype == "object":
                converted = pd.to_numeric(df[col], errors="coerce")
                if converted.notna().sum() >= len(df) * 0.7 and converted.notna().sum() > 0:
                    df[col] = converted

        return df

    @staticmethod
    def analyze_columns(df):
        num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        str_cols = df.select_dtypes(include=["object"]).columns.tolist()

        binary_cols = []
        metric_cols = []
        id_cols = []

        for c in num_cols:
            unq = df[c].nunique()
            if unq == 2:
                binary_cols.append(c)
            elif unq > len(df) * 0.9 and unq > 50:
                id_cols.append(c)
            else:
                metric_cols.append(c)

        long_text_cols = []
        short_cat_cols = []

        for c in str_cols:
            sample_str = df[c].dropna().astype(str)
            avg_len = sample_str.str.len().mean() if len(sample_str) > 0 else 0
            if avg_len > 60:
                long_text_cols.append(c)
            else:
                short_cat_cols.append(c)

        return {
            "numeric": metric_cols,
            "binary": binary_cols,
            "id": id_cols,
            "short_categorical": short_cat_cols,
            "long_text": long_text_cols
        }

    @staticmethod
    def get_kpis(df):
        cols_info = DataEngine.analyze_columns(df)
        kpis = []

        kpis.append({
            "label": "Total Records",
            "value": f"{len(df):,}",
            "sub": f"{len(df.columns)} Columns Analyzed",
            "type": "count",
            "icon": "fas fa-database",
            "color": "teal"
        })

        for b_col in cols_info["binary"][:2]:
            val_counts = df[b_col].value_counts()
            pos_val = val_counts.index.max()
            pos_cnt = val_counts.get(pos_val, 0)
            pct = round(pos_cnt / len(df) * 100, 1) if len(df) > 0 else 0
            kpis.append({
                "label": f"{b_col.replace('_', ' ').title()} Rate",
                "value": f"{pct}%",
                "sub": f"{pos_cnt:,} Positive Flagged",
                "type": "percentage",
                "icon": "fas fa-shield-halved",
                "color": "clay"
            })

        for m_col in cols_info["numeric"][:3]:
            tot = df[m_col].sum()
            avg = df[m_col].mean()
            val_str = f"{tot:,.2f}" if tot > 1000 else f"{avg:,.2f}"
            lbl_prefix = "Total" if tot > 1000 else "Average"
            kpis.append({
                "label": f"{lbl_prefix} {m_col.replace('_', ' ').title()}",
                "value": val_str,
                "sub": f"Max: {df[m_col].max():,.2f} • Min: {df[m_col].min():,.2f}" if len(df) > 0 else "N/A",
                "type": "metric",
                "icon": "fas fa-chart-line",
                "color": "teal"
            })

        for c_col in cols_info["short_categorical"][:2]:
            unq = df[c_col].dropna().nunique()
            mode_val = df[c_col].mode()
            top_str = mode_val.iloc[0] if not mode_val.empty else "N/A"
            kpis.append({
                "label": f"Unique {c_col.replace('_', ' ').title()}",
                "value": f"{unq:,}",
                "sub": f"Top: {str(top_str)[:25]}",
                "type": "category",
                "icon": "fas fa-layer-group",
                "color": "sand"
            })

        for t_col in cols_info["long_text"][:1]:
            avg_words = df[t_col].dropna().astype(str).apply(lambda x: len(x.split())).mean() if len(df) > 0 else 0
            kpis.append({
                "label": f"{t_col.replace('_', ' ').title()} Length",
                "value": f"{int(avg_words)} Words",
                "sub": "Average Text Entry Volume",
                "type": "text",
                "icon": "fas fa-file-lines",
                "color": "slate"
            })

        return kpis[:6]

    @staticmethod
    def get_data_health(df):
        health = []
        total_rows = len(df)
        cols_info = DataEngine.analyze_columns(df)

        for col in df.columns:
            non_null = int(df[col].notna().sum())
            missing = total_rows - non_null
            pct_complete = round(non_null / total_rows * 100, 1) if total_rows > 0 else 0
            unique_count = int(df[col].nunique())

            if col in cols_info["binary"]:
                col_type = "Binary Flag"
            elif col in cols_info["numeric"]:
                col_type = "Numeric Metric"
            elif col in cols_info["long_text"]:
                col_type = "Text Document"
            elif col in cols_info["id"]:
                col_type = "Identifier"
            else:
                col_type = "Category"

            status = "Healthy" if pct_complete >= 95 else ("Moderate" if pct_complete >= 80 else "Sparse")
            status_color = "teal" if status == "Healthy" else ("sand" if status == "Moderate" else "clay")

            health.append({
                "column": col.replace('_', ' ').title(),
                "type": col_type,
                "complete_pct": pct_complete,
                "missing": missing,
                "unique": unique_count,
                "status": status,
                "status_color": status_color
            })

        return health

    @staticmethod
    def extract_keywords_and_domains(df):
        keywords = []
        domains = []
        cols_info = DataEngine.analyze_columns(df)

        text_cols = cols_info["long_text"] + [c for c in cols_info["short_categorical"] if "subject" in c or "title" in c]
        if text_cols:
            all_words = []
            sample_df = df[text_cols[0]].dropna().astype(str).head(500)
            for text in sample_df:
                words = re.findall(r"\b[a-zA-Z]{4,15}\b", text.lower())
                all_words.extend([w for w in words if w not in STOPWORDS])
            if all_words:
                counts = Counter(all_words).most_common(16)
                keywords = [{"word": w, "count": c} for w, c in counts]

        email_cols = [c for c in df.columns if any(k in c.lower() for k in ["sender", "receiver", "from", "to", "email"])]
        if email_cols:
            all_domains = []
            sample_emails = df[email_cols[0]].dropna().astype(str).head(1000)
            for email in sample_emails:
                match = re.search(r"@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", email)
                if match:
                    all_domains.append(match.group(1).lower())
            if all_domains:
                counts = Counter(all_domains).most_common(10)
                domains = [{"domain": d, "count": c} for d, c in counts]

        return {"keywords": keywords, "domains": domains}

    @staticmethod
    def generate_insights(df):
        cols_info = DataEngine.analyze_columns(df)
        insights = []

        insights.append({
            "title": "Dataset Architecture",
            "text": f"Successfully ingested <strong>{len(df):,} records</strong> across <strong>{len(df.columns)} fields</strong>. Identified {len(cols_info['numeric'])} numerical metrics, {len(cols_info['short_categorical'])} categories, and {len(cols_info['long_text'])} text content columns.",
            "color": "teal",
            "icon": "fas fa-cubes"
        })

        for b_col in cols_info["binary"][:1]:
            rate = round(df[b_col].mean() * 100, 1) if len(df) > 0 else 0
            b_name = b_col.replace('_', ' ').title()
            insights.append({
                "title": f"Target Concentration ({b_name})",
                "text": f"Indicator <code>{b_name}</code> has a <strong>{rate}% concentration rate</strong>. High ratio categorization detected.",
                "color": "clay",
                "icon": "fas fa-bullseye"
            })

        for m_col in cols_info["numeric"][:2]:
            col_data = df[m_col].dropna()
            if len(col_data) > 0 and col_data.std() > 0:
                mean_v = col_data.mean()
                max_v = col_data.max()
                skew_v = col_data.skew()
                skew_desc = "symmetrically distributed"
                if skew_v > 1: skew_desc = "strongly right-skewed"
                elif skew_v < -1: skew_desc = "left-skewed"
                m_name = m_col.replace('_', ' ').title()
                insights.append({
                    "title": f"{m_name} Metrics",
                    "text": f"Average of <strong>{mean_v:,.2f}</strong> with maximum of <strong>{max_v:,.2f}</strong>. Distribution is {skew_desc}.",
                    "color": "teal",
                    "icon": "fas fa-chart-area"
                })

        for c_col in cols_info["short_categorical"][:2]:
            clean_series = df[c_col].dropna().astype(str)
            clean_series = clean_series[~clean_series.str.lower().isin(["nan", "none", "unknown", "null", ""])]
            if not clean_series.empty:
                vc = clean_series.value_counts()
                top_name = vc.index[0]
                pct = round(vc.iloc[0] / len(df) * 100, 1) if len(df) > 0 else 0
                c_name = c_col.replace('_', ' ').title()
                insights.append({
                    "title": f"Leading {c_name}",
                    "text": f"<code>{top_name[:30]}</code> is the primary category, accounting for <strong>{pct}%</strong> of all entries ({vc.iloc[0]:,} instances).",
                    "color": "sand",
                    "icon": "fas fa-award"
                })

        return insights

# ----------------------------------------------------
# ADVANCED CHART ENGINE
# ----------------------------------------------------
class ChartEngine:
    THEME_COLORS = ["#0F766E", "#14B8A6", "#C2410C", "#D97706", "#475569", "#06B6D4", "#8B5CF6"]

    @classmethod
    def apply_neutral_layout(cls, fig, title=""):
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(255,255,255,0.7)",
            font=dict(family="Inter, sans-serif", size=11, color="#1C1917"),
            margin=dict(l=55, r=30, t=45, b=50),
            xaxis=dict(gridcolor="#E5E4DC", linecolor="#D4D4CE", zerolinecolor="#E5E4DC"),
            yaxis=dict(gridcolor="#E5E4DC", linecolor="#D4D4CE", zerolinecolor="#E5E4DC"),
            title=dict(text=title, font=dict(size=13, color="#1C1917", family="Outfit, sans-serif"), x=0.0, xanchor="left"),
            height=340,
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=10)),
            hoverlabel=dict(bgcolor="#FFFFFF", font_size=12, bordercolor="#0F766E")
        )
        return fig

    @classmethod
    def build_dashboard_figs(cls, df):
        cols_info = DataEngine.analyze_columns(df)
        fig_dict = {}

        primary_cat = None
        for c in cols_info["short_categorical"]:
            clean_s = df[c].dropna().astype(str)
            clean_s = clean_s[~clean_s.str.lower().isin(["nan", "none", "unknown", "null", ""])]
            if not clean_s.empty and clean_s.nunique() > 1:
                primary_cat = c
                break

        if primary_cat:
            clean_s = df[primary_cat].dropna().astype(str)
            clean_s = clean_s[~clean_s.str.lower().isin(["nan", "none", "unknown", "null", ""])]
            top_df = clean_s.value_counts().head(8).reset_index()
            top_df.columns = [primary_cat, "count"]
            top_df["display_label"] = top_df[primary_cat].apply(lambda x: x[:22] + "..." if len(x) > 22 else x)
            top_df = top_df.sort_values("count", ascending=True)

            fig1 = px.bar(
                top_df, y="display_label", x="count", orientation="h",
                color_discrete_sequence=["#0F766E"], text="count"
            )
            fig1.update_traces(textposition="outside", marker_line_width=0)
            fig1.update_layout(yaxis_title="", xaxis_title="Occurrences")
            cls.apply_neutral_layout(fig1, f"Top {primary_cat.replace('_', ' ').title()} Occurrences")
            fig_dict["primary_bar"] = {
                "id": "chart_primary_bar",
                "badge": "BAR CHART",
                "title": f"Top {primary_cat.replace('_', ' ').title()} Occurrences",
                "fig": fig1
            }

        pie_built = False
        if cols_info["binary"]:
            b_col = cols_info["binary"][0]
            val_counts = df[b_col].value_counts().reset_index()
            val_counts.columns = [b_col, "count"]
            val_counts["label"] = val_counts[b_col].apply(lambda x: f"{b_col.replace('_',' ').title()}: {x}")
            fig2 = px.pie(
                val_counts, names="label", values="count",
                color_discrete_sequence=["#0F766E", "#C2410C"], hole=0.5
            )
            fig2.update_traces(textposition="inside", textinfo="percent+label")
            cls.apply_neutral_layout(fig2, f"{b_col.replace('_', ' ').title()} Proportion")
            fig_dict["share_pie"] = {
                "id": "chart_share_pie",
                "badge": "DONUT CHART",
                "title": f"{b_col.replace('_', ' ').title()} Proportion",
                "fig": fig2
            }
            pie_built = True

        if not pie_built:
            cat_for_pie = None
            for c in cols_info["short_categorical"]:
                if c != primary_cat:
                    cat_for_pie = c
                    break
            if not cat_for_pie and primary_cat:
                cat_for_pie = primary_cat

            if cat_for_pie:
                clean_s = df[cat_for_pie].dropna().astype(str)
                clean_s = clean_s[~clean_s.str.lower().isin(["nan", "none", "unknown", "null", ""])]
                if not clean_s.empty:
                    vc = clean_s.value_counts()
                    top5 = vc.head(5)
                    others = vc.iloc[5:].sum()
                    pie_data = pd.DataFrame({
                        "label": [x[:18] for x in top5.index.tolist()] + (["Other"] if others > 0 else []),
                        "count": top5.values.tolist() + ([others] if others > 0 else [])
                    })
                    fig2 = px.pie(
                        pie_data, names="label", values="count",
                        color_discrete_sequence=cls.THEME_COLORS, hole=0.5
                    )
                    fig2.update_traces(textposition="inside", textinfo="percent")
                    cls.apply_neutral_layout(fig2, f"{cat_for_pie.replace('_', ' ').title()} Share")
                    fig_dict["share_pie"] = {
                        "id": "chart_share_pie",
                        "badge": "DONUT CHART",
                        "title": f"{cat_for_pie.replace('_', ' ').title()} Share",
                        "fig": fig2
                    }

        hist_built = False
        for n_col in cols_info["numeric"]:
            s_data = df[n_col].dropna()
            if len(s_data) > 5 and s_data.std() > 0 and s_data.nunique() >= 3:
                fig3 = px.histogram(df, x=n_col, color_discrete_sequence=["#14B8A6"], nbins=20)
                fig3.update_layout(xaxis_title=n_col.replace('_', ' ').title(), yaxis_title="Frequency")
                cls.apply_neutral_layout(fig3, f"{n_col.replace('_', ' ').title()} Distribution")
                fig_dict["dist_hist"] = {
                    "id": "chart_dist_hist",
                    "badge": "HISTOGRAM",
                    "title": f"{n_col.replace('_', ' ').title()} Distribution",
                    "fig": fig3
                }
                hist_built = True
                break

        if not hist_built and cols_info["long_text"]:
            t_col = cols_info["long_text"][0]
            word_counts = df[t_col].dropna().astype(str).apply(lambda x: len(x.split()))
            fig3 = px.histogram(x=word_counts, color_discrete_sequence=["#14B8A6"], nbins=25)
            fig3.update_layout(xaxis_title=f"{t_col.replace('_', ' ').title()} Word Count", yaxis_title="Number of Records")
            cls.apply_neutral_layout(fig3, f"{t_col.replace('_', ' ').title()} Word Count Distribution")
            fig_dict["dist_hist"] = {
                "id": "chart_dist_hist",
                "badge": "HISTOGRAM",
                "title": f"{t_col.replace('_', ' ').title()} Word Count Distribution",
                "fig": fig3
            }
            hist_built = True

        secondary_built = False
        for c in cols_info["short_categorical"]:
            if c != primary_cat:
                clean_s = df[c].dropna().astype(str)
                clean_s = clean_s[~clean_s.str.lower().isin(["nan", "none", "unknown", "null", ""])]
                if not clean_s.empty and clean_s.nunique() > 1:
                    top_df = clean_s.value_counts().head(7).reset_index()
                    top_df.columns = [c, "count"]
                    top_df["display_label"] = top_df[c].apply(lambda x: x[:22] + "..." if len(x) > 22 else x)
                    top_df = top_df.sort_values("count", ascending=True)

                    fig4 = px.bar(
                        top_df, y="display_label", x="count", orientation="h",
                        color_discrete_sequence=["#D97706"], text="count"
                    )
                    fig4.update_traces(textposition="outside", marker_line_width=0)
                    fig4.update_layout(yaxis_title="", xaxis_title="Occurrences")
                    cls.apply_neutral_layout(fig4, f"Top {c.replace('_', ' ').title()} Distribution")
                    fig_dict["secondary_bar"] = {
                        "id": "chart_secondary_bar",
                        "badge": "BAR CHART",
                        "title": f"Top {c.replace('_', ' ').title()} Distribution",
                        "fig": fig4
                    }
                    secondary_built = True
                    break

        if not secondary_built:
            valid_num_cols = [c for c in cols_info["numeric"] if df[c].dropna().std() > 0]
            if len(valid_num_cols) >= 2:
                corr = df[valid_num_cols[:5]].corr().round(2)
                fig4 = px.imshow(
                    corr, text_auto=True,
                    color_continuous_scale=[[0, "#C2410C"], [0.5, "#FAF9F5"], [1, "#0F766E"]]
                )
                cls.apply_neutral_layout(fig4, "Numeric Correlation Matrix")
                fig_dict["corr_matrix"] = {
                    "id": "chart_corr_matrix",
                    "badge": "HEATMAP",
                    "title": "Numeric Correlation Matrix",
                    "fig": fig4
                }

        return fig_dict

    @classmethod
    def build_dashboard_charts(cls, df):
        fig_dict = cls.build_dashboard_figs(df)
        charts_json = []
        for key, item in fig_dict.items():
            charts_json.append({
                "id": item["id"],
                "badge": item["badge"],
                "title": item["title"],
                "json": pio.to_json(item["fig"])
            })
        return charts_json

    @classmethod
    def generate_custom_chart(cls, df, chart_type, x_col, y_col=None, agg="count"):
        if x_col not in df.columns:
            raise ValueError(f"Column '{x_col}' does not exist.")

        title = f"{x_col.replace('_', ' ').title()}"

        if chart_type in ["pie", "donut"]:
            clean_s = df[x_col].dropna().astype(str)
            clean_s = clean_s[~clean_s.str.lower().isin(["nan", "none", "unknown", "null", ""])]
            vc = clean_s.value_counts()
            top7 = vc.head(7)
            others = vc.iloc[7:].sum()
            pie_data = pd.DataFrame({
                "label": [x[:20] for x in top7.index.tolist()] + (["Other"] if others > 0 else []),
                "count": top7.values.tolist() + ([others] if others > 0 else [])
            })
            fig = px.pie(
                pie_data, names="label", values="count",
                color_discrete_sequence=cls.THEME_COLORS,
                hole=0.45
            )
            fig.update_traces(textposition="inside", textinfo="percent+label")
            cls.apply_neutral_layout(fig, f"{title} Proportions")
            return pio.to_json(fig)

        elif chart_type == "hbar":
            if agg == "count" or not y_col or y_col not in df.columns:
                clean_s = df[x_col].dropna().astype(str)
                clean_s = clean_s[~clean_s.str.lower().isin(["nan", "none", "unknown", "null", ""])]
                top_df = clean_s.value_counts().head(10).reset_index()
                top_df.columns = [x_col, "count"]
                top_df["label"] = top_df[x_col].apply(lambda x: x[:22] + "..." if len(x) > 22 else x)
                top_df = top_df.sort_values("count", ascending=True)
                fig = px.bar(top_df, y="label", x="count", orientation="h", color_discrete_sequence=["#0F766E"], text="count")
                fig.update_traces(textposition="outside")
                fig.update_layout(yaxis_title="", xaxis_title="Count")
                cls.apply_neutral_layout(fig, f"Top {title} (Count)")
                return pio.to_json(fig)
            else:
                grouped = df.groupby(x_col)[y_col].agg("sum" if agg == "sum" else "mean").reset_index()
                grouped = grouped.sort_values(y_col, ascending=False).head(10).sort_values(y_col, ascending=True)
                grouped["label"] = grouped[x_col].astype(str).apply(lambda x: x[:22] + "..." if len(x) > 22 else x)
                fig = px.bar(grouped, y="label", x=y_col, orientation="h", color_discrete_sequence=["#0F766E"])
                cls.apply_neutral_layout(fig, f"{y_col.replace('_',' ').title()} by {title}")
                return pio.to_json(fig)

        elif chart_type == "bar":
            if agg == "count" or not y_col or y_col not in df.columns:
                clean_s = df[x_col].dropna().astype(str)
                clean_s = clean_s[~clean_s.str.lower().isin(["nan", "none", "unknown", "null", ""])]
                top_df = clean_s.value_counts().head(10).reset_index()
                top_df.columns = [x_col, "count"]
                top_df["label"] = top_df[x_col].apply(lambda x: x[:16] + "..." if len(x) > 16 else x)
                fig = px.bar(top_df, x="label", y="count", color_discrete_sequence=["#14B8A6"], text="count")
                fig.update_traces(textposition="outside")
                fig.update_layout(xaxis_title="", yaxis_title="Count")
                cls.apply_neutral_layout(fig, f"{title} Frequency")
                return pio.to_json(fig)
            else:
                grouped = df.groupby(x_col)[y_col].agg("sum" if agg == "sum" else "mean").reset_index().head(10)
                grouped["label"] = grouped[x_col].astype(str).apply(lambda x: x[:16] + "..." if len(x) > 16 else x)
                fig = px.bar(grouped, x="label", y=y_col, color_discrete_sequence=["#14B8A6"])
                cls.apply_neutral_layout(fig, f"{y_col.replace('_',' ').title()} by {title}")
                return pio.to_json(fig)

        elif chart_type == "line":
            if y_col and y_col in df.columns:
                fig = px.line(df.head(50), x=x_col, y=y_col, markers=True, color_discrete_sequence=["#0F766E"])
                cls.apply_neutral_layout(fig, f"{y_col.replace('_',' ').title()} Trend across {title}")
                return pio.to_json(fig)
            else:
                counts = df[x_col].value_counts().reset_index()
                counts.columns = [x_col, "count"]
                counts = counts.head(30)
                fig = px.line(counts, x=x_col, y="count", markers=True, color_discrete_sequence=["#0F766E"])
                return pio.to_json(fig)

        elif chart_type == "hist":
            if pd.api.types.is_numeric_dtype(df[x_col]):
                fig = px.histogram(df, x=x_col, color_discrete_sequence=["#14B8A6"], nbins=25)
                cls.apply_neutral_layout(fig, f"Distribution of {title}")
                return pio.to_json(fig)
            else:
                word_counts = df[x_col].dropna().astype(str).apply(lambda x: len(x.split()))
                fig = px.histogram(x=word_counts, color_discrete_sequence=["#14B8A6"], nbins=25)
                fig.update_layout(xaxis_title=f"{title} Word Length", yaxis_title="Frequency")
                return pio.to_json(fig)

        elif chart_type == "box":
            target_col = y_col if (y_col and pd.api.types.is_numeric_dtype(df[y_col])) else x_col
            if not pd.api.types.is_numeric_dtype(df[target_col]):
                df_temp = pd.DataFrame({"length": df[target_col].dropna().astype(str).str.len()})
                target_col = "length"
            else:
                df_temp = df
            fig = px.box(df_temp, y=target_col, color_discrete_sequence=["#0F766E"], points="outliers")
            cls.apply_neutral_layout(fig, f"Box Plot of {title}")
            return pio.to_json(fig)

        else:
            raise ValueError(f"Unsupported chart type: {chart_type}")

# ----------------------------------------------------
# REPORT GENERATOR ENGINE (EMBEDDED CHARTS IN PDF)
# ----------------------------------------------------
class ReportEngine:
    @staticmethod
    def generate_pdf(df, filename, kpis, insights, data_health):
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.lib import colors
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image, PageBreak

            output = io.BytesIO()
            doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=40, bottomMargin=36)
            styles = getSampleStyleSheet()
            story = []

            title_style = ParagraphStyle("T1", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=22, textColor=colors.HexColor("#0F766E"), spaceAfter=6, alignment=0)
            subtitle_style = ParagraphStyle("S1", parent=styles["Normal"], fontName="Helvetica", fontSize=10, textColor=colors.HexColor("#57534E"), spaceAfter=14)
            h2_style = ParagraphStyle("H2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=13, textColor=colors.HexColor("#1C1917"), spaceBefore=14, spaceAfter=8)
            body_style = ParagraphStyle("B1", parent=styles["Normal"], fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#334155"), spaceAfter=5)

            # Header
            story.append(Paragraph("Lumina Insights — Executive Analytics Report", title_style))
            story.append(Paragraph(f"Dataset: <b>{filename}</b> &nbsp;|&nbsp; Generated: {datetime.now().strftime('%B %d, %Y - %H:%M')}", subtitle_style))
            story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#0F766E"), spaceAfter=14))

            # KPIs Table
            story.append(Paragraph("Executive Performance Metrics", h2_style))
            kpi_data = [["Metric", "Value", "Context"]]
            for k in kpis:
                kpi_data.append([k.get("label", ""), str(k.get("value", "")), k.get("sub", "")])

            t_kpi = Table(kpi_data, colWidths=[2.2 * inch, 2.0 * inch, 3.2 * inch])
            t_kpi.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F766E")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#F8FAF9"), colors.white]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            story.append(t_kpi)
            story.append(Spacer(1, 14))

            # Automated Insights
            story.append(Paragraph("Automated Domain Findings", h2_style))
            for ins in insights:
                clean_text = ins.get("text", "").replace("<strong>", "<b>").replace("</strong>", "</b>")
                clean_text = clean_text.replace("<code>", "<i>").replace("</code>", "</i>")
                clean_text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", clean_text)
                clean_text = re.sub(r"`(.*?)`", r"<i>\1</i>", clean_text)
                story.append(Paragraph(f"<b>{ins.get('title', '')}</b>: {clean_text}", body_style))
            story.append(Spacer(1, 14))

            # Visual Charts in PDF
            story.append(PageBreak())
            story.append(Paragraph("Visual Analytics & Distributions", h2_style))
            story.append(Paragraph("The key visual distributions extracted from the dataset are rendered below:", body_style))
            story.append(Spacer(1, 8))

            fig_dict = ChartEngine.build_dashboard_figs(df)
            for chart_key, chart_item in fig_dict.items():
                try:
                    img_bytes = chart_item["fig"].to_image(format="png", width=680, height=300)
                    img_io = io.BytesIO(img_bytes)
                    story.append(Paragraph(f"<b>{chart_item['title']}</b> ({chart_item['badge']})", h2_style))
                    story.append(Image(img_io, width=6.6 * inch, height=2.9 * inch))
                    story.append(Spacer(1, 10))
                except Exception as chart_err:
                    print(f"Chart image export error for {chart_key}: {chart_err}")

            # Column Health Table
            story.append(PageBreak())
            story.append(Paragraph("Dataset Integrity & Health Audit", h2_style))
            health_data = [["Field", "Type", "Completeness", "Missing Values", "Unique Count", "Status"]]
            for h in data_health[:15]:
                health_data.append([
                    h.get("column", ""),
                    h.get("type", ""),
                    f"{h.get('complete_pct', 0)}%",
                    str(h.get("missing", 0)),
                    str(h.get("unique", 0)),
                    h.get("status", "")
                ])

            t_health = Table(health_data, colWidths=[1.8 * inch, 1.3 * inch, 1.1 * inch, 1.1 * inch, 1.1 * inch, 1.0 * inch])
            t_health.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#F8FAFC"), colors.white]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(t_health)

            doc.build(story)
            output.seek(0)
            return output.getvalue(), None
        except Exception as e:
            return None, str(e)

# ----------------------------------------------------
# NATURAL LANGUAGE QUERY ENGINE
# ----------------------------------------------------
def process_natural_query(df, query_str):
    q = query_str.lower().strip()
    cols_info = DataEngine.analyze_columns(df)

    def find_matching_col(candidates):
        for c in candidates:
            if c.replace("_", " ") in q or c in q:
                return c
        return candidates[0] if candidates else None

    # TOP N
    if any(k in q for k in ["top", "highest", "best", "most"]):
        n_match = re.search(r"\d+", q)
        n = int(n_match.group()) if n_match else 5
        col = find_matching_col(cols_info["short_categorical"] + cols_info["numeric"])
        if col:
            clean_s = df[col].dropna().astype(str)
            clean_s = clean_s[~clean_s.str.lower().isin(["nan", "none", "unknown", "null", ""])]
            counts = clean_s.value_counts().head(n).reset_index()
            counts.columns = [col, "count"]
            counts["label"] = counts[col].apply(lambda x: x[:20] + "..." if len(x) > 20 else x)
            fig = px.bar(counts, y="label", x="count", orientation="h", color_discrete_sequence=["#0F766E"], text="count")
            fig.update_traces(textposition="outside")
            ChartEngine.apply_neutral_layout(fig, f"Top {n} {col.replace('_',' ').title()}")
            return {
                "answer": f"Here are the top {n} entries for <strong>{col.replace('_',' ').title()}</strong>.",
                "data": counts[[col, "count"]].to_dict(orient="records"),
                "chart_json": pio.to_json(fig)
            }

    # PIE / DONUT BREAKDOWN
    if any(k in q for k in ["pie", "proportion", "share", "breakdown", "percentage"]):
        col = find_matching_col(cols_info["short_categorical"] + cols_info["binary"])
        if col:
            chart_json = ChartEngine.generate_custom_chart(df, "donut", col)
            return {
                "answer": f"Here is the proportion breakdown for <strong>{col.replace('_',' ').title()}</strong>.",
                "data": df[col].value_counts().head(5).to_dict(),
                "chart_json": chart_json
            }

    # HISTOGRAM / DISTRIBUTION
    if any(k in q for k in ["distribution", "histogram", "spread"]):
        col = find_matching_col(cols_info["numeric"] + cols_info["long_text"])
        if col:
            chart_json = ChartEngine.generate_custom_chart(df, "hist", col)
            return {
                "answer": f"Here is the distribution spread for <strong>{col.replace('_',' ').title()}</strong>.",
                "data": None,
                "chart_json": chart_json
            }

    # DEFAULT SUMMARY
    return {
        "answer": f"Dataset Overview: <strong>{len(df):,} total rows</strong> and <strong>{len(df.columns)} fields</strong> loaded successfully.",
        "data": df.head(5).to_dict(orient="records"),
        "chart_json": None
    }

def store_session_dataset(df, filename, source_type="upload"):
    dataset_id = str(uuid.uuid4())
    _active_datasets[dataset_id] = df
    session["dataset_id"] = dataset_id
    session["filename"] = filename
    session["source_type"] = source_type

    kpis = DataEngine.get_kpis(df)
    insights = DataEngine.generate_insights(df)

    database.save_dataset(dataset_id, filename, source_type, len(df), len(df.columns), source_type)
    database.save_insights(dataset_id, insights)

    return dataset_id, kpis, insights

# ----------------------------------------------------
# ROUTES
# ----------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if file.filename == "" or not allowed_file(file.filename):
        return jsonify({"error": "Invalid file format. Please upload CSV or XLSX."}), 400

    try:
        filename = secure_filename(file.filename)
        dataset_id = str(uuid.uuid4())
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], f"{dataset_id}_{filename}")
        file.save(filepath)

        df = DataEngine.load_and_clean(filepath)
        dataset_id, kpis, insights = store_session_dataset(df, filename, "upload")

        return jsonify({
            "success": True,
            "dataset_id": dataset_id,
            "filename": filename,
            "rows": len(df),
            "cols": len(df.columns),
            "kpis": kpis,
            "insights": insights
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ----------------------------------------------------
# EXTERNAL DATA CONNECTOR ROUTES
# ----------------------------------------------------
@app.route("/api/connect/gsheet", methods=["POST"])
def connect_gsheet():
    data = request.json or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "Please provide a valid Google Sheet link."}), 400

    try:
        # Extract spreadsheet key and gid
        key_match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
        if not key_match:
            return jsonify({"error": "Invalid Google Sheet link. Could not extract spreadsheet ID."}), 400
        sheet_key = key_match.group(1)

        gid_match = re.search(r"[#&?]gid=([0-9]+)", url)
        gid = gid_match.group(1) if gid_match else "0"

        export_url = f"https://docs.google.com/spreadsheets/d/{sheet_key}/export?format=csv&gid={gid}"
        
        req = urllib.request.Request(export_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as response:
            csv_bytes = response.read()

        df = pd.read_csv(io.BytesIO(csv_bytes), encoding="utf-8", on_bad_lines="skip")
        df = DataEngine.clean_dataframe(df)

        filename = f"GoogleSheet_{sheet_key[:8]}"
        dataset_id, kpis, insights = store_session_dataset(df, filename, "gsheet")

        return jsonify({
            "success": True,
            "dataset_id": dataset_id,
            "filename": filename,
            "rows": len(df),
            "cols": len(df.columns),
            "kpis": kpis,
            "insights": insights
        })

    except Exception as e:
        return jsonify({"error": f"Failed to connect Google Sheet: {str(e)}. Make sure 'Anyone with the link can view' is turned on."}), 400

@app.route("/api/connect/url", methods=["POST"])
def connect_url():
    data = request.json or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "Please provide a valid web URL."}), 400

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as response:
            content = response.read()

        if url.lower().endswith(".json"):
            df = pd.read_json(io.BytesIO(content))
        else:
            df = pd.read_csv(io.BytesIO(content), encoding="utf-8", on_bad_lines="skip")

        df = DataEngine.clean_dataframe(df)
        filename = os.path.basename(url.split("?")[0]) or "Remote_Dataset.csv"
        dataset_id, kpis, insights = store_session_dataset(df, filename, "url")

        return jsonify({
            "success": True,
            "dataset_id": dataset_id,
            "filename": filename,
            "rows": len(df),
            "cols": len(df.columns),
            "kpis": kpis,
            "insights": insights
        })

    except Exception as e:
        return jsonify({"error": f"Failed to load dataset from URL: {str(e)}"}), 400

@app.route("/api/connect/sqlite", methods=["POST"])
def connect_sqlite():
    if "file" in request.files:
        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "No SQLite file selected."}), 400

        filename = secure_filename(file.filename)
        db_id = str(uuid.uuid4())
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], f"{db_id}_{filename}")
        file.save(filepath)
    else:
        filepath = request.json.get("filepath", "") if request.json else ""
        if not filepath or not os.path.exists(filepath):
            return jsonify({"error": "SQLite file not found."}), 400
        filename = os.path.basename(filepath)

    table_name = request.form.get("table") or (request.json.get("table") if request.json else None)

    try:
        conn = sqlite3.connect(filepath)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        tables = [row[0] for row in cur.fetchall()]

        if not tables:
            conn.close()
            return jsonify({"error": "No user tables found in SQLite database."}), 400

        selected_table = table_name if (table_name and table_name in tables) else tables[0]
        df = pd.read_sql_query(f"SELECT * FROM \"{selected_table}\" LIMIT 50000", conn)
        conn.close()

        df = DataEngine.clean_dataframe(df)
        dataset_id, kpis, insights = store_session_dataset(df, f"{filename} [{selected_table}]", "sqlite")

        return jsonify({
            "success": True,
            "dataset_id": dataset_id,
            "filename": f"{filename} [{selected_table}]",
            "tables": tables,
            "selected_table": selected_table,
            "rows": len(df),
            "cols": len(df.columns),
            "kpis": kpis,
            "insights": insights
        })

    except Exception as e:
        return jsonify({"error": f"SQLite error: {str(e)}"}), 400

@app.route("/api/dashboard", methods=["GET"])
def get_dashboard():
    dataset_id = session.get("dataset_id")
    if not dataset_id or dataset_id not in _active_datasets:
        return jsonify({"error": "No dataset currently active"}), 404

    df = _active_datasets[dataset_id]
    kpis = DataEngine.get_kpis(df)
    insights = database.get_saved_insights(dataset_id)
    charts = ChartEngine.build_dashboard_charts(df)
    data_health = DataEngine.get_data_health(df)
    intel = DataEngine.extract_keywords_and_domains(df)

    raw_preview = df.head(10).copy()
    columns_list = list(raw_preview.columns)
    formatted_preview = []

    for idx, row in raw_preview.iterrows():
        row_dict = {}
        for col in columns_list:
            val = str(row[col]) if pd.notna(row[col]) else ""
            is_long = len(val) > 80
            row_dict[col] = {
                "short_text": val[:80] + "..." if is_long else val,
                "full_text": val if is_long else None,
                "is_truncated": is_long
            }
        formatted_preview.append(row_dict)

    return jsonify({
        "filename": session.get("filename", "Dataset"),
        "rows": len(df),
        "cols": len(df.columns),
        "kpis": kpis,
        "insights": insights,
        "charts": charts,
        "data_health": data_health,
        "keywords": intel.get("keywords", []),
        "domains": intel.get("domains", []),
        "preview": formatted_preview,
        "columns": columns_list
    })

@app.route("/api/filter", methods=["POST"])
def filter_dataset():
    dataset_id = session.get("dataset_id")
    if not dataset_id or dataset_id not in _active_datasets:
        return jsonify({"error": "No active dataset"}), 400

    df_full = _active_datasets[dataset_id]
    data = request.json or {}
    search_query = data.get("search", "").strip().lower()
    filter_col = data.get("filter_col")
    filter_val = data.get("filter_val")

    df_filtered = df_full.copy()

    if filter_col and filter_col in df_filtered.columns and filter_val is not None:
        df_filtered = df_filtered[df_filtered[filter_col].astype(str).str.lower() == str(filter_val).lower()]

    if search_query:
        mask = pd.Series(False, index=df_filtered.index)
        for col in df_filtered.select_dtypes(include=["object"]).columns:
            mask = mask | df_filtered[col].astype(str).str.lower().str.contains(search_query, regex=False, na=False)
        df_filtered = df_filtered[mask]

    kpis = DataEngine.get_kpis(df_filtered)
    raw_preview = df_filtered.head(10).copy()
    columns_list = list(raw_preview.columns)
    formatted_preview = []

    for idx, row in raw_preview.iterrows():
        row_dict = {}
        for col in columns_list:
            val = str(row[col]) if pd.notna(row[col]) else ""
            is_long = len(val) > 80
            row_dict[col] = {
                "short_text": val[:80] + "..." if is_long else val,
                "full_text": val if is_long else None,
                "is_truncated": is_long
            }
        formatted_preview.append(row_dict)

    return jsonify({
        "matched_rows": len(df_filtered),
        "total_rows": len(df_full),
        "kpis": kpis,
        "preview": formatted_preview
    })

@app.route("/api/custom_chart", methods=["POST"])
def custom_chart():
    dataset_id = session.get("dataset_id")
    if not dataset_id or dataset_id not in _active_datasets:
        return jsonify({"error": "No active dataset"}), 400

    data = request.json or {}
    chart_type = data.get("chart_type", "bar")
    x_col = data.get("x_col")
    y_col = data.get("y_col")
    agg = data.get("agg", "count")

    if not x_col:
        return jsonify({"error": "Please select a column."}), 400

    df = _active_datasets[dataset_id]
    try:
        chart_json = ChartEngine.generate_custom_chart(df, chart_type, x_col, y_col, agg)
        return jsonify({"success": True, "chart_json": chart_json})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/query", methods=["POST"])
def query_data():
    dataset_id = session.get("dataset_id")
    if not dataset_id or dataset_id not in _active_datasets:
        return jsonify({"error": "No active dataset. Upload a dataset first."}), 400

    data = request.json or {}
    question = data.get("question", "").strip()
    if not question:
        return jsonify({"error": "Please enter a valid question."}), 400

    df = _active_datasets[dataset_id]
    result = process_natural_query(df, question)

    database.add_query_history(dataset_id, question, result["answer"])
    history = database.get_query_history(dataset_id)

    return jsonify({
        "question": question,
        "answer": result["answer"],
        "data": result["data"],
        "chart_json": result["chart_json"],
        "history": history
    })

@app.route("/api/download/excel", methods=["GET"])
def download_excel():
    dataset_id = session.get("dataset_id")
    if not dataset_id or dataset_id not in _active_datasets:
        return jsonify({"error": "No active dataset"}), 404

    df = _active_datasets[dataset_id]
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Cleaned Data", index=False)
        num_df = df.select_dtypes(include=[np.number])
        if not num_df.empty:
            num_df.describe().to_excel(writer, sheet_name="Summary Stats")

    output.seek(0)
    return send_file(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", as_attachment=True, download_name=f"lumina_export_{dataset_id[:8]}.xlsx")

@app.route("/api/download/pdf", methods=["GET"])
def download_pdf():
    dataset_id = session.get("dataset_id")
    if not dataset_id or dataset_id not in _active_datasets:
        return jsonify({"error": "No active dataset"}), 404

    df = _active_datasets[dataset_id]
    filename = session.get("filename", "Dataset")
    kpis = DataEngine.get_kpis(df)
    insights = database.get_saved_insights(dataset_id)
    data_health = DataEngine.get_data_health(df)

    pdf_bytes, err = ReportEngine.generate_pdf(df, filename, kpis, insights, data_health)
    if err:
        return jsonify({"error": f"PDF Generation Error: {err}"}), 500

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"lumina_report_{dataset_id[:8]}.pdf"
    )

@app.route("/api/clear", methods=["POST"])
def clear_session():
    session.clear()
    return jsonify({"success": True})

if __name__ == "__main__":
    print("[SERVER] Starting Lumina Insights Server on http://localhost:5000 ...")
    app.run(debug=True, host="0.0.0.0", port=5000)
