import discord
from discord.ext import commands, tasks
from discord import app_commands
import random
import yt_dlp
import asyncio
import os
from collections import deque
from datetime import datetime, timezone, timedelta
import sys
import nacl
import traceback

print("=" * 50)
print("Python:", sys.version)
print("Executable:", sys.executable)
print("PyNaCl:", nacl.__version__)
print("=" * 50)

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
TOKEN = os.getenv('DISCORD_TOKEN') 
CHANNEL_ID = None

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =====================
# 데이터 저장 및 관리 (서버별 독립 구조)
# =====================
user_money = {}
user_daily_pay = {}
user_lotto_count = {}
user_inventory = {}
user_fortune_data = {}
user_match_data = {}
active_games = {}  # 퀴즈 중단 방지용

def get_user_data(data_dict, guild_id, user_id, default_value):
    g_id = str(guild_id)
    u_id = str(user_id)
    if g_id not in data_dict:
        data_dict[g_id] = {}
    if u_id not in data_dict[g_id]:
        data_dict[g_id][u_id] = default_value
    return data_dict[g_id][u_id]

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
    'options': '-vn',
}

YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'nocheckcertificate': True,
    'cookiefile': 'cookies.txt',
}

# =====================
# 보조 함수 (대기열 관리)
# =====================
def check_queue(interaction: discord.Interaction):
    """노래 재생이 끝나면 호출되어 다음 곡을 재생합니다."""
    guild_id = interaction.guild.id
    
    if guild_id in queues and queues[guild_id]:
        next_song = queues[guild_id].popleft()
        
        source = discord.FFmpegOpusAudio(next_song['url'], executable="ffmpeg", **FFMPEG_OPTIONS)
        interaction.guild.voice_client.play(source, after=lambda e: check_queue(interaction))
        
        coro = interaction.channel.send(f"🎶 다음 곡 재생: **{next_song['title']}**")
        asyncio.run_coroutine_threadsafe(coro, bot.loop)
    else:
        if guild_id in queues:
            del queues[guild_id]

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
        channel = guild.system_channel
        if channel and channel.permissions_for(guild.me).send_messages:
            await channel.send(message)
            continue

        for ch in guild.text_channels:
            if ch.permissions_for(guild.me).send_messages:
                await ch.send(message)
                break

async def send_once(key, hour, minute, message):
    now = now_kst()
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
    await send_once("morning", 6, 0, "기상! 기상! ٩(◕ᗜ◕)و 햇살이 똑똑똑~ 오늘 하루도 귀엽게 시작해 보자구요! ☀️")

@tasks.loop(minutes=1)
async def lunch():
    await send_once("lunch", 12, 0, "🍚 점심시간! 맛있게 드세요!")

@tasks.loop(minutes=1)
async def dinner():
    await send_once("dinner", 19, 0, "🛌 오늘도 고생했어요! 저녁 챙겨드세요!")

@tasks.loop(minutes=1)
async def test_greeting():
    await send_once("test_14", 14, 0, "☕ 커피 한 잔 드실 시간입니다!")

# =====================
# 봇 준비 완료 및 슬래시 커맨드 동기화
# =====================
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"✅ {bot.user.name} 연결 완료! {len(synced)}개 명령어 동기화됨")
    except Exception as e:
        print(f"❌ 동기화 중 오류 발생: {e}")

    if not morning.is_running(): morning.start()
    if not lunch.is_running(): lunch.start()
    if not dinner.is_running(): dinner.start()
    if not test_greeting.is_running(): test_greeting.start()

# =====================
# 명령어: 오늘의운세
# =====================
@bot.tree.command(name="오늘의운세", description="이 서버에서 하루에 한 번, 오늘의 행운을 확인하세요!")
async def 오늘의운세(interaction: discord.Interaction):
    g_id = interaction.guild.id
    u_id = interaction.user.id
    today = str(now_kst().date())

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
        "오늘은 결정 장애가 심해질 수 있으니 추천 메뉴로! 🍱❓", "간식 운 최고!!🍪", "졸림 주의!! 💤", "배터리 조심!! 방전 조심!!",
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
    set_user_data(user_fortune_data, g_id, u_id, today)
    
    embed = discord.Embed(title="🔮 오늘의 운세", description=selected, color=0xffd700)
    embed.set_footer(text=f"{interaction.user.display_name}님의 하루를 응원합니다! (서버 전용)")
    await interaction.response.send_message(embed=embed)

