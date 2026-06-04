"""seed hospital image_url and specialty

Revision ID: f7a2b9c4d6e8
Revises: e6f1a2b3c4d5
Create Date: 2026-06-04

성신여대 주변 병원 45건에 image_url(네이버 외부 URL) + specialty 채우기.
- image_url: 네이버 플레이스 이미지 URL 그대로 저장 (백엔드 prefix 처리 없음 확인됨)
- specialty: 소개글 기반 분류 (정형외과 6 / 내과 1 / 나머지 None)
- 식별: name + address (우리동물병원 2건 중복이라 name만으로는 구분 불가)
- 응답 형식 불변, 값만 채워짐
"""
from alembic import op
import sqlalchemy as sa

revision = "f7a2b9c4d6e8"
down_revision = "e6f1a2b3c4d5"
branch_labels = None
depends_on = None

# (name, address, image_url, specialty)
UPDATES = [
    ('성신동물병원', '서울 성북구 아리랑로 18', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20200613_156%2F1591980554288cYR3E_JPEG%2Fqf0CSdVGaf-zgxFXUMw2Ge87.jpg', None),
    ('드림동물병원', '서울 성북구 동소문로 74', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20190710_105%2F1562732469898RDbFA_JPEG%2F-z728L_PWP4dnp7fT6op4NIz.jpeg.jpg', None),
    ('VIP동물의료센터 성북점', '서울 성북구 동소문로 73', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20200709_32%2F1594285734376XLDUo_JPEG%2F0CoCREBgnMT2lEniddaeYzCy.jpg', None),
    ('로이동물병원', '서울 성북구 아리랑로 27', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20220611_166%2F1654915158901Get2z_JPEG%2F48863B6B-1762-4762-810D-EF027FBFA112.jpeg', '내과'),
    ('나래동물병원', '서울 성북구 동소문로 66', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20150901_268%2F14410337995482qjB8_JPEG%2F96572415950372_0.jpg', None),
    ('서울동물종합병원', '서울 성북구 보문로 137', None, None),
    ('원러브동물의료센터', '서울 성북구 아리랑로 75', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20230803_17%2F1691029783388U5d3Q_JPEG%2FA9_05068.jpg', '정형외과'),
    ('24시 애니 동물병원', '서울 성북구 보문로 99', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20240716_56%2F1721105614557lbFkb_PNG%2F004.png', '정형외과'),
    ('ZOO동물병원', '서울 성북구 정릉로 328', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20201219_200%2F16083610216487i2h4_JPEG%2FJdoMG_Mj_IKlnIXyr_MJvfLJ.jpeg.jpg', None),
    ('한사랑동물병원', '서울 성북구 성북로 27', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20200310_217%2F1583834275016hwT3n_JPEG%2FddYQJ_XhEuEvIcoozsftGAr6.jpg', None),
    ('앙리동물병원', '서울 성북구 성북로 66', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20250331_100%2F1743408502781l9JH4_PNG%2FChatGPT_Image_2025%25B3%25E2_3%25BF%25F9_31%25C0%25CF_%25BF%25C0%25C8%25C4_12_10_28.png', '정형외과'),
    ('폴라동물병원', '서울 종로구 낙산길 311', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20240823_169%2F1724406317743yyADI_JPEG%2FKakaoTalk_20240823_184406882.jpg', None),
    ('아이튼튼동물병원', '서울 성북구 길음로 11', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20260314_293%2F1773465252524YT2nY_PNG%2FChatGPT_Image_2026%25B3%25E2_3%25BF%25F9_14%25C0%25CF_%25BF%25C0%25C8%25C4_02_09_10.png', None),
    ('길음동물병원', '서울 성북구 동소문로 248', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20210731_2%2F1627695104973RGxLG_JPEG%2FJ3ggOJnWTxNuUoXVNlXwUnkf.JPG.jpg', None),
    ('뉴욕동물병원', '서울 종로구 창경궁로35길 19', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20250626_107%2F1750909354780fJ8lR_JPEG%2FScreenshot_20250626_122647_Samsung_Internet.jpg', None),
    ('포포동물병원', '서울 성북구 보문로 51', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20221026_18%2F1666713413109f0GvT_JPEG%2F84DF139D-0A9C-423A-9469-85B26580A08A.jpeg', None),
    ('우리동물병원', '서울 종로구 지봉로 96-3', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20230223_23%2F1677091214991l8Jww_JPEG%2F20230220_112117.jpg', None),
    ('안암동물병원', '서울 동대문구 안암로 40', None, None),
    ('카카오N동물병원', '서울 성북구 길음로 33', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20190129_1%2F15486906940746JAgB_JPEG%2FFiIzHA1xsM69h-m5O3_g5cpY.jpeg.jpg', None),
    ('강북동물병원', '서울 성북구 종암로 65', None, None),
    ('미소동물병원', '서울 성북구 종암로 91', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fpup-review-phinf.pstatic.net%2FMjAyMzA0MTZfMjYg%2FMDAxNjgxNjMyNzIyNDY3.560LMB4-YGJefw2TNyJd2mC0P_Bud26731_lJedTAm0g.grX3NaNb4LT-H7KRtFcVPZsfMgDiaCMPsL83wkgcxyYg.JPEG%2F20230414_104308.jpg%3Ftype%3Dw1500_60_sharpen', None),
    ('쓰담쓰담 동물병원', '서울 성북구 종암로 113', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20160122_176%2F1453432699697NvFGG_JPEG%2F176069506843452_0.jpeg', None),
    ('스마트동물병원 성북길음점', '서울 성북구 길음로13길 22', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20161020_86%2F1476954172892HpbHt_JPEG%2F176970583272680_0.jpeg', None),
    ('호담동물병원', '서울 성북구 동소문로 302', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20200303_182%2F1583213393774joS39_JPEG%2FlGIskhtSHoUOoy4harOddPHb.jpg', None),
    ('해동물병원', '서울 종로구 지봉로 53-1', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20240129_232%2F17065192137866irPi_JPEG%2F20240129_180320.jpg', None),
    ('보성통증동물병원', '서울 성북구 보국문로 68-1', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20260413_54%2F17760485566728BTU3_JPEG%2FKakaoTalk_20260413_114859553.jpg', '정형외과'),
    ('우리동물병원', '서울 성북구 삼양로 84', None, None),
    ('24시 루시드동물메디컬센터', '서울 강북구 월계로 3', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20240904_75%2F1725414729488xt3YE_PNG%2F018.png', '정형외과'),
    ('포유동물병원', '서울 성북구 오패산로 22', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20191215_294%2F1576346406539lqzjs_JPEG%2FY3R8Od_3jXsbblwYTeti9hgs.jpg', None),
    ('삼성동물병원', '서울 강북구 삼양로19길 25', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20191005_284%2F1570274889823GPDgK_JPEG%2FSeVk0e2bp6uFgA5DhG-gpGGq.jpg', None),
    ('도담도담동물병원', '서울 성북구 화랑로 76', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20150901_114%2F1441105321210EfyFP_JPEG%2F156355624171100_1.jpeg', None),
    ('맑은동물병원', '서울 동대문구 청계천로 417', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20150831_99%2F1440993775442V3zmN_JPEG%2FSUBMIT_1428036803783_11883258.jpg', None),
    ('더편한동물병원', '서울 성북구 숭인로 50', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20260602_212%2F17803925224825Trso_JPEG%2F%25B4%25F5%25C6%25ED%25C7%25D1%25B5%25BF%25B9%25B0%25BA%25B4%25BF%25F8_%25C7%25C3%25B7%25B9%25C0%25CC%25BD%25BA_%25C0%25CC%25B9%25CC%25C1%25F6_%2528%25B8%25DE%25C0%25CE_%25BC%25F6%25C1%25A4%2529.jpg', None),
    ('그린동물병원', '서울 동대문구 정릉천동로 58', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20230203_22%2F1675372684532M0oEY_JPEG%2F20230130_145400.jpg', None),
    ('웰니스클리닉 청계천점', '서울 중구 청계천로 400', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20191104_295%2F1572845038197NYLLm_JPEG%2FZPsJDsu4EjzDbzcu7kUgMLLC.jpg', None),
    ('넬동물의료센터', '서울 성북구 오패산로 75-1', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20150829_93%2F1440776177437PUGEj_JPEG%2FSUBMIT_1440776122542_37005936.jpg', None),
    ('디아크동물병원', '서울 동대문구 홍릉로 64-1', None, None),
    ('웰빙비비펫동물병원', '서울 성북구 화랑로 91', None, None),
    ('창문동물병원', '서울 강북구 월계로 35', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20191227_231%2F1577414234309Jns1T_JPEG%2F70rRHw6-WeyZ4bKnxSVDULib.jpg', None),
    ('푸른동물종합병원', '서울 동대문구 홍릉로 48-1', None, None),
    ('텐즈힐링동물병원', '서울 성동구 마장로 137', None, None),
    ('웰튼동물의료센터', '서울 중구 난계로 197', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20241023_187%2F1729660960504JlVmV_JPEG%2F241022_%25C0%25A3%25C6%25B0%25B5%25BF%25B9%25B0%25BA%25B4%25BF%25F8_%25C7%25C3%25B7%25B9%25C0%25CC%25BD%25BA_01.jpg', '정형외과'),
    ('쿠키동물병원', '서울 강북구 삼양로27길 19', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20190816_208%2F1565930330025jhfzj_JPEG%2FSfWzjBE-K-sTtaQ5KwczcJF3.jpg', None),
    ('호동물병원', '서울 강북구 월계로 53', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20251222_277%2F1766392414869OScPs_PNG%2F%25BF%25DC%25BA%25CE_%25C0%25FC%25B8%25E9.png', None),
    ('엘동물병원', '서울 동대문구 고산자로 391', 'https://search.pstatic.net/common/?src=https%3A%2F%2Fldb-phinf.pstatic.net%2F20231028_274%2F16984597660460Vbc9_JPEG%2FIMG_4790.jpeg', None),
]

hospitals = sa.table(
    "hospitals",
    sa.column("name", sa.String),
    sa.column("address", sa.String),
    sa.column("image_url", sa.String),
    sa.column("specialty", sa.String),
)


def upgrade():
    conn = op.get_bind()
    for name, address, image_url, specialty in UPDATES:
        conn.execute(
            hospitals.update()
            .where(sa.and_(hospitals.c.name == name, hospitals.c.address == address))
            .values(image_url=image_url, specialty=specialty)
        )


def downgrade():
    conn = op.get_bind()
    for name, address, _, _ in UPDATES:
        conn.execute(
            hospitals.update()
            .where(sa.and_(hospitals.c.name == name, hospitals.c.address == address))
            .values(image_url=None, specialty=None)
        )
