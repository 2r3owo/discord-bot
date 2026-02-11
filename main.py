import discord
from discord.ext import commands, tasks
import random
import yt_dlp
import datetime
import asyncio
import os
from collections import deque  # 대기열을 위한 deque
import urllib.parse  # 코드 맨 위에 추가
from io import BytesIO # 이미지를 바이트로 변환하기 위해 필요
import random

# =====================
# 설정 부분
# =====================
TOKEN = os.getenv('DISCORD_TOKEN') 
CHANNEL_ID = None

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# 데이터 저장 딕셔너리
user_fortune_data = {}
user_match_data = {}
user_money = {}
user_daily_pay = {}
user_lotto_count = {}
user_inventory = {}

# 노래 대기열 저장소 (서버별 관리)
queues = {}

# YDL 및 FFMPEG 옵션
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
}

# =====================
# 보조 함수 (대기열 관리) - 수정됨
# =====================
def check_queue(ctx):
    """노래 재생이 끝나면 호출되어 다음 곡을 재생합니다."""
    if ctx.guild.id in queues and queues[ctx.guild.id]:
        next_song = queues[ctx.guild.id].popleft()
        
        # Railway 환경을 위해 executable="ffmpeg"를 명시적으로 추가했습니다.
        source = discord.FFmpegOpusAudio(next_song['url'], executable="ffmpeg", **FFMPEG_OPTIONS)
        ctx.voice_client.play(source, after=lambda e: check_queue(ctx))
        
        bot.loop.create_task(ctx.send(f"🎶 다음 곡 재생: **{next_song['title']}**"))
    else:
        if ctx.guild.id in queues:
            del queues[ctx.guild.id]

# =====================
# 유틸리티 함수
# =====================
def now_kst():
    # 한국 시간(UTC+9) 계산
    return datetime.datetime.utcnow() + datetime.timedelta(hours=9)

# =====================
# 봇 준비 및 스케줄러 시작
# =====================
@bot.event
async def on_ready():
    print(f"✅ 봇 로그인 완료: {bot.user}")
    
    # --- 이 부분을 추가하세요 ---
    try:
        synced = await bot.tree.sync()
        print(f"🔄 {len(synced)}개의 명령어 동기화 완료! (삭제된 것 반영됨)")
    except Exception as e:
        print(f"❌ 동기화 중 오류 발생: {e}")
    # --------------------------

    if not morning.is_running():
        morning.start()
    if not lunch.is_running():
        lunch.start()
    if not dinner.is_running():
        dinner.start()
# =====================
# 자동 인사 스케줄러
# =====================
last_sent = {"morning": None, "lunch": None, "dinner": None}

async def send_once(key, hour, minute, message):
    now = now_kst()
    if now.hour == hour and now.minute == minute:
        if last_sent[key] != now.date():
            channel = bot.get_channel(CHANNEL_ID)
            if channel:
                await channel.send(message)
                last_sent[key] = now.date()

@tasks.loop(minutes=1)
async def morning():
    await send_once("morning", 6, 0, "@everyone 기상! 기상! ٩(◕ᗜ◕)و 햇살이 똑똑똑~ 오늘 하루도 귀엽게 시작해 보자구요! 파이팅!! 아, 아침밥 드세요!☀️")

@tasks.loop(minutes=1)
async def lunch():
    await send_once("lunch", 12, 0, "@everyone 꼬르륵.. 배꼽시계가 울려요! 맛있는 거 먹고 배 뚠뚠하게 채우기! 🍚✨")

@tasks.loop(minutes=1)
async def dinner():
    await send_once("dinner", 19, 0, "@everyone 오늘 하루도 갓생 사느라 고생해따! 이제 침대랑 한 몸이 되어서 뒹굴뒹굴할 시간! 그 전에~ 맛있는 저녁은 꼬옥! 드세요! 🛌")

