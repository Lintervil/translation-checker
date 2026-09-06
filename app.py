from __future__ import annotations

import hashlib
import html
import io
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

from checker import automatic_exceptions, check_page, parse_exceptions, top_words
from crawler import crawl_pages, crawl_site, normalize_url
from sitemap import get_sitemap_pages


st.set_page_config(
    page_title="Перевод QA",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root { color-scheme: dark; }
    .stApp { background: #0c1015; color: #e8edf2; }
    [data-testid="stHeader"] { background: #0c1015; }
    [data-testid="stSidebar"] { background: #121820; border-right: 1px solid #273240; }
    .block-container { max-width: 1480px; padding-top: 2.4rem; }
    h1, h2, h3 { color: #f5f7fa !important; letter-spacing: -0.025em; }
    .eyebrow { color: #8fa2b5; font-size: .76rem; font-weight: 800; letter-spacing: .13em; text-transform: uppercase; }
    .lede { color: #a4b1bf; font-size: 1.04rem; max-width: 850px; margin-bottom: 1.5rem; }
    .metric-card { background: #121820; border: 1px solid #273240; border-radius: 10px; padding: 15px 18px; min-height: 84px; }
    .metric-label { color: #8fa2b5; font-size: .74rem; text-transform: uppercase; letter-spacing: .08em; }
    .metric-value { color: #f5f7fa; font-size: 1.8rem; font-weight: 760; margin-top: 5px; }
    .issue-card { background: #171d25; border: 1px solid #34404e; border-left: 3px solid #ff6259; border-radius: 8px; padding: 12px 15px; margin: 7px 0; }
    .issue-word { color: #ff9d96; font-size: 1.05rem; font-weight: 750; }
    .issue-meta { color: #a4b1bf; font-size: .84rem; margin-top: 4px; }
    .status-ok { color: #58d68d; font-weight: 700; }
    .status-error { color: #ff8179; font-weight: 700; }
    .source-pill { color: #a4b1bf; border: 1px solid #34404e; border-radius: 99px; padding: 3px 9px; font-size: .76rem; }
    div[data-testid="stExpander"] { border: 1px solid #273240; border-radius: 10px; background: #121820; }
    div[data-testid="stCode"] { border: 1px solid #34404e; border-radius: 7px; }
    </style>
    """,
    unsafe_allow_html=True,
)


def _safe(value: str) -> str:
    return html.escape(str(value or ""), quote=True)


def _issue_rows(pages: list[dict]) -> list[dict[str, str]]:
    rows = []
    for page_number, page in enumerate(pages, 1):
        for issue in page.get("issues", []):
            rows.append(
                {
                    "Страница": page_number,
                    "URL": page["url"],
                    "Слово или фраза": issue["word"],
                    "Контекст": issue["context"],
                    "Источник": issue["source"],
                }
            )
    return rows


def _recheck_pages(pages: list[dict], custom_exceptions: str, automatic_whitelist: set[str], ignored_words: set[str]) -> None:
    combined = parse_exceptions(custom_exceptions) | set(automatic_whitelist) | set(ignored_words)
    for page in pages:
        page["issues"] = check_page(page, combined)


def _ignore_word_key(word: str) -> str:
    digest = hashlib.sha1(word.casefold().encode("utf-8")).hexdigest()[:12]
    return f"ignore-word-{digest}"


def _show_frequent_word_controls(pages: list[dict]) -> None:
    counts = dict(top_words(pages))
    ignored = set(st.session_state.get("ignored_words", set()))
    words = sorted(set(counts) | ignored)
    if not words:
        return

    st.markdown("### Исключения из текущего отчёта")
    st.caption("Поставьте галочку рядом со словом, которое является брендом, моделью или постоянным термином. Оно сразу исчезнет из ошибок.")
    columns = st.columns(2)
    selected: set[str] = set()
    for index, word in enumerate(words):
        count = counts.get(word)
        label = f"{word} · {count} раз" if count is not None else f"{word} · исключено"
        with columns[index % 2]:
            if st.checkbox(label, value=word in ignored, key=_ignore_word_key(word)):
                selected.add(word)

    if selected != ignored:
        st.session_state["ignored_words"] = selected
        _recheck_pages(
            pages,
            st.session_state.get("custom_exceptions", ""),
            set(st.session_state.get("automatic_whitelist", set())),
            selected,
        )

def _show_page(page_number: int, page: dict) -> None:
    issues = page.get("issues", [])
    crawl_error = page.get("error", "")
    label = f"❌ Страница {page_number}: {page['url']} · найдено слов: {len(issues)}" if issues else f"✅ Страница {page_number}: {page['url']} · слов: 0"
    with st.expander(label, expanded=bool(issues or crawl_error)):
        st.markdown(
            f"<a href='{_safe(page['url'])}' target='_blank' rel='noopener'>Открыть оригинальную страницу в новой вкладке ↗</a>",
            unsafe_allow_html=True,
        )
        if crawl_error:
            st.error(f"Страница не загрузилась: {crawl_error}")
            return

        if issues:
            st.markdown("#### Найденные нарушения")
            for issue in issues:
                st.markdown(
                    f"<div class='issue-card'><div class='issue-word'>{_safe(issue['word'])}</div>"
                    f"<div class='issue-meta'>{_safe(issue['context'])}</div>"
                    f"<div class='issue-meta'><span class='source-pill'>{_safe(issue['source'])}</span> "
                    "</div></div>",
                    unsafe_allow_html=True,
                )
                st.caption("Задача для контент-менеджера · кнопка копирования встроена в блок")
                st.code(
                    f"Страница: {page['url']}\n- {issue['word']} — «{issue['context']}»",
                    language=None,
                )
        else:
            st.markdown("<div class='status-ok'>Непереведённый английский текст не найден.</div>", unsafe_allow_html=True)


def _finalize_pages(pages: list[dict], start_url: str, custom_exceptions: str, ignore_site_names: bool) -> None:
    automatic_whitelist = automatic_exceptions(start_url, pages) if ignore_site_names else set()
    st.session_state["ignored_words"] = set()
    st.session_state["automatic_whitelist"] = automatic_whitelist
    for key in list(st.session_state):
        if key.startswith("ignore-word-"):
            del st.session_state[key]
    for page in pages:
        page["issues"] = check_page(page, parse_exceptions(custom_exceptions) | automatic_whitelist)
    st.session_state["automatic_whitelist_count"] = len(automatic_whitelist)
    st.session_state["pages"] = pages
    st.session_state["crawl_limit_reached"] = bool(pages and pages[0].get("_limit_reached"))


def _show_navigation_plan(pages: list[dict], start_url: str) -> None:
    labels = {
        "home": "Главная",
        "catalog": "Каталог",
        "product": "Карточка товара",
        "content": "Статья/информация",
        "nav": "Навигация",
    }
    counts: dict[str, int] = {}
    for page in pages:
        kind = page.get("kind", "content")
        counts[kind] = counts.get(kind, 0) + 1
    st.markdown("### План проверки")
    st.caption(
        f"План построен от {start_url}: сначала главная и каталоги, затем карточки товаров, после этого статьи и остальные ссылки."
    )
    metric_columns = st.columns(5)
    for column, kind in zip(metric_columns, ["home", "catalog", "product", "content", "total"]):
        with column:
            label = "Всего" if kind == "total" else labels.get(kind, kind)
            value = len(pages) if kind == "total" else counts.get(kind, 0)
            st.metric(label, value)
    rows = [
        {"Порядок": index, "Тип": labels.get(page.get("kind", "content"), "Страница"), "URL": page["url"]}
        for index, page in enumerate(pages, 1)
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


st.markdown("<div class='eyebrow'>Translation QA / Russian websites</div>", unsafe_allow_html=True)
st.title("Проверка качества перевода сайтов")
st.markdown(
    "<div class='lede'>Расчет плана навигации</div>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### Параметры проверки")
    site_url = st.text_input(
        "URL сайта",
        value=st.session_state.get("site_url", "https://gorenje-ru.ru/"),
        placeholder="https://example.ru/",
        help="Проверяются только ссылки на том же домене.",
    )
    navigation_mode = "🧭 Навигация — путь пользователя"
    sitemap_mode = "🗺 Sitemap — страницы для поисковика"
    all_links_mode = "🔗 Все ссылки"
    page_mode = st.radio(
        "Какие страницы проверять",
        [navigation_mode, sitemap_mode, all_links_mode],
        index=0,
        help="Навигация проверяет главную, видимые ссылки из её блоков, шапки и футера, разделы каталога и несколько карточек товара.",
    )
    depth = st.number_input(
        "Глубина обхода",
        min_value=0,
        max_value=3,
        value=3,
        step=1,
        disabled=page_mode == sitemap_mode,
        help="Используется в режимах навигации и всех ссылок. 0 — только указанная страница, 3 — глубокий обход.",
    )
    max_pages = st.number_input(
        "Лимит страниц",
        min_value=1,
        max_value=500,
        value=100,
        step=10,
        help="Защитный предел по умолчанию — 100 страниц, чтобы сайт не ушёл в бесконечный обход.",
    )
    unlimited_pages = st.checkbox(
        "Снять защитный лимит страниц",
        value=False,
        disabled=page_mode == sitemap_mode,
        help="Отключает предел полностью. Используйте только если уверены, что на сайте нет бесконечных фильтров и календарей.",
    )
    product_sample = st.number_input(
        "Карточек товара на раздел",
        min_value=1,
        max_value=10,
        value=3,
        step=1,
        help="Из каждой страницы каталога проверяется несколько карточек, а не все товары.",
    )
    custom_exceptions = st.text_area(
        "Свои слова и модели-исключения",
        value=st.session_state.get("custom_exceptions", ""),
        height=130,
        placeholder="Например:\nBrandName\nвнутренний термин",
        help="Одно слово на строку, либо через запятую. Сохраняется в текущей сессии приложения.",
    )
    ignore_site_names = st.checkbox(
        "Автоматически исключать название сайта, бренды и модели",
        value=True,
        help="Белый список собирается из домена, логотипа и названий товаров в H1. Отключите для максимально строгой проверки.",
    )
    expand_dynamic = st.checkbox(
        "Раскрывать динамический контент",
        value=True,
        help="Прокрутка lazy-load, меню, аккордеоны, табы и стрелки каруселей.",
    )
    plan_navigation = st.button(
        "Рассчитать план навигации",
        disabled=page_mode != navigation_mode,
        use_container_width=True,
        help="Показывает порядок страниц и количество до запуска проверки.",
    )
    check_plan = st.button(
        "Проверить составленный план",
        disabled=page_mode != navigation_mode or not st.session_state.get("navigation_plan_pages"),
        type="primary",
        use_container_width=True,
    )
    run = st.button("Запустить проверку", type="primary", use_container_width=True)
    if st.button("Очистить результаты", use_container_width=True):
        st.session_state.pop("pages", None)
        st.session_state.pop("navigation_plan_pages", None)
        st.session_state.pop("navigation_plan_url", None)
        st.rerun()
    st.divider()
    st.caption("По умолчанию проверяется путь пользователя: главная, её блоки, шапка, футер, статьи, каталог и несколько карточек товара на раздел.")


if plan_navigation or check_plan or run:
    normalized = normalize_url(site_url)
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        st.error("Введите корректный URL, например https://example.ru/")
    else:
        st.session_state["site_url"] = site_url
        st.session_state["custom_exceptions"] = custom_exceptions
        progress = st.progress(0)
        status = st.empty()
        try:
            if plan_navigation and page_mode == navigation_mode:
                pages = crawl_site(
                    normalized,
                    max_depth=None if unlimited_pages else int(depth),
                    max_pages=None if unlimited_pages else int(max_pages),
                    product_sample=int(product_sample),
                    expand_dynamic=expand_dynamic,
                    smart_mode=True,
                    progress=progress.progress,
                    status=status.info,
                )
                st.session_state["navigation_plan_pages"] = pages
                st.session_state["navigation_plan_url"] = normalized
                st.session_state.pop("pages", None)
                progress.progress(1.0)
                status.success(f"План построен: {len(pages)} страниц")
            elif check_plan and page_mode == navigation_mode:
                pages = st.session_state.pop("navigation_plan_pages", [])
                plan_url = st.session_state.pop("navigation_plan_url", normalized)
                _finalize_pages(pages, plan_url, custom_exceptions, ignore_site_names)
                progress.progress(1.0)
                status.success(f"Проверка завершена: {len(pages)} страниц")
            elif run:
                if page_mode == sitemap_mode:
                    sitemap_items = get_sitemap_pages(
                        normalized,
                        headers={"User-Agent": "TranslationQA/1.0"},
                        max_pages=int(max_pages),
                    )
                    st.info(f"Отобрано страниц из sitemap: {len(sitemap_items)}")
                    sitemap_urls = [item["url"] for item in sitemap_items]
                    if sitemap_urls:
                        pages = crawl_pages(
                            sitemap_urls,
                            max_pages=len(sitemap_urls),
                            expand_dynamic=expand_dynamic,
                            progress=progress.progress,
                            status=status.info,
                            headers={"User-Agent": "TranslationQA/1.0"},
                        )
                    else:
                        pages = []
                        status.warning("В sitemap не найдено подходящих страниц")
                elif page_mode == navigation_mode:
                    pages = crawl_site(
                        normalized,
                        max_depth=None if unlimited_pages else int(depth),
                        max_pages=None if unlimited_pages else int(max_pages),
                        product_sample=int(product_sample),
                        expand_dynamic=expand_dynamic,
                        smart_mode=True,
                        progress=progress.progress,
                        status=status.info,
                    )
                else:
                    pages = crawl_site(
                        normalized,
                        max_depth=None if unlimited_pages else int(depth),
                        max_pages=None if unlimited_pages else int(max_pages),
                        product_sample=int(product_sample),
                        expand_dynamic=expand_dynamic,
                        smart_mode=False,
                        progress=progress.progress,
                        status=status.info,
                    )
                st.session_state.pop("navigation_plan_pages", None)
                st.session_state.pop("navigation_plan_url", None)
                _finalize_pages(pages, normalized, custom_exceptions, ignore_site_names)
                progress.progress(1.0)
                if st.session_state["crawl_limit_reached"]:
                    status.warning(f"Проверка остановлена на защитном лимите: {len(pages)} страниц")
                elif pages:
                    status.success(f"Проверка завершена: {len(pages)} страниц")
        except Exception as error:
            st.error(f"Не удалось запустить проверку: {error}")


plan_pages = st.session_state.get("navigation_plan_pages")
if plan_pages:
    _show_navigation_plan(plan_pages, st.session_state.get("navigation_plan_url", site_url))

pages = st.session_state.get("pages")
if pages is None:
    if plan_pages:
        st.info("План готов. Нажмите слева «Проверить составленный план», чтобы получить отчёт.")
    else:
        st.info("Укажите сайт слева и нажмите «Рассчитать план навигации» или «Запустить проверку».")
else:
    _show_frequent_word_controls(pages)
    issue_count = sum(len(page.get("issues", [])) for page in pages)
    error_pages = sum(bool(page.get("issues")) for page in pages)
    failed_pages = sum(bool(page.get("error")) for page in pages)
    metrics = st.columns(4)
    for column, label, value in zip(
        metrics,
        ["Проверено страниц", "Страниц с нарушениями", "Найдено слов", "Ошибок загрузки"],
        [len(pages), error_pages, issue_count, failed_pages],
    ):
        with column:
            st.markdown(
                f"<div class='metric-card'><div class='metric-label'>{label}</div><div class='metric-value'>{value}</div></div>",
                unsafe_allow_html=True,
            )

    st.markdown("### Частые нарушения")
    automatic_count = st.session_state.get("automatic_whitelist_count", 0)
    if automatic_count:
        st.caption(f"Автоматически исключено названий сайта и моделей: {automatic_count}")
    frequent = top_words(pages)
    if frequent:
        st.dataframe(
            pd.DataFrame(frequent, columns=["Слово или фраза", "Количество"]),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.success("Непереведённого английского текста не найдено.")

    st.markdown("### Отчёт по страницам")
    rows = _issue_rows(pages)
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    else:
        st.info("Таблица нарушений пуста: английские слова вне белого списка не найдены.")
    filter_text = st.text_input("Фильтр по URL или найденному слову", placeholder="Например: catalog или collection")
    only_problems = st.checkbox("Показывать только страницы с нарушениями")
    for index, page in enumerate(pages, 1):
        searchable = page["url"] + " " + " ".join(issue["word"] for issue in page.get("issues", []))
        if filter_text and filter_text.casefold() not in searchable.casefold():
            continue
        if only_problems and not page.get("issues"):
            continue
        _show_page(index, page)

    csv_data = pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig")
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, index=False, sheet_name="Нарушения")
        pd.DataFrame(
            [{"URL": page["url"], "Глубина": page["depth"], "Найдено слов": len(page.get("issues", [])), "Ошибка загрузки": page.get("error", "")} for page in pages]
        ).to_excel(writer, index=False, sheet_name="Страницы")

    st.markdown("### Скачать данные")
    left, right = st.columns(2)
    with left:
        st.download_button("Скачать CSV", csv_data, "translation-report.csv", "text/csv")
    with right:
        st.download_button("Скачать Excel", excel_buffer.getvalue(), "translation-report.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
