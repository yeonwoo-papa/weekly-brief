"""
주간 주요국 금융·거시경제 일정 및 시장 영향 리포트 생성기 (Gemini 4 Argon 기반)
--------------------------------------------------------------------------------
- 실행 주기: 매주 월요일 오전 08:00 (자체 스케줄러 내장 또는 Windows 작업 스케줄러 연동)
- 사용 모델: gemini-4-argon (Google Search Grounding 및 ThinkingConfig 활성화)
- 주요 기능:
  1. 한국·미국·주요 선진국(유로존·영국·일본) 주간 금융·경제 일정 웹 검색 조회
  2. 시장 컨센서스 및 주요 IB(Goldman Sachs, JPMorgan, Morgan Stanley, BofA, Citi 등) 예측치 수집
  3. 국내주식(KOSPI·업종·외국인 수급) 및 미국 관련 ETF(S&P500·나스닥·섹터·환노출/환헤지) 영향 분석
  4. HTML 및 PDF 리포트 자동 생성 (Playwright Chromium 활용) + 텔레그램 알림/파일 전송 지원

사전 패키지 설치:
    pip install --upgrade "google-genai>=2.34.0" markdown playwright requests python-dotenv schedule
    playwright install chromium

환경 변수 설정 (.env 또는 시스템 환경변수):
    GEMINI_API_KEY="발급받은_Google_AI_Studio_API_키"
    TELEGRAM_BOT_TOKEN="텔레그램_봇_토큰"       # (선택) 설정 시 텔레그램으로 요약 및 PDF 전송
    TELEGRAM_CHAT_ID="텔레그램_채팅_ID"         # (선택)
"""

import argparse
import datetime
import os
from pathlib import Path
import time
import xml.etree.ElementTree as ET
import requests
import markdown
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# =====================================================================
# 1. 기본 설정
# =====================================================================
MODEL_CANDIDATES = [
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
]
MODEL_ID = MODEL_CANDIDATES[0]
THINKING_LEVEL = "MEDIUM"  # 무료 티어 토큰/할당량 초과(429) 방지를 위해 MEDIUM 권장 ("LOW", "MEDIUM", "HIGH")
OUTPUT_DIR = Path("./weekly_macro_reports")


def get_week_date_range() -> tuple[str, str, str]:
    """실행일 기준 이번 주 월요일~일요일 날짜 문자열을 반환합니다."""
    today = datetime.date.today()
    # 월요일(0) 기준으로 이번 주 시작일 계산 (일요일에 실행하더라도 돌아오는 주 또는 해당 주 계산)
    monday = today - datetime.timedelta(days=today.weekday())
    sunday = monday + datetime.timedelta(days=6)
    week_label = f"{monday.strftime('%Y-%m-%d')} ~ {sunday.strftime('%Y-%m-%d')}"
    file_stamp = monday.strftime("%Y%m%d")
    return week_label, monday.strftime("%Y년 %m월 %d일"), file_stamp