# =====================
# 명령어: 궁합 💘
# =====================
@bot.tree.command(name="궁합", description="이 서버에서 상대방과의 오늘의 궁합 점수를 확인합니다.")
async def 궁합(interaction: discord.Interaction, user: discord.Member):
    g_id = interaction.guild.id
    u_id = interaction.user.id
    today = str(now_kst().date())

    if user == interaction.user:
        await interaction.response.send_message("😳 자기 자신과의 궁합은 언제나 100점! 다른 분을 선택해 보세요.", ephemeral=True)
        return

    match_key = f"{g_id}_{u_id}_{user.id}"

    if match_key in user_match_data and user_match_data[match_key] == today:
        await interaction.response.send_message(
            f"⚠️ {interaction.user.mention}님, 이 서버에서 {user.display_name}님과의 궁합은 이미 확인하셨어요!",
            ephemeral=True
        )
        return

    score = random.randint(0, 100)
    user_match_data[match_key] = today

    if score >= 90:
        comments = ["✨ 전생에 나라를 구했나요? 완벽한 천생연분!", "💎 눈에서 꿀이 떨어지는 찰떡궁합!", "🔥 태양보다 뜨거운 조합!", "💘 독심술 수준으로 잘 통하네요.", "💍 세기의 커플 탄생 예감!"]
    elif score >= 70:
        comments = ["💖 눈빛만 봐도 통하는 사이!", "🍗 닭다리 양보 가능한 찐우정/사랑!", "서로를 웃기는 능력이 탁월해요.", "든든한 아군을 얻으셨네요!"]
    elif score >= 40:
        comments = ["😊 평범하지만 은근히 잘 맞는 구석이 있죠.", "커피 한 잔 하며 수다 떨기 좋은 날.", "운명은 아니어도 꽤 괜찮은 인연!"]
    elif score >= 10:
        comments = ["🤔 가끔 외계어로 대화하는 느낌?", "🧊 조금 서먹한 사이, 대화가 필요해!", "⚡ 자존심 싸움 금지! 한 명은 져주세요."]
    else:
        comments = ["💨 MBTI가 정반대인가요? 도망쳐!!", "🚫 오늘은 차단이 답이다. (농담!)", "🧊 아메리카노보다 차가운 분위기."]

    selected_comment = random.choice(comments)

    embed = discord.Embed(title="💘 오늘의 궁합 (서버별 독립)", color=0xff69b4)
    embed.add_field(name="오늘의 파트너", value=f"{interaction.user.mention} ❤️ {user.mention}", inline=False)
    embed.add_field(name="오늘의 점수", value=f"**{score}점**", inline=False)
    embed.add_field(name="한줄평", value=f"> {selected_comment}", inline=False)
    embed.set_footer(text=f"현재 서버 기준 궁합입니다!")
    await interaction.response.send_message(embed=embed)

# =====================
# 경제 시스템: 돈내놔 / 잔고
# =====================
@bot.tree.command(name="돈내놔", description="이 서버에서 하루 3번, 10,000원씩 지원금을 받습니다.")
async def 돈내놔(interaction: discord.Interaction):
    g_id = interaction.guild.id
    u_id = interaction.user.id
    today = str(now_kst().date())

    daily_info = get_user_data(user_daily_pay, g_id, u_id, [today, 0])
    if daily_info[0] != today:
        daily_info = [today, 0]

    if daily_info[1] < 3:
        current_money = get_user_data(user_money, g_id, u_id, 0)
        new_money = current_money + 10000
        set_user_data(user_money, g_id, u_id, new_money)
        
        daily_info[1] += 1
        set_user_data(user_daily_pay, g_id, u_id, daily_info)
        
        await interaction.response.send_message(
            f"💰 {interaction.user.mention}님께 **이 서버 전용** 지원금 10,000원을 드렸습니다!\n"
            f"📅 오늘 횟수: {daily_info[1]}/3회\n"
            f"💵 현재 서버 잔액: {new_money:,}원"
        )
    else:
        await interaction.response.send_message(f"⚠️ 이 서버에서는 오늘 이미 3번 다 받으셨어요! 내일 다시 오세요.", ephemeral=True)