# =====================
# 명령어: 오늘의운세 (슬래시 커맨드 버전)
# =====================
@bot.tree.command(name="오늘의운세", description="하루에 한 번, 오늘의 행운을 확인하세요!")
async def 오늘의운세(interaction: discord.Interaction):
    # 1. 정보 가져오기
    user_id = interaction.user.id
    today = now_kst().date()

    # 2. 중복 체크
    if user_id in user_fortune_data and user_fortune_data[user_id] == today:
        await interaction.response.send_message(
            f"⚠️ {interaction.user.mention}님, 운세는 하루에 한 번만 볼 수 있어요!", 
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
    user_fortune_data[user_id] = today
    
    # 3. 임베드 생성 및 전송 (수정된 부분)
    embed = discord.Embed(title="🔮 오늘의 운세", description=selected, color=0xffd700)
    # ctx.author.display_name 대신 interaction.user.display_name 사용
    embed.set_footer(text=f"{interaction.user.display_name}님의 하루를 응원합니다!")
    
    # ctx.send 대신 interaction.response.send_message 사용
    await interaction.response.send_message(embed=embed)

# =====================
# 명령어: 궁합 (슬래시 커맨드 버전) 💘
# =====================
@bot.tree.command(name="궁합", description="상대방과의 오늘의 궁합 점수를 확인합니다. (상대별 하루 1회)")
async def 궁합(interaction: discord.Interaction, user: discord.Member): # 1. ctx 대신 interaction 사용, user를 인자로 받음
    user_id = interaction.user.id
    today = now_kst().date()

    # 슬래시 커맨드는 'user'가 필수값이므로 None 체크는 생략 가능합니다.
    # 본인과의 궁합 체크
    if user == interaction.user:
        await interaction.response.send_message("😳 자기 자신과의 궁합은 언제나 100점! 다른 분을 선택해 보세요.", ephemeral=True)
        return

    # 상대방 ID까지 포함해서 유니크한 키 생성
    match_key = (user_id, user.id)

    # 하루 1회 제한 체크 (특정 상대방 기준)
    if match_key in user_match_data and user_match_data[match_key] == today:
        await interaction.response.send_message(
            f"⚠️ {interaction.user.mention}님, {user.display_name}님과의 궁합은 이미 확인하셨어요! 내일 다시 봐요. 😉",
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

    # 임베드 생성 (ctx 대신 interaction 사용하도록 수정)
    embed = discord.Embed(title="💘 오늘의 궁합 (상대별 하루 한정!)", color=0xff69b4)
    embed.add_field(name="오늘의 파트너", value=f"{interaction.user.mention} ❤️ {user.mention}", inline=False)
    embed.add_field(name="오늘의 점수", value=f"**{score}점**", inline=False)
    embed.add_field(name="한줄평", value=f"> {selected_comment}", inline=False)
    embed.set_footer(text=f"다른 유저와도 궁합을 볼 수 있습니다!")
    
    # 2. 결과 전송 (interaction.response.send_message)
    await interaction.response.send_message(embed=embed)

# =====================
# 경제 시스템: 돈내놔 (슬래시 커맨드 버전)
# =====================
@bot.tree.command(name="돈내놔", description="하루 3번, 10,000원씩 지원금을 받습니다.")
async def 돈내놔(interaction: discord.Interaction): # ctx -> interaction
    user_id = interaction.user.id # ctx.author -> interaction.user
    today = now_kst().date()

    # 초기 데이터 설정 (기존 로직 유지)
    if user_id not in user_money:
        user_money[user_id] = 0
    if user_id not in user_daily_pay:
        user_daily_pay[user_id] = [today, 0]

    # 날짜가 바뀌었으면 횟수 초기화
    if user_daily_pay[user_id][0] != today:
        user_daily_pay[user_id] = [today, 0]

    if user_daily_pay[user_id][1] < 3:
        user_money[user_id] += 10000
        user_daily_pay[user_id][1] += 1
        count = user_daily_pay[user_id][1]
        # ctx.send -> interaction.response.send_message
        await interaction.response.send_message(f"💰 {interaction.user.mention}님께 10,000원을 드렸습니다! (오늘 {count}/3회 수행)\n현재 잔액: {user_money[user_id]:,}원")
    else:
        await interaction.response.send_message(f"⚠️ 오늘은 이미 3번 다 받으셨어요! 내일 다시 오세요.", ephemeral=True)

# =====================
# 경제 시스템: 잔고 (슬래시 커맨드 버전)
# =====================
@bot.tree.command(name="잔고", description="현재 보유 중인 잔액을 확인합니다.")
async def 잔고(interaction: discord.Interaction): # ctx -> interaction
    money = user_money.get(interaction.user.id, 0) # ctx.author -> interaction.user
    # ctx.send -> interaction.response.send_message
    await interaction.response.send_message(f"💵 {interaction.user.mention}님의 현재 잔고는 **{money:,}원**입니다.")

# =====================
# 도박: 홀짝맞추기 (슬래시 커맨드 버전)
# =====================
@bot.tree.command(name="홀짝", description="배팅금을 걸고 홀/짝을 맞춥니다. (성공 시 2배!)")
async def 홀짝(interaction: discord.Interaction, bet: int, pick: str): # ctx 대신 interaction 사용
    user_id = interaction.user.id
    current_money = user_money.get(user_id, 0)

    # 1. 예외 처리 로직 (기존과 동일)
    if bet <= 0:
        return await interaction.response.send_message("❌ 1원 이상 배팅해야 합니다.", ephemeral=True)
    
    if current_money < bet:
        return await interaction.response.send_message(f"❌ 잔액이 부족합니다. (현재: {current_money:,}원)", ephemeral=True)
    
    if pick not in ['홀', '짝']:
        return await interaction.response.send_message("❓ `홀` 또는 `짝` 중에서 선택해 주세요.", ephemeral=True)

    # 2. 게임 결과 계산 (기존과 동일)
    result = random.choice(['홀', '짝'])
    
    if pick == result:
        user_money[user_id] += bet
        # 3. 결과 전송 (interaction.response.send_message)
        await interaction.response.send_message(
            f"🎊 결과는 **[{result}]**! 성공했습니다! \n"
            f"💰 {bet:,}원을 얻어 현재 잔고는 **{user_money[user_id]:,}원**입니다."
        )
    else:
        user_money[user_id] -= bet
        # 3. 결과 전송
        await interaction.response.send_message(
            f"💀 결과는 **[{result}]**... 아쉽게 실패했습니다. \n"
            f"💸 {bet:,}원을 잃어 현재 잔고는 **{user_money[user_id]:,}원**입니다."
        )

# =====================
# 도박: 로또 (슬래시 커맨드 버전)
# =====================
@bot.tree.command(name="로또", description="로또를 구매합니다. (1,000원, 하루 15회 제한)")
async def 로또(interaction: discord.Interaction): # ctx -> interaction
    user_id = interaction.user.id # ctx.author -> interaction.user
    today = now_kst().date()
    current_money = user_money.get(user_id, 0)
    lotto_price = 1000

    # 1. 로또 횟수 데이터 초기화 및 날짜 체크 (기존 로직 유지)
    if user_id not in user_lotto_count:
        user_lotto_count[user_id] = [today, 0]
    
    # 날짜가 바뀌었으면 횟수 리셋
    if user_lotto_count[user_id][0] != today:
        user_lotto_count[user_id] = [today, 0]

    # 2. 횟수 제한 체크 (15회)
    if user_lotto_count[user_id][1] >= 15:
        return await interaction.response.send_message(
            f"⚠️ {interaction.user.mention}님, 로또는 하루에 15번까지만 구매할 수 있습니다! 내일 다시 도전하세요.", 
            ephemeral=True
        )

    # 3. 잔액 체크
    if current_money < lotto_price:
        return await interaction.response.send_message(
            f"❌ 잔액이 부족합니다. 로또는 {lotto_price:,}원입니다.", 
            ephemeral=True
        )

    # 4. 로또 실행
    user_money[user_id] -= lotto_price
    user_lotto_count[user_id][1] += 1 # 구매 횟수 증가
    current_count = user_lotto_count[user_id][1]

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

    user_money[user_id] += win
    
    # 5. 결과 임베드 전송 (interaction 기반으로 수정)
    embed = discord.Embed(title="🎟️ 로또 결과", description=res, color=0x00ff00 if win > 0 else 0xff0000)
    if win > 0:
        embed.add_field(name="당첨금", value=f"{win:,}원")
    
    embed.add_field(name="현재 잔고", value=f"{user_money[user_id]:,}원", inline=True)
    embed.add_field(name="오늘 구매 횟수", value=f"{current_count} / 15회", inline=True)
    embed.set_footer(text="지나친 도박은 가산을 탕진합니다.")
    
    # 최종 전송
    await interaction.response.send_message(embed=embed)

# ===================== 
# 경제 시스템: 데이터 설정
# ===================== 

FISH_DATA = {
    # --- 기존 항목 ---
    "👟 장화": {"price": 50, "chance": 25},
    "🐟 피라미": {"price": 1000, "chance": 30},
    "🐠 고등어": {"price": 3000, "chance": 20},
    "🐡 복어": {"price": 5000, "chance": 15},
    "🦈 상어": {"price": 20000, "chance": 10},
    "🐳 고래": {"price": 50000, "chance": 5},
    "🪼 해파리": {"price": 1500, "chance": 20},
    "🦐 새우": {"price": 800, "chance": 25},
    "🐙 문어": {"price": 4500, "chance": 12},
    "🦀 게": {"price": 2500, "chance": 18},
    "🐢 거북이": {"price": 15000, "chance": 7},
    "🫵 해마": {"price": 2000, "chance": 50}
}
@bot.tree.command(name="낚시", description="낚싯대를 던져 물고기를 잡습니다.")
async def 낚시(interaction: discord.Interaction):
    user_id = interaction.user.id
    
    # 인벤토리 초기화 (기존 로직)
    if user_id not in user_inventory:
        user_inventory[user_id] = {}

    # 첫 응답은 send_message로 보냅니다.
    await interaction.response.send_message(f"🎣 {interaction.user.display_name}님이 낚싯대를 던졌습니다... (기다리는 중)")
    await asyncio.sleep(2) # 2초 대기

    # 확률 기반 낚시 로직 (기존 로직)
    fish_names = list(FISH_DATA.keys())
    fish_weights = [f["chance"] for f in FISH_DATA.values()]
    caught_fish = random.choices(fish_names, weights=fish_weights, k=1)[0]

    # 인벤토리에 추가
    user_inventory[user_id][caught_fish] = user_inventory[user_id].get(caught_fish, 0) + 1
    
    embed = discord.Embed(title="🎣 낚시 성공!", description=f"와우! **{caught_fish}**를 잡았습니다!", color=0x3498db)
    embed.set_footer(text=f"현재 보관함에 {caught_fish} {user_inventory[user_id][caught_fish]}마리 보유 중")
    
    # 낚시 중이라는 메시지 이후에 결과를 추가로 보낼 때는 follow-up을 사용합니다.
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="보관함", description="내가 잡은 물고기 목록을 확인합니다.")
async def 보관함(interaction: discord.Interaction):
    user_id = interaction.user.id
    inventory = user_inventory.get(user_id, {})
    
    if not inventory or sum(inventory.values()) == 0:
        return await interaction.response.send_message("텅~ 보관함이 비어있습니다. 낚시를 먼저 해보세요!", ephemeral=True)

    msg = "\n".join([f"{name}: {count}마리" for name, count in inventory.items() if count > 0])
    embed = discord.Embed(title=f"🎒 {interaction.user.display_name}님의 보관함", description=msg, color=0x95a5a6)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="물고기팔기", description="보관함에 있는 모든 물고기를 판매합니다.")
