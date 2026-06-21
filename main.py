import discord
from discord.ext import commands, tasks
import random
import yt_dlp
import asyncio
import os
from collections import deque
from datetime import datetime, timezone, timedelta

# 초성을 추출하는 함수
def get_chosung(text):
    CHOSUNG_LIST = ['ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ']
    result = ""
    for char in text:
        if '가' <= char <= '힣':
            char_code = ord(char) - ord('가')
            chosung_index = char_code // 588
            result += CHOSUNG_LIST[chosung_index]
        else:
            result += char
    return result

# 한국 시간(KST) 설정 함수
def now_kst():
    return datetime.now(timezone(timedelta(hours=9)))

# =====================
# 설정 부분
# =====================
TOKEN = "여기에_디스코드_봇_토큰_붙여넣기"
print("TOKEN =", TOKEN)
CHANNEL_ID = None

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =====================
# 데이터 저장 및 관리 (서버별 독립 구조)
# =====================
# 구조: {str(guild_id): {str(user_id): value}}
user_money = {}
user_daily_pay = {}
user_lotto_count = {}
user_inventory = {}
user_fortune_data = {}
user_match_data = {}
active_games = {}  # 퀴즈 중단 방지용

# [서버별 데이터를 안전하게 가져오기 위한 함수]
def get_user_data(data_dict, guild_id, user_id, default_value):
    g_id = str(guild_id)
    u_id = str(user_id)
    if g_id not in data_dict:
        data_dict[g_id] = {}
    if u_id not in data_dict[g_id]:
        data_dict[g_id][u_id] = default_value
    return data_dict[g_id][u_id]

# [서버별 데이터를 저장하기 위한 함수]
def set_user_data(data_dict, guild_id, user_id, value):
    g_id = str(guild_id)
    u_id = str(user_id)
    if g_id not in data_dict:
        data_dict[g_id] = {}
    data_dict[g_id][u_id] = value

# 노래 대기열 저장소 (서버별 관리)
queues = {}

# YDL 및 FFMPEG 옵션
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn', # 비디오는 빼고 오디오만!
}

YDL_OPTIONS = {
    'format': 'bestaudio/best',  # 'bestaudio'가 안되면 'best'라도 가져오게 설정
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'nocheckcertificate': True,
    'cookiefile': 'cookies.txt', # 방금 공들여 만드신 쿠키!
}

# =====================
# 보조 함수 (대기열 관리) - 수정 및 보완
# =====================
def check_queue(interaction: discord.Interaction):
    """노래 재생이 끝나면 호출되어 다음 곡을 재생합니다."""
    guild_id = interaction.guild.id
    
    if guild_id in queues and queues[guild_id]:
        next_song = queues[guild_id].popleft()
        
        # FFmpeg 소스 생성
        source = discord.FFmpegOpusAudio(next_song['url'], executable="ffmpeg", **FFMPEG_OPTIONS)
        
        # 다음 곡 재생 (after에 다시 check_queue를 등록하여 무한 반복)
        interaction.guild.voice_client.play(source, after=lambda e: check_queue(interaction))
        
        # 다음 곡 재생 알림 (비동기 루프 사용)
        coro = interaction.channel.send(f"🎶 다음 곡 재생: **{next_song['title']}**")
        asyncio.run_coroutine_threadsafe(coro, bot.loop)
    else:
        # 더 이상 재생할 곡이 없으면 대기열 삭제 (자동 퇴장은 선택 사항)
        if guild_id in queues:
            del queues[guild_id]

# =====================
# 유틸리티 함수
# =====================
def now_kst():
    # 한국 시간(UTC+9) 계산
    return datetime.datetime.utcnow() + datetime.timedelta(hours=9)

# =====================
# KST 시간 함수
# =====================
def now_kst():
    return datetime.now(timezone(timedelta(hours=9)))


# =====================
# 자동 인사 스케줄러
# =====================
last_sent = {
    "morning": None,
    "lunch": None,
    "dinner": None,
    "test_14": None,
}


async def send_to_all_guilds(message):
    for guild in bot.guilds:

        # 1️⃣ system_channel 우선
        channel = guild.system_channel
        if channel and channel.permissions_for(guild.me).send_messages:
            await channel.send(message)
            continue

        # 2️⃣ 없으면 첫 번째 전송 가능한 채널
        for ch in guild.text_channels:
            if ch.permissions_for(guild.me).send_messages:
                await ch.send(message)
                break


async def send_once(key, hour, minute, message):
    now = now_kst()

    # 정각 + 1분 허용
    if now.hour == hour and 0 <= now.minute - minute < 2:
        if last_sent.get(key) == now.date():
            return

        try:
            await send_to_all_guilds(message)
            last_sent[key] = now.date()
            print(f"✅ {key} 인사 전송 완료")
        except Exception as e:
            print(f"❌ {key} 인사 전송 실패:", e)


@tasks.loop(minutes=1)
async def morning():
    await send_once(
        "morning",
        6,
        0,
        "기상! 기상! ٩(◕ᗜ◕)و 햇살이 똑똑똑~ 오늘 하루도 귀엽게 시작해 보자구요! ☀️"
    )


@tasks.loop(minutes=1)
async def lunch():
    await send_once(
        "lunch",
        12,
        0,
        "🍚 점심시간! 맛있게 드세요!"
    )


@tasks.loop(minutes=1)
async def dinner():
    await send_once(
        "dinner",
        19,
        0,
        "🛌 오늘도 고생했어요! 저녁 챙겨드세요!"
    )


# =====================
# 🧪 테스트용 인사 (14:00)
# =====================
@tasks.loop(minutes=1)
async def test_greeting():
    await send_once(
        "test_14",
        14,
        0,
        "☕ 커피 한 잔 드실 시간입니다!"
    )


# =====================
# 봇 준비 완료 시 루프 시작
# =====================
@bot.event
async def on_ready():
    print(f"✅ 봇 로그인 완료: {bot.user}")

    if not morning.is_running():
        morning.start()

    if not lunch.is_running():
        lunch.start()

    if not dinner.is_running():
        dinner.start()

    if not test_greeting.is_running():
        test_greeting.start()

# =====================
# 명령어: 오늘의운세 (서버별 독립 버전)
# =====================
@bot.tree.command(name="오늘의운세", description="이 서버에서 하루에 한 번, 오늘의 행운을 확인하세요!")
async def 오늘의운세(interaction: discord.Interaction):
    # 1. 정보 가져오기
    g_id = interaction.guild.id
    u_id = interaction.user.id
    today = str(now_kst().date())

    # 2. 중복 체크 (서버별 데이터 함수 사용)
    last_date = get_user_data(user_fortune_data, g_id, u_id, "")

    if last_date == today:
        await interaction.response.send_message(
            f"⚠️ {interaction.user.mention}님, 이 서버에서 운세는 하루에 한 번만 볼 수 있어요!", 
            ephemeral=True
        )
        return

    fortune_results = [
        "오늘은 최고의 행운이 따르는 날! 로또 한 장 어때요? 💎", "오늘은 휴식이 최고의 보약입니다. 일찍 자요! 😴🛌",
        "생각지도 못한 곳에서 작은 선물을 받게 될 거예요. 🎁", "오늘은 차분하게 휴식을 취하는 것이 운을 불러옵니다. ☕",
        "새로운 일에 도전하기 딱 좋은 날입니다! 자신감을 가지세요. 🔥",
        "오늘은 결정 장애가 심해질 수 있으니 추천 메뉴로! 🍱❓", "간식 운 최고!!🍪", "졸림 주의!! 💤", "배터리 조심!! 방전 조심!!", "",
        "주변의 달콤한 유혹에 주의하세요. 원칙을 지키는 게 답인 하루입니다.",
        "오늘은 당신이 가는 곳마다 꽃길이 펼쳐질 거예요!🌸",
        "앗! 방금 행운의 다람쥐가 당신 주머니에 복을 넣고 갔어요!🐿️ 금화 쏘옥!",
        "길냥이에게 선택을 받을지도 모르는 하루입니다.🐈인간이여, 운명을 받아들이세요!",
        "오늘은 뭘 해도 귀여움 받는 날! 자신있게 윙크!😉",
        "힘들 땐 초코우유 한 모금!! 기운이 불끈 솟아날 거예요!🍫🥛",
        "곰돌이처럼 포근하고 따뜻한 하루 보내세요!🧸",
        "오늘은 좀 졸릴 수 있어요... 토끼 낮잠 추천!!🐇💤",
        "당신의 매력 지수가 오늘은 100% 충전 완료!!🔋",
        "예상치 못한 비가 올 수도 있어요. 작은 우산 챙기기!!☂️",
        "플레이리스트에서 제일 좋아하는 노래가 흘러나올 확률 90%!!🎵",
        "앗, 발가락 끝을 가구에 콩! 부딪힐 수 있으니 발밑 조심!🦶🏻💥",
        "과식 주의보! 맛있다고 계속 먹으면 배가 빵빵 🫃🚫",
        "반려동물이 평소보다 더 애교를 부려줄 거예요 🐶🐱💖",
        "주변 사람의 불평을 들어주느라 기가 빨릴 수 있어요 🌀🔋",
        "너무 완벽하려고 애쓰지 마세요. 실수해도 귀여워요 🧸💖",
        "잃어버렸던 소중한 물건을 찾게 되는 날!!🔎", 
        "오늘은 뭘 먹어도 0칼로리 기분! 꿀맛 식사 보장!!", 
        "오늘은 몸이 천근만근... 무리한 운동은 금물이에요.💦", 
        "사랑스러움 상승하는 날!!💞", "오늘은 맛있는 걸 먹으면 모든 스트레스가 풀릴 거예요! 🍕"
    ]

    selected = random.choice(fortune_results)
    
    # 데이터 저장 (서버별로 저장)
    set_user_data(user_fortune_data, g_id, u_id, today)
    
    # 3. 임베드 생성 및 전송
    embed = discord.Embed(title="🔮 오늘의 운세", description=selected, color=0xffd700)
    embed.set_footer(text=f"{interaction.user.display_name}님의 하루를 응원합니다! (서버 전용)")
    
    await interaction.response.send_message(embed=embed)