@bot.tree.command(name="잔고", description="이 서버에서 보유 중인 잔액을 확인합니다.")
async def 잔고(interaction: discord.Interaction):
    money = get_user_data(user_money, interaction.guild.id, interaction.user.id, 0)
    await interaction.response.send_message(f"💵 {interaction.user.mention}님의 **현재 서버** 잔고는 **{money:,}원**입니다.")

# =====================
# 도박: 홀짝 / 로또 / 배팅
# =====================
@bot.tree.command(name="홀짝", description="배팅금을 걸고 홀/짝을 맞춥니다. (성공 시 2배!)")
async def 홀짝(interaction: discord.Interaction, bet: int, pick: str):
    g_id = interaction.guild.id
    u_id = interaction.user.id
    current_money = get_user_data(user_money, g_id, u_id, 0)

    if bet <= 0:
        return await interaction.response.send_message("❌ 1원 이상 배팅해야 합니다.", ephemeral=True)
    if current_money < bet:
        return await interaction.response.send_message(f"❌ 이 서버의 잔액이 부족합니다. (현재: {current_money:,}원)", ephemeral=True)
    if pick not in ['홀', '짝']:
        return await interaction.response.send_message("❓ `홀` 또는 `짝` 중에서 선택해 주세요.", ephemeral=True)

    result = random.choice(['홀', '짝'])
    if pick == result:
        new_money = current_money + bet
        set_user_data(user_money, g_id, u_id, new_money)
        await interaction.response.send_message(f"🎊 결과는 **[{result}]**! 성공했습니다! \n💰 {bet:,}원을 얻어 현재 **이 서버** 잔고는 **{new_money:,}원**입니다.")
    else:
        new_money = current_money - bet
        set_user_data(user_money, g_id, u_id, new_money)
        await interaction.response.send_message(f"💀 결과는 **[{result}]**... 아쉽게 실패했습니다. \n💸 {bet:,}원을 잃어 현재 **이 서버** 잔고는 **{new_money:,}원**입니다.")

@bot.tree.command(name="로또", description="로또를 구매합니다. (1,000원, 서버별 하루 15회 제한)")
async def 로또(interaction: discord.Interaction):
    g_id = interaction.guild.id
    u_id = interaction.user.id
    today = str(now_kst().date())
    lotto_price = 1000

    current_money = get_user_data(user_money, g_id, u_id, 0)
    count_info = get_user_data(user_lotto_count, g_id, u_id, [today, 0])

    if count_info[0] != today:
        count_info = [today, 0]

    if count_info[1] >= 15:
        return await interaction.response.send_message(f"⚠️ {interaction.user.mention}님, **이 서버**에서는 하루 15번까지만 구매할 수 있습니다!", ephemeral=True)
    if current_money < lotto_price:
        return await interaction.response.send_message(f"❌ **이 서버의 잔액**이 부족합니다. (로또 {lotto_price:,}원)", ephemeral=True)

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

    current_money += win
    set_user_data(user_money, g_id, u_id, current_money)
    set_user_data(user_lotto_count, g_id, u_id, count_info)

    embed = discord.Embed(title="🎟️ 서버별 로또 결과", description=res, color=0x00ff00 if win > 0 else 0xff0000)
    if win > 0: embed.add_field(name="당첨금", value=f"{win:,}원")
    embed.add_field(name="이 서버 잔고", value=f"{current_money:,}원", inline=True)
    embed.add_field(name="오늘 구매 횟수", value=f"{count_info[1]} / 15회", inline=True)
    embed.set_footer(text="지나친 도박은 가산을 탕진합니다.")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="도박", description="배팅금을 걸고 도박을 합니다. (성공 확률 45%, 보상 2배)")