async def 물고기팔기(interaction: discord.Interaction):
    user_id = interaction.user.id
    inventory = user_inventory.get(user_id, {})
    
    if not inventory or sum(inventory.values()) == 0:
        return await interaction.response.send_message("❌ 팔 수 있는 물고기가 없습니다.", ephemeral=True)

    total_profit = 0
    for fish_name, count in inventory.items():
        if count > 0:
            profit = FISH_DATA[fish_name]["price"] * count
            total_profit += profit
            inventory[fish_name] = 0 # 판매 후 초기화

    # 돈 지급 (기존 변수 user_money 사용)
    user_money[user_id] = user_money.get(user_id, 0) + total_profit
    
    await interaction.response.send_message(f"💰 물고기를 모두 팔아 **{total_profit:,}원**을 벌었습니다!\n현재 잔고: **{user_money[user_id]:,}원**")


# =====================
# 도박: 배팅 (슬래시 커맨드 버전)
# =====================
@bot.tree.command(name="도박", description="배팅금을 걸고 도박을 합니다. (성공 확률 45%, 보상 2배)")
async def 도박(interaction: discord.Interaction, bet: int): # ctx -> interaction, 배팅금 인자 추가
    user_id = interaction.user.id
    current_money = user_money.get(user_id, 0)

    # 1. 예외 처리 (기존 로직 유지)
    if bet <= 0:
        return await interaction.response.send_message("❌ 1원 이상 배팅해야 합니다.", ephemeral=True)
    
    if current_money < bet:
        return await interaction.response.send_message(f"❌ 잔액이 부족합니다. (현재: {current_money:,}원)", ephemeral=True)

    # 2. 45% 확률로 성공 로직 (기존과 동일)
    result = random.randint(1, 100)
    
    if result <= 45:
        win_money = bet * 2
        user_money[user_id] += (win_money - bet) # 배팅금 제외 순수익 더하기
        # 3. 결과 전송 (interaction.response.send_message)
        await interaction.response.send_message(
            f"🍀 **대성공!** 🍀\n{interaction.user.mention}님, 45%의 확률을 뚫고 **{win_money:,}원**을 획득하셨습니다! \n"
            f"💰 현재 잔고: {user_money[user_id]:,}원"
        )
    else:
        user_money[user_id] -= bet
        # 3. 결과 전송
        await interaction.response.send_message(
            f"💸 **탕진잼...** 💸\n{interaction.user.mention}님, 배팅한 **{bet:,}원**이 공중분해 되었습니다. \n"
            f"💰 현재 잔고: {user_money[user_id]:,}원"
        )

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

