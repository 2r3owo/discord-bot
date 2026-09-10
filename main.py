import discord
from discord.ext import commands, tasks
import random
import yt_dlp
import asyncio
import os
from collections import deque
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify, render_template_string
from PIL import Image
import io
import base64
import threading
import secrets
import time
import uuid
from pathlib import Path

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

PORT = int(os.getenv("PORT", "8080"))
DRAW_URL = os.getenv("DRAW_URL", "http://localhost:8080").rstrip("/")

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

# 음악 상태창(서버별 1개)
music_status_messages = {}
music_now_playing = {}

# =====================
# YouTube 쿠키 설정 (Railway용)
# =====================
# Railway 서버에서는 내 PC의 Chrome 쿠키를 직접 읽을 수 없기 때문에
# Railway Variables의 YOUTUBE_COOKIES_B64 값을 사용해 쿠키 파일을 생성합니다.
YT_COOKIE_PATH = "/tmp/youtube_cookies.txt"

def setup_youtube_cookies():
    # 1순위: Railway Variables에 여러 조각으로 나눈 Base64 쿠키
    # 예: YOUTUBE_COOKIES_B64_1, YOUTUBE_COOKIES_B64_2, YOUTUBE_COOKIES_B64_3 ...
    cookie_parts = []
    i = 1
    while True:
        part = os.getenv(f"YOUTUBE_COOKIES_B64_{i}", "").strip()
        if not part:
            break
        cookie_parts.append(part)
        i += 1

    # 기존 YOUTUBE_COOKIES_B64도 계속 지원
    cookies_b64 = "".join(cookie_parts) if cookie_parts else os.getenv("YOUTUBE_COOKIES_B64", "").strip()
    if cookies_b64:
        try:
            cookie_bytes = base64.b64decode(cookies_b64, validate=True)

            # yt-dlp가 읽을 수 있는 Netscape/Mozilla 쿠키 파일인지 간단히 확인
            first_line = cookie_bytes.splitlines()[0].decode("utf-8", errors="ignore").strip() if cookie_bytes.splitlines() else ""
            if first_line not in ("# HTTP Cookie File", "# Netscape HTTP Cookie File"):
                print("⚠️ YOUTUBE_COOKIES_B64가 Netscape/Mozilla 쿠키 파일 형식이 아닙니다.")
                return None

            with open(YT_COOKIE_PATH, "wb") as f:
                f.write(cookie_bytes)

            print("🍪 YouTube 쿠키 로드 완료 (Railway Secret)")
            return YT_COOKIE_PATH

        except Exception as e:
            print(f"⚠️ YouTube 쿠키(Base64) 로드 실패: {e}")

    # 2순위: Railway Variable에 일반 텍스트로 넣은 쿠키
    cookies_text = os.getenv("YOUTUBE_COOKIES", "")
    if cookies_text.strip():
        try:
            # Railway에 \n 문자 그대로 들어온 경우 실제 줄바꿈으로 변환
            cookies_text = cookies_text.replace("\\n", "\n")
            first_line = cookies_text.splitlines()[0].strip() if cookies_text.splitlines() else ""

            if first_line not in ("# HTTP Cookie File", "# Netscape HTTP Cookie File"):
                print("⚠️ YOUTUBE_COOKIES가 Netscape/Mozilla 쿠키 파일 형식이 아닙니다.")
                return None

            with open(YT_COOKIE_PATH, "w", encoding="utf-8", newline="\n") as f:
                f.write(cookies_text)

            print("🍪 YouTube 쿠키 로드 완료 (Railway Variable)")
            return YT_COOKIE_PATH

        except Exception as e:
            print(f"⚠️ YouTube 쿠키 로드 실패: {e}")

    # 3순위: 프로젝트에 cookies.txt가 실제로 존재하는 경우
    if os.path.exists("cookies.txt"):
        print("🍪 로컬 cookies.txt 사용")
        return "cookies.txt"

    print("⚠️ YouTube 쿠키가 없습니다. Railway에서는 YOUTUBE_COOKIES_B64 설정이 필요할 수 있습니다.")
    return None


YT_COOKIE_FILE = setup_youtube_cookies()

# YDL 및 FFMPEG 옵션
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn', # 비디오는 빼고 오디오만!
}

YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': False,
    'default_search': 'auto',
    'nocheckcertificate': True,
    # YouTube 최신 JS challenge 대응
    'remote_components': {'ejs:github'},
    'js_runtimes': {'deno': {}},
}

# 쿠키는 필요한 방식에서만 사용합니다.
# web_embedded / web_safari / android_vr / tv 는 쿠키 없이 시도합니다.
YT_USER_AGENT = os.getenv("YOUTUBE_USER_AGENT", "").strip()