def build_prompt(week_range: str) -> str:
    """Gemini 4 Argon 모델에 전달할 프롬프트를 생성합니다."""
    return f"""
당신은 글로벌 매크로 전략가이자 자산배분 애널리스트입니다.
이번 주({week_range})에 발표 예정인 한국, 미국 및 주요 선진국(유로존, 영국, 일본)의 금융·거시경제 이벤트 일정을 웹 검색으로 조회하고,
투자자의 핵심 자산 구성인 **국내주식(KOSPI, 주요 업종, 외국인/기관 수급)**과 **미국 관련 ETF(S&P500, 나스닥100, 주요 섹터 ETF, 환노출/환헤지형)**에 초점을 맞춘 주간 심층 보고서를 작성해 주세요.

반드시 Google 검색을 통해 최신 공식 발표 일정과 시장 컨센서스, 주요 IB(Goldman Sachs, JPMorgan, Morgan Stanley, Bank of America, Citi, Barclays 등) 및 국내외 주요 금융·연구기관(한국은행, KDI, 주요 증권사 리서치센터)의 전망치를 확인하고, 모든 수치와 전망 근거에 클릭 가능한 출처 링크([출처명](URL))를 포함해 주세요.

보고서는 아래 4개 섹션의 Markdown 구조로 작성해 주세요:

# 주간 글로벌 금융·거시경제 일정 및 포트폴리오 영향 보고서 ({week_range})

## 1. Executive Summary (이번 주 핵심 요약)
- **이번 주 3대 핵심 빅 이벤트:** 시장 변동성을 좌우할 가장 중요한 일정 요약
- **주간 글로벌 매크로 테마:** 주요 IB들이 공통으로 주목하는 핵심 변수 (금리 경로, 인플레이션, 고용, 유동성 등)
- **자산군별 주간 핵심 뷰:** 국내주식(KOSPI) 및 미국 ETF(환노출 vs 환헤지) 대응 한 줄 요약

## 2. 주간 주요국 금융·경제 발표 일정표 (한국 시간 KST 기준)
- 요일별·시간순(월요일~일요일)으로 정렬된 Markdown 표를 작성해 주세요.
- 표 컬럼: `일시(KST)` | `국가` | `이벤트/지표명` | `이전 수치` | `시장 컨센서스` | `주요 IB 전망 및 특징` | `중요도(★~★★★)`

## 3. 핵심 이벤트별 주요 IB 예측 및 시나리오 분석
중요도가 높은 핵심 이벤트(FOMC/금통위/ECB/BOJ 통화정책, 미국 CPI·PPI·PCE·고용보고서·GDP·ISM, 한국 수출입·물가 등)별로 각각 아래 항목을 상세히 분석해 주세요:
- **컨센서스 및 주요 IB 리포트 전망:** 기관별 구체적 수치 예측과 논거 (반드시 검증된 출처 링크 병기)
- **시나리오 A (예상치 상회 / 매파적 결과 시):**
  - 미 국채 금리(2년물·10년물) 및 원/달러 환율(USD/KRW) 예상 반응
  - **국내주식(KOSPI) 영향:** 외국인 수급 방향성, 수출주(반도체·자동차·2차전지 등) 및 내수/금융주 영향
  - **미국 관련 ETF 영향:** 지수형(S&P500·나스닥100), 성장주/가치주 섹터 ETF, 환노출형 vs 환헤지형(H) 유불리
- **시나리오 B (예상치 하회 / 비둘기파적 결과 시):**
  - 미 국채 금리 및 원/달러 환율 예상 반응
  - **국내주식(KOSPI) 영향:** 외국인 수급 및 주요 업종별 반응
  - **미국 관련 ETF 영향:** 지수·섹터별 반응 및 환노출/환헤지 전략
- **핵심 관전 포인트:** 헤드라인 수치 외에 시장이 민감하게 반응할 세부 항목(예: 근원 서비스 물가, 시간당 평균임금, 점도표, 총재 기자회견 발언 등)

## 4. 국내주식 및 미국 ETF 포트폴리오 주간 대응 전략
- **국내주식(KOSPI) 체크포인트:** 주간 외국인 수급 변수, 원/달러 환율 레벨에 따른 업종별 유불리, 변동성 확대 구간 대응 기준
- **미국 관련 ETF 체크포인트:** 미 국채 금리 및 달러 인덱스 흐름에 따른 미국 지수/섹터 ETF 비중 조절 포인트, 환율 흐름을 고려한 환노출/환헤지 선택 기준
"""


# =====================================================================
# 2. Gemini 4 Argon API 호출 (Google Search Grounding 활성화)
# =====================================================================