@bot.tree.command(name="야재생해", description="현재 곡을 중단하고 새로운 곡을 즉시 재생합니다. (대기열 초기화)")
async def 야재생해(interaction: discord.Interaction, search: str):
    if not interaction.user.voice:
        return await interaction.response.send_message("❌ 음성채널에 먼저 들어가 주세요", ephemeral=True)

    # 슬래시 커맨드는 응답 시간이 짧으므로 미리 생각 중임을 표시
    await interaction.response.defer()

    if not interaction.guild.voice_client:
        await interaction.user.voice.channel.connect(timeout=60.0, reconnect=True)

    try:
        queues[interaction.guild.id] = deque()
        
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(f"ytsearch:{search}" if not search.startswith("https://") else search, download=False))
            if 'entries' in info: info = info['entries'][0]
        
        url = info['url']
        title = info['title']
        
        if interaction.guild.voice_client.is_playing():
            interaction.guild.voice_client.stop()
        
        source = await discord.FFmpegOpusAudio.from_probe(url, executable="ffmpeg", **FFMPEG_OPTIONS)
        interaction.guild.voice_client.play(source, after=lambda e: check_queue(interaction)) # interaction으로 전달
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
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("⏹️ 재생을 중지했습니다.")
    else:
        await interaction.response.send_message("❌ 재생 중인 노래가 없어요.", ephemeral=True)