def make_youtube_options(mode, outtmpl):
    """YouTube 재생 방식별 yt-dlp 설정.

    최근 YouTube에서 tv_downgraded/web_safari/mweb 조합이
    "The page needs to be reloaded"를 반환하는 경우가 있어,
    일반 공개 영상은 쿠키 없이 default 클라이언트를 우선 사용합니다.
    """
    opts = dict(YDL_OPTIONS)
    opts['outtmpl'] = outtmpl
    opts['format'] = 'bestaudio/best'
    opts['noplaylist'] = True
    opts['quiet'] = True
    opts['no_warnings'] = False
    opts.pop('cookiefile', None)

    if YT_USER_AGENT:
        opts['http_headers'] = {
            'User-Agent': YT_USER_AGENT,
            'Referer': 'https://www.youtube.com/',
        }

    pot_url = os.getenv('YTDLP_POT_PROVIDER_URL', 'http://127.0.0.1:4416').strip()

    # 핵심: 최근 YouTube 문제를 피하기 위해 default를 우선 사용하고
    # 문제가 많은 tv_downgraded는 명시적으로 제외합니다.
    if mode == 'default_nocookie':
        opts['extractor_args'] = {
            'youtube': {
                'player_client': ['default', '-tv_downgraded', 'web_embedded'],
            },
        }
        return opts

    if mode == 'default_cookie':
        opts['extractor_args'] = {
            'youtube': {
                'player_client': ['default', '-tv_downgraded', 'web_embedded'],
            },
        }
        if YT_COOKIE_FILE:
            opts['cookiefile'] = YT_COOKIE_FILE
        return opts

    if mode == 'web_embedded':
        opts['extractor_args'] = {
            'youtube': {
                'player_client': ['web_embedded'],
            },
        }
        return opts

    if mode == 'android_vr':
        opts['extractor_args'] = {
            'youtube': {
                'player_client': ['android_vr'],
            },
        }
        opts['format'] = '18/bestaudio/best'
        return opts

    if mode == 'mweb_nocookie':
        opts['extractor_args'] = {
            'youtube': {
                'player_client': ['mweb'],
            },
            'youtubepot-bgutilhttp': {
                'base_url': pot_url,
            },
        }
        return opts

    raise ValueError(f'알 수 없는 YouTube 재생 방식: {mode}')

# 현재 yt-dlp / 쿠키 상태를 Railway 로그에서 바로 확인할 수 있게 합니다.
try:
    print(f"🧩 yt-dlp 버전: {getattr(yt_dlp.version, '__version__', 'unknown')}")
except Exception:
    print("🧩 yt-dlp 버전 확인 실패")
print(f"🍪 YouTube 쿠키: {'설정됨' if YT_COOKIE_FILE else '없음'}")