# =====================
# 명령어: 궁합 (서버별 독립 버전) 💘
# =====================
@bot.tree.command(name="궁합", description="이 서버에서 상대방과의 오늘의 궁합 점수를 확인합니다.")
async def 궁합(interaction: discord.Interaction, user: discord.Member):
    g_id = interaction.guild.id
    u_id = interaction.user.id
    today = str(now_kst().date())

    # 본인과의 궁합 체크
    if user == interaction.user:
        await interaction.response.send_message("😳 자기 자신과의 궁합은 언제나 100점! 다른 분을 선택해 보세요.", ephemeral=True)
        return

    # 서버 ID + 사용자 ID + 상대방 ID를 조합한 유니크 키 생성
    match_key = f"{g_id}_{u_id}_{user.id}"

    # 하루 1회 제한 체크 (특정 상대방 기준)
    # user_match_data를 바로 쓰지 않고 유연하게 관리하기 위해 match_key 활용
    if match_key in user_match_data and user_match_data[match_key] == today:
        await interaction.response.send_message(
            f"⚠️ {interaction.user.mention}님, 이 서버에서 {user.display_name}님과의 궁합은 이미 확인하셨어요!",
            ephemeral=True
        )
        return

    # 점수 생성
    score = random.randint(0, 100)
    user_match_data[match_key] = today  # 데이터 저장

    # 멘트 로직 (기존 데이터 그대로 유지)
    if score >= 90:
        comments = [
            "✨ 전생에 나라를 구했나요? 완벽한 천생연분!", "💎 눈에서 꿀이 떨어지는 찰떡궁합!", "🔥 태양보다 뜨거운 조합!", "💘 독심술 수준으로 잘 통하네요.",
            "💍 세기의 커플 탄생 예감!", "어떤 시련도 웃으며 넘길 무적의 조합!!", "오늘 약속 잡으면 행운이 따를 거예요!!", "복권 같이 사면 당첨될지도? 🍀",
            "숨만 쉬어도 서로 귀여워 보이는 날!", "에스프레소에 샷 추가한 듯한 시너지!", "역대급 맛집 탐방 성공률 100%!", "하는 말마다 띵언이 되는 날.",
            "우주의 기운이 두 분께 쏠리고 있어요.", "리액션이 방청객 알바급으로 폭발!", "세상에서 가장 행복한 콤비!", "존재 자체가 축복인 관계.",
            "오늘 두 분의 티키타카는 국가대표급!", "서로의 수호천사가 되어주는 날.", "함께라면 두려울 게 없는 무적 상태!", "서로에게 럭키비키한 하루!"
        ]
    elif score >= 70:
        comments = [
            "💖 눈빛만 봐도 통하는 사이!", "🍗 닭다리 양보 가능한 찐우정/사랑!", "서로를 웃기는 능력이 탁월해요.", "든든한 아군을 얻으셨네요!",
            "100점이 머지않은 훌륭한 관계!", "🥰 시간 가는 줄 모르는 즐거운 사이.", "사회적으로 인정받은(?) 훌륭한 콤비!", "달콤함 한도 초과!",
            "깊은 대화가 술술 풀리는 날.", "카톡 답장 속도가 광속인 날!", "드립과 받아치기의 완벽한 조화.", "게임 승률이 20% 상승하는 날!",
            "스타일이 은근히 커플룩 같은 날!", "심심할 틈이 전혀 없는 활기찬 하루.", "우울함도 한 방에 날려줄 구원자!", "서로의 인생곡을 찾아줄 운명.",
            "인생샷 건지기 딱 좋은 날입니다.", "설렘의 기류가 몽글몽글 피어나요.", "서로의 장점이 2배로 잘 보이는 날.", "같이만 있어도 기분이 Up!"
        ]
    elif score >= 40:
        comments = [
            "😊 평범하지만 은근히 잘 맞는 구석이 있죠.", "커피 한 잔 하며 수다 떨기 좋은 날.", "운명은 아니어도 꽤 괜찮은 인연!", "노래 추천 하나씩 주고받아 보세요.",
            "가늘고 길게 갈 실속형 인연!", "조금씩 알아가는 재미가 있는 사이.", "소소한 즐거움이 가득한 하루.", "비즈니스에서 절친으로 발전할 운명!",
            "문득 생각나면 연락하기 좋은 사이.", "성장 가능성이 무궁무진한 관계!", "담백하고 편안한 평양냉면 같은 사이.", "소소하게 웃을 일이 생기는 날.",
            "고민 상담하기에 아주 적절한 타이밍.", "메뉴 결정이 의외로 빠른 궁합.", "서로의 실수를 쿨하게 넘겨주는 날.", "잔잔한 호수 같은 평화로운 사이.",
            "알고리즘이 겹치는 걸 발견할지도!", "이름만 불러도 기분이 살짝 좋아져요.", "특별한 계획 없어도 즐거운 날.", "서로를 은근히 닮아가는 중입니다.",
            "배려의 아이콘들이 만났군요.", "따뜻한 안부가 잘 어울리는 하루.", "단톡방 분위기 메이커 듀오!", "작은 선물로 점수가 쑥 오를 사이.",
            "집중력이 평소보다 잘 유지되는 날.", "말하고 듣는 밸런스가 아주 좋아요.", "편안한 소파 같은 존재가 되어줄게요.", "약속 시간에 딱 맞춰 만날 확률 50%!",
            "과하지도 부족하지도 않은 딱 좋은 거리.", "먼저 연락하면 길한 하루입니다.", "발걸음 속도가 신기하게 잘 맞네요.", "서로의 텐션을 조절해주는 안전장치.",
            "수고했어 한마디면 사르르 녹을 궁합.", "영화 취향이 겹칠 확률이 높아요.", "예의상 웃다가 진짜 터지는 날.", "적당한 자극과 안정을 주는 사이.",
            "황금 거리를 유지하는 스마트한 인연.", "서로에게 가장 솔직해져도 좋은 날.", "서로의 MBTI를 궁금해할 타이밍!", "함께 있으면 마음이 차분해져요."
        ]
    elif score >= 10:
        comments = [
            "🤔 가끔 외계어로 대화하는 느낌?", "🧊 조금 서먹한 사이, 대화가 필요해!", "⚡ 자존심 싸움 금지! 한 명은 져주세요.", "🌫️ 안개 속의 관계, 더 알아가 보세요.",
            "다른 행성에서 온 것 같은 느낌...👽", "정적이 흐를 땐 맛있는 걸 드세요!", "아직은 서로가 너무 어려운 단계.", "현미경으로 매력을 찾아봐야 할지도?",
            "이모티콘으로 소통하는 게 안전합니다.", "무리한 드립은 절대 금지!", "이상하게 정적이 자주 흐르는 날.", "컨디션이 서로 정반대일 수 있어요.",
            "맞춤법 지적은 분위기를 싸하게 만듭니다.", "약속 정하다가 기운 빠질 수 있음 주의!", "다른 언어를 쓰는 느낌을 받을 수 있어요.", "답장 고민을 평소보다 오래 하게 됨.",
            "주변 사람들이 눈치를 살필 수도?", "예민한 부분은 건드리지 마세요!", "하고 싶은 말은 1초만 참고 하기.", "투명한 벽이 1cm 정도 생긴 기분."
        ]
    else:
        comments = [
            "💨 MBTI가 정반대인가요? 도망쳐!!", "🚫 오늘은 차단이 답이다. (농담!)", "🧊 아메리카노보다 차가운 분위기.", "🧱 사이에 거대한 벽이 느껴져요.",
            "화를 내면 본인이 더 손해인 날!! 참으세요!", "마주치면 '안녕'만 하고 지나가기!", "숨소리조차 거슬릴 수 있는 위험 단계.", "1분 만에 끝장 토론이 벌어질 듯.",
            "오늘은 서로가 '금지어'라고 생각하세요.", "같이 있으면 배터리만 빨리 닳는 기분.", "피자와 우유 같은 불협화음!!", "각자 행복한 게 나은 하루.",
            "길에서 마주쳐도 모르는 척할 확률 99%!"
        ]

    selected_comment = random.choice(comments)

    # 임베드 생성
    embed = discord.Embed(title="💘 오늘의 궁합 (서버별 독립)", color=0xff69b4)
    embed.add_field(name="오늘의 파트너", value=f"{interaction.user.mention} ❤️ {user.mention}", inline=False)
    embed.add_field(name="오늘의 점수", value=f"**{score}점**", inline=False)
    embed.add_field(name="한줄평", value=f"> {selected_comment}", inline=False)
    embed.set_footer(text=f"현재 서버 기준 궁합입니다!")
    
    await interaction.response.send_message(embed=embed)

# =====================
# 경제 시스템: 돈내놔 (서버별 독립 버전)
# =====================
@bot.tree.command(name="돈내놔", description="이 서버에서 하루 3번, 10,000원씩 지원금을 받습니다.")
async def 돈내놔(interaction: discord.Interaction):
    g_id = interaction.guild.id
    u_id = interaction.user.id
    today = str(now_kst().date())

    # 1. 일일 횟수 정보 가져오기 (없으면 [오늘날짜, 0회]로 시작)
    # 데이터 구조: [날짜문자열, 횟수]
    daily_info = get_user_data(user_daily_pay, g_id, u_id, [today, 0])

    # 2. 날짜가 바뀌었으면 횟수 초기화
    if daily_info[0] != today:
        daily_info = [today, 0]

    # 3. 3회 미만인지 확인
    if daily_info[1] < 3:
        # 이 서버의 현재 잔액 가져오기
        current_money = get_user_data(user_money, g_id, u_id, 0)
        
        # 돈 추가 및 저장
        new_money = current_money + 10000
        set_user_data(user_money, g_id, u_id, new_money)
        
        # 횟수 추가 및 저장
        daily_info[1] += 1
        set_user_data(user_daily_pay, g_id, u_id, daily_info)
        
        await interaction.response.send_message(
            f"💰 {interaction.user.mention}님께 **이 서버 전용** 지원금 10,000원을 드렸습니다!\n"
            f"📅 오늘 횟수: {daily_info[1]}/3회\n"
            f"💵 현재 서버 잔액: {new_money:,}원"
        )
    else:
        await interaction.response.send_message(
            f"⚠️ 이 서버에서는 오늘 이미 3번 다 받으셨어요! 내일 다시 오세요.", 
            ephemeral=True
        )
# =====================
# 경제 시스템: 잔고 (서버별 독립 버전)
# =====================
@bot.tree.command(name="잔고", description="이 서버에서 보유 중인 잔액을 확인합니다.")
async def 잔고(interaction: discord.Interaction):
    # interaction.guild.id를 사용해 현재 서버의 잔고를 가져옵니다.
    # get_user_data 함수를 사용하여 데이터가 없을 경우 기본값 0을 반환합니다.
    money = get_user_data(user_money, interaction.guild.id, interaction.user.id, 0)
    
    await interaction.response.send_message(
        f"💵 {interaction.user.mention}님의 **현재 서버** 잔고는 **{money:,}원**입니다."
    )

# =====================
# 도박: 홀짝맞추기 (서버별 독립 버전)
# =====================
@bot.tree.command(name="홀짝", description="배팅금을 걸고 홀/짝을 맞춥니다. (성공 시 2배!)")
async def 홀짝(interaction: discord.Interaction, bet: int, pick: str):
    g_id = interaction.guild.id
    u_id = interaction.user.id
    
    # 이 서버의 현재 잔고 가져오기
    current_money = get_user_data(user_money, g_id, u_id, 0)

    # 1. 예외 처리
    if bet <= 0:
        return await interaction.response.send_message("❌ 1원 이상 배팅해야 합니다.", ephemeral=True)
    
    if current_money < bet:
        return await interaction.response.send_message(f"❌ 이 서버의 잔액이 부족합니다. (현재: {current_money:,}원)", ephemeral=True)
    
    if pick not in ['홀', '짝']:
        return await interaction.response.send_message("❓ `홀` 또는 `짝` 중에서 선택해 주세요.", ephemeral=True)

    # 2. 게임 결과 계산
    result = random.choice(['홀', '짝'])
    
    if pick == result:
        # 성공: 잔고에 배팅금 합산 후 저장
        new_money = current_money + bet
        set_user_data(user_money, g_id, u_id, new_money)
        
        await interaction.response.send_message(
            f"🎊 결과는 **[{result}]**! 성공했습니다! \n"
            f"💰 {bet:,}원을 얻어 현재 **이 서버** 잔고는 **{new_money:,}원**입니다."
        )
    else:
        # 실패: 잔고에서 배팅금 차감 후 저장
        new_money = current_money - bet
        set_user_data(user_money, g_id, u_id, new_money)
        
        await interaction.response.send_message(
            f"💀 결과는 **[{result}]**... 아쉽게 실패했습니다. \n"
            f"💸 {bet:,}원을 잃어 현재 **이 서버** 잔고는 **{new_money:,}원**입니다."
        )
    