def fetch_live_macro_rss(max_items: int = 25) -> str:
    """Google Search Grounding이 무료 티어에서 제한될 경우를 대비해 무료 RSS에서 최신 경제/시장 뉴스를 수집합니다."""
    feeds = [
        ("미국/글로벌 증시", "https://news.google.com/rss/search?q=FOMC+OR+US+retail+sales+OR+Nvidia+earnings+OR+Goldman+Sachs+forecast&hl=en-US&gl=US&ceid=US:en"),
        ("한국 금융/코스피", "https://news.google.com/rss/search?q=%ED%95%9C%EA%B5%AD%EC%9D%80%ED%96%89+%EA%B8%88%EB%A6%AC+OR+%EC%BD%94%EC%8A%A4%ED%94%BC+%EC%A0%84%EB%A7%9D+OR+%EA%B2%BD%EC%A0%9C%EC%A7%80%ED%91%9C+%EC%9D%BC%EC%A0%95&hl=ko&gl=KR&ceid=KR:ko"),
    ]
    lines: list[str] = []
    for label, url in feeds:
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            root = ET.fromstring(r.content)
            items = root.findall(".//item")[: max_items // 2]
            lines.append(f"### [{label} 최신 헤드라인]")
            for it in items:
                title = (it.findtext("title") or "").strip()
                link = (it.findtext("link") or "").strip()
                pub = (it.findtext("pubDate") or "").strip()
                if title:
                    lines.append(f"- {title} ({pub}) - {link}")
        except Exception:
            continue
    return "\n".join(lines)

def generate_macro_report_markdown(week_range: str) -> str:
    """Gemini 4 Argon 모델을 호출하여 Google 검색 기반 마크다운 보고서를 생성합니다."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY 환경변수가 설정되어 있지 않습니다.")

    client = genai.Client(api_key=api_key)
    prompt = build_prompt(week_range)

    global MODEL_ID
    response = None
    last_error = None

    # 1차 시도: Google Search Grounding 포함 호출
    for candidate_model in MODEL_CANDIDATES:
        try:
            print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {candidate_model} (Search 포함) 모델로 주간 리포트 생성 중...")
            response = client.models.generate_content(
                model=candidate_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(
                        thinking_level=THINKING_LEVEL,
                    ),
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    max_output_tokens=16384,
                ),
            )
            MODEL_ID = candidate_model
            break
        except Exception as e:
            last_error = e
            print(f"[경고] {candidate_model} (Search 포함) 호출 실패 ({e}).")
            time.sleep(1)

    # 2차 시도: Search Grounding이 무료 티어에서 막힌 경우, 무료 RSS 뉴스 수집 후 일반 호출로 전환
    if response is None:
        print("[안내] 무료 RSS 피드에서 최신 금융 뉴스를 수집하여 일반 모드로 재시도합니다...")
        rss_context = fetch_live_macro_rss()
        fallback_prompt = prompt + f"\n\n[참고용 최신 금융·거시경제 RSS 뉴스]\n{rss_context}"
        for candidate_model in MODEL_CANDIDATES:
            try:
                print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {candidate_model} (RSS 기반) 모델로 재시도 중...")
                response = client.models.generate_content(
                    model=candidate_model,
                    contents=fallback_prompt,
                    config=types.GenerateContentConfig(
                        max_output_tokens=16384,
                    ),
                )
                MODEL_ID = candidate_model
                break
            except Exception as e:
                last_error = e
                print(f"[경고] {candidate_model} (RSS 기반) 호출 실패 ({e}).")
                time.sleep(1)

    if response is None:
        raise RuntimeError(f"모든 Gemini 모델 호출에 실패했습니다. 마지막 오류: {last_error}")

    report_md = response.text or ""

    # 검색 출처 메타데이터가 있을 경우 하단에 참고 링크 부록으로 자동 추가
    grounding_links = extract_grounding_links(response)
    if grounding_links:
        report_md += "\n\n## 부록: 참고 자료 및 검색 출처\n"
        for title, uri in grounding_links:
            report_md += f"- [{title}]({uri})\n"

    return report_md


def extract_grounding_links(response) -> list[tuple[str, str]]:
    """응답의 Grounding Metadata에서 웹 검색 출처(제목, URL) 목록을 추출합니다."""
    links: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    try:
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            metadata = getattr(candidate, "grounding_metadata", None)
            if not metadata:
                continue
            chunks = getattr(metadata, "grounding_chunks", None) or []
            for chunk in chunks:
                web = getattr(chunk, "web", None)
                if web and getattr(web, "uri", None):
                    uri = web.uri
                    title = getattr(web, "title", None) or uri
                    if uri not in seen_urls:
                        seen_urls.add(uri)
                        links.append((title, uri))
    except Exception:
        pass
    return links


# =====================================================================
# 3. Markdown -> HTML 및 PDF 변환
# =====================================================================
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>주간 글로벌 금융 일정 및 시장 영향 보고서 ({week_range})</title>
    <style>
        @page {{
            size: A4;
            margin: 18mm 15mm 18mm 15mm;
        }}
        body {{
            font-family: "Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", sans-serif;
            font-size: 10.5pt;
            line-height: 1.6;
            color: #1f2937;
            margin: 0;
            padding: 0;
        }}
        h1 {{
            font-size: 18pt;
            color: #0f172a;
            border-bottom: 2px solid #1e3a8a;
            padding-bottom: 8px;
            margin-top: 0;
        }}
        h2 {{
            font-size: 13.5pt;
            color: #1e3a8a;
            background-color: #f1f5f9;
            padding: 6px 10px;
            border-left: 4px solid #1e3a8a;
            margin-top: 22px;
            margin-bottom: 10px;
            page-break-after: avoid;
        }}
        h3 {{
            font-size: 11.5pt;
            color: #0f172a;
            margin-top: 16px;
            margin-bottom: 6px;
            page-break-after: avoid;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 12px 0 18px 0;
            font-size: 9.5pt;
        }}
        th {{
            background-color: #1e3a8a;
            color: #ffffff;
            font-weight: 600;
            padding: 8px 10px;
            border: 1px solid #cbd5e1;
            text-align: left;
        }}
        td {{
            padding: 7px 10px;
            border: 1px solid #cbd5e1;
            vertical-align: top;
        }}
        tr:nth-child(even) td {{
            background-color: #f8fafc;
        }}
        ul, ol {{
            margin-top: 4px;
            margin-bottom: 10px;
            padding-left: 20px;
        }}
        li {{
            margin-bottom: 4px;
        }}
        a {{
            color: #2563eb;
            text-decoration: none;
        }}
        blockquote {{
            border-left: 3px solid #94a3b8;
            background: #f8fafc;
            margin: 10px 0;
            padding: 8px 12px;
            color: #334155;
        }}
        .footer-meta {{
            margin-top: 24px;
            padding-top: 8px;
            border-top: 1px solid #cbd5e1;
            font-size: 8.5pt;
            color: #64748b;
            text-align: right;
        }}
    </style>
</head>
<body>
    {body_html}
    <div class="footer-meta">
        Generated by {model_id} (Thinking: {thinking_level}) | 생성 시각: {generated_at}
    </div>
</body>
</html>
"""


def save_report_files(report_md: str, week_range: str, file_stamp: str) -> tuple[Path, Path, Path]:
    """마크다운 텍스트를 .md, .html, .pdf 파일로 각각 저장합니다."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    md_path = OUTPUT_DIR / f"weekly_macro_report_{file_stamp}.md"
    html_path = OUTPUT_DIR / f"weekly_macro_report_{file_stamp}.html"
    pdf_path = OUTPUT_DIR / f"weekly_macro_report_{file_stamp}.pdf"

    # 1. Markdown 저장
    md_path.write_text(report_md, encoding="utf-8")

    # 2. HTML 변환 및 저장
    body_html = markdown.markdown(
        report_md,
        extensions=["tables", "fenced_code", "nl2br", "sane_lists"],
    )
    full_html = HTML_TEMPLATE.format(
        week_range=week_range,
        body_html=body_html,
        model_id=MODEL_ID,
        thinking_level=THINKING_LEVEL,
        generated_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S KST"),
    )
    html_path.write_text(full_html, encoding="utf-8")

    # 3. Playwright (Chromium)를 이용한 PDF 렌더링
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(full_html, wait_until="networkidle")
            page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                margin={"top": "18mm", "bottom": "18mm", "left": "15mm", "right": "15mm"},
            )
            browser.close()
        print(f"[완료] PDF 리포트 저장 완료: {pdf_path.resolve()}")
    except Exception as e:
        print(f"[안내] PDF 변환 중 예외 발생 ({e}). HTML 및 Markdown 파일은 정상 저장되었습니다: {html_path.resolve()}")

    return md_path, html_path, pdf_path


# =====================================================================
# 4. 텔레그램 알림 및 PDF 파일 전송 (선택 사항)
# =====================================================================
def send_telegram_report(pdf_path: Path, week_range: str, report_md: str) -> None:
    """TELEGRAM_BOT_TOKEN과 TELEGRAM_CHAT_ID가 설정된 경우 요약 메시지 및 PDF 파일을 전송합니다."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        return

    # 상단 요약 부분만 추출하여 메시지로 먼저 전송 (최대 1,000자)
    preview_text = report_md[:1000] + ("\n...(상세 내용은 첨부 PDF 참조)" if len(report_md) > 1000 else "")
    msg_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    requests.post(
        msg_url,
        data={
            "chat_id": chat_id,
            "text": f"📊 [주간 주요국 금융 일정 및 시장 영향 리포트: {week_range}]\nModel: {MODEL_ID}\n\n{preview_text}",
        },
        timeout=30,
    )

    # 생성된 PDF 파일 첨부 전송
    if pdf_path.exists():
        doc_url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
        with pdf_path.open("rb") as f:
            requests.post(
                doc_url,
                data={"chat_id": chat_id, "caption": f"📎 {week_range} 주간 금융 일정 상세 보고서 (PDF)"},
                files={"document": (pdf_path.name, f, "application/pdf")},
                timeout=60,
            )
        print("[완료] 텔레그램으로 리포트 요약 및 PDF 파일 전송을 완료했습니다.")


# =====================================================================
# 5. 실행 엔트리포인트 및 스케줄러
# =====================================================================
def run_weekly_job() -> None:
    """1회 주간 리포트 생성 및 파일 저장/전송 작업을 수행합니다."""
    week_range, _, file_stamp = get_week_date_range()
    report_md = generate_macro_report_markdown(week_range)
    _, _, pdf_path = save_report_files(report_md, week_range, file_stamp)
    send_telegram_report(pdf_path, week_range, report_md)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gemini 4 Argon 기반 주간 금융 리포트 자동 생성기")
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="상시 실행 모드로 전환하여 매주 월요일 08:00에 자동 실행합니다.",
    )
    args = parser.parse_args()

    if args.daemon:
        import schedule

        schedule.every().monday.at("08:00").do(run_weekly_job)
        print(f"[대기 중] 매주 월요일 08:00에 {MODEL_ID} 모델로 리포트를 생성합니다. (Ctrl+C로 종료)")
        while True:
            schedule.run_pending()
            time.sleep(30)
    else:
        run_weekly_job()


if __name__ == "__main__":
    main()