@bot.tree.command(name="야넘겨", description="현재 노래를 건너뛰고 다음 곡을 재생합니다.")
async def 야넘겨(interaction: discord.Interaction):
    if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
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
# 명령어: 야그려줘 (무료 버전 - 가입/키 필요 없음)
# =====================
@bot.tree.command(name="야그려줘", description="AI가 그림을 그려줍니다. (무료 서버 사용)")
async def 야그려줘_무료(interaction: discord.Interaction, prompt: str):
    # 1. 봇이 작업 중임을 알림 (생각 중... 표시)
    await interaction.response.defer()
    
    try:
        # 2. 한글 검색어를 URL에 쓸 수 있게 변환 (핵심!)
        encoded_prompt = urllib.parse.quote(prompt)
        
        # 3. 이미지 주소 생성 (매번 다른 그림이 나오도록 seed 추가)
        seed = random.randint(1, 999999)
        image_url = f"https://pollinations.ai/p/{encoded_prompt}?width=1024&height=1024&seed={seed}&nologo=true"
        
        # 4. 임베드 설정
        embed = discord.Embed(
            title=f"🎨 요청하신 그림이 완성됐어요!",
            description=f"**프롬프트:** {prompt}",
            color=0x1abc9c
        )
        embed.set_image(url=image_url)
        embed.set_footer(text="이미지가 안 보이면 잠시만 기다려 주세요.")

        # 5. 결과 전송 (defer를 사용했으므로 followup.send 사용)
        await interaction.followup.send(embed=embed)

    except Exception as e:
        # 에러 발생 시 출력
        await interaction.followup.send(f"❌ 그림을 그리는 중 오류가 발생했어요: {e}")

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
        description="이 봇에서 사용할 수 있는 전체 슬래시 명령어 목록입니다.",
        color=0x3498db
    )

    # 일상 & 운세
    embed.add_field(
        name="🔮 일상 & 운세",
       value="""`/오늘의운세`: 하루 한 번 나의 운세를 확인합니다.
`/궁합 @상대방`: 멘션한 유저와 오늘의 궁합을 봅니다.""",
        inline=False
    )

    # 경제 시스템
    embed.add_field(
        name="💰 경제 & 낚시",
        value="`/돈내놔`: 하루 3회, 10,000원을 지원받습니다.\n"
              "`/잔고`: 현재 내 지갑에 있는 돈을 확인합니다.\n"
              "`/낚시`: 물고기(또는 장화)를 잡습니다.\n"
              "`/보관함`: 내가 잡은 물고기 목록을 봅니다.\n"
              "`/물고기팔기`: 잡은 물고기를 모두 팔아 돈을 법니다.",
        inline=False
    )

    # 도박 시스템
    embed.add_field(
        name="🎰 도박",
        value="`/홀짝 [금액] [홀/짝]`: 홀짝을 맞춰 돈을 두 배로!\n"
              "`/도박 [금액]`: 45% 확률로 배팅금의 2배를 얻습니다.\n"
              "`/로또`: 1,000원으로 인생 역전! (하루 15회)",
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
              "`/야재생해 [검색어/URL]`: 노래를 검색하거나 링크로 즉시 재생합니다.\n"
              "`/야기다려 [검색어]`: 노래를 대기열에 추가합니다.\n"
              "`/야목록`: 현재 대기열에 담긴 노래들을 확인합니다.\n"
              "`/야멈춰`: 재생 중인 노래를 중지합니다.\n"
              "`/야넘겨`: 다음 노래로 넘깁니다.\n"
              "`/야꺼져`: 봇을 음성 채널에서 내보냅니다.",
        inline=False
    )

    # 푸터 설정 (interaction.user 사용)
    embed.set_footer(
        text=f"요청자: {interaction.user.display_name}", 
        icon_url=interaction.user.display_avatar.url
    )
    
    await interaction.response.send_message(embed=embed)

# =====================
# 실행
# =====================
bot.run(TOKEN)