# =====================
# 도박: 로또 (서버별 독립 버전)
# =====================
@bot.tree.command(name="로또", description="로또를 구매합니다. (1,000원, 서버별 하루 15회 제한)")
async def 로또(interaction: discord.Interaction):
    g_id = interaction.guild.id
    u_id = interaction.user.id
    today = str(now_kst().date())
    lotto_price = 1000

    # 1. 데이터 가져오기 (서버별 독립)
    current_money = get_user_data(user_money, g_id, u_id, 0)
    count_info = get_user_data(user_lotto_count, g_id, u_id, [today, 0])

    # 2. 날짜가 바뀌었으면 해당 서버의 횟수 리셋
    if count_info[0] != today:
        count_info = [today, 0]

    # 3. 횟수 제한 체크 (15회)
    if count_info[1] >= 15:
        return await interaction.response.send_message(
            f"⚠️ {interaction.user.mention}님, **이 서버**에서는 하루 15번까지만 구매할 수 있습니다!", 
            ephemeral=True
        )

    # 4. 잔액 체크 (이 서버의 돈이 충분한지)
    if current_money < lotto_price:
        return await interaction.response.send_message(
            f"❌ **이 서버의 잔액**이 부족합니다. (로또 {lotto_price:,}원)", 
            ephemeral=True
        )

    # 5. 로또 실행 및 차감
    current_money -= lotto_price
    count_info[1] += 1
    
    draw = random.randint(1, 100)
    if draw == 1:
        win = 50000
        res = "🎊 대박!! 로또 1등 당첨! 🎊"
    elif 2 <= draw <= 6:
        win = 20000
        res = "⭐ 축하합니다! 로또 2등 당첨!"
    elif 7 <= draw <= 16:
        win = 10000
        res = "✅ 로또 3등에 당첨되었습니다."
    else:
        win = 0
        res = "😭 아쉽게도 꽝입니다..."

    # 결과 저장 (돈 증가 및 횟수 업데이트)
    current_money += win
    set_user_data(user_money, g_id, u_id, current_money)
    set_user_data(user_lotto_count, g_id, u_id, count_info)

    # 6. 결과 임베드 생성
    embed = discord.Embed(
        title="🎟️ 서버별 로또 결과", 
        description=res, 
        color=0x00ff00 if win > 0 else 0xff0000
    )
    if win > 0:
        embed.add_field(name="당첨금", value=f"{win:,}원")
    
    embed.add_field(name="이 서버 잔고", value=f"{current_money:,}원", inline=True)
    embed.add_field(name="오늘 구매 횟수", value=f"{count_info[1]} / 15회", inline=True)
    embed.set_footer(text="지나친 도박은 가산을 탕진합니다.")
    
    await interaction.response.send_message(embed=embed)

# ===================== 
# 경제 시스템: 낚시 시스템 (수정 버전)
# ===================== 

FISH_DATA = {
    # --- 쓰레기류 (Trash) - 가격 100원 통일 ---
    "낡은 장화 👞": {"chance": 10, "price": 100, "is_trash": True},
    "뭉쳐진 휴지 🧻": {"chance": 10, "price": 100, "is_trash": True},
    "찢어진 신문지 🗞️": {"chance": 10, "price": 100, "is_trash": True},
    "찌그러진 캔 🥫": {"chance": 10, "price": 100, "is_trash": True},
    "플라스틱 병 🧴": {"chance": 10, "price": 100, "is_trash": True},

    # --- 일반 어종 (Common) ---
    "피라미 🐟": {"chance": 12, "price": 100},
    "붕어 🐠": {"chance": 10, "price": 500},
    "고등어 🐟": {"chance": 9, "price": 700},
    "새우 🦐": {"chance": 8, "price": 800},
    "불가사리 🌟": {"chance": 7, "price": 1200},
    "연어 🍣": {"chance": 6.5, "price": 1500},

    # --- 고급 어종 (Uncommon) ---
    "잉어 🎏": {"chance": 6, "price": 2000},
    "게 🦀": {"chance": 5.5, "price": 2500},
    "오징어 🦑": {"chance": 5, "price": 3000},
    "갈치 🗡️": {"chance": 4.5, "price": 3500},
    "해파리 🪼": {"chance": 4, "price": 4000},
    "복어 🐡": {"chance": 4, "price": 4500},
    "해마 🦄": {"chance": 3.5, "price": 5000},

    # --- 희귀 어종 (Rare) ---
    "가오리 🪁": {"chance": 3, "price": 6000},
    "문어 🐙": {"chance": 3, "price": 7000},
    "랍스터 🦞": {"chance": 2.5, "price": 8500},
    "거북이 🐢": {"chance": 2, "price": 10000},
    "참치 🐟": {"chance": 1.5, "price": 12000},

    # --- 전설 어종 (Legendary) ---
    "상어 🦈": {"chance": 0.5, "price": 15000},
    "황금잉어 ✨": {"chance": 0.4, "price": 20000},
    "고래 🐋": {"chance": 0.3, "price": 25000},
    "물범 🦭": {"chance": 0.2, "price": 30000},
    "심해어 👹": {"chance": 0.1, "price": 30000}
}

@bot.tree.command(name="낚시", description="이 서버의 보관함에 물고기를 잡습니다.")
async def 낚시(interaction: discord.Interaction):
    g_id = interaction.guild.id
    u_id = interaction.user.id
    await interaction.response.send_message(f"🎣 {interaction.user.display_name}님이 낚싯대를 던졌습니다... (기다리는 중)")
    
    try:
        inventory = get_user_data(user_inventory, g_id, u_id, {})
        await asyncio.sleep(2) 

        fish_names = list(FISH_DATA.keys())
        fish_weights = [f["chance"] for f in FISH_DATA.values()]
        caught_item = random.choices(fish_names, weights=fish_weights, k=1)[0]
        fish_info = FISH_DATA[caught_item]

        if fish_info.get("is_trash"):
            embed = discord.Embed(title="⚙️ 낚시 실패...", description=f"에고... **{caught_item}**을 낚았습니다.", color=0x95a5a6)
            return await interaction.edit_original_response(content=None, embed=embed)

        inventory[caught_item] = inventory.get(caught_item, 0) + 1
        set_user_data(user_inventory, g_id, u_id, inventory)
        
        embed = discord.Embed(title="✨ 낚시 성공!", description=f"**{interaction.user.display_name}**님, **{caught_item}**를 잡았습니다!", color=0x3498db)
        embed.set_footer(text=f"현재 보관함에 {caught_item} {inventory[caught_item]}마리 보유 중")
        await interaction.edit_original_response(content=None, embed=embed)
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ 오류 발생: {e}")

@bot.tree.command(name="물고기가격", description="물고기들의 판매 가격을 확인합니다.")
async def 물고기가격(interaction: discord.Interaction):
    lines = [f"**{name}**: {info['price']:,}원" for name, info in FISH_DATA.items() if not info.get("is_trash")]
    trash = [f"**{name}**: 0원" for name, info in FISH_DATA.items() if info.get("is_trash")]
    
    embed = discord.Embed(title="🐟 물고기 시세표", color=0x5865F2)
    embed.add_field(name="[물고기]", value="\n".join(lines), inline=True)
    embed.add_field(name="[꽝/쓰레기]", value="\n".join(trash), inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="보관함", description="현재 서버에서 잡은 물고기 목록을 확인합니다.")
async def 보관함(interaction: discord.Interaction):
    g_id = interaction.guild.id
    u_id = interaction.user.id
    inventory = get_user_data(user_inventory, g_id, u_id, {})
    
    if not inventory or sum(inventory.values()) == 0:
        return await interaction.response.send_message("텅~ 보관함이 비어있습니다.", ephemeral=True)

    msg = "\n".join([f"**{name}**: {count}마리" for name, count in inventory.items() if count > 0])
    embed = discord.Embed(title=f"🎒 {interaction.user.display_name}님의 보관함", description=msg, color=0x95a5a6)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="팔기", description="물고기를 판매합니다. 이름을 입력하지 않으면 모두 판매합니다.")
@discord.app_commands.describe(물고기이름="판매할 물고기 이름 (비우면 모두 판매)", 갯수="판매할 마리 수 (비우면 해당 물고기 모두 판매)")
async def 팔기(interaction: discord.Interaction, 물고기이름: str = None, 갯수: int = None):
    g_id = interaction.guild.id
    u_id = interaction.user.id
    inventory = get_user_data(user_inventory, g_id, u_id, {})

    if not inventory or sum(inventory.values()) == 0:
        return await interaction.response.send_message("❌ 판매할 물고기가 없습니다.", ephemeral=True)

    total_profit = 0

    # 1. 특정 물고기 부분 판매
    if 물고기이름:
        if 물고기이름 not in inventory or inventory[물고기이름] <= 0:
            return await interaction.response.send_message(f"❌ 보관함에 **{물고기이름}**이 없습니다.", ephemeral=True)
        
        current_count = inventory[물고기이름]
        sell_count = 갯수 if 갯수 is not None else current_count
        
        if sell_count <= 0:
            return await interaction.response.send_message("❌ 1마리 이상 판매해야 합니다.", ephemeral=True)
        if sell_count > current_count:
            return await interaction.response.send_message(f"❌ 부족합니다. (현재 {current_count}마리 보유)", ephemeral=True)
        
        profit = FISH_DATA[물고기이름]["price"] * sell_count
        inventory[물고기이름] -= sell_count
        total_profit = profit
        result_msg = f"✅ **{물고기이름} {sell_count}마리**를 팔아 **{total_profit:,}원**을 벌었습니다!"

    # 2. 전체 판매
    else:
        for f_name, count in inventory.items():
            if count > 0 and f_name in FISH_DATA:
                total_profit += FISH_DATA[f_name]["price"] * count
                inventory[f_name] = 0
        result_msg = f"💰 모든 물고기를 팔아 **{total_profit:,}원**을 벌었습니다!"

    # 데이터 업데이트
    set_user_data(user_inventory, g_id, u_id, inventory)
    current_money = get_user_data(user_money, g_id, u_id, 0)
    set_user_data(user_money, g_id, u_id, current_money + total_profit)
    
    await interaction.response.send_message(f"{result_msg}\n💵 현재 잔고: **{current_money + total_profit:,}원**")