async def 도박(interaction: discord.Interaction, bet: int):
    g_id = interaction.guild.id
    u_id = interaction.user.id
    current_money = get_user_data(user_money, g_id, u_id, 0)

    if bet <= 0:
        return await interaction.response.send_message("❌ 1원 이상 배팅해야 합니다.", ephemeral=True)
    if current_money < bet:
        return await interaction.response.send_message(f"❌ **이 서버의 잔액**이 부족합니다. (현재 잔고: {current_money:,}원)", ephemeral=True)

    result = random.randint(1, 100)
    if result <= 45:
        new_money = current_money + bet
        set_user_data(user_money, g_id, u_id, new_money)
        await interaction.response.send_message(f"🍀 **대성공!** 🍀\n{interaction.user.mention}님, 45%의 확률을 뚫고 **{bet*2:,}원**을 획득하셨습니다! \n💰 현재 **이 서버** 잔고: {new_money:,}원")
    else:
        new_money = current_money - bet
        set_user_data(user_money, g_id, u_id, new_money)
        await interaction.response.send_message(f"💸 **탕진잼...** 💸\n{interaction.user.mention}님, 배팅한 **{bet:,}원**이 공중분해 되었습니다. \n💰 현재 **이 서버** 잔고: {new_money:,}원")

# ===================== 
# 경제 시스템: 낚시 시스템
# ===================== 
FISH_DATA = {
    "낡은 장화 👞": {"chance": 10, "price": 100, "is_trash": True},
    "뭉쳐진 휴지 🧻": {"chance": 10, "price": 100, "is_trash": True},
    "찢어진 신문지 🗞️": {"chance": 10, "price": 100, "is_trash": True},
    "찌그러진 캔 🥫": {"chance": 10, "price": 100, "is_trash": True},
    "플라스틱 병 🧴": {"chance": 10, "price": 100, "is_trash": True},
    "피라미 🐟": {"chance": 12, "price": 100},
    "붕어 🐠": {"chance": 10, "price": 500},
    "고등어 🐟": {"chance": 9, "price": 700},
    "새우 🦐": {"chance": 8, "price": 800},
    "불가사리 🌟": {"chance": 7, "price": 1200},
    "연어 🍣": {"chance": 6.5, "price": 1500},
    "잉어 🎏": {"chance": 6, "price": 2000},
    "게 🦀": {"chance": 5.5, "price": 2500},
    "오징어 🦑": {"chance": 5, "price": 3000},
    "갈치 🗡️": {"chance": 4.5, "price": 3500},
    "해파리 🪼": {"chance": 4, "price": 4000},
    "복어 🐡": {"chance": 4, "price": 4500},
    "해마 🦄": {"chance": 3.5, "price": 5000},
    "가오리 🪁": {"chance": 3, "price": 6000},
    "문어 🐙": {"chance": 3, "price": 7000},
    "랍스터 🦞": {"chance": 2.5, "price": 8500},
    "거북이 🐢": {"chance": 2, "price": 10000},
    "참치 🐟": {"chance": 1.5, "price": 12000},
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
    else:
        for f_name, count in inventory.items():
            if count > 0 and f_name in FISH_DATA:
                total_profit += FISH_DATA[f_name]["price"] * count
                inventory[f_name] = 0
        result_msg = f"💰 모든 물고기를 팔아 **{total_profit:,}원**을 벌었습니다!"

    set_user_data(user_inventory, g_id, u_id, inventory)
    current_money = get_user_data(user_money, g_id, u_id, 0)
    set_user_data(user_money, g_id, u_id, current_money + total_profit)
    await interaction.response.send_message(f"{result_msg}\n💵 현재 잔고: **{current_money + total_profit:,}원**")

# ===================== 
# 경제 시스템: 사냥 시스템
# ===================== 
HUNT_DATA = {
    "🪰 파리": {"chance": 400, "price": 100}, "🦟 모기": {"chance": 380, "price": 200}, "🐜 개미": {"chance": 360, "price": 300},
    "🐞 무당벌레": {"chance": 340, "price": 400}, "🦗 귀뚜라미": {"chance": 320, "price": 500}, "🐭 생쥐": {"chance": 300, "price": 600},
    "🕷️ 거미": {"chance": 280, "price": 700}, "🐦 참새": {"chance": 260, "price": 800}, "🐌 달팽이": {"chance": 240, "price": 900},
    "🐥 병아리": {"chance": 220, "price": 1000}, "🐿️ 다람쥐": {"chance": 200, "price": 1200}, "🐸 개구리": {"chance": 190, "price": 1500},
    "🦎 도마뱀": {"chance": 180, "price": 1800}, "🦇 박쥐": {"chance": 170, "price": 2000}, "🐰 토끼": {"chance": 160, "price": 2200},
    "🐢 거북이": {"chance": 150, "price": 2500}, "🐥 오리": {"chance": 145, "price": 2800}, "🕊️ 비둘기": {"chance": 140, "price": 3000},
    "🐓 수탉": {"chance": 135, "price": 3500}, "🦔 고슴도치": {"chance": 130, "price": 4200}, "🐱 길고양이": {"chance": 120, "price": 5000},
    "🐒 원숭이": {"chance": 115, "price": 5500}, "🐕 들개": {"chance": 110, "price": 6000}, "🦦 수달": {"chance": 105, "price": 6600},
    "🦝 너구리": {"chance": 100, "price": 7200}, "🦡 오소리": {"chance": 95, "price": 8500}, "🦩 홍학": {"chance": 90, "price": 9200},
    "🦊 여우": {"chance": 85, "price": 10000}, "🦌 사슴": {"chance": 80, "price": 11500}, "🐗 멧돼지": {"chance": 78, "price": 13000},
    "🐍 뱀": {"chance": 75, "price": 14500}, "🦃 칠면조": {"chance": 72, "price": 16000}, "🦅 독수리": {"chance": 70, "price": 17500},
    "🦉 부엉이": {"chance": 68, "price": 18000}, "🐺 늑대": {"chance": 65, "price": 19000}, "Scorpion 전갈": {"chance": 62, "price": 20000},
    "🦭 물개": {"chance": 60, "price": 21000}, "🐆 표범": {"chance": 58, "price": 23000}, "🦓 얼룩말": {"chance": 55, "price": 24000},
    "🐊 악어": {"chance": 52, "price": 25000}, "🐻 곰": {"chance": 50, "price": 27000}, "🐃 버팔로": {"chance": 48, "price": 28500},
    "🐫 낙타": {"chance": 46, "price": 28800}, "🦏 코뿔소": {"chance": 44, "price": 29000}, "🐋 고래": {"chance": 42, "price": 29200},
    "🦍 고릴라": {"chance": 40, "price": 29500}, "🦒 기린": {"chance": 38, "price": 29600}, "🐯 호랑이": {"chance": 36, "price": 29800},
    "🦁 사자": {"chance": 34, "price": 30000}, "🐘 코끼리": {"chance": 32, "price": 30000}, "🦖 공룡": {"chance": 30, "price": 30000},
    "🦕 브라키오": {"chance": 28, "price": 30000}, "🦄 유니콘": {"chance": 26, "price": 30000}, "🐺 펜릴": {"chance": 25, "price": 30000},
    "🔥 피닉스": {"chance": 24, "price": 30000}, "🧜 인어": {"chance": 23, "price": 30000}, "🐉 용": {"chance": 22, "price": 30000},
    "🦁 키메라": {"chance": 21, "price": 30000}, "✨ 해태": {"chance": 20.5, "price": 30000}, "👑 그리핀": {"chance": 20, "price": 30000}
}

@bot.tree.command(name="사냥", description="야생 동물을 사냥하여 돈을 법니다. (부상 주의!)")
async def 사냥(interaction: discord.Interaction):
    g_id = interaction.guild.id
    u_id = interaction.user.id
    await interaction.response.send_message(f"🏹 {interaction.user.display_name}님이 숲으로 사냥을 떠납니다... 🌲")
    await asyncio.sleep(2) 

    is_success = random.random() < 0.6 
    current_money = get_user_data(user_money, g_id, u_id, 0)

    if is_success:
        animal_names = list(HUNT_DATA.keys())
        animal_weights = [a["chance"] for a in HUNT_DATA.values()]
        caught_animal = random.choices(animal_names, weights=animal_weights, k=1)[0]
        reward = HUNT_DATA[caught_animal]["price"]
        
        new_money = current_money + reward
        set_user_data(user_money, g_id, u_id, new_money)

        embed = discord.Embed(title="🎯 사냥 성공!", description=f"**{caught_animal}**을(를) 잡았습니다!\n판매 수익으로 **{reward:,}원**을 벌었습니다.", color=0x2ecc71)
        embed.set_footer(text=f"현재 서버 잔고: {new_money:,}원")
        await interaction.edit_original_response(content=None, embed=embed)
    else:
        damage_cost = random.randint(100, 1000)
        new_money = max(0, current_money - damage_cost)
        set_user_data(user_money, g_id, u_id, new_money)

        embed = discord.Embed(title="⚠️ 사냥 실패 및 부상", description=f"동물을 놓치고 상처를 입었습니다...\n치료비로 **{damage_cost:,}원**이 지출되었습니다.", color=0xe74c3c)
        embed.set_footer(text=f"현재 서버 잔고: {new_money:,}원")
        await interaction.edit_original_response(content=None, embed=embed)

@bot.tree.command(name="동물가격표", description="사냥할 수 있는 동물들의 가격과 난이도를 확인합니다.")
async def 동물가격표(interaction: discord.Interaction):
    embed = discord.Embed(title="📜 사냥 동물 시세표 (전체 60종)", description="희귀한 동물일수록 잡을 확률이 낮지만 훨씬 비쌉니다.\n" + "─" * 20, color=0xf1c40f)
    
    current_text = ""
    field_count = 1
    
    for i, (name, info) in enumerate(HUNT_DATA.items()):
        if info["chance"] >= 100: difficulty = "🟢 쉬움"
        elif info["chance"] >= 50: difficulty = "🟡 보통"
        elif info["chance"] >= 30: difficulty = "🟠 높음"
        else: difficulty = "🔴 매우어려움"
        
        current_text += f"{name} | **{info['price']:,}원** | {difficulty}\n"
        if (i + 1) % 12 == 0 or (i + 1) == len(HUNT_DATA):
            embed.add_field(name=f"목록 ({field_count}/5)", value=current_text, inline=False)
            current_text = ""
            field_count += 1

    embed.set_footer(text="주의: 사냥 실패 시 치료비가 발생할 수 있습니다. | 총 60종의 생명체가 서식 중")
    await interaction.response.send_message(embed=embed)

# =====================
# 명령어: 퍼니퀴즈 / 야그만해
# =====================
@bot.tree.command(name="퍼니퀴즈", description="10문제 중 가장 많이 맞힌 사람이 3만 원을 획득합니다! (30초, 3단계 힌트)")
async def 가사빈칸(interaction: discord.Interaction):
    g_id = interaction.guild_id
    if active_games.get(g_id):
        return await interaction.response.send_message("❌ 이 서버에서 이미 게임이 진행 중입니다!", ephemeral=True)

    active_games[g_id] = True
    lyrics_pool = [
        {"quiz": "동해 물과 [ ?? ]산이 마르고 닳도록", "answer": "백두"},
        {"quiz": "아름다운 이 땅에 금수강산에 [ ?? ] 할아버지가 터 잡으시고", "answer": "단군"},
        {"quiz": "나의 살던 [ ?? ]은 꽃 피는 산골", "answer": "고향"},
        {"quiz": "보고 싶다 보고 싶다 이런 내가 [ ?? ]", "answer": "미워"}
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
        
        chosung_hint = get_chosung(answer_raw)
        hint2_text = answer_raw[0] + "○" * (len(answer_raw) - 1)
        hint3_text = answer_raw[:2] + "○" * (len(answer_raw) - 2) if len(answer_raw) > 1 else answer_raw

        embed = discord.Embed(title=f"🎵 가사 빈칸 게임 ({i}/10 라운드)", description=f"**문제:** `{quiz_text}`\n\n⏱️ **제한 시간:** 30초", color=0x00ffcc)
        quiz_msg = await interaction.channel.send(embed=embed)

        def check(m):
            return m.channel == interaction.channel and m.content.replace(" ", "") == answer_text and not m.author.bot

        final_answer_msg = None
        try:
            final_answer_msg = await bot.wait_for('message', check=check, timeout=10.0)
        except asyncio.TimeoutError:
            if not active_games.get(g_id): return
            hint1_embed = discord.Embed(title=f"🎵 가사 빈칸 게임 ({i}/10 라운드) - 1차 힌트", description=f"**문제:** `{quiz_text}`\n💡 **초성 힌트:** `{chosung_hint}`\n\n⏱️ **남은 시간:** 20초", color=0xffff00)
            await quiz_msg.edit(embed=hint1_embed)
            try:
                final_answer_msg = await bot.wait_for('message', check=check, timeout=5.0)
            except asyncio.TimeoutError:
                if not active_games.get(g_id): return
                hint2_embed = discord.Embed(title=f"🎵 가사 빈칸 게임 ({i}/10 라운드) - 2차 힌트", description=f"**문제:** `{quiz_text}`\n💡 **초성:** `{chosung_hint}`\n🎁 **첫 글자 오픈:** `{hint2_text}`\n\n⏱️ **남은 시간:** 15초", color=0xffa500)
                await quiz_msg.edit(embed=hint2_embed)
                try:
                    final_answer_msg = await bot.wait_for('message', check=check, timeout=5.0)
                except asyncio.TimeoutError:
                    if not active_games.get(g_id): return
                    hint3_embed = discord.Embed(title=f"🎵 가사 빈칸 게임 ({i}/10 라운드) - 3차 힌트", description=f"**문제:** `{quiz_text}`\n💡 **초성:** `{chosung_hint}`\n🎁 **두 글자 오픈:** `{hint3_text}`\n\n⏱️ **마지막 10초!**", color=0xff4500)
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

@bot.tree.command(name="야그만해", description="이 서버에서 진행 중인 퀴즈를 중단합니다.")
async def 중단(interaction: discord.Interaction):
    g_id = interaction.guild_id
    if active_games.get(g_id):
        active_games[g_id] = False
        await interaction.response.send_message("🛑 이 서버의 게임 중단 요청을 완료했습니다.")
    else:
        await interaction.response.send_message("❓ 현재 이 서버에서 진행 중인 게임이 없습니다.", ephemeral=True)

# =====================
# 음성 및 노래 재생 관련
# =====================
import traceback

@bot.tree.command(name="야드루와", description="봇을 현재 음성 채널에 참여시킵니다.")
async def 야드루와(interaction: discord.Interaction):
    # 1. 음성 채널에 없는 경우는 즉시 처리 가능하므로 바로 응답 (3초 미만 소요)
    if not interaction.user.voice:
        return await interaction.response.send_message("❌ 먼저 음성채널에 들어가 주세요", ephemeral=True)

    # 2. 음성 채널 연결은 시간이 걸릴 수 있으므로 디스코드에게 시간 연장 요청! ("봇이 생각 중..." 상태가 됩니다)
    await interaction.response.defer(ephemeral=True)

    try:
        voice_client = interaction.guild.voice_client
        if voice_client:
            if voice_client.channel != interaction.user.voice.channel:
                await voice_client.move_to(interaction.user.voice.channel)
        else:
            await interaction.user.voice.channel.connect()
        
        # ⭐ 중요: defer()를 썼을 때는 send_message 대신 followup.send를 사용해야 합니다.
        await interaction.followup.send("🎧 들어왔어요!")

    except Exception as e:
        traceback.print_exc()
        error_msg = f"❌ 오류 종류: {type(e).__name__}\n❌ 오류 내용: {str(e)}"
        # ⭐ 에러 발생 시에도 마찬가지로 followup.send를 사용합니다.
        await interaction.followup.send(error_msg)

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
# 명령어: 야청소해
# =====================
@bot.tree.command(name="야청소해", description="메시지를 지정한 개수만큼 삭제합니다.")
@app_commands.describe(amount="삭제할 메시지 개수 또는 '전부' 입력")
@app_commands.checks.has_permissions(manage_messages=True)
async def 청소(interaction: discord.Interaction, amount: str):
    if amount == "전부":
        limit = 999
    else:
        try:
            limit = int(amount)
            if limit <= 0:
                return await interaction.response.send_message("❌ 1개 이상의 숫자를 입력해야 합니다.", ephemeral=True)
            if limit > 999: limit = 999 
        except ValueError:
            return await interaction.response.send_message("❌ 숫자를 입력하거나 '전부'라고 입력해 주세요.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=limit)
    await interaction.followup.send(f"🧹 **{len(deleted)}개**의 메시지를 깨끗하게 치웠어요!", ephemeral=True)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("🚫 이 명령어를 사용하려면 **메시지 관리** 권한이 필요합니다!", ephemeral=True)
    else:
        print(f"Error: {error}")

# =====================
# 명령어: 야도와줘 (슬래시 커맨드 통합 가이드)
# =====================
@bot.tree.command(name="야도와줘", description="봇의 모든 명령어 목록을 확인합니다.")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="🤖 봇 명령어 가이드", description="이 봇의 데이터(돈, 낚시 등)는 **각 서버별로 독립적으로 관리**됩니다.", color=0x3498db)

    embed.add_field(
        name="🔮 일상 & 운세",
        value="`/오늘의운세`: 하루 한 번 나의 운세를 확인합니다.\n`/궁합 @상대방`: 멘션한 유저와 오늘의 궁합을 봅니다.",
        inline=False
    )
    embed.add_field(
        name="💰 경제 & 낚시 & 사냥",
        value="`/돈내놔`: 하루 3회, 이 서버 전용 지원금을 받습니다.\n`/잔고`: 이 서버의 지갑에 있는 돈을 확인합니다.\n`/낚시`: 물고기를 잡아 보관함에 저장합니다.\n`/보관함`: 이 서버에서 잡은 내 물고기 목록을 봅니다.\n`/물고기가격`: 어떤 물고기가 비싼지 시세를 확인합니다.\n`/팔기`: 물고기를 판매합니다. (이름/갯수 기입 가능)\n`/사냥`: 야생 동물을 사냥해 즉시 돈을 멉니다.\n`/동물가격표`: 사냥 등급 및 보상을 조회합니다.",
        inline=False
    )
    embed.add_field(
        name="🎮 미니게임 & 🎰 도박",
        value="`/퍼니퀴즈`: 가사 빈칸 맞히기! (우승 시 30,000원)\n`/야그만해`: 진행 중인 퀴즈를 즉시 중단합니다.\n`/홀짝 [금액] [홀/짝]`: 홀짝을 맞춰 돈을 두 배로!\n`/도박 [금액]`: 45% 확률로 배팅금의 2배를 얻습니다.\n`/로또`: 1,000원으로 인생 역전! (서버당 하루 15회)",
        inline=False
    )
    embed.add_field(
        name="🛠️ 관리 기능 & 🎶 음악 재생",
        value="`/야청소해 [숫자/전부]`: 메시지를 깔끔하게 지웁니다. (최대 999개)\n`/야드루와`: 봇을 내 음성 채널로 부릅니다.\n`/야재생해 [검색어/URL]`: 노래를 즉시 재생합니다.\n`/야기다려 [검색어]`: 노래를 대기열에 추가합니다.\n`/야목록`: 현재 대기열 목록을 확인합니다.\n`/야멈춰`: 중지 / `/야넘겨`: 다음 곡 / `/야꺼져`: 퇴장",
        inline=False
    )

    embed.set_footer(text=f"요청자: {interaction.user.display_name} | 데이터는 서버별로 저장됩니다.", icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=embed)

# =====================
# 실행
# =====================
bot.run(TOKEN)
