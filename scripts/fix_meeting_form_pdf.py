from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "졸업프로젝트_면담확인서_페이지수정.pdf"

pdfmetrics.registerFont(TTFont("Malgun", r"C:\Windows\Fonts\malgun.ttf"))
pdfmetrics.registerFont(TTFont("MalgunBold", r"C:\Windows\Fonts\malgunbd.ttf"))

PAGE_W, PAGE_H = A4
LEFT = 24 * mm
RIGHT = 24 * mm
TOP = 24 * mm
BOTTOM = 20 * mm
CONTENT_W = PAGE_W - LEFT - RIGHT

normal = ParagraphStyle(
    "normal",
    fontName="Malgun",
    fontSize=10.4,
    leading=18.5,
    textColor=colors.HexColor("#111111"),
    alignment=TA_LEFT,
    wordWrap="CJK",
    spaceAfter=10,
)
cell = ParagraphStyle(
    "cell",
    parent=normal,
    fontSize=10.3,
    leading=15,
    spaceAfter=0,
)
label = ParagraphStyle(
    "label",
    parent=cell,
    alignment=TA_CENTER,
)
body = ParagraphStyle(
    "body",
    parent=normal,
    fontSize=10.15,
    leading=18.2,
    spaceAfter=0,
)


def P(text: str, style=cell) -> Paragraph:
    return Paragraph(text.replace("\n", "<br/>"), style)


def heading(week: int) -> Paragraph:
    return Paragraph(
        f'<font name="MalgunBold">졸업프로젝트 면담확인서 - </font>'
        f'<font name="MalgunBold" color="#0000EE">9월 {week}주차</font>',
        ParagraphStyle(
            f"heading-{week}",
            fontName="MalgunBold",
            fontSize=22,
            leading=28,
            alignment=TA_CENTER,
            textColor=colors.black,
        ),
    )


def make_week(week: int, topic: str, date: str, paragraphs: list[str]):
    elements = [heading(week), Spacer(1, 15 * mm)]

    header = Table(
        [
            [P("팀원", label), P("이동찬", cell)],
            [P("주제", label), P(topic, cell)],
            [P("면담일시", label), P(date, label), P("지도교수", label), P("(인)", label)],
        ],
        colWidths=[22 * mm, 50 * mm, 38 * mm, CONTENT_W - 110 * mm],
        rowHeights=[17 * mm, 10 * mm, 12 * mm],
    )
    header.setStyle(
        TableStyle(
            [
                ("SPAN", (1, 0), (3, 0)),
                ("SPAN", (1, 1), (3, 1)),
                ("BOX", (0, 0), (-1, -1), 0.65, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.65, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
            ]
        )
    )
    elements.append(header)

    content = "<br/><br/>".join(paragraphs)
    body_table = Table(
        [[P("면<br/><br/>담<br/><br/>내<br/><br/>용", label), P(content, body)]],
        colWidths=[22 * mm, CONTENT_W - 22 * mm],
        rowHeights=[150 * mm],
    )
    body_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.65, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.65, colors.black),
                ("VALIGN", (0, 0), (0, 0), "MIDDLE"),
                ("VALIGN", (1, 0), (1, 0), "TOP"),
                ("LEFTPADDING", (1, 0), (1, 0), 4 * mm),
                ("RIGHTPADDING", (1, 0), (1, 0), 4 * mm),
                ("TOPPADDING", (1, 0), (1, 0), 9 * mm),
                ("BOTTOMPADDING", (1, 0), (1, 0), 6 * mm),
            ]
        )
    )
    elements.append(body_table)
    return elements