# ===================== 
# 경제 시스템: 사냥 시스템
# ===================== 

HUNT_DATA = {
    # --- [1단계: 흔한 소형 생물] ---
    "🪰 파리": {"chance": 400, "price": 100},
    "🦟 모기": {"chance": 380, "price": 200},
    "🐜 개미": {"chance": 360, "price": 300},
    "🐞 무당벌레": {"chance": 340, "price": 400},
    "🦗 귀뚜라미": {"chance": 320, "price": 500}, # 추가
    "🐭 생쥐": {"chance": 300, "price": 600},
    "🕷️ 거미": {"chance": 280, "price": 700}, # 추가
    "🐦 참새": {"chance": 260, "price": 800},
    "🐌 달팽이": {"chance": 240, "price": 900}, # 추가
    "🐥 병아리": {"chance": 220, "price": 1000},

    # --- [2단계: 야생 소형 동물] ---
    "🐿️ 다람쥐": {"chance": 200, "price": 1200},
    "🐸 개구리": {"chance": 190, "price": 1500},
    "🦎 도마뱀": {"chance": 180, "price": 1800},
    "🦇 박쥐": {"chance": 170, "price": 2000}, # 추가
    "🐰 토끼": {"chance": 160, "price": 2200},
    "🐢 거북이": {"chance": 150, "price": 2500}, # 추가
    "🐥 오리": {"chance": 145, "price": 2800},
    "🕊️ 비둘기": {"chance": 140, "price": 3000}, # 추가
    "🐓 수탉": {"chance": 135, "price": 3500},
    "🦔 고슴도치": {"chance": 130, "price": 4200},

    # --- [3단계: 중형 야생 동물] ---
    "🐱 길고양이": {"chance": 120, "price": 5000},
    "🐒 원숭이": {"chance": 115, "price": 5500}, # 추가
    "🐕 들개": {"chance": 110, "price": 6000},
    "🦦 수달": {"chance": 105, "price": 6600}, # 추가
    "🦝 너구리": {"chance": 100, "price": 7200},
    "🦡 오소리": {"chance": 95, "price": 8500},
    "🦩 홍학": {"chance": 90, "price": 9200}, # 추가
    "🦊 여우": {"chance": 85, "price": 10000},
    "🦌 사슴": {"chance": 80, "price": 11500},
    "🐗 멧돼지": {"chance": 78, "price": 13000},

    # --- [4단계: 위험한 포식자] ---
    "🐍 뱀": {"chance": 75, "price": 14500},
    "🦃 칠면조": {"chance": 72, "price": 16000},
    "🦅 독수리": {"chance": 70, "price": 17500},
    "🦉 부엉이": {"chance": 68, "price": 18000}, # 추가
    "🐺 늑대": {"chance": 65, "price": 19000},
    "🦂 전갈": {"chance": 62, "price": 20000}, # 추가
    "🦭 물개": {"chance": 60, "price": 21000},
    "🐆 표범": {"chance": 58, "price": 23000},
    "🦓 얼룩말": {"chance": 55, "price": 24000}, # 추가
    "🐊 악어": {"chance": 52, "price": 25000},

    # --- [5단계: 대형 맹수 & 희귀종] ---
    "🐻 곰": {"chance": 50, "price": 27000},
    "🐃 버팔로": {"chance": 48, "price": 28500},
    "🐫 낙타": {"chance": 46, "price": 28800}, # 추가
    "🦏 코뿔소": {"chance": 44, "price": 29000},
    "🐋 고래": {"chance": 42, "price": 29200}, # 추가
    "🦍 고릴라": {"chance": 40, "price": 29500},
    "🦒 기린": {"chance": 38, "price": 29600}, # 추가
    "🐯 호랑이": {"chance": 36, "price": 29800},
    "🦁 사자": {"chance": 34, "price": 30000},
    "🐘 코끼리": {"chance": 32, "price": 30000},

    # --- [6단계: 환상 속의 영수] ---
    "🦖 공룡": {"chance": 30, "price": 30000},
    "🦕 브라키오": {"chance": 28, "price": 30000}, # 추가
    "🦄 유니콘": {"chance": 26, "price": 30000},
    "🐺 펜릴": {"chance": 25, "price": 30000}, # 추가
    "🔥 피닉스": {"chance": 24, "price": 30000},
    "🧜 인어": {"chance": 23, "price": 30000}, # 추가
    "🐉 용": {"chance": 22, "price": 30000},
    "🦁 키메라": {"chance": 21, "price": 30000}, # 추가
    "✨ 해태": {"chance": 20.5, "price": 30000},
    "👑 그리핀": {"chance": 20, "price": 30000} # 추가
}

@bot.tree.command(name="사냥", description="야생 동물을 사냥하여 돈을 법니다. (부상 주의!)")
async def 사냥(interaction: discord.Interaction):
    g_id = interaction.guild.id
    u_id = interaction.user.id
    
    # 1. 초기 메시지 전송
    await interaction.response.send_message(f"🏹 {interaction.user.display_name}님이 숲으로 사냥을 떠납니다... 🌲")
    
    # 2초 대기 (긴장감 조성)
    await asyncio.sleep(2) 

    # 2. 성공/실패 판정 (60% 성공, 40% 실패/부상)
    is_success = random.random() < 0.6 
    current_money = get_user_data(user_money, g_id, u_id, 0)

    if is_success:
        # --- 사냥 성공 로직 ---
        animal_names = list(HUNT_DATA.keys())
        animal_weights = [a["chance"] for a in HUNT_DATA.values()]
        
        # 확률에 따라 동물 선택
        caught_animal = random.choices(animal_names, weights=animal_weights, k=1)[0]
        reward = HUNT_DATA[caught_animal]["price"]
        
        # 돈 지급 및 저장 (서버별 독립)
        new_money = current_money + reward
        set_user_data(user_money, g_id, u_id, new_money)

        embed = discord.Embed(
            title="🎯 사냥 성공!", 
            description=f"**{caught_animal}**을(를) 잡았습니다!\n판매 수익으로 **{reward:,}원**을 벌었습니다.", 
            color=0x2ecc71
        )
        embed.set_footer(text=f"현재 서버 잔고: {new_money:,}원")
        await interaction.edit_original_response(content=None, embed=embed)

    else:
        # --- 사냥 실패 및 부상 로직 ---
        # 100원에서 1000원 사이의 랜덤 부상 비용 발생
        damage_cost = random.randint(100, 1000)
        
        # 돈 차감 (0원 이하로는 안 내려가게 설정)
        new_money = max(0, current_money - damage_cost)
        set_user_data(user_money, g_id, u_id, new_money)

        embed = discord.Embed(
            title="⚠️ 사냥 실패 및 부상", 
            description=f"동물을 놓치고 상처를 입었습니다...\n치료비로 **{damage_cost:,}원**이 지출되었습니다.", 
            color=0xe74c3c
        )
        embed.set_footer(text=f"현재 서버 잔고: {new_money:,}원")
        await interaction.edit_original_response(content=None, embed=embed)

@bot.tree.command(name="동물가격표", description="사냥할 수 있는 동물들의 가격과 난이도를 확인합니다.")
async def 동물가격표(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📜 사냥 동물 시세표 (전체 60종)",
        description="희귀한 동물일수록 잡을 확률이 낮지만 훨씬 비쌉니다.\n" + "─" * 20,
        color=0xf1c40f
    )
    
    # 60개를 적절히 나누어 필드에 추가 (한 필드당 10~12개 정도가 가독성이 좋습니다)
    current_text = ""
    field_count = 1
    
    for i, (name, info) in enumerate(HUNT_DATA.items()):
        # 확률이 전반적으로 높아졌으므로 난이도 기준을 재설정합니다.
        # 최하 확률이 20이므로, 그에 맞춰 범위를 조정했습니다.
        if info["chance"] >= 100: 
            difficulty = "🟢 쉬움"
        elif info["chance"] >= 50: 
            difficulty = "🟡 보통"
        elif info["chance"] >= 30:
            difficulty = "🟠 높음"
        else: 
            difficulty = "🔴 매우어려움"
        
        current_text += f"{name} | **{info['price']:,}원** | {difficulty}\n"
        
        # 12개마다 새로운 필드로 분리하여 가독성 확보
        if (i + 1) % 12 == 0 or (i + 1) == len(HUNT_DATA):
            embed.add_field(
                name=f"목록 ({field_count}/5)", 
                value=current_text, 
                inline=False
            )
            current_text = ""
            field_count += 1

    embed.set_footer(text="주의: 사냥 실패 시 치료비가 발생할 수 있습니다. | 총 60종의 생명체가 서식 중")
    await interaction.response.send_message(embed=embed)
# # =====================
# 도박: 배팅 (서버별 독립 버전)
# =====================
@bot.tree.command(name="도박", description="배팅금을 걸고 도박을 합니다. (성공 확률 45%, 보상 2배)")
async def 도박(interaction: discord.Interaction, bet: int):
    g_id = interaction.guild.id
    u_id = interaction.user.id
    
    # 이 서버의 현재 잔고 가져오기
    current_money = get_user_data(user_money, g_id, u_id, 0)

    # 1. 예외 처리
    if bet <= 0:
        return await interaction.response.send_message("❌ 1원 이상 배팅해야 합니다.", ephemeral=True)
    
    if current_money < bet:
        return await interaction.response.send_message(
            f"❌ **이 서버의 잔액**이 부족합니다. (현재 잔고: {current_money:,}원)", 
            ephemeral=True
        )

    # 2. 45% 확률로 성공 로직
    result = random.randint(1, 100)
    
    if result <= 45:
        # 성공: 배팅금의 2배를 얻음 (기존 잔고 + 배팅금액 만큼 추가)
        new_money = current_money + bet
        set_user_data(user_money, g_id, u_id, new_money)
        
        await interaction.response.send_message(
            f"🍀 **대성공!** 🍀\n{interaction.user.mention}님, 45%의 확률을 뚫고 **{bet*2:,}원**을 획득하셨습니다! \n"
            f"💰 현재 **이 서버** 잔고: {new_money:,}원"
        )
    else:
        # 실패: 배팅금 차감
        new_money = current_money - bet
        set_user_data(user_money, g_id, u_id, new_money)
        
        await interaction.response.send_message(
            f"💸 **탕진잼...** 💸\n{interaction.user.mention}님, 배팅한 **{bet:,}원**이 공중분해 되었습니다. \n"
            f"💰 현재 **이 서버** 잔고: {new_money:,}원"
        )

# =====================
# 명령어: 퍼니퀴즈
# =====================
# 1. 봇이 켜질 때 슬래시 명령어를 디스코드에 등록하는 설정
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"{bot.user.name} 연결 완료!")
        print(f"동기화된 명령어 개수: {len(synced)}개")
    except Exception as e:
        print(f"동기화 중 오류 발생: {e}")