# =====================
# 보조 함수 (대기열 관리) - 수정 및 보완
# =====================
# =====================
# FFmpeg 재생 보조 함수
# =====================
def _cleanup_file(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
            print(f"🧹 임시 음원 파일 삭제: {path}")
    except Exception as e:
        print(f"⚠️ 임시 파일 삭제 실패: {e}")


def download_song(search_or_url, guild_id):
    """YouTube 음원을 로컬 /tmp 파일로 다운로드합니다.

    YouTube가 클라이언트/쿠키/PO Token에 따라 응답을 다르게 주기 때문에
    현재 권장 순서대로 여러 클라이언트를 자동 재시도합니다.
    """
    query = search_or_url if search_or_url.startswith(("https://", "http://")) else f"ytsearch:{search_or_url}"
    unique = uuid.uuid4().hex
    outtmpl = f"/tmp/discord_music_{guild_id}_{unique}.%(ext)s"

    # 최근 YouTube에서 mweb + 계정 쿠키 조합으로 발생하는
    # "The page needs to be reloaded"를 피하기 위해 쿠키 없는 mweb부터 시작합니다.
    # YouTube가 최근 android_vr/web 계열의 일반 오디오 포맷을
    # 더 자주 제한하고 있어, 현재 비교적 안전한 경로를 먼저 시도합니다.
    # 특히 android_vr의 format 18은 최근에도 별도 GVS PO Token 없이
    # 남아 있는 경우가 있어 오디오 추출용 fallback으로 사용합니다.
    modes = [
        # 1순위: 공개 영상은 쿠키 없이 default 클라이언트 사용
        'default_nocookie',
        # 2순위: embedded fallback
        'web_embedded',
        # 3순위: android_vr format 18 fallback
        'android_vr',
        # 4순위: PO Token을 사용하는 mweb
        'mweb_nocookie',
        # 5순위: 마지막에만 기존 쿠키 사용
        'default_cookie',
    ]

    last_error = None

    for mode in modes:
        try:
            print(f"🔎 YouTube 재생 방식 시도: {mode}")
            opts = make_youtube_options(mode, outtmpl)

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(query, download=False)

                if info and 'entries' in info:
                    entries = [e for e in info.get('entries', []) if e]
                    if not entries:
                        raise RuntimeError("검색 결과에서 재생할 영상을 찾지 못했습니다.")
                    info = entries[0]

                if not info:
                    raise RuntimeError("YouTube에서 영상 정보를 받지 못했습니다.")

                title = info.get('title', '알 수 없는 곡')
                print(f"⬇️ 음원 다운로드 시작 ({mode}): {title}")
                ydl.process_info(info)
                filepath = ydl.prepare_filename(info)

            # 컨테이너/확장자 변경 등으로 prepare_filename과 실제 파일명이
            # 달라지는 경우를 대비합니다.
            if not os.path.exists(filepath):
                candidates = list(Path('/tmp').glob(f"discord_music_{guild_id}_{unique}.*"))
                if candidates:
                    filepath = str(candidates[0])
                else:
                    raise FileNotFoundError(f"다운로드 파일을 찾지 못했습니다: {filepath}")

            print(f"✅ 음원 다운로드 완료 ({mode}): {filepath}")
            return filepath, title

        except Exception as e:
            last_error = e
            error_text = str(e).replace('\n', ' ')
            print(f"⚠️ YouTube 방식 {mode} 실패: {error_text[:500]}")

            for candidate in Path('/tmp').glob(f"discord_music_{guild_id}_{unique}.*"):
                try:
                    candidate.unlink()
                except Exception:
                    pass

    raise RuntimeError(
        "YouTube에서 음원을 가져오지 못했습니다. "
        f"마지막 시도 오류: {last_error}"
    )


def make_ffmpeg_source(filepath):
    """다운로드된 로컬 음원 파일을 Discord용 PCM 오디오로 재생합니다."""
    return discord.FFmpegPCMAudio(
        filepath,
        executable="ffmpeg",
        before_options='-nostdin',
        options='-vn'
    )


async def update_music_status(guild: discord.Guild, channel: discord.abc.Messageable):
    """채널에 남아있는 음악 상태 Embed를 생성/갱신합니다.

    재생 중인 곡과 다음 곡들을 한눈에 보여주며, 메시지를 삭제하지 않고
    같은 상태창 하나를 계속 수정해서 채널이 지저분해지지 않게 합니다.
    """
    guild_id = guild.id
    current = music_now_playing.get(guild_id)
    queue = queues.get(guild_id, deque())

    embed = discord.Embed(
        title="🎶 지금 재생 중",
        description=(f"**{current}**" if current else "현재 재생 중인 곡이 없어요."),
        color=discord.Color.blurple()
    )

    if queue:
        lines = []
        for i, song in enumerate(list(queue)[:10], 1):
            lines.append(f"`{i:02d}`  {song['title']}")
        if len(queue) > 10:
            lines.append(f"… 외 {len(queue) - 10}곡")
        embed.add_field(name="📥 다음 곡", value="\n".join(lines), inline=False)
        embed.set_footer(text=f"대기열 {len(queue)}곡 · /야목록으로 전체 보기")
    else:
        embed.add_field(name="📥 다음 곡", value="대기 중인 곡이 없어요.", inline=False)
        embed.set_footer(text="대기열에 곡을 추가하면 여기에 표시돼요.")

    message = music_status_messages.get(guild_id)
    try:
        if message:
            await message.edit(embed=embed)
        else:
            message = await channel.send(embed=embed)
            music_status_messages[guild_id] = message
    except discord.NotFound:
        try:
            message = await channel.send(embed=embed)
            music_status_messages[guild_id] = message
        except Exception as e:
            print(f"⚠️ 음악 상태창 생성 실패: {e!r}")
    except discord.Forbidden as e:
        print(f"⚠️ 음악 상태창 권한 부족: {e!r}")
    except Exception as e:
        print(f"⚠️ 음악 상태창 갱신 실패: {e!r}")


def schedule_music_status(interaction: discord.Interaction):
    """음악 콜백에서도 안전하게 상태창을 갱신합니다."""
    try:
        coro = update_music_status(interaction.guild, interaction.channel)
        asyncio.run_coroutine_threadsafe(coro, bot.loop)
    except Exception as e:
        print(f"⚠️ 음악 상태창 예약 실패: {e!r}")


def check_queue(interaction: discord.Interaction):
    """노래 재생이 끝나면 다음 곡을 재생합니다."""
    guild_id = interaction.guild.id

    if guild_id in queues and queues[guild_id]:
        next_song = queues[guild_id].popleft()
        music_now_playing[guild_id] = next_song['title']
        filepath = next_song['filepath']
        source = make_ffmpeg_source(filepath)

        def _after_next(error):
            if error:
                print(f"❌ FFmpeg 재생 오류(대기열): {error!r}")
            _cleanup_file(filepath)
            check_queue(interaction)

        try:
            interaction.guild.voice_client.play(source, after=_after_next)
            schedule_music_status(interaction)
        except Exception as e:
            print(f"❌ 다음 곡 재생 시작 실패: {e!r}")
            _cleanup_file(filepath)
            check_queue(interaction)
    else:
        if guild_id in queues:
            del queues[guild_id]
        music_now_playing.pop(guild_id, None)
        schedule_music_status(interaction)

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
# 음성 및 노래 재생 관련 (버튼형 음악 플레이어)
# =====================

# 반복 모드: off / one / all
music_repeat_mode = {}
# 현재 재생 곡 정보: {guild_id: {'title': ..., 'filepath': ..., 'query': ...}}
music_current_song = {}
# 이전 곡 기록: {guild_id: [song_dict, ...]}
music_history = {}
# 현재 재생이 '다음' 버튼에 의해 강제로 넘어가는지 표시
music_skip_requested = set()
# 기존 재생을 교체/퇴장할 때 이전 after 콜백이 새 곡 상태를 건드리지 않도록 보호
music_ignore_after = set()


def repeat_label(guild_id):
    mode = music_repeat_mode.get(guild_id, 'off')
    return {'off': '꺼짐', 'one': '한 곡', 'all': '전체'}.get(mode, '꺼짐')


def _song_title(song):
    return song.get('title', '알 수 없는 곡') if song else '알 수 없는 곡'


async def update_music_status(guild: discord.Guild, channel: discord.abc.Messageable):
    """채널에 남겨두는 음악 플레이어 패널을 갱신합니다."""
    guild_id = guild.id
    current_song = music_current_song.get(guild_id)
    current = _song_title(current_song) if current_song else music_now_playing.get(guild_id)
    queue = queues.get(guild_id, deque())
    vc = guild.voice_client

    if vc and vc.is_paused():
        state_text = "⏸️ 일시정지됨"
    elif vc and vc.is_playing():
        state_text = "▶️ 재생 중"
    else:
        state_text = "⏹️ 재생 대기"

    embed = discord.Embed(
        title="🎶  하치와래 MUSIC",
        description=f"**{current or '재생할 곡이 없어요.'}**\n{state_text}",
        color=discord.Color.blurple()
    )

    if queue:
        lines = []
        for i, song in enumerate(list(queue)[:8], 1):
            lines.append(f"`{i:02d}`  {song['title']}")
        if len(queue) > 8:
            lines.append(f"… 외 {len(queue) - 8}곡")
        embed.add_field(name="📥 다음 곡", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="📥 다음 곡", value="아직 대기 중인 곡이 없어요.", inline=False)

    embed.set_footer(text=f"대기열 {len(queue)}곡  ·  🔁 반복 {repeat_label(guild_id)}")

    view = MusicPlayerView()
    message = music_status_messages.get(guild_id)
    try:
        if message:
            await message.edit(embed=embed, view=view)
        else:
            message = await channel.send(embed=embed, view=view)
            music_status_messages[guild_id] = message
    except discord.NotFound:
        try:
            message = await channel.send(embed=embed, view=view)
            music_status_messages[guild_id] = message
        except Exception as e:
            print(f"⚠️ 음악 플레이어 생성 실패: {e!r}")
    except discord.Forbidden as e:
        print(f"⚠️ 음악 플레이어 권한 부족: {e!r}")
    except Exception as e:
        print(f"⚠️ 음악 플레이어 갱신 실패: {e!r}")


def schedule_music_status(guild: discord.Guild, channel: discord.abc.Messageable):
    try:
        coro = update_music_status(guild, channel)
        asyncio.run_coroutine_threadsafe(coro, bot.loop)
    except Exception as e:
        print(f"⚠️ 음악 플레이어 갱신 예약 실패: {e!r}")


def _play_song_now(guild: discord.Guild, song, channel):
    """동기적인 FFmpeg play 시작 보조 함수."""
    vc = guild.voice_client
    if not vc:
        return False

    filepath = song['filepath']
    source = make_ffmpeg_source(filepath)
    guild_id = guild.id
    music_current_song[guild_id] = song
    music_now_playing[guild_id] = song['title']

    def _after(error):
        if error:
            print(f"❌ FFmpeg 재생 오류: {error!r}")
        if guild_id in music_ignore_after:
            music_ignore_after.discard(guild_id)
            _cleanup_file(song.get('filepath'))
            return
        handle_song_finished(guild, channel, song)

    vc.play(source, after=_after)
    schedule_music_status(guild, channel)
    return True


def handle_song_finished(guild: discord.Guild, channel: discord.abc.Messageable, finished_song):
    """현재 곡이 끝났을 때 반복/대기열을 처리합니다."""
    guild_id = guild.id
    forced_skip = guild_id in music_skip_requested
    music_skip_requested.discard(guild_id)
    mode = music_repeat_mode.get(guild_id, 'off')

    # '한 곡 반복'은 일반적으로 끝났을 때만 반복하고, 다음 버튼으로 넘기면 반복하지 않습니다.
    if mode == 'one' and not forced_skip:
        try:
            _play_song_now(guild, dict(finished_song), channel)
            return
        except Exception as e:
            print(f"❌ 한 곡 반복 재생 실패: {e!r}")

    # 전체 반복은 끝난 곡을 대기열 맨 뒤로 보냅니다.
    if mode == 'all':
        queues.setdefault(guild_id, deque()).append(dict(finished_song))

    _cleanup_file(finished_song.get('filepath'))
    music_history.setdefault(guild_id, []).append(dict(finished_song))
    music_history[guild_id] = music_history[guild_id][-20:]

    if queues.get(guild_id):
        next_song = queues[guild_id].popleft()
        try:
            _play_song_now(guild, next_song, channel)
        except Exception as e:
            print(f"❌ 다음 곡 재생 실패: {e!r}")
            _cleanup_file(next_song.get('filepath'))
            handle_song_finished(guild, channel, next_song)
    else:
        music_current_song.pop(guild_id, None)
        music_now_playing.pop(guild_id, None)
        schedule_music_status(guild, channel)


# 기존 코드와의 호환용
# (다른 곳에서 check_queue를 호출해도 버튼형 플레이어와 함께 동작하도록 유지)
def check_queue(interaction: discord.Interaction):
    guild = interaction.guild
    if guild:
        handle_song_finished(guild, interaction.channel, music_current_song.get(guild.id, {}))


class AddSongModal(discord.ui.Modal, title="🎵 노래 추가"):
    search = discord.ui.TextInput(
        label="노래 제목 또는 YouTube 링크",
        placeholder="예: BABYMONSTER Really Like You",
        required=True,
        max_length=200
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.user.voice:
            return await interaction.response.send_message("❌ 먼저 음성채널에 들어가 주세요.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild:
            return await interaction.followup.send("❌ 서버에서만 사용할 수 있어요.", ephemeral=True)

        try:
            if not guild.voice_client:
                await interaction.user.voice.channel.connect(timeout=60.0, reconnect=True)
            elif guild.voice_client.channel != interaction.user.voice.channel:
                await guild.voice_client.move_to(interaction.user.voice.channel)

            loop = asyncio.get_event_loop()
            filepath, title = await loop.run_in_executor(
                None, lambda: download_song(str(self.search.value), guild.id)
            )
            song = {'filepath': filepath, 'title': title, 'query': str(self.search.value)}

            queues.setdefault(guild.id, deque())
            if guild.voice_client.is_playing() or guild.voice_client.is_paused():
                queues[guild.id].append(song)
            else:
                _play_song_now(guild, song, interaction.channel)

            await update_music_status(guild, interaction.channel)
            await interaction.followup.send(f"✅ **{title}** 을(를) {'대기열에 추가했어요!' if len(queues[guild.id]) else '재생했어요!'}", ephemeral=True)
        except Exception as e:
            print(f"❌ 버튼 노래 추가 오류: {e!r}")
            await interaction.followup.send(f"❌ 재생 중 오류 발생: {e}", ephemeral=True)


class MusicPlayerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _voice_check(self, interaction):
        if not interaction.user.voice:
            await interaction.response.send_message("❌ 먼저 음성채널에 들어가 주세요.", ephemeral=True)
            return False
        if not interaction.guild or not interaction.guild.voice_client:
            await interaction.response.send_message("❌ 봇이 음성채널에 없어요.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="", emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="music_stop")
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._voice_check(interaction): return
        guild = interaction.guild
        guild_id = guild.id
        queues.setdefault(guild_id, deque()).clear()
        music_skip_requested.add(guild_id)
        if guild.voice_client.is_playing() or guild.voice_client.is_paused():
            guild.voice_client.stop()
        music_current_song.pop(guild_id, None)
        music_now_playing.pop(guild_id, None)
        music_repeat_mode[guild_id] = 'off'
        await update_music_status(guild, interaction.channel)
        await interaction.response.send_message("⏹️ 재생을 정지했어요.", ephemeral=True)

    @discord.ui.button(label="", emoji="⏮️", style=discord.ButtonStyle.secondary, custom_id="music_previous")
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._voice_check(interaction): return
        guild = interaction.guild
        history = music_history.get(guild.id, [])
        if not history:
            return await interaction.response.send_message("❌ 이전 곡이 없어요.", ephemeral=True)
        old = history.pop()
        query = old.get('query')
        if not query:
            return await interaction.response.send_message("❌ 이전 곡 정보를 찾을 수 없어요.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            if guild.voice_client.is_playing() or guild.voice_client.is_paused():
                music_ignore_after.add(guild.id)
                music_skip_requested.discard(guild.id)
                guild.voice_client.stop()
            loop = asyncio.get_event_loop()
            filepath, title = await loop.run_in_executor(None, lambda: download_song(query, guild.id))
            song = {'filepath': filepath, 'title': title, 'query': query}
            _play_song_now(guild, song, interaction.channel)
            await update_music_status(guild, interaction.channel)
            await interaction.followup.send(f"⏮️ 이전 곡: **{title}**", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 이전 곡 재생 실패: {e}", ephemeral=True)

    @discord.ui.button(label="", emoji="⏯️", style=discord.ButtonStyle.secondary, custom_id="music_pause")
    async def pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._voice_check(interaction): return
        vc = interaction.guild.voice_client
        if vc.is_playing():
            vc.pause()
            msg = "⏸️ 일시정지했어요."
        elif vc.is_paused():
            vc.resume()
            msg = "▶️ 다시 재생했어요."
        else:
            msg = "❌ 재생 중인 곡이 없어요."
        await update_music_status(interaction.guild, interaction.channel)
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="", emoji="⏭️", style=discord.ButtonStyle.success, custom_id="music_next")
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._voice_check(interaction): return
        vc = interaction.guild.voice_client
        if not (vc.is_playing() or vc.is_paused()):
            return await interaction.response.send_message("❌ 넘길 노래가 없어요.", ephemeral=True)
        music_skip_requested.add(interaction.guild.id)
        vc.stop()
        await interaction.response.send_message("⏭️ 다음 곡으로 넘겼어요.", ephemeral=True)

    @discord.ui.button(label="", emoji="🔀", style=discord.ButtonStyle.secondary, custom_id="music_shuffle")
    async def shuffle(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._voice_check(interaction): return
        q = queues.get(interaction.guild.id)
        if not q or len(q) < 2:
            return await interaction.response.send_message("❌ 섞을 대기열이 2곡 이상 필요해요.", ephemeral=True)
        items = list(q)
        random.shuffle(items)
        queues[interaction.guild.id] = deque(items)
        await update_music_status(interaction.guild, interaction.channel)
        await interaction.response.send_message("🔀 대기열을 섞었어요!", ephemeral=True)

    @discord.ui.button(label="", emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="music_repeat")
    async def repeat(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._voice_check(interaction): return
        gid = interaction.guild.id
        mode = music_repeat_mode.get(gid, 'off')
        music_repeat_mode[gid] = {'off': 'one', 'one': 'all', 'all': 'off'}[mode]
        await update_music_status(interaction.guild, interaction.channel)
        await interaction.response.send_message(f"🔁 반복: **{repeat_label(gid)}**", ephemeral=True)

    @discord.ui.button(label="", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="music_queue")
    async def queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        gid = interaction.guild.id
        q = queues.get(gid, deque())
        current = music_current_song.get(gid)
        embed = discord.Embed(title="📋 음악 대기열", color=discord.Color.blurple())
        if current:
            embed.add_field(name="▶️ 현재 재생", value=current['title'], inline=False)
        if q:
            text = "\n".join(f"`{i:02d}` {song['title']}" for i, song in enumerate(q, 1))
            embed.add_field(name="📥 다음 곡", value=text[:4000], inline=False)
        else:
            embed.add_field(name="📥 다음 곡", value="대기열이 비어 있어요.", inline=False)
        embed.set_footer(text=f"반복 {repeat_label(gid)}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="", emoji="➕", style=discord.ButtonStyle.primary, custom_id="music_add")
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddSongModal())

    @discord.ui.button(label="", emoji="🗑️", style=discord.ButtonStyle.secondary, custom_id="music_clear_queue")
    async def clear_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        gid = interaction.guild.id
        q = queues.get(gid)
        if not q:
            return await interaction.response.send_message("📁 대기열이 이미 비어 있어요.", ephemeral=True)
        count = len(q)
        while q:
            song = q.popleft()
            _cleanup_file(song.get('filepath'))
        await update_music_status(interaction.guild, interaction.channel)
        await interaction.response.send_message(f"🗑️ 대기열 {count}곡을 비웠어요.", ephemeral=True)

    @discord.ui.button(label="", emoji="⭐", style=discord.ButtonStyle.secondary, custom_id="music_info")
    async def info(self, interaction: discord.Interaction, button: discord.ui.Button):
        gid = interaction.guild.id
        embed = discord.Embed(
            title="🎶 음악 플레이어",
            description="버튼으로 음악을 편하게 조작할 수 있어요!",
            color=discord.Color.blurple()
        )
        embed.add_field(name="⏯️ 재생", value="일시정지 / 다시 재생", inline=True)
        embed.add_field(name="🔁 반복", value=f"현재: {repeat_label(gid)}", inline=True)
        embed.add_field(name="🔀 셔플", value="대기열 섞기", inline=True)
        embed.set_footer(text="➕ 버튼을 누르면 노래를 바로 추가할 수 있어요.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


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
        await update_music_status(interaction.guild, interaction.channel)
        await interaction.response.send_message("🎧 들어왔어요! 아래 음악 플레이어를 사용해 주세요.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ 접속 중 오류 발생: {e}", ephemeral=True)


@bot.tree.command(name="야꺼져", description="봇을 음성 채널에서 퇴장시킵니다.")
async def 야꺼져(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        music_skip_requested.add(interaction.guild.id)
        if interaction.guild.voice_client.is_playing() or interaction.guild.voice_client.is_paused():
            interaction.guild.voice_client.stop()
        await interaction.guild.voice_client.disconnect()
        music_current_song.pop(interaction.guild.id, None)
        music_now_playing.pop(interaction.guild.id, None)
        queues.setdefault(interaction.guild.id, deque()).clear()
        await update_music_status(interaction.guild, interaction.channel)
        await interaction.response.send_message("👋 나갈게요!", ephemeral=True)
    else:
        await interaction.response.send_message("❌ 저는 지금 음성 채널에 있지 않아요.", ephemeral=True)


@bot.tree.command(name="야재생해", description="현재 곡을 중단하고 새로운 곡을 즉시 재생합니다.")
async def 야재생해(interaction: discord.Interaction, search: str):
    if not interaction.user.voice:
        return await interaction.response.send_message("❌ 음성채널에 먼저 들어가 주세요", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    if not interaction.guild.voice_client:
        await interaction.user.voice.channel.connect(timeout=60.0, reconnect=True)
    try:
        guild = interaction.guild
        queues[guild.id] = deque()
        if guild.voice_client.is_playing() or guild.voice_client.is_paused():
            music_skip_requested.add(guild.id)
            guild.voice_client.stop()
        loop = asyncio.get_event_loop()
        filepath, title = await loop.run_in_executor(None, lambda: download_song(search, guild.id))
        song = {'filepath': filepath, 'title': title, 'query': search}
        _play_song_now(guild, song, interaction.channel)
        await update_music_status(guild, interaction.channel)
        await interaction.followup.send("🎵 재생을 시작했어요! 아래 버튼으로 조작해 주세요.", ephemeral=True)
    except Exception as e:
        print(f"❌ /야재생해 오류: {e!r}")
        await interaction.followup.send(f"❌ 재생 중 오류 발생: {e}", ephemeral=True)


@bot.tree.command(name="야기다려", description="노래를 대기열에 추가합니다.")
async def 야기다려(interaction: discord.Interaction, search: str):
    if not interaction.user.voice:
        return await interaction.response.send_message("❌ 음성채널에 먼저 들어가 주세요", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    if not interaction.guild.voice_client:
        await interaction.user.voice.channel.connect(timeout=60.0, reconnect=True)
    try:
        guild = interaction.guild
        loop = asyncio.get_event_loop()
        filepath, title = await loop.run_in_executor(None, lambda: download_song(search, guild.id))
        song = {'filepath': filepath, 'title': title, 'query': search}
        queues.setdefault(guild.id, deque())
        if guild.voice_client.is_playing() or guild.voice_client.is_paused():
            queues[guild.id].append(song)
            message = f"📥 **{title}** 을(를) 대기열에 넣었어요!"
        else:
            _play_song_now(guild, song, interaction.channel)
            message = f"🎵 **{title}** 을(를) 재생했어요!"
        await update_music_status(guild, interaction.channel)
        await interaction.followup.send(message, ephemeral=True)
    except Exception as e:
        print(f"❌ /야기다려 오류: {e!r}")
        await interaction.followup.send(f"❌ 대기열 추가 중 오류 발생: {e}", ephemeral=True)


@bot.tree.command(name="야멈춰", description="재생 중인 노래를 중지합니다.")
async def 야멈춰(interaction: discord.Interaction):
    if interaction.guild.voice_client and (interaction.guild.voice_client.is_playing() or interaction.guild.voice_client.is_paused()):
        queues.setdefault(interaction.guild.id, deque()).clear()
        music_skip_requested.add(interaction.guild.id)
        interaction.guild.voice_client.stop()
        music_repeat_mode[interaction.guild.id] = 'off'
        await update_music_status(interaction.guild, interaction.channel)
        await interaction.response.send_message("⏹️ 재생을 중지했어요.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ 재생 중인 노래가 없어요.", ephemeral=True)


@bot.tree.command(name="야넘겨", description="현재 노래를 건너뛰고 다음 곡을 재생합니다.")
async def 야넘겨(interaction: discord.Interaction):
    if interaction.guild.voice_client and (interaction.guild.voice_client.is_playing() or interaction.guild.voice_client.is_paused()):
        music_skip_requested.add(interaction.guild.id)
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("⏭️ 다음 곡으로 넘겼어요!", ephemeral=True)
    else:
        await interaction.response.send_message("❌ 넘길 노래가 없습니다.", ephemeral=True)


@bot.tree.command(name="야목록", description="현재 노래 대기열을 확인합니다.")
async def 야목록(interaction: discord.Interaction):
    gid = interaction.guild.id
    q = queues.get(gid, deque())
    current = music_current_song.get(gid)
    embed = discord.Embed(title="📋 음악 대기열", color=discord.Color.blurple())
    if current:
        embed.add_field(name="▶️ 현재 재생", value=current['title'], inline=False)
    if q:
        lines = [f"`{i:02d}`  {song['title']}" for i, song in enumerate(q, 1)]
        embed.add_field(name="📥 다음 곡", value="\n".join(lines[:20]), inline=False)
        if len(lines) > 20:
            embed.set_footer(text=f"외 {len(lines) - 20}곡 · 반복 {repeat_label(gid)}")
        else:
            embed.set_footer(text=f"총 {len(lines)}곡 대기 중 · 반복 {repeat_label(gid)}")
    else:
        embed.add_field(name="📥 다음 곡", value="대기열이 비어 있어요.", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

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
              "`/팔기`: 물고기를 판매합니다. (이름/갯수를 넣으면 골라서 판매 가능!)\n"
              "`/사냥`: 동물들을 잡아 돈을 얻습니다.\n"
              "`/그림`: 웹 그림판을 열고 완성한 그림을 이 채널에 올립니다.\n"
              "`/그림대회`: 그림대회용 그림판을 엽니다.\n",
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
# 🎨 웹 그림판
# =====================
app = Flask(__name__)
draw_sessions = {}
DRAW_SESSION_TTL = 12 * 60 * 60
DRAW_MAX_BYTES = 8 * 1024 * 1024

DRAW_HTML = """
<!doctype html><html lang="ko"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Discord 그림판</title>
<style>
body{margin:0;background:#f3f4f6;font-family:Arial,sans-serif}
#bar{position:sticky;top:0;background:white;padding:10px;border-bottom:1px solid #ddd;z-index:2}
button,input{margin:3px;padding:7px}canvas{display:block;background:white;border:1px solid #ccc;margin:12px auto;max-width:calc(100% - 24px);touch-action:none}
</style></head><body>
<div id="bar">
<b>🎨 Discord 그림판</b><br>
<button onclick="tool='brush'">브러시</button><button onclick="tool='eraser'">지우개</button>
<button onclick="tool='line'">직선</button><button onclick="tool='rect'">사각형</button>
<button onclick="tool='circle'">원</button><button onclick="addText()">텍스트</button>
<input id="color" type="color" value="#000000">
크기 <input id="size" type="range" min="1" max="60" value="6">
투명도 <input id="alpha" type="range" min="1" max="100" value="100">
<button onclick="undo()">↩ 실행취소</button><button onclick="redo()">↪ 다시실행</button>
<button onclick="clearCanvas()">🗑 초기화</button><button onclick="finish()">📤 Discord에 올리기</button>
</div>
<canvas id="c" width="1000" height="700"></canvas>
<script>
const sid={{sid|tojson}}, c=document.getElementById('c'), x=c.getContext('2d');
let tool='brush',down=false,sx=0,sy=0,lx=0,ly=0,h=[],f=[];
x.fillStyle='#fff';x.fillRect(0,0,c.width,c.height);
function pos(e){let r=c.getBoundingClientRect();return{x:(e.clientX-r.left)*c.width/r.width,y:(e.clientY-r.top)*c.height/r.height}}
function state(){return c.toDataURL('image/png')}
function restore(s){let i=new Image();i.onload=()=>{x.clearRect(0,0,c.width,c.height);x.drawImage(i,0,0)};i.src=s}
function setup(){x.lineWidth=+size.value;x.globalAlpha=+alpha.value/100;x.lineCap='round';x.strokeStyle=color.value;x.fillStyle=color.value}
function start(e){e.preventDefault();h.push(state());if(h.length>30)h.shift();f=[];let p=pos(e);sx=lx=p.x;sy=ly=p.y;down=true}
function move(e){if(!down)return;e.preventDefault();let p=pos(e);setup();
 if(tool==='brush'||tool==='eraser'){x.globalCompositeOperation=tool==='eraser'?'destination-out':'source-over';x.beginPath();x.moveTo(lx,ly);x.lineTo(p.x,p.y);x.stroke();x.globalCompositeOperation='source-over';lx=p.x;ly=p.y;return}
 restore(h[h.length-1]);setup();
 if(tool==='line'){x.beginPath();x.moveTo(sx,sy);x.lineTo(p.x,p.y);x.stroke()}
 if(tool==='rect')x.strokeRect(sx,sy,p.x-sx,p.y-sy);
 if(tool==='circle'){let rx=(p.x-sx)/2,ry=(p.y-sy)/2;x.beginPath();x.ellipse(sx+rx,sy+ry,Math.abs(rx),Math.abs(ry),0,0,Math.PI*2);x.stroke()}
}
function end(){down=false}
function addText(){let t=prompt('텍스트를 입력하세요');if(!t)return;h.push(state());setup();x.font=(+size.value*4)+'px Arial';x.fillText(t,50,100)}
function undo(){if(!h.length)return;f.push(state());let s=h.pop();if(h.length)restore(s);else{ x.clearRect(0,0,c.width,c.height);x.fillStyle='#fff';x.fillRect(0,0,c.width,c.height)}}
function redo(){if(!f.length)return;h.push(state());restore(f.pop())}
function clearCanvas(){h.push(state());f=[];x.clearRect(0,0,c.width,c.height);x.fillStyle='#fff';x.fillRect(0,0,c.width,c.height)}
async function finish(){let r=await fetch('/draw/'+sid+'/finish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image:state()})});let j=await r.json();alert(j.ok?'Discord 채널에 업로드했습니다!':(j.error||'업로드 실패'))}
c.addEventListener('pointerdown',start);c.addEventListener('pointermove',move);c.addEventListener('pointerup',end);c.addEventListener('pointercancel',end);
</script></body></html>
"""

def cleanup_draw_sessions():
    now=time.time()
    for sid in list(draw_sessions):
        if now-draw_sessions[sid]["created"] > DRAW_SESSION_TTL:
            draw_sessions.pop(sid,None)

@app.route("/draw/<sid>")
def draw_page(sid):
    cleanup_draw_sessions()
    if sid not in draw_sessions:
        return "그림판 세션이 만료되었습니다.",404
    return render_template_string(DRAW_HTML,sid=sid)

@app.route("/draw/<sid>/finish",methods=["POST"])
def draw_finish(sid):
    cleanup_draw_sessions()
    session=draw_sessions.get(sid)
    if not session:return jsonify(ok=False,error="세션이 만료되었습니다."),404
    data=(request.get_json(silent=True) or {}).get("image","")
    if not data.startswith("data:image/png;base64,"):
        return jsonify(ok=False,error="잘못된 이미지입니다."),400
    try:
        raw=base64.b64decode(data.split(",",1)[1],validate=True)
        if len(raw)>DRAW_MAX_BYTES:return jsonify(ok=False,error="이미지가 너무 큽니다."),413
        im=Image.open(io.BytesIO(raw));im.verify()
        buf=io.BytesIO(raw);buf.seek(0)
    except Exception:
        return jsonify(ok=False,error="이미지를 처리할 수 없습니다."),400
    async def send():
        ch=bot.get_channel(session["channel_id"])
        if ch is None: ch=await bot.fetch_channel(session["channel_id"])
        await ch.send(f"🎨 <@{session['user_id']}>님의 그림판 작품",file=discord.File(buf,"drawing.png"))
    try:
        asyncio.run_coroutine_threadsafe(send(),bot.loop).result(timeout=30)
        draw_sessions.pop(sid,None)
        return jsonify(ok=True)
    except Exception as e:
        print("그림 업로드 오류:",e)
        return jsonify(ok=False,error="Discord 업로드에 실패했습니다."),500

def run_draw_server():
    app.run(host="0.0.0.0",port=PORT,debug=False,use_reloader=False)

@bot.tree.command(name="그림",description="Discord 그림판을 엽니다.")
async def 그림(interaction: discord.Interaction):
    if interaction.guild is None:
        return await interaction.response.send_message("❌ 서버에서 사용해 주세요.",ephemeral=True)
    cleanup_draw_sessions()
    sid=secrets.token_urlsafe(32)
    draw_sessions[sid]={"guild_id":interaction.guild.id,"channel_id":interaction.channel.id,"user_id":interaction.user.id,"created":time.time()}
    view=discord.ui.View()
    view.add_item(discord.ui.Button(label="🎨 그림판 열기",style=discord.ButtonStyle.link,url=f"{DRAW_URL}/draw/{sid}"))
    await interaction.response.send_message(f"🎨 {interaction.user.mention}님, 그림판을 열었어요!",view=view)

@bot.event
async def on_ready():
    try:
        synced=await bot.tree.sync()
        print(f"✅ {bot.user} 연결 완료! {len(synced)}개 명령어 동기화됨")
    except Exception as e:
        print(f"❌ 명령어 동기화 오류: {e}")
    if not getattr(bot,"_music_view_started",False):
        bot._music_view_started=True
        bot.add_view(MusicPlayerView())
        print("🎶 음악 플레이어 버튼 활성화")
    if not getattr(bot,"_draw_started",False):
        bot._draw_started=True
        threading.Thread(target=run_draw_server,daemon=True).start()
        print(f"🎨 그림판 서버 시작: {DRAW_URL}")

# =====================
# 실행
# =====================
bot.run(TOKEN)