weeks = [
    (
        2,
        "관심 분야 공유 및 졸업 프로젝트 주제 탐색",
        "2026. 09. 10.",
        [
            "첫 면담으로 간단한 인사와 함께 졸업 프로젝트 진행 방식에 관해 이야기하였다. 평소 데이터 엔지니어링과 AI를 활용한 서비스 개발에 관심이 있으며, 공공데이터나 실제 생활에서 느낀 불편을 해결하는 프로젝트를 진행해 보고 싶다고 말씀드렸다.",
            "아직 구체적인 주제가 정해지지 않은 상태였기 때문에, 관심 분야를 바탕으로 구현 가능성과 활용 목적이 분명한 주제를 찾아보기로 하였다. 다음 면담까지 졸업 프로젝트로 진행하고 싶은 구체적인 주제 후보를 정리해 오기로 하였다.",
        ],
    ),
    (
        3,
        "프로젝트 후보 비교 및 최종 주제 선정",
        "2026. 09. 17.",
        [
            "졸업 프로젝트 후보로 다음 두 가지 주제를 정리하여 면담을 진행하였다.",
            "첫 번째는 다대일 AI 모의면접 플랫폼이다. 자기소개서와 지원 직무를 분석하여 실무 면접관과 인사 면접관 역할의 AI가 질문을 생성하고, 이전 질문과 답변을 공유하면서 각자의 관점에서 꼬리질문을 이어가는 서비스이다. 답변 내용뿐만 아니라 말하기 속도, 침묵, 시선 등의 음성·영상 정보까지 분석하여 피드백을 제공하는 방향으로 생각하였다.",
            "두 번째는 서울시 따릉이 수요 예측 및 재배치 지원 시스템이다. 따릉이를 이용할 때 원하는 대여소에 자전거가 없는 경우를 자주 경험한 것에서 시작한 주제이다. 대여·반납 이력, 실시간 자전거 수, 날씨 등의 데이터를 활용해 대여소별 수요를 예측하고, 부족·과잉이 예상되는 대여소와 재배치 후보를 운영자에게 제공하는 것을 목표로 하였다.",
            "두 주제를 비교한 결과, AI 모의면접은 기능 범위가 넓어질 가능성이 크고 기존 AI 서비스와 차별화하기 어려울 수 있다는 의견이 있었다. 반면 따릉이 재배치 시스템은 데이터 수집·정제·예측·서빙·시각화 과정을 모두 포함할 수 있고, 문제와 서비스 목적도 명확하다는 점에서 졸업 프로젝트에 더 적합하다고 판단하였다. 이에 따라 최종 주제를 따릉이 수요 예측 및 재배치 지원 시스템으로 결정하였다.",
            "다음 면담까지 활용 가능한 따릉이 데이터와 구체적인 서비스 기능을 조사하기로 하였다.",
        ],
    ),
    (
        4,
        "따릉이 재배치 지원 서비스의 기능 및 구현 방향 구체화",
        "2026. 10. 01.",
        [
            "선정한 주제를 구체화하기 위해 따릉이 관련 데이터와 서비스의 주요 기능을 정리하였다. 대여소별 실시간 자전거 수, 거치대 수, 위치 정보와 5분 단위 대여·반납 이력, 시간대별 운영현황 등을 주요 데이터로 활용하기로 하였다.",
            "향후 30분 동안의 예상 대여량과 반납량을 이용해 예상 재고를 계산하고, 이를 바탕으로 대여소의 상태를 정상·부족·과잉으로 구분하는 방향을 설명하였다. 예측 결과를 통해 자전거 부족·과잉이 예상되는 대여소, 재배치 우선순위, 보충 또는 수거 권장 수량을 제공하기로 하였다. 또한 부족 대여소와 가까운 과잉 대여소를 연결하여 출발·도착 대여소, 이동 권장 수량, 거리, 재배치 후 예상 재고를 보여주는 기능도 구상하였다.",
            "서비스 결과는 운영자용 대시보드에서 확인할 수 있도록 구성하였다. 전체 대여소 현황을 보여주는 요약 지표, 서울 지도, 재배치 우선순위 표, 대여소별 재고 추이와 예측 결과를 보여주는 상세 패널, 추천 재배치 경로 등을 주요 화면으로 계획하였다.",
            "교수님께서는 다음 면담까지 더미데이터를 사용하여 전체 서비스의 동작을 확인할 수 있는 간단한 프로토타입을 먼저 구현해 보는 것이 좋겠다고 말씀하셨다. 기본 대시보드와 예측·재배치 흐름을 구현하여 필요한 입력 데이터와 출력 결과를 확인한 후, 적용 가능한 시계열 및 머신러닝 모델을 조사하고 수요 예측에 사용할 모델의 종류와 학습 방법을 구체화하기로 하였다.",
        ],
    ),
]


def build_pdf() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=LEFT,
        rightMargin=RIGHT,
        topMargin=TOP,
        bottomMargin=BOTTOM,
        title="졸업프로젝트 면담확인서",
        author="이동찬",
    )
    frame = Frame(LEFT, BOTTOM, CONTENT_W, PAGE_H - TOP - BOTTOM, id="main", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="meeting", frames=[frame])])

    story = []
    for index, week in enumerate(weeks):
        story.extend(make_week(*week))
        if index != len(weeks) - 1:
            story.append(PageBreak())
    doc.build(story)


if __name__ == "__main__":
    build_pdf()