# =====================
# 명령어: 퍼니퀴즈 (중단 기능 포함)
# =====================
@bot.tree.command(name="퍼니퀴즈", description="10문제 중 가장 많이 맞힌 사람이 3만 원을 획득합니다! (30초, 3단계 힌트)")
async def 가사빈칸(interaction: discord.Interaction):
    g_id = interaction.guild_id
    
    if active_games.get(g_id):
        return await interaction.response.send_message("❌ 이 서버에서 이미 게임이 진행 중입니다!", ephemeral=True)

    active_games[g_id] = True
    # 1. 문제 데이터 (제목 요소 완벽 제거 및 순수 가사 구성)
    lyrics_pool = [
        {"quiz": "동해 물과 [ ?? ]산이 마르고 닳도록", "answer": "백두"},
        {"quiz": "아름다운 이 땅에 금수강산에 [ ?? ] 할아버지가 터 잡으시고", "answer": "단군"},
        {"quiz": "나의 살던 [ ?? ]은 꽃 피는 산골", "answer": "고향"},
        {"quiz": "보고 싶다 보고 싶다 이런 내가 [ ?? ]", "answer": "미워"},
        {"quiz": "모든 날 모든 [ ?? ] 함께해", "answer": "순간"},
        {"quiz": "나랑 [ ?? ] 보러 가지 않을래", "answer": "별"},
        {"quiz": "그대 내게 [ ?? ]을 주는 사람", "answer": "행복"},
        {"quiz": "서로의 마음에 [ ?? ]을 띄우고", "answer": "작은배"},
        {"quiz": "걱정 말아요 그대 그대여 [ ?? ] 하지 말아요", "answer": "아무걱정"},
        {"quiz": "당신은 [ ?? ] 받기 위해 태어난 사람", "answer": "사랑"},
        {"quiz": "흔들리는 [ ?? ] 속에서 네 샴푸향이 느껴진거야", "answer": "꽃들"},
        {"quiz": "비가 오는 날엔 나를 [ ?? ]와", "answer": "찾아"},
        {"quiz": "사랑이 어떻게 [ ?? ]니", "answer": "변하"},
        {"quiz": "취기를 빌려 오늘 너에게 [ ?? ]할게", "answer": "고백"},
        {"quiz": "만약에 내가 간다면 내가 [ ?? ]가 된다면", "answer": "나비"},
        {"quiz": "빨간 맛 [ ?? ]해 허니", "answer": "궁금"},
        {"quiz": "뚜두뚜두 [ ?? ]를 쏴라", "answer": "총"},
        {"quiz": "내가 제일 잘 [ ?? ]", "answer": "나가"},
        {"quiz": "벌써 [ ?? ]시인데 아직도 난 너를", "answer": "12"},
        {"quiz": "머리부터 발끝까지 다 [ ?? ]스러워", "answer": "사랑"},
        {"quiz": "어제보다 오늘 더 [ ?? ]해", "answer": "사랑"},
        {"quiz": "우리집으로 [ ?? ]", "answer": "가자"},
        {"quiz": "니가 하면 로맨스 내가 하면 [ ?? ]", "answer": "불륜"},
        {"quiz": "나의 모든 순간은 [ ?? ]였다", "answer": "너"},
        {"quiz": "그때 헤어지면 돼 지금은 [ ?? ]해", "answer": "사랑"},
        {"quiz": "오늘도 난 술을 마셔 너를 [ ?? ]내기 위해", "answer": "지워"},
        {"quiz": "내 생에 가장 [ ?? ]다운 날들", "answer": "아름"},
        {"quiz": "말하지 않아도 [ ?? ] 수 있어", "answer": "알"},
        {"quiz": "시간이 약이라는 말은 다 [ ?? ]말이야", "answer": "거짓"},
        {"quiz": "내 피 땀 [ ?? ] 내 마지막 춤을 다 가져가", "answer": "눈물"},
        {"quiz": "영원히 우린 [ ?? ]해", "answer": "함께"},
        {"quiz": "어텐션 [ ?? ]를 집중해", "answer": "시선"},
        {"quiz": "너를 [ ?? ]한 거니까 (Hype Boy)", "answer": "선택"},
        {"quiz": "너무 떨려서 [ ?? ]도 못해 (Super Shy)", "answer": "말"},
        {"quiz": "설렐 때만 [ ?? ] 사랑하니까 (Peek-A-Boo)", "answer": "사랑"},
        {"quiz": "조금 더 [ ?? ]을 내 (Cheer Up)", "answer": "힘"},
        {"quiz": "으르렁 으르렁 으르렁 [ ?? ]", "answer": "대"},
        {"quiz": "너를 [ ?? ]하는 밤 (별이 빛나는 밤)", "answer": "그리워"},
        {"quiz": "너의 모든 게 [ ?? ]해 (작은 것들을 위한 시)", "answer": "궁금"},
        {"quiz": "빛으로 이 밤을 [ ?? ] (Dynamite)", "answer": "밝혀"},
        {"quiz": "너의 [ ?? ]을 녹여버릴 거야 (Butter)", "answer": "마음"},
        {"quiz": "내 [ ?? ]은 핫해 (Queencard)", "answer": "몸매"},
        {"quiz": "나는 네가 [ ?? ] (Love Lee)", "answer": "좋아"},
        {"quiz": "위아래 위 위 [ ?? ]", "answer": "아래"},
        {"quiz": "너의 [ ?? ]이 들려와", "answer": "숨소리"},
        {"quiz": "깨지지 않게 [ ?? ]해줘 (유리구슬)", "answer": "약속"},
        {"quiz": "살짝 설렜어 난 [ ?? ]이 아니야", "answer": "장난"},
        {"quiz": "내가 가는 길은 [ ?? ] (I AM)", "answer": "빛"},
        {"quiz": "너는 [ ?? ] 같아 (Oh My God)", "answer": "천사"},
        {"quiz": "너의 [ ?? ]을 태워버려 (화)", "answer": "기억"},
        {"quiz": "너는 나의 [ ?? ] (비올레타)", "answer": "꽃"},
        {"quiz": "너의 [ ?? ]을 보여줘 (Mr.)", "answer": "마음"},
        {"quiz": "모두 다 같이 [ ?? ] (Jumping)", "answer": "뛰어"},
        {"quiz": "너의 [ ?? ]을 열어봐 (Pandora)", "answer": "상자"},
        {"quiz": "정신이 너무 [ ?? ] (총 맞은 것처럼)", "answer": "없어"},
        {"quiz": "가끔 미치게 네가 [ ?? ] 싶을 때가 있어", "answer": "보고"},
        {"quiz": "차가운 겨울바람이 불면 [ ?? ]가 생각나", "answer": "너"},
        {"quiz": "다시 써보려 해 [ ?? ]이 되길", "answer": "해피엔딩"},
        {"quiz": "다시 만날 수 있을까 [ ?? ]처럼", "answer": "운명"},
        {"quiz": "매일 기다려 너를 [ ?? ]하며", "answer": "그리워"},
        {"quiz": "다시 돌아오길 [ ?? ]해", "answer": "간절"},
        {"quiz": "네가 내게 준 [ ?? ]을 기억해", "answer": "상처"},
        {"quiz": "사랑해 미안해 [ ?? ]는 말 못해", "answer": "고맙다"},
        {"quiz": "밤하늘의 [ ?? ]을 따서 너에게 줄게", "answer": "별"},
        {"quiz": "어느새 훌쩍 커버린 [ ?? ]가 낯설어", "answer": "내모습"},
        {"quiz": "내가 만약 괴로울 때면 내가 [ ?? ]가 되어줄게", "answer": "위로"},
        {"quiz": "우리의 [ ?? ]은 아직 끝나지 않았어", "answer": "노래"},
        {"quiz": "사랑은 [ ?? ]처럼 왔다가 가네", "answer": "바람"},
        {"quiz": "너를 위해 노래할게 이 [ ?? ]이 끝날 때까지", "answer": "순간"},
        {"quiz": "눈물이 나면 [ ?? ]를 봐", "answer": "하늘"},
        {"quiz": "우리가 [ ?? ]했던 시간을 기억해", "answer": "함께"},
        {"quiz": "지나가면 [ ?? ]만 남겠지 (사랑이 지나가면)", "answer": "추억"},
        {"quiz": "끝나지 않은 [ ?? ]을 들려줄게", "answer": "이야기"},
        {"quiz": "되돌릴 수 있다면 [ ?? ]로 갈까", "answer": "과거"},
        {"quiz": "우리의 [ ?? ]을 약속해", "answer": "영원"},
        {"quiz": "이 밤이 지나면 너를 [ ?? ] 수 있을까", "answer": "잊을"},
        {"quiz": "사랑은 [ ?? ]처럼 달콤해", "answer": "초콜릿"},
        {"quiz": "나의 [ ?? ]은 멈추지 않아", "answer": "질주"},
        {"quiz": "네가 없는 세상은 [ ?? ] 같아", "answer": "지옥"},
        {"quiz": "서로에게 [ ?? ]가 되어주자", "answer": "빛"},
        {"quiz": "너를 만나고 내 [ ?? ]이 바뀌었어", "answer": "인생"},
        {"quiz": "너의 [ ?? ]을 지켜줄게", "answer": "눈물"},
        {"quiz": "사랑은 [ ?? ]처럼 갑자기 찾아와", "answer": "소나기"},
        {"quiz": "너와 함께라면 어디든 [ ?? ]", "answer": "천국"},
        {"quiz": "너를 사랑하는 건 나의 [ ?? ]", "answer": "운명"},
        {"quiz": "이별은 항상 [ ?? ]만 남겨", "answer": "슬픔"},
        {"quiz": "너의 [ ?? ]이 되고 싶어", "answer": "그림자"},
        {"quiz": "너는 내게 [ ?? ] 같은 존재야", "answer": "기적"},
        {"quiz": "너의 [ ?? ]에 귀를 기울여", "answer": "목소리"},
        {"quiz": "너를 향한 나의 [ ?? ]를 봐", "answer": "진심"},
        {"quiz": "사랑은 [ ?? ]처럼 피어나", "answer": "꽃"},
        {"quiz": "우리의 [ ?? ]은 끝나지 않아", "answer": "여행"},
        {"quiz": "사랑해라는 말 [ ?? ] 아껴둬", "answer": "조금"},
        {"quiz": "우리의 [ ?? ]을 축복해", "answer": "만남"},
        {"quiz": "사랑은 [ ?? ]처럼 투명해", "answer": "유리"},
        {"quiz": "너와 나 사이의 [ ?? ]을 지워", "answer": "거리"},
        {"quiz": "너를 잊는 건 [ ?? ] 일이야", "answer": "불가능한"},
        {"quiz": "사랑은 [ ?? ]처럼 따뜻해", "answer": "햇살"},
        {"quiz": "너의 [ ?? ] 속에 머물고 싶어", "answer": "기억"},
        {"quiz": "너를 사랑해 [ ?? ]만큼", "answer": "죽을"},
        {"quiz": "사랑은 [ ?? ]을 변화시켜", "answer": "사람"},
        {"quiz": "너의 [ ?? ]가 되어줄게", "answer": "안식처"},
        {"quiz": "너와 함께라면 [ ?? ] 없어", "answer": "겁"},
        {"quiz": "너의 [ ?? ]을 믿어", "answer": "진심"},
        {"quiz": "사랑하는 게 나의 [ ?? ]야", "answer": "전부"},
        {"quiz": "사랑은 [ ?? ]을 멈추게 해", "answer": "시간"},
        {"quiz": "너의 [ ?? ]를 기억할게", "answer": "향기"},
        {"quiz": "우리의 [ ?? ]은 영원할 거야", "answer": "사랑"},
        {"quiz": "니가 왜 거기서 [ ?? ]", "answer": "나와"},
        {"quiz": "막걸리 [ ?? ]잔", "answer": "한"},
        {"quiz": "찐찐찐찐 [ ?? ]이야", "answer": "찐"},
        {"quiz": "어느 60대 노부부 [ ?? ]", "answer": "이야기"},
        {"quiz": "남행열차에 몸을 [ ?? ]", "answer": "실었네"},
        {"quiz": "아모르 [ ?? ]", "answer": "파티"},
        {"quiz": "내 나이가 [ ?? ]어서", "answer": "어때"},
        {"quiz": "무조건 무조건 [ ?? ]야", "answer": "이야"},
        {"quiz": "난 이제 [ ?? ]었어 (땡벌)", "answer": "지쳤"},
        {"quiz": "사랑은 아무나 [ ?? ]", "answer": "하나"},
        {"quiz": "곤드레 [ ?? ]", "answer": "만드레"},
        {"quiz": "당신은 나의 [ ?? ] (동반자)", "answer": "동반자"},
        {"quiz": "안동 [ ?? ]에서", "answer": "역"},
        {"quiz": "보릿 [ ?? ]", "answer": "고개"},
        {"quiz": "그대여 [ ?? ] (초혼)", "answer": "다시"},
        {"quiz": "사랑아 [ ?? ] 사랑아", "answer": "내"},
        {"quiz": "사랑의 [ ?? ]", "answer": "배터리"},
        {"quiz": "어머나 [ ?? ]마", "answer": "어머"},
        {"quiz": "짠짜라 [ ?? ]", "answer": "짠"},
        {"quiz": "엄지 [ ?? ]", "answer": "척"},
        {"quiz": "고장난 [ ?? ]", "answer": "벽시계"},
        {"quiz": "찔레꽃 붉게 피는 [ ?? ]", "answer": "남쪽나라"},
        {"quiz": "울고 넘는 [ ?? ]", "answer": "박달재"},
        {"quiz": "홍도야 [ ?? ] 마라", "answer": "울지"},
        {"quiz": "단장의 미아리 [ ?? ]", "answer": "고개"},
        {"quiz": "신라의 [ ?? ] 밤", "answer": "달밤"},
        {"quiz": "비 내리는 [ ?? ]", "answer": "고모령"},
        {"quiz": "나그네 [ ?? ]", "answer": "설음"},
        {"quiz": "번지 없는 [ ?? ]", "answer": "주막"},
        {"quiz": "꿈에 본 [ ?? ]", "answer": "내고향"},
        {"quiz": "봄바람 휘날리며 흩날리는 [ ?? ] 잎이", "answer": "벚꽃"},
        {"quiz": "아름답게 [ ?? ]네 (작은 별)", "answer": "비치"},
        {"quiz": "어디를 [ ?? ]느냐 (산토끼)", "answer": "가"},
        {"quiz": "학교 종이 [ ?? ]친다 어서 모이자", "answer": "땡땡땡"},
        {"quiz": "세 마리가 [ ?? ] 집에 있어", "answer": "한"},
        {"quiz": "엉덩이는 [ ?? ] 빨가면 사과", "answer": "빨개"},
        {"quiz": "비행기 날아라 [ ?? ]라", "answer": "높이"},
        {"quiz": "꼬부랑 [ ?? ]가 고갯길을 (꼬부랑 할머니)", "answer": "할머니"},
        {"quiz": "엄마가 [ ?? ] 가러 가면 (섬집 아기)", "answer": "굴"},
        {"quiz": "코끼리 아저씨는 [ ?? ]가 손이래", "answer": "코"},
        {"quiz": "개울가에 [ ?? ] 한 마리 (올챙이와 개구리)", "answer": "올챙이"},
        {"quiz": "이리 날아 [ ?? ]라 (나비야)", "answer": "오"},
        {"quiz": "머리 어깨 [ ?? ] 발", "answer": "무릎"},
        {"quiz": "그대로 [ ?? ]라", "answer": "멈춰"},
        {"quiz": "누가 와서 [ ?? ]요 (옹달샘)", "answer": "먹나"},
        {"quiz": "기차 길 옆 [ ?? ] 아기", "answer": "옥수수"},
        {"quiz": "햇볕은 [ ?? ] 반짝", "answer": "쨍쨍"},
        {"quiz": "꼭꼭 [ ?? ] 머리카락 보일라", "answer": "숨어라"},
        {"quiz": "우리의 [ ?? ]은 통일", "answer": "소원"},
        {"quiz": "아빠 힘내세요 [ ?? ]가 있잖아요", "answer": "우리"},
        {"quiz": "꼬마 눈사람 [ ?? ] 눈사람", "answer": "하얀"},
        {"quiz": "멋쟁이 [ ?? ] 울퉁불퉁", "answer": "토마토"},
        {"quiz": "노는 게 제일 [ ?? ] (뽀로로)", "answer": "좋아"},
        {"quiz": "태극기가 [ ?? ]입니다", "answer": "바람에"},
        {"quiz": "어린이날 [ ?? ]들은 자란다", "answer": "우리"},
        {"quiz": "스승의 은혜는 [ ?? ] 같아서", "answer": "하늘"},
        {"quiz": "독도는 우리 땅 [ ?? ] 울릉군", "answer": "강원도"},
        {"quiz": "사랑이라는 [ ?? ]로 너를 가두고 싶지 않아", "answer": "이름"},
        {"quiz": "우린 너무 [ ?? ]을 사랑했었나 봐", "answer": "서로"},
        {"quiz": "너와 함께 걷던 이 [ ?? ]을 기억해", "answer": "거리"},
        {"quiz": "감미로운 [ ?? ]의 속삭임", "answer": "그대"},
        {"quiz": "향기를 남기고 [ ?? ]은 눈물을 남기고", "answer": "이별"},
        {"quiz": "너에게 난 [ ?? ]이 되고 싶어", "answer": "우주"},
        {"quiz": "오랜 시간 동안 [ ?? ]해온 나의 사랑", "answer": "간직"},
        {"quiz": "눈을 감으면 자꾸만 [ ?? ]오르는 그 얼굴", "answer": "떠"},
        {"quiz": "나의 밤은 깊어만 가고 [ ?? ]이 없는 이 밤", "answer": "끝"},
        {"quiz": "어디에도 없는 [ ?? ] 너의 곁에 있을게", "answer": "기억"},
        {"quiz": "흩날리는 기억들 속에 [ ?? ]을 찾아봐", "answer": "조각"},
        {"quiz": "내 품에 안겨 눈을 [ ?? ]요", "answer": "감아"},
        {"quiz": "어둠 속에서 빛을 찾아 [ ?? ]이는 나", "answer": "헤매"},
        {"quiz": "사랑하고 싶어 죽을 만큼 [ ?? ]하고 싶어", "answer": "사랑"},
        {"quiz": "우리의 사랑은 [ ?? ]처럼 짧았지", "answer": "여름밤"},
        {"quiz": "눈물이 흐르면 [ ?? ]이 날까요", "answer": "기억"},
        {"quiz": "이 밤의 끝을 잡고 있는 나의 [ ?? ]", "answer": "미련"},
        {"quiz": "우리는 서로에게 [ ?? ]가 되어주었지", "answer": "등불"},
        {"quiz": "그대여 [ ?? ]을 잊지 말아요", "answer": "오늘"},
        {"quiz": "너의 그 한마디 말도 그 [ ?? ]도 나에겐 의미", "answer": "웃음"},
        {"quiz": "겁이 나지만 [ ?? ]밖에 난 몰라", "answer": "사랑"},
        {"quiz": "우리의 [ ?? ]을 위해 건배", "answer": "행복"},
        {"quiz": "시간아 [ ?? ]라 더 빨리 달려라", "answer": "멈춰"},
        {"quiz": "사랑이라는 건 [ ?? ]일지도 몰라", "answer": "꿈"},
        {"quiz": "여백 하나 남겨둔 [ ?? ]", "answer": "마음"},
        {"quiz": "네가 진짜로 [ ?? ]는 게 뭐야", "answer": "원하"},
        {"quiz": "만나서 [ ?? ]습니다 다음에 또 만나요", "answer": "반가워"},
        {"quiz": "안녕은 영원한 [ ?? ]은 아니겠지요", "answer": "헤어짐"},
        {"quiz": "여우야 여우야 뭐하니 [ ?? ] 잔다", "answer": "잠"},
        {"quiz": "작은 [ ?? ] 노래하며 날아갑니다", "answer": "새"},
        {"quiz": "시원한 [ ?? ] 바람 (산바람 강바람)", "answer": "시원한"},
        {"quiz": "나뭇잎 배 [ ?? ] 띄워", "answer": "살짝"},
        {"quiz": "눈을 감고 [ ?? ]을 들어봐요", "answer": "노래"},
        {"quiz": "모두 다 같이 [ ?? ]", "answer": "박수"},
        {"quiz": "네모난 [ ?? ] 속에 담긴 세상", "answer": "상자"},
        {"quiz": "조금 더 높은 곳에 [ ?? ]가 있을 뿐", "answer": "니"},
        {"quiz": "비 오는 거리에서 그대 [ ?? ]를 생각해요", "answer": "모습"},
        {"quiz": "언젠간 가겠지 푸르른 이 [ ?? ]", "answer": "청춘"},
        {"quiz": "붉은 노을처럼 난 너를 [ ?? ]해", "answer": "사랑"},
        {"quiz": "그녀를 만나는 곳 [ ?? ]m 전", "answer": "100"},
        {"quiz": "내 마음의 보석 상자 속의 [ ?? ]들", "answer": "기억"},
        {"quiz": "어쩌다 마주친 그대 모습이 너무 [ ?? ]어", "answer": "예뻤"},
        {"quiz": "나 어떡해 너를 [ ?? ] 보낸 뒤", "answer": "떠나"},
        {"quiz": "여행을 떠나요 즐거운 [ ?? ]으로", "answer": "마음"},
        {"quiz": "단발머리 하고 그대 [ ?? ]이면", "answer": "웃음"},
        {"quiz": "나를 봐요 [ ?? ] 보지 말고", "answer": "딴데"},
        {"quiz": "청바지가 잘 어울리는 [ ?? ]", "answer": "여자"},
        {"quiz": "저 푸른 초원 위에 [ ?? ]을 짓고", "answer": "그림같은집"},
        {"quiz": "그대 내 곁에 [ ?? ]으면 (사랑밖에 난 몰라)", "answer": "있어준다면"},
        {"quiz": "우리 만남은 [ ?? ]이 아니야", "answer": "우연"},
        {"quiz": "그대 앞에만 서면 나는 왜 [ ?? ]해지는가", "answer": "작아"},
        {"quiz": "우리 몸엔 우리 [ ?? ]", "answer": "것이좋은것이여"},
        {"quiz": "찰랑찰랑 [ ?? ]이 넘치네", "answer": "술잔"},
        {"quiz": "무조건 무조건 [ ?? ]야", "answer": "이야"},
        {"quiz": "빙글빙글 [ ?? ]가며 (둥글게 둥글게)", "answer": "돌아"},
        {"quiz": "보았니 [ ?? ]이 가득한 (파란 나라)", "answer": "꿈과사랑"},
        {"quiz": "어젯밤 자정 무렵 [ ?? ] 아빠가 나를 불렀지", "answer": "술취하신"},
        {"quiz": "뒷다리가 쑥 [ ?? ]다리가 쑥", "answer": "앞"},
        {"quiz": "정글 숲을 지나서 [ ?? ] 가네", "answer": "가자"},
        {"quiz": "아름답게 [ ?? ]네 (작은 별)", "answer": "비치"},
        {"quiz": "나뭇잎 배 [ ?? ] 띄워", "answer": "살짝"},
        {"quiz": "나의 살던 고향은 [ ?? ] 꽃 피는 산골", "answer": "꽃피는"},
        {"quiz": "아카시아 꽃이 활짝 피었네 [ ?? ] 꽃이 활짝 피었네", "answer": "하얀"},
        {"quiz": "손이 시려워 [ ?? ]이 시려워 (겨울 바람)", "answer": "발"},
        {"quiz": "주위를 둘러보면 온통 [ ?? ] 것들뿐", "answer": "네모난"},
        {"quiz": "노란 풍선이 [ ?? ]로 날아가면", "answer": "하늘"},
        {"quiz": "단지 널 사랑해 이렇게 [ ?? ]", "answer": "말했지"},
        {"quiz": "Love Is [ ?? ]", "answer": "보고싶고"},
        {"quiz": "나를 사랑한다고 [ ?? ] 말해줘", "answer": "자꾸만"},
        {"quiz": "Gee Gee Gee Gee [ ?? ] 베이베", "answer": "베이베"},
        {"quiz": "오빤 [ ?? ] 스타일", "answer": "강남"},
        {"quiz": "그만하자 그만하자 [ ?? ]만 하니까", "answer": "사랑"},
        {"quiz": "이 밤 그날의 [ ?? ]을 당신의 창 가까이 보낼게요", "answer": "반딧불"},
        {"quiz": "나는요 [ ?? ]이 좋은걸", "answer": "오빠"},
        {"quiz": "우리가 만나 [ ?? ]지 못할 추억이 됐다", "answer": "지우"},
        {"quiz": "나를 [ ?? ]하지 마라 아직도 나는 너를", "answer": "미워"},
        {"quiz": "이젠 [ ?? ]이 되어버린 너의 목소리", "answer": "환상"},
        {"quiz": "우리 함께 [ ?? ]던 그 길을 걸어봐", "answer": "걷"},
        {"quiz": "차가운 [ ?? ]가 내리는 날엔 네가 생각나", "answer": "빗줄기"},
        {"quiz": "너의 [ ?? ]을 보면 내 마음이 떨려와", "answer": "눈빛"},
        {"quiz": "우리의 [ ?? ]을 위해 마지막 잔을 비워", "answer": "이별"},
        {"quiz": "영원할 것 같았던 우리의 [ ?? ]", "answer": "맹세"},
        {"quiz": "내 마음속에 [ ?? ]처럼 남겨진 너", "answer": "흉터"},
        {"quiz": "너를 향한 나의 [ ?? ]은 변함없어", "answer": "그리움"},
        {"quiz": "달콤한 [ ?? ]로 나를 속이지 마", "answer": "유혹"},
        {"quiz": "어둠 속에서 나를 [ ?? ]줄 사람은 너뿐이야", "answer": "구해"},
        {"quiz": "너의 [ ?? ]를 따라 여기까지 왔어", "answer": "흔적"},
        {"quiz": "사랑은 [ ?? ]처럼 왔다가 연기처럼 사라져", "answer": "안개"},
        {"quiz": "너의 [ ?? ]에 기대어 잠들고 싶어", "answer": "어깨"},
        {"quiz": "무심코 던진 [ ?? ]에 내 마음은 무너져", "answer": "한마디"},
        {"quiz": "너와 나 사이엔 [ ?? ] 수 없는 벽이 있어", "answer": "넘을"},
        {"quiz": "시간이 흐를수록 [ ?? ]해지는 너의 얼굴", "answer": "희미"},
        {"quiz": "나의 [ ?? ]을 다해 너를 사랑했어", "answer": "진심"},
        {"quiz": "꿈속에서도 너를 [ ?? ]헤매는 나", "answer": "찾아"},
        {"quiz": "우리의 [ ?? ]은 여기까지인가 봐", "answer": "인연"}
    ]

    await interaction.response.send_message("🎮 **가사 빈칸 게임 시작!** (중단: `/야그만해`)\n단계별로 힌트가 제공됩니다. 우승 상금: **30,000원**!")
    await asyncio.sleep(2)

    current_game_pool = random.sample(lyrics_pool, min(10, len(lyrics_pool)))
    scoreboard = {}

    for i, selected in enumerate(current_game_pool, 1):
        if not active_games.get(g_id):
            await interaction.channel.send("🛑 **게임이 강제 중단되었습니다.**")
            return

        quiz_text = selected["quiz"]
        answer_raw = selected["answer"]
        answer_text = answer_raw.replace(" ", "")
        
        # --- 힌트 데이터 미리 생성 ---
        chosung_hint = get_chosung(answer_raw)
        
        # 2단계: 첫 글자 오픈 (예: 백○○)
        hint2_text = answer_raw[0] + "○" * (len(answer_raw) - 1)
        
        # 3단계: 두 글자 오픈 (예: 백두○, 정답이 두 글자면 전체 공개됨)
        if len(answer_raw) > 1:
            hint3_text = answer_raw[:2] + "○" * (len(answer_raw) - 2)
        else:
            hint3_text = answer_raw  # 한 글자면 그냥 정답 공개

        embed = discord.Embed(
            title=f"🎵 가사 빈칸 게임 ({i}/10 라운드)",
            description=f"**문제:** `{quiz_text}`\n\n⏱️ **제한 시간:** 30초",
            color=0x00ffcc
        )
        quiz_msg = await interaction.channel.send(embed=embed)

        def check(m):
            return m.channel == interaction.channel and \
                   m.content.replace(" ", "") == answer_text and \
                   not m.author.bot

        final_answer_msg = None

        try:
            # --- [단계 0] 첫 10초: 힌트 없음 ---
            final_answer_msg = await bot.wait_for('message', check=check, timeout=10.0)
            
        except asyncio.TimeoutError:
            if not active_games.get(g_id): return
            
            # --- [단계 1] 10초 경과: 초성 힌트 (10초 대기) ---
            hint1_embed = discord.Embed(
                title=f"🎵 가사 빈칸 게임 ({i}/10 라운드) - 1차 힌트",
                description=f"**문제:** `{quiz_text}`\n💡 **초성 힌트:** `{chosung_hint}`\n\n⏱️ **남은 시간:** 20초",
                color=0xffff00
            )
            await quiz_msg.edit(embed=hint1_embed)
            
            try:
                final_answer_msg = await bot.wait_for('message', check=check, timeout=5.0)
            except asyncio.TimeoutError:
                if not active_games.get(g_id): return
                
                # --- [단계 2] 15초 경과: 한 글자 오픈 (5초 대기) ---
                hint2_embed = discord.Embed(
                    title=f"🎵 가사 빈칸 게임 ({i}/10 라운드) - 2차 힌트",
                    description=f"**문제:** `{quiz_text}`\n💡 **초성:** `{chosung_hint}`\n🎁 **첫 글자 오픈:** `{hint2_text}`\n\n⏱️ **남은 시간:** 15초",
                    color=0xffa500
                )
                await quiz_msg.edit(embed=hint2_embed)
                
                try:
                    final_answer_msg = await bot.wait_for('message', check=check, timeout=5.0)
                except asyncio.TimeoutError:
                    if not active_games.get(g_id): return
                    
                    # --- [단계 3] 20초 경과: 두 글자 오픈 (마지막 10초 대기) ---
                    hint3_embed = discord.Embed(
                        title=f"🎵 가사 빈칸 게임 ({i}/10 라운드) - 3차 힌트",
                        description=f"**문제:** `{quiz_text}`\n💡 **초성:** `{chosung_hint}`\n🎁 **두 글자 오픈:** `{hint3_text}`\n\n⏱️ **마지막 10초!**",
                        color=0xff4500
                    )
                    await quiz_msg.edit(embed=hint3_embed)
                    
                    try:
                        final_answer_msg = await bot.wait_for('message', check=check, timeout=10.0)
                    except asyncio.TimeoutError:
                        await interaction.channel.send(f"⏰ **시간 초과!** 정답은 **[{answer_raw}]**였습니다.")

        if final_answer_msg:
            scoreboard[final_answer_msg.author.id] = scoreboard.get(final_answer_msg.author.id, 0) + 1
            await interaction.channel.send(f"✅ **{final_answer_msg.author.mention}님 정답!** (현재 {scoreboard[final_answer_msg.author.id]}점)")

        if i < 10 and active_games.get(g_id):
            await asyncio.sleep(2)

    # --- 게임 종료 후 결과 발표 및 상금 지급 로직 ---
    active_games[g_id] = False
    if not scoreboard:
        await interaction.channel.send("🏁 **게임 종료!** 우승자가 없습니다.")
        return

    max_score = max(scoreboard.values())
    final_winners = [u_id for u_id, score in scoreboard.items() if score == max_score]
    
    result_text = "🏆 **최종 게임 결과** 🏆\n"
    for u_id, score in scoreboard.items():
        user = await bot.fetch_user(u_id)
        result_text += f"- {user.display_name}: {score}점\n"
    await interaction.channel.send(result_text)

    reward = 30000
    winner_mentions = []
    for w_id in final_winners:
        current_money = get_user_data(user_money, g_id, w_id, 0)
        set_user_data(user_money, g_id, w_id, current_money + reward)
        winner_obj = await bot.fetch_user(w_id)
        winner_mentions.append(winner_obj.mention)

    await interaction.channel.send(f"🎊 우승자 {', '.join(winner_mentions)}님께 **상금** **{reward:,}원**을 지급했습니다!")

