import streamlit as st
import pandas as pd
import plotly.express as px
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from style import COLOR_SISTEMA, TOTAL_ROW_BG, TOTAL_ROW_FG, TABLE_STYLES

st.title("📊 Dashboard")

try:
    from queries import (get_kpis, get_donantes_overlap, get_suscripciones_detalle, get_cobros_mensuales,
                          get_activacion_socios, get_caida_socios)

    @st.cache_data(ttl=300)
    def _kpis(): return get_kpis()

    @st.cache_data(ttl=300)
    def _donantes_overlap(): return get_donantes_overlap()

    @st.cache_data(ttl=300)
    def _suscripciones_detalle(): return get_suscripciones_detalle()

    @st.cache_data(ttl=300)
    def _cobros_mensuales(): return get_cobros_mensuales()

    @st.cache_data(ttl=300)
    def _activacion_socios(): return get_activacion_socios()

    @st.cache_data(ttl=300)
    def _caida_socios(): return get_caida_socios()

    # ── Formateo completo (sin abreviaciones) ────────────────────────────────
    def _fmt_m(n): return f"${float(n):,.0f}"
    def _fmt_n(n): return f"{int(n):,}"

    # ── Meses en Español ──────────────────────────────────────────────────────
    _MES_ES = {
        "January": "Enero",   "February": "Febrero",  "March": "Marzo",
        "April": "Abril",     "May": "Mayo",           "June": "Junio",
        "July": "Julio",      "August": "Agosto",      "September": "Septiembre",
        "October": "Octubre", "November": "Noviembre", "December": "Diciembre",
    }
    _month_order_es = ["Enero","Febrero","Marzo","Abril","Mayo","Junio",
                       "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]

    # ── KPI card futurista ────────────────────────────────────────────────────
    def _kpi_card(label, value, caption, color):
        st.markdown(f"""
        <div style="
            background: linear-gradient(135deg, #131929 0%, #1a2340 100%);
            border-radius: 12px; padding: 20px 24px;
            border-left: 3px solid {color};
            box-shadow: 0 4px 20px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.04);
            min-height: 110px; margin-bottom: 8px; position: relative; overflow: hidden;
        ">
          <div style="position:absolute;top:0;right:0;width:110px;height:110px;
              background:radial-gradient(circle,{color}22 0%,transparent 70%);
              border-radius:50%;transform:translate(35px,-35px);pointer-events:none;"></div>
          <p style="color:#8892b0;font-size:11px;text-transform:uppercase;letter-spacing:1.2px;
              margin:0 0 10px;font-weight:600">{label}</p>
          <p style="color:{color};font-size:30px;font-weight:700;margin:0 0 6px;line-height:1;
              text-shadow:0 0 20px {color}55">{value}</p>
          <p style="color:#4a5568;font-size:11px;margin:0">{caption}</p>
        </div>
        """, unsafe_allow_html=True)

    kpis = _kpis()

    tasa = 0
    denominador = kpis["cobros_30d_exitosos"] + kpis["cobros_30d_rechazados"]
    if denominador > 0:
        tasa = kpis["cobros_30d_exitosos"] / denominador * 100

    # ── Resumen general ───────────────────────────────────────────────────────
    st.subheader("Resumen general")

    r1c1, r1c2, r1c3 = st.columns(3)
    with r1c1:
        _kpi_card("Donantes Históricos", _fmt_n(kpis['donantes_activos']),
                  "total histórico", "#6366f1")
    with r1c2:
        _kpi_card("Suscripciones activas", _fmt_n(kpis['suscripciones_activas']),
                  f"{_fmt_m(kpis['monto_suscripciones_activas'])} suscritos", "#8b5cf6")
    with r1c3:
        _kpi_card("Recaudado (mes)", _fmt_m(kpis['ingresos_mes']),
                  f"{_fmt_n(kpis['cobros_exitosos_mes'])} cobros pagados", "#10b981")

    r2c1, r2c2, r2c3 = st.columns(3)
    with r2c1:
        _kpi_card("Tasa éxito 30d", f"{tasa:.1f}%",
                  f"{_fmt_n(kpis['cobros_30d_exitosos'])} de {_fmt_n(denominador)} cobros", "#f59e0b")
    with r2c2:
        _kpi_card("Activación (mes)", _fmt_n(kpis['activacion_mes_cantidad']),
                  f"{_fmt_m(kpis['activacion_mes_monto'])} en nuevas subs", "#22d3ee")
    with r2c3:
        _kpi_card("Caída (mes)", _fmt_n(kpis['caida_mes_cantidad']),
                  f"{_fmt_m(kpis['caida_mes_monto'])} en bajas", "#f97316")

    st.divider()

    # ── Donantes por canal ────────────────────────────────────────────────────
    st.subheader("Donantes por canal")
    df_ov = _donantes_overlap()
    if not df_ov.empty:
        canales_names = ["VirtualPOS VP1", "VirtualPOS VP2", "TCH", "Payku", "Toku"]
        cols_flags = ["vp1", "vp2", "tch", "payku", "toku"]
        matrix = pd.DataFrame(0, index=canales_names, columns=canales_names, dtype=int)
        for i, ci in enumerate(cols_flags):
            for j, cj in enumerate(cols_flags):
                matrix.iloc[i, j] = int((df_ov[ci] & df_ov[cj]).sum())
        matrix.index.name = "Canal"
        matrix.loc["Total"] = matrix.sum(axis=0)
        def _style_overlap(df):
            s = pd.DataFrame("text-align: center;", index=df.index, columns=df.columns)
            s.loc["Total"] = f"background-color: {TOTAL_ROW_BG}; color: {TOTAL_ROW_FG}; text-align: center; font-weight: 700;"
            for canal in [c for c in df.index if c != "Total"]:
                if canal in df.columns:
                    s.at[canal, canal] = f"background-color: {TOTAL_ROW_BG}; color: {TOTAL_ROW_FG}; text-align: center; font-weight: 700;"
            return s
        st.table(
            matrix.style.apply(_style_overlap, axis=None).set_table_styles(TABLE_STYLES)
        )

    st.divider()

    # ── Suscripciones por canal y estado ─────────────────────────────────────
    col_sus_h, col_sus_t = st.columns([3, 1], vertical_alignment="bottom")
    with col_sus_h:
        st.subheader("Suscripciones por canal y estado")
    with col_sus_t:
        modo = st.segmented_control("", ["🔢 Cantidad", "💵 Monto suscrito"], default="🔢 Cantidad", key="sus_modo", label_visibility="collapsed")
    if modo is None:
        modo = "🔢 Cantidad"
    df_sus_det = _suscripciones_detalle()
    if not df_sus_det.empty:
        value_col = "cantidad" if "Cantidad" in (modo or "") else "monto_suscrito"
        pivot = df_sus_det.pivot_table(
            index="estado", columns="sistema", values=value_col, aggfunc="sum", fill_value=0
        )
        col_order = [c for c in ["virtualpos_vp1", "virtualpos_vp2", "tch", "payku", "toku"] if c in pivot.columns]
        pivot = pivot[col_order]
        pivot.columns = [
            {"virtualpos_vp1": "VirtualPOS VP1", "virtualpos_vp2": "VirtualPOS VP2",
             "tch": "TCH", "payku": "Payku", "toku": "Toku"}.get(c, c)
            for c in pivot.columns
        ]
        pivot.index.name = "Estado Sub"
        pivot["Total"] = pivot.sum(axis=1)
        pivot.loc["Total"] = pivot.sum(axis=0)
        if "Monto" in (modo or ""):
            pivot = pivot.apply(lambda col: col.map(lambda x: f"${float(x):,.0f}"))
        def _style_totals(df):
            s = pd.DataFrame("", index=df.index, columns=df.columns)
            s["Total"] = f"background-color: {TOTAL_ROW_BG}; color: {TOTAL_ROW_FG}; text-align: center; font-weight: 700;"
            s.loc["Total"] = f"background-color: {TOTAL_ROW_BG}; color: {TOTAL_ROW_FG}; text-align: center; font-weight: 700;"
            return s
        styled = (
            pivot.style
            .apply(_style_totals, axis=None)
            .set_table_styles(TABLE_STYLES)
        )
        st.table(styled)
    else:
        st.info("Sin datos.")

    st.divider()

    # ── Cobros pagados ────────────────────────────────────────────────────────
    _RENAME_SISTEMA = {
        "virtualpos_vp1": "VP1", "virtualpos_vp2": "VP2",
        "tch": "TCH", "payku": "Payku", "toku": "Toku",
    }

    col_cob_h, col_cob_t = st.columns([3, 1], vertical_alignment="bottom")
    with col_cob_h:
        st.subheader("Cobros pagados")
    with col_cob_t:
        modo_c = st.segmented_control("", ["🔢 Cantidad", "💰 Monto"], default="🔢 Cantidad", key="cobros_modo", label_visibility="collapsed")
    if modo_c is None:
        modo_c = "🔢 Cantidad"
    df_cobros_m = _cobros_mensuales()
    if not df_cobros_m.empty:
        value_col_c = "cantidad" if "Cantidad" in (modo_c or "") else "monto_total"
        df_cobros_m["mes"] = df_cobros_m["mes"].map(_MES_ES)
        _col_rename_c = {
            "virtualpos_vp1": "VirtualPOS VP1", "virtualpos_vp2": "VirtualPOS VP2",
            "tch": "TCH", "payku": "Payku", "toku": "Toku",
        }
        _col_order_c = ["virtualpos_vp1", "virtualpos_vp2", "tch", "payku", "toku"]
        _month_order = _month_order_es
        def _style_cobros(df):
            s = pd.DataFrame("", index=df.index, columns=df.columns)
            s["Total"] = f"background-color: {TOTAL_ROW_BG}; color: {TOTAL_ROW_FG}; text-align: center; font-weight: 700;"
            s.loc["Total"] = f"background-color: {TOTAL_ROW_BG}; color: {TOTAL_ROW_FG}; text-align: center; font-weight: 700;"
            return s

        def _bar_cobros(df_src, y_col, y_label):
            if df_src.empty: return None
            month_idx = {m: i for i, m in enumerate(_month_order)}
            df_p = df_src.copy()
            df_p["_ord"] = df_p["mes"].map(month_idx).fillna(99)
            df_p = df_p.sort_values("_ord")
            df_p["sistema_label"] = df_p["sistema"].map(_RENAME_SISTEMA).fillna(df_p["sistema"])
            color_map = {_RENAME_SISTEMA.get(k, k): v for k, v in COLOR_SISTEMA.items()}
            fig = px.bar(df_p, x="mes", y=y_col, color="sistema_label", barmode="stack",
                         color_discrete_map=color_map,
                         labels={"mes": "Mes", y_col: y_label, "sistema_label": "Sistema"},
                         height=280)
            fig.update_layout(
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                font_color="#e2e8f0", margin=dict(l=0, r=0, t=10, b=0),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, title=None),
            )
            fig.update_xaxes(gridcolor="rgba(168,85,247,0.1)", showgrid=True)
            fig.update_yaxes(gridcolor="rgba(168,85,247,0.1)", showgrid=True)
            return fig

        anios = sorted(df_cobros_m["año"].unique(), reverse=True)
        tabs = st.tabs([str(a) for a in anios])
        for tab, anio in zip(tabs, anios):
            with tab:
                df_year = df_cobros_m[df_cobros_m["año"] == anio]
                y_label_c = "Cobros" if modo_c == "Cantidad" else "Monto ($)"
                fig_c = _bar_cobros(df_year, value_col_c, y_label_c)
                if fig_c:
                    st.plotly_chart(fig_c, use_container_width=True)
                pivot_c = df_year.pivot_table(
                    index="mes", columns="sistema", values=value_col_c, aggfunc="sum", fill_value=0
                )
                existing = [c for c in _col_order_c if c in pivot_c.columns]
                pivot_c = pivot_c[existing]
                pivot_c.columns = [_col_rename_c.get(c, c) for c in pivot_c.columns]
                pivot_c.index.name = "Mes"
                pivot_c = pivot_c.reindex([m for m in _month_order if m in pivot_c.index])
                pivot_c["Total"] = pivot_c.sum(axis=1)
                pivot_c.loc["Total"] = pivot_c.sum(axis=0)
                if "Monto" in (modo_c or ""):
                    pivot_c = pivot_c.apply(lambda col: col.map(lambda x: f"${float(x):,.0f}"))
                st.table(
                    pivot_c.style.apply(_style_cobros, axis=None).set_table_styles(TABLE_STYLES)
                )
    else:
        st.info("Sin cobros registrados.")

    st.divider()

    # ── Activación y caída de socios ──────────────────────────────────────────
    col_mov_h, col_mov_t = st.columns([3, 1], vertical_alignment="bottom")
    with col_mov_h:
        st.subheader("Activación y caída de socios")
    with col_mov_t:
        modo_mov = st.segmented_control("", ["🔢 Cantidad", "💰 Monto"], default="🔢 Cantidad", key="mov_modo", label_visibility="collapsed")
    if modo_mov is None:
        modo_mov = "🔢 Cantidad"

    df_act = _activacion_socios()
    df_cai = _caida_socios()

    if not df_act.empty or not df_cai.empty:
        value_col_mov = "cantidad" if "Cantidad" in (modo_mov or "") else "monto_total"
        if not df_act.empty: df_act["mes"] = df_act["mes"].map(_MES_ES)
        if not df_cai.empty: df_cai["mes"] = df_cai["mes"].map(_MES_ES)
        _col_rename_mov = {
            "virtualpos_vp1": "VirtualPOS VP1", "virtualpos_vp2": "VirtualPOS VP2",
            "tch": "TCH", "payku": "Payku", "toku": "Toku",
        }
        _col_order_mov = ["virtualpos_vp1", "virtualpos_vp2", "tch", "payku", "toku"]
        _month_order_mov = _month_order_es

        def _style_mov(df):
            s = pd.DataFrame("", index=df.index, columns=df.columns)
            s["Total"] = f"background-color: {TOTAL_ROW_BG}; color: {TOTAL_ROW_FG}; text-align: center; font-weight: 700;"
            s.loc["Total"] = f"background-color: {TOTAL_ROW_BG}; color: {TOTAL_ROW_FG}; text-align: center; font-weight: 700;"
            return s

        def _bar_mov(df_src, y_col, y_label):
            if df_src.empty: return None
            month_idx = {m: i for i, m in enumerate(_month_order_mov)}
            df_p = df_src.copy()
            df_p["_ord"] = df_p["mes"].map(month_idx).fillna(99)
            df_p = df_p.sort_values("_ord")
            df_p["sistema_label"] = df_p["sistema"].map(_RENAME_SISTEMA).fillna(df_p["sistema"])
            color_map = {_RENAME_SISTEMA.get(k, k): v for k, v in COLOR_SISTEMA.items()}
            fig = px.bar(df_p, x="mes", y=y_col, color="sistema_label", barmode="stack",
                         color_discrete_map=color_map,
                         labels={"mes": "Mes", y_col: y_label, "sistema_label": "Sistema"},
                         height=260)
            fig.update_layout(
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                font_color="#e2e8f0", margin=dict(l=0, r=0, t=10, b=0),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, title=None),
            )
            fig.update_xaxes(gridcolor="rgba(168,85,247,0.1)", showgrid=True)
            fig.update_yaxes(gridcolor="rgba(168,85,247,0.1)", showgrid=True)
            return fig

        def _build_pivot_mov(df_src, vcol, fmt_monto):
            if df_src.empty:
                return None
            pv = df_src.pivot_table(index="mes", columns="sistema", values=vcol, aggfunc="sum", fill_value=0)
            existing = [c for c in _col_order_mov if c in pv.columns]
            pv = pv[existing]
            pv.columns = [_col_rename_mov.get(c, c) for c in pv.columns]
            pv.index.name = "Mes"
            pv = pv.reindex([m for m in _month_order_mov if m in pv.index])
            pv["Total"] = pv.sum(axis=1)
            pv.loc["Total"] = pv.sum(axis=0)
            if fmt_monto:
                pv = pv.apply(lambda col: col.map(lambda x: f"${float(x):,.0f}"))

            return pv

        fmt = (modo_mov == "Monto")
        y_label_mov = "Suscripciones" if modo_mov == "Cantidad" else "Monto ($)"
        anios_mov = sorted(
            set(df_act["año"].dropna().astype(int).unique()) | set(df_cai["año"].dropna().astype(int).unique()),
            reverse=True,
        )
        tabs_mov = st.tabs([str(a) for a in anios_mov])
        for tab, anio in zip(tabs_mov, anios_mov):
            with tab:
                df_act_y = df_act[df_act["año"] == anio] if not df_act.empty else pd.DataFrame()
                df_cai_y = df_cai[df_cai["año"] == anio] if not df_cai.empty else pd.DataFrame()
                pv_act = _build_pivot_mov(df_act_y, value_col_mov, fmt)
                pv_cai = _build_pivot_mov(df_cai_y, value_col_mov, fmt)

                col_act, col_cai = st.columns(2)

                with col_act:
                    st.markdown("**Activaciones**")
                    fig_act = _bar_mov(df_act_y, value_col_mov, y_label_mov)
                    if fig_act:
                        st.plotly_chart(fig_act, use_container_width=True)
                    if pv_act is not None:
                        st.table(
                            pv_act.style.apply(_style_mov, axis=None).set_table_styles(TABLE_STYLES)
                        )
                    else:
                        st.caption("Sin activaciones este año.")

                with col_cai:
                    st.markdown("**Caídas**")
                    fig_cai = _bar_mov(df_cai_y, value_col_mov, y_label_mov)
                    if fig_cai:
                        st.plotly_chart(fig_cai, use_container_width=True)
                    if pv_cai is not None:
                        st.table(
                            pv_cai.style.apply(_style_mov, axis=None).set_table_styles(TABLE_STYLES)
                        )
                    else:
                        st.caption("Sin caídas registradas este año.")
    else:
        st.info("Sin datos de movimientos.")

except Exception as e:
    st.error(f"Error al cargar el dashboard: {e}")
