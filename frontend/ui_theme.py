"""CoursePilot 的轻量视觉规范；业务页面仍使用 Streamlit 原生组件。"""

import streamlit as st


def apply_platform_theme():
    st.html("""
    <style>
      [data-testid="stAppViewContainer"] { background: #f6f8fb; }
      [data-testid="stHeader"] { background: rgba(246,248,251,.94); }
      [data-testid="stMainBlockContainer"] { max-width: 1260px; padding-top: 1.75rem; padding-bottom: 4rem; }
      [data-testid="stSidebar"] { background: #eaf0f4; border-right: 1px solid #dce6eb; }
      [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: .8rem; }
      [data-testid="stSidebar"] [role="radiogroup"] label { border-radius: 10px; padding: .42rem .55rem; }
      [data-testid="stSidebar"] [role="radiogroup"] label:hover { background: #dcebef; }
      [data-testid="stMetric"] { background: white; border: 1px solid #e1e8ed; border-radius: 14px; padding: 1rem 1.15rem; }
      [data-testid="stVerticalBlockBorderWrapper"] { border-color: #e1e8ed; border-radius: 16px; }
      [data-testid="stForm"] { border-color: #e1e8ed; border-radius: 16px; }
      [data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; }
      h1, h2, h3 { letter-spacing: -.025em; color: #142a3a; }
      h1 { font-weight: 760; }
      .cp-eyebrow { color: #127178; font-size: .78rem; font-weight: 750; letter-spacing: .13em; text-transform: uppercase; }
      .cp-hero { background: linear-gradient(110deg,#123246,#174b58 62%,#126d72); border-radius: 20px; color: white; padding: 1.7rem 2rem; margin: .35rem 0 1.55rem; }
      .cp-hero h1 { color: white; font-size: clamp(1.7rem,3vw,2.35rem); margin: .3rem 0 .35rem; }
      .cp-hero p { color: #d8e8ea; margin: 0; max-width: 54rem; line-height: 1.65; }
      .cp-hero .cp-eyebrow { color: #99e1d8; }
      .cp-brand { font-size: 1.35rem; font-weight: 800; color: #133847; letter-spacing: -.04em; }
      .cp-brand-mark { display:inline-block; background:#126d72; color:white; border-radius:9px; padding:.08rem .5rem; margin-right:.45rem; }
      .cp-muted { color:#607484; font-size:.86rem; line-height:1.5; }
    </style>
    """)


def page_intro(title: str, description: str, eyebrow: str = "COURSEPILOT / WORKSPACE"):
    """静态标题区，不插入任何用户提交的内容。"""
    st.html(
        '<div class="cp-hero"><div class="cp-eyebrow">' + eyebrow +
        '</div><h1>' + title + '</h1><p>' + description + '</p></div>'
    )


def sidebar_brand():
    st.html(
        '<div class="cp-brand"><span class="cp-brand-mark">C</span>CoursePilot</div>'
        '<div class="cp-muted">教学、测评与智能复习工作台</div>'
    )