# =====================
# 명령어: 야그만해 (서버별 독립 버전)
# =====================
@bot.tree.command(name="야그만해", description="이 서버에서 진행 중인 퀴즈를 중단합니다.")
async def 중단(interaction: discord.Interaction):
    g_id = interaction.guild_id
    if active_games.get(g_id):
        active_games[g_id] = False
        await interaction.response.send_message("🛑 이 서버의 게임 중단 요청을 완료했습니다.")
    else:
        await interaction.response.send_message("❓ 현재 이 서버에서 진행 중인 게임이 없습니다.", ephemeral=True)

# =====================
# 봇 준비 완료 (통합 버전 - 상단/하단 중복 금지!)
# =====================
@bot.event
async def on_ready():
    # 슬래시 커맨드 동기화
    try:
        synced = await bot.tree.sync()
        print(f"✅ {bot.user.name} 연결 완료! {len(synced)}개 명령어 동기화됨")
    except Exception as e:
        print(f"❌ 동기화 중 오류: {e}")

    # 인사 스케줄러 실행 (기존에 정의하신 morning, lunch 등)
    if not morning.is_running(): morning.start()
    if not lunch.is_running(): lunch.start()
    if not dinner.is_running(): dinner.start()
    if not test_greeting.is_running(): test_greeting.start()

# =====================
# 음성 및 노래 재생 관련 (슬래시 커맨드 버전)
# =====================

@bot.tree.command(name="야드루와", description="봇을 현재 음성 채널에 참여시킵니다.")
async def 야드루와(interaction: discord.Interaction):
    if not interaction.user.voice:
        return await interaction.response.send_message("❌ 먼저 음성채널에 들어가 주세요", ephemeral=True)

    try:
        if interaction.guild.voice_client:
            if interaction.guild.voice_client.channel != interaction.user.voice.channel:
                await interaction.guild.voice_client.move_to(interaction.user.voice.channel)
        else:
            await interaction.user.voice.channel.connect(timeout=60.0, reconnect=True)
        await interaction.response.send_message("🎧 들어왔어요!")
    except Exception as e:
        await interaction.response.send_message(f"❌ 접속 중 오류 발생: {e}", ephemeral=True)

@bot.tree.command(name="야꺼져", description="봇을 음성 채널에서 퇴장시킵니다.")
async def 야꺼져(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("👋 나갈게요!")
    else:
        await interaction.response.send_message("❌ 저는 지금 음성 채널에 있지 않아요.", ephemeral=True)

@bot.tree.command(name="야재생해", description="현재 곡을 중단하고 새로운 곡을 즉시 재생합니다.")
async def 야재생해(interaction: discord.Interaction, search: str):
    if not interaction.user.voice:
        return await interaction.response.send_message("❌ 음성채널에 먼저 들어가 주세요", ephemeral=True)

    await interaction.response.defer()

    if not interaction.guild.voice_client:
        await interaction.user.voice.channel.connect(timeout=60.0, reconnect=True)

    try:
        # 즉시 재생이므로 대기열 초기화
        queues[interaction.guild.id] = deque()
        
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(f"ytsearch:{search}" if not search.startswith("https://") else search, download=False))
            if 'entries' in info: info = info['entries'][0]
        
        url = info['url']
        title = info['title']
        
        if interaction.guild.voice_client.is_playing():
            interaction.guild.voice_client.stop() # stop 시 check_queue가 호출되지만 대기열이 비어있어 안전함
        
        source = await discord.FFmpegOpusAudio.from_probe(url, executable="ffmpeg", **FFMPEG_OPTIONS)
        interaction.guild.voice_client.play(source, after=lambda e: check_queue(interaction))
        await interaction.followup.send(f"🎶 즉시 재생 시작: **{title}**")
        
    except Exception as e:
        await interaction.followup.send(f"❌ 재생 중 오류 발생: {e}")

@bot.tree.command(name="야기다려", description="노래를 대기열에 추가합니다.")
async def 야기다려(interaction: discord.Interaction, search: str):
    if not interaction.user.voice:
        return await interaction.response.send_message("❌ 음성채널에 먼저 들어가 주세요", ephemeral=True)

    await interaction.response.defer()

    if not interaction.guild.voice_client:
        await interaction.user.voice.channel.connect()

    try:
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(f"ytsearch:{search}" if not search.startswith("https://") else search, download=False))
            if 'entries' in info: info = info['entries'][0]

        url = info['url']
        title = info['title']

        if interaction.guild.id not in queues:
            queues[interaction.guild.id] = deque()

        if interaction.guild.voice_client.is_playing():
            queues[interaction.guild.id].append({'url': url, 'title': title})
            await interaction.followup.send(f"✅ 대기열에 추가됨: **{title}**")
        else:
            source = await discord.FFmpegOpusAudio.from_probe(url, executable="ffmpeg", **FFMPEG_OPTIONS)
            interaction.guild.voice_client.play(source, after=lambda e: check_queue(interaction))
            await interaction.followup.send(f"🎶 재생 시작: **{title}**")

    except Exception as e:
        await interaction.followup.send(f"❌ 대기열 추가 중 오류 발생: {e}")

@bot.tree.command(name="야멈춰", description="재생 중인 노래를 중지합니다.")
async def 야멈춰(interaction: discord.Interaction):
    if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
        # 대기열까지 다 날려버리고 싶다면 아래 주석 해제
        # if interaction.guild.id in queues: queues[interaction.guild.id].clear()
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("⏹️ 재생을 중지했습니다.")
    else:
        await interaction.response.send_message("❌ 재생 중인 노래가 없어요.", ephemeral=True)

@bot.tree.command(name="야넘겨", description="현재 노래를 건너뛰고 다음 곡을 재생합니다.")
async def 야넘겨(interaction: discord.Interaction):
    if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
        # .stop()을 하면 자동으로 play의 after(check_queue)가 실행되어 다음 곡으로 넘어갑니다.
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("⏭️ 현재 노래를 넘겼습니다!")
    else:
        await interaction.response.send_message("❌ 넘길 노래가 없습니다.", ephemeral=True)

@bot.tree.command(name="야목록", description="현재 노래 대기열을 확인합니다.")
async def 야목록(interaction: discord.Interaction):
    if interaction.guild.id in queues and queues[interaction.guild.id]:
        msg = "📋 **현재 대기열 목록:**\n"
        for i, song in enumerate(queues[interaction.guild.id], 1):
            msg += f"{i}. {song['title']}\n"
        await interaction.response.send_message(msg)
    else:
        await interaction.response.send_message("📁 대기열이 비어 있습니다.", ephemeral=True)

# =====================
# 명령어: 야청소해 (슬래시 커맨드 버전)
# =====================
from discord import app_commands # 상단에 추가되어 있는지 확인하세요

@bot.tree.command(name="야청소해", description="메시지를 지정한 개수만큼 삭제합니다.")
@app_commands.describe(amount="삭제할 메시지 개수 또는 '전부' 입력")
@app_commands.checks.has_permissions(manage_messages=True) # 권한 체크
async def 청소(interaction: discord.Interaction, amount: str):
    """
    사용법: 
    /야청소해 amount: 10  -> 10개 삭제
    /야청소해 amount: 전부 -> 대량 삭제
    """
    
    # 슬래시 커맨드는 명령어 자체가 보이지 않으므로 +1을 할 필요가 없습니다.
    if amount == "전부":
        limit = 999
    else:
        try:
            limit = int(amount)
            if limit <= 0:
                return await interaction.response.send_message("❌ 1개 이상의 숫자를 입력해야 합니다.", ephemeral=True)
            if limit > 999:
                limit = 999 
        except ValueError:
            return await interaction.response.send_message("❌ 숫자를 입력하거나 '전부'라고 입력해 주세요.", ephemeral=True)

    # 지우는 동안 응답 대기 (생각 중...)
    await interaction.response.defer(ephemeral=True)
    
    # 메시지 삭제 실행
    deleted = await interaction.channel.purge(limit=limit)
    
    # 결과 메시지 전송 (ephemeral=True로 설정하면 3초 뒤 삭제 로직 없이도 깔끔합니다)
    await interaction.followup.send(f"🧹 **{len(deleted)}개**의 메시지를 깨끗하게 치웠어요!", ephemeral=True)

# 권한 부족 시 에러 처리 (슬래시 커맨드용)
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("🚫 이 명령어를 사용하려면 **메시지 관리** 권한이 필요합니다!", ephemeral=True)
    else:
        # 다른 에러 발생 시 처리
        print(f"Error: {error}")

# =====================
# 명령어: 야도와줘 (슬래시 커맨드 통합 버전)
# =====================
@bot.tree.command(name="야도와줘", description="봇의 모든 명령어 목록을 확인합니다.")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 봇 명령어 가이드",
        description="이 봇의 데이터(돈, 낚시 등)는 **각 서버별로 독립적으로 관리**됩니다.",
        color=0x3498db
    )

    # 일상 & 운세
    embed.add_field(
        name="🔮 일상 & 운세",
        value="`/오늘의운세`: 하루 한 번 나의 운세를 확인합니다.\n"
              "`/궁합 @상대방`: 멘션한 유저와 오늘의 궁합을 봅니다.",
        inline=False
    )

    # 경제 시스템 (수정 및 추가됨)
    embed.add_field(
        name="💰 경제 & 낚시",
        value="`/돈내놔`: 하루 3회, 이 서버 전용 지원금을 받습니다.\n"
              "`/잔고`: 이 서버의 지갑에 있는 돈을 확인합니다.\n"
              "`/낚시`: 물고기를 잡아 보관함에 저장합니다.\n"
              "`/보관함`: 이 서버에서 잡은 내 물고기 목록을 봅니다.\n"
              "`/가격표`: 어떤 물고기가 비싼지 시세를 확인합니다. (신규)\n"
              "`/팔기`: 물고기를 판매합니다. (이름/갯수를 넣으면 골라서 판매 가능!)",
        inline=False
    )

    # 미니게임
    embed.add_field(
        name="🎮 미니게임",
        value="`/퍼니퀴즈`: 가사 빈칸 맞히기! (우승 시 30,000원)\n"
              "`/야그만해`: 진행 중인 퀴즈를 즉시 중단합니다.",
        inline=False
    )

    # 도박 시스템
    embed.add_field(
        name="🎰 도박",
        value="`/홀짝 [금액] [홀/짝]`: 홀짝을 맞춰 돈을 두 배로!\n"
              "`/도박 [금액]`: 45% 확률로 배팅금의 2배를 얻습니다.\n"
              "`/로또`: 1,000원으로 인생 역전! (서버당 하루 15회)",
        inline=False
    )

    # 관리 기능
    embed.add_field(
        name="🛠️ 관리 기능",
        value="`/야청소해 [숫자/전부]`: 메시지를 깔끔하게 지웁니다. (최대 999개)",
        inline=False
    )

    # 음악 시스템
    embed.add_field(
        name="🎶 음악 재생",
        value="`/야드루와`: 봇을 내 음성 채널로 부릅니다.\n"
              "`/야재생해 [검색어/URL]`: 노래를 즉시 재생합니다.\n"
              "`/야기다려 [검색어]`: 노래를 대기열에 추가합니다.\n"
              "`/야목록`: 현재 대기열 목록을 확인합니다.\n"
              "`/야멈춰`: 중지 / `/야넘겨`: 다음 곡 / `/야꺼져`: 퇴장",
        inline=False
    )

    # 푸터 설정
    embed.set_footer(
        text=f"요청자: {interaction.user.display_name} | 데이터는 서버별로 저장됩니다.", 
        icon_url=interaction.user.display_avatar.url
    )
    
    await interaction.response.send_message(embed=embed)

# =====================
# 실행
# =====================
bot.run(TOKEN)
