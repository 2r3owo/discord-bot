import discord
from discord.ext import commands, tasks
import random
import yt_dlp
import asyncio
import os
from urllib.request import Request, urlopen
from urllib.parse import quote, urlparse, parse_qs
import re
import html
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
# 음악 재생 상태 관리(기존 호출부 호환용)
music_current_song = {}
music_history = {}
music_repeat_mode = {}
music_skip_requested = set()
music_ignore_after = set()

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
}

# 쿠키는 필요한 방식에서만 사용합니다.
# web_embedded / web_safari / android_vr / tv 는 쿠키 없이 시도합니다.
YT_USER_AGENT = os.getenv("YOUTUBE_USER_AGENT", "").strip()


class _SilentYTDLPLogger:
    def debug(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        # 상세 YouTube 오류는 Discord 메시지나 Railway 로그에 노출하지 않습니다.
        pass


def make_youtube_options(mode, outtmpl):
    """YouTube 다운로드 설정. 서버에서 사용 가능한 포맷을 자동 선택합니다."""
    opts = dict(YDL_OPTIONS)
    opts.update({
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "extractor_retries": 2,
        "check_formats": False,
        "geo_bypass": True,
        "format": "bestaudio/best",
        "logger": _SilentYTDLPLogger(),
    })
    # 강제 player_client/PO Token/비디오 형식 지정은 제거합니다.
    opts.pop("extractor_args", None)
    opts.pop("cookiefile", None)
    return opts

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
    """YouTube 링크/검색어를 음원 파일로 다운로드합니다."""
    query = str(search_or_url).strip()
    if not query:
        raise ValueError("YouTube 링크 또는 검색어가 비어 있어요.")
    target = query if query.startswith(("https://", "http://")) else f"ytsearch1:{query}"
    unique = uuid.uuid4().hex
    outtmpl = f"/tmp/discord_music_{guild_id}_{unique}.%(ext)s"

    # Railway에서 가능한 설정을 순서대로 시도합니다.
    attempts = [
        "default",
        "cookie_web",
    ]
    last_error = None

    for mode in attempts:
        try:
            opts = make_youtube_options(mode, outtmpl)
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(target, download=True)
                if not info:
                    raise RuntimeError("YouTube 정보를 가져오지 못했어요.")
                if "entries" in info:
                    info = next((entry for entry in info["entries"] if entry), None)
                if not info:
                    raise RuntimeError("재생할 YouTube 영상을 찾지 못했어요.")

                filepath = ydl.prepare_filename(info)
                if not os.path.isfile(filepath):
                    # 확장자가 후처리되거나 실제 파일명이 달라진 경우를 대비합니다.
                    stem = os.path.splitext(filepath)[0]
                    candidates = [str(x) for x in Path("/tmp").glob(Path(stem).name + ".*")]
                    filepath = next((x for x in candidates if os.path.isfile(x)), filepath)
                if not os.path.isfile(filepath):
                    raise FileNotFoundError("YouTube 음원 파일이 생성되지 않았어요.")

                title = info.get("title") or query
                thumbnail = info.get("thumbnail") or ""
                webpage_url = info.get("webpage_url") or (query if query.startswith("http") else "")
                print(f"✅ YouTube 다운로드 성공 ({mode}): {title}")
                return filepath, title, thumbnail, webpage_url
        except Exception as e:
            last_error = e
            print(f"⚠️ YouTube 다운로드 실패 ({mode}): {e!r}")
            # 실패한 시도에서 남은 임시 파일을 정리합니다.
            for candidate in Path("/tmp").glob(f"discord_music_{guild_id}_{unique}.*"):
                try:
                    candidate.unlink()
                except Exception:
                    pass

    raise RuntimeError(f"YouTube에서 음원을 가져오지 못했어요: {last_error}")

async def update_music_status(guild: discord.Guild, channel: discord.abc.Messageable):
    """음악 상태 메시지를 갱신합니다. 상태 메시지가 없어도 재생을 방해하지 않습니다."""
    try:
        message = music_status_messages.get(guild.id)
        current = music_current_song.get(guild.id)
        queue = queues.get(guild.id, deque())
        title = current.get("title") if current else None
        description = f"🎵 **{title}**" if title else "재생할 곡이 없어요."
        if queue:
            description += f"\n📥 대기열 {len(queue)}곡"
        embed = discord.Embed(title="🎵 음악 상태", description=description, color=discord.Color.blurple())
        if message is not None:
            await message.edit(embed=embed)
    except (discord.NotFound, discord.HTTPException, AttributeError) as e:
        print(f"⚠️ 음악 상태창 갱신 실패: {e!r}")
    except Exception as e:
        print(f"⚠️ 음악 상태창 갱신 중 예외: {e!r}")


def schedule_music_status(guild: discord.Guild, channel: discord.abc.Messageable):
    try:
        coro = update_music_status(guild, channel)
        asyncio.run_coroutine_threadsafe(coro, bot.loop)
    except Exception as e:
        print(f"⚠️ 음악 플레이어 갱신 예약 실패: {e!r}")


def make_ffmpeg_source(filepath):
    """다운로드된 음원 파일을 Discord FFmpeg 오디오 소스로 변환합니다."""
    if not filepath or not os.path.isfile(filepath):
        raise FileNotFoundError(f"음원 파일을 찾을 수 없습니다: {filepath}")
    return discord.FFmpegPCMAudio(
        filepath,
        executable="ffmpeg",
        before_options="-nostdin",
        options="-vn -sn -dn -loglevel warning"
    )


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

    try:
        vc.play(source, after=_after)
    except Exception:
        music_current_song.pop(guild_id, None)
        music_now_playing.pop(guild_id, None)
        raise
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
            filepath, title, thumbnail, webpage_url = await loop.run_in_executor(
                None, lambda: download_song(str(self.search.value), guild.id)
            )
            song = {'filepath': filepath, 'title': title, 'query': str(self.search.value), 'thumbnail': thumbnail, 'webpage_url': webpage_url}

            queues.setdefault(guild.id, deque())
            if guild.voice_client.is_playing() or guild.voice_client.is_paused():
                queues[guild.id].append(song)
            else:
                music_stopped_song.pop(guild.id, None)
                _play_song_now(guild, song, interaction.channel)

            await update_music_status(guild, interaction.channel)
            await interaction.followup.send(f"✅ **{title}** 을(를) {'대기열에 추가했어요!' if len(queues[guild.id]) else '재생했어요!'}", ephemeral=True)
        except Exception as e:
            print(f"❌ 버튼 노래 추가 오류: {e!r}")
            await interaction.followup.send(f"❌ 재생 중 오류 발생: {e}", ephemeral=True)



# =====================
# 음악 패널 버튼: 멜론 TOP100 / 최신곡 / 즐겨찾기
# =====================
music_chart_cache = {}
music_chart_week = {}
music_favorites = {}

def _chart_key(guild_id, chart_type):
    return (guild_id, chart_type)


def _current_chart_week():
    today = date.today()
    year, week, _ = today.isocalendar()
    return f"{year}년 {week}주차"

def _clean_chart_text(value):
    return html.unescape(re.sub(r"<[^>]+>", "", value or "")).strip()

def _fetch_melon_chart(chart_type="top100", limit=100):
    """멜론 TOP100/최신곡을 최대 100곡까지 가져옵니다.
    멜론 페이지의 데스크톱·모바일 HTML 구조가 달라도 여러 패턴으로 읽습니다.
    """
    if chart_type == "top100":
        urls = [
            "https://www.melon.com/chart/index.htm",
            "https://m2.melon.com/m6/chart/realtime/index.htm",
            f"https://www.melon.com/chart/index.htm?dayTime={datetime.now().strftime("%Y%m%d%H")}",
        ]
    else:
        urls = [
            "https://www.melon.com/new/index.htm",
            "https://www.melon.com/new/index.htm?startIndex=1&pageSize=100",
            "https://m2.melon.com/m6/chart/new/index.htm",
            "https://m2.melon.com/m6/chart/new/index.htm?startIndex=1&pageSize=100",
        ]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        "Referer": "https://www.melon.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    last_error = None
    raws = []
    for url in urls:
        try:
            req = Request(url, headers=headers)
            raw = urlopen(req, timeout=25).read().decode("utf-8", errors="ignore")
            if raw and len(raw) > 1000:
                raws.append(raw)
        except Exception as e:
            last_error = e

    if not raws:
        raise RuntimeError("멜론 차트 정보를 가져오지 못했어요.") from last_error

    result = []
    seen = set()

    def add_track(title, artist, image=""):
        title = _clean_chart_text(title)
        artist = _clean_chart_text(artist)
        if not title or not artist:
            return
        key = (title, artist)
        if key in seen or len(result) >= limit:
            return
        seen.add(key)
        result.append({
            "rank": len(result) + 1,
            "title": title,
            "artist": artist,
            "query": f"{title} {artist}",
            "thumbnail": html.unescape(image or ""),
        })

    for raw in raws:
        # 일반 차트: lst50/lst100 한 행씩 처리
        rows = re.findall(r"<tr[^>]*class=[\"'][^\"']*(?:lst50|lst100)[^\"']*[\"'][^>]*>(.*?)</tr>", raw, re.S | re.I)
        # 최신곡 페이지는 wrap_song_info 블록을 사용하는 경우가 있음
        if not rows:
            rows = re.findall(r"<div[^>]*class=[\"'][^\"']*wrap_song_info[^\"']*[\"'][^>]*>(.*?)</div>\s*</div>", raw, re.S | re.I)
        if not rows:
            rows = re.findall(r"<tr[^>]*>(.*?)</tr>", raw, re.S | re.I)

        for row in rows:
            title = re.search(r"class=[\"'][^\"']*(?:rank01|song|song_name|title)[^\"']*[\"'][^>]*>.*?<a[^>]*>(.*?)</a>", row, re.S | re.I)
            artist = re.search(r"class=[\"'][^\"']*(?:rank02|artist|artist_name)[^\"']*[\"'][^>]*>.*?<a[^>]*>(.*?)</a>", row, re.S | re.I)
            if not title:
                title = re.search(r"<a[^>]*class=[\"'][^\"']*(?:song|title)[^\"']*[\"'][^>]*>(.*?)</a>", row, re.S | re.I)
            if not artist:
                artist = re.search(r"<a[^>]*class=[\"'][^\"']*artist[^\"']*[\"'][^>]*>(.*?)</a>", row, re.S | re.I)
            image = re.search(r"<img[^>]*(?:src|data-original|data-lazy)= [\"']?([^\"' >]+)".replace("= ", "="), row, re.S | re.I)
            if title and artist:
                add_track(title.group(1), artist.group(1), image.group(1) if image else "")
            if len(result) >= limit:
                break
        if len(result) >= limit:
            break

        # HTML 구조가 바뀐 경우 rank01/rank02가 같은 영역에 있는 패턴으로 재시도
        if len(result) < limit:
            blocks = re.findall(r".{0,900}rank01.{0,1800}rank02.{0,900}", raw, re.S | re.I)
            for block in blocks:
                title = re.search(r"rank01[^>]*>.*?<a[^>]*>(.*?)</a>", block, re.S | re.I)
                artist = re.search(r"rank02[^>]*>.*?<a[^>]*>(.*?)</a>", block, re.S | re.I)
                if title and artist:
                    add_track(title.group(1), artist.group(1))
                if len(result) >= limit:
                    break

    if not result:
        raise RuntimeError("멜론 차트 정보를 가져오지 못했어요. 멜론 페이지가 차단했거나 구조가 변경되었어요.")
    return result[:limit]


@tasks.loop(hours=24)
async def refresh_latest_chart_daily():
    """최신가요 목록을 하루에 한 번 새로 가져옵니다."""
    try:
        tracks = await asyncio.to_thread(_fetch_melon_chart, "latest", 100)
        # 서버별로 같은 최신 국내 가요 목록을 갱신
        for guild in bot.guilds:
            music_chart_cache[_chart_key(guild.id, "latest")] = tracks
        print("🆕 최신 국내 가요 100곡 일일 갱신 완료")
    except Exception as error:
        print(f"⚠️ 최신가요 일일 갱신 실패: {error}")


@refresh_latest_chart_daily.before_loop
async def before_refresh_latest_chart_daily():
    await bot.wait_until_ready()

def _chart_embed(chart_type, tracks, page=0):
    name = f"멜론 국내 TOP100 ({_current_chart_week()})" if chart_type == "top100" else "멜론 국내 최신가요 100"
    per_page = 20
    start = page * per_page
    shown = tracks[start:start + per_page]
    embed = discord.Embed(
        title=f"🎵 {name}",
        description="아래 목록에서 곡을 선택한 뒤 버튼으로 재생하거나 즐겨찾기에 추가하세요.",
        color=discord.Color.green(),
    )
    if shown:
        embed.add_field(
            name=f"{start + 1}~{start + len(shown)}위",
            value="\n".join(
                f"`{track['rank']:02d}` {track['title']} — {track['artist']}"
                for track in shown
            )[:4000],
            inline=False,
        )
    embed.set_footer(text=f"페이지 {page + 1}/{max(1, (len(tracks) + per_page - 1) // per_page)} · 곡을 선택하면 재생할 수 있어요.")
    if shown and shown[0].get("thumbnail"):
        embed.set_thumbnail(url=shown[0]["thumbnail"])
    return embed

class ChartSelect(discord.ui.Select):
    def __init__(self, tracks):
        options = [
            discord.SelectOption(
                label=f"{track['rank']}. {track['title']}"[:100],
                description=track["artist"][:100],
                value=str(index),
            )
            for index, track in enumerate(tracks[:25])
        ]
        super().__init__(
            placeholder="재생하거나 즐겨찾기할 곡 선택",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.tracks = tracks

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_index = int(self.values[0])
        track = self.tracks[self.view.selected_index]
        await interaction.response.edit_message(
            embed=_chart_embed(self.view.chart_type, self.tracks, self.view.page),
            view=self.view,
        )
        await interaction.followup.send(
            f"선택됨: **{track['title']} — {track['artist']}**",
            ephemeral=True,
        )

class ChartView(discord.ui.View):
    def __init__(self, guild_id, chart_type, tracks, page=0):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.chart_type = chart_type
        self.tracks = tracks
        self.page = page
        self.selected_index = None
        self.add_item(ChartSelect(tracks[page * 20:(page + 1) * 20]))

    def selected_track(self):
        if self.selected_index is None:
            return None
        start = self.page * 20
        index = start + self.selected_index
        return self.tracks[index] if 0 <= index < len(self.tracks) else None

    async def _add_song(self, interaction, play_now=False):
        track = self.selected_track()
        if not track:
            return await interaction.response.send_message("❌ 먼저 곡을 선택해 주세요.", ephemeral=True)
        if not interaction.user.voice:
            return await interaction.response.send_message("❌ 먼저 음성채널에 들어가 주세요.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        try:
            if not guild.voice_client:
                await interaction.user.voice.channel.connect(timeout=60.0, reconnect=True)
            loop = asyncio.get_event_loop()
            filepath, title, thumbnail, webpage_url = await loop.run_in_executor(
                None, lambda: download_song(track["query"], guild.id)
            )
            song = {
                "filepath": filepath,
                "title": title or track["title"],
                "query": track["query"],
                "thumbnail": thumbnail or track.get("thumbnail", ""),
                "webpage_url": webpage_url,
            }
            queues.setdefault(guild.id, deque())
            if play_now:
                if guild.voice_client.is_playing() or guild.voice_client.is_paused():
                    music_skip_requested.add(guild.id)
                    guild.voice_client.stop()
                _play_song_now(guild, song, interaction.channel)
                message = f"🎵 **{song['title']}** 재생을 시작했어요."
            elif guild.voice_client.is_playing() or guild.voice_client.is_paused():
                queues[guild.id].append(song)
                message = f"📥 **{song['title']}** 대기열에 추가했어요."
            else:
                _play_song_now(guild, song, interaction.channel)
                message = f"🎵 **{song['title']}** 재생을 시작했어요."
            await update_music_status(guild, interaction.channel)
            await interaction.followup.send(message, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 곡 재생 실패: {e}", ephemeral=True)

    @discord.ui.button(label="선택 재생", emoji="▶️", style=discord.ButtonStyle.success, row=1)
    async def play_selected(self, interaction, button):
        await self._add_song(interaction, play_now=True)

    @discord.ui.button(label="대기열 추가", emoji="📥", style=discord.ButtonStyle.secondary, row=1)
    async def queue_selected(self, interaction, button):
        await self._add_song(interaction, play_now=False)

    @discord.ui.button(label="즐겨찾기 추가", emoji="⭐", style=discord.ButtonStyle.primary, row=1)
    async def favorite_selected(self, interaction, button):
        track = self.selected_track()
        if not track:
            return await interaction.response.send_message("❌ 먼저 곡을 선택해 주세요.", ephemeral=True)
        key = (self.guild_id, interaction.user.id)
        favorites = music_favorites.setdefault(key, [])
        if not any(item["query"] == track["query"] for item in favorites):
            favorites.append(track)
        await interaction.response.send_message(f"⭐ **{track['title']}** 을(를) 즐겨찾기에 저장했어요.", ephemeral=True)

    @discord.ui.button(label="즐겨찾기 재생", emoji="💛", style=discord.ButtonStyle.secondary, row=2)
    async def play_favorites(self, interaction, button):
        favorites = music_favorites.get((self.guild_id, interaction.user.id), [])
        if not favorites:
            return await interaction.response.send_message("❌ 저장된 즐겨찾기가 없어요.", ephemeral=True)
        self.tracks = favorites
        self.chart_type = "favorites"
        self.page = 0
        self.selected_index = None
        await interaction.response.edit_message(
            embed=_chart_embed("latest", favorites, 0),
            view=ChartView(self.guild_id, "favorites", favorites, 0),
        )



# =====================
# 멜론 플레이리스트 기능
# =====================
def _fetch_melon_playlist(playlist_id, limit=100):
    url = f"https://www.melon.com/playlist/detail/view.htm?plId={playlist_id}"
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "ko-KR,ko;q=0.9"}
    raw = urlopen(Request(url, headers=headers), timeout=25).read().decode("utf-8", errors="ignore")
    tracks, seen = [], set()

    # 플레이리스트 페이지의 곡 제목/가수 영역을 최대한 넓게 읽습니다.
    titles = re.findall(r'class=["\'][^"\']*(?:song_name|songname)[^"\']*["\'][^>]*>.*?<a[^>]*>(.*?)</a>', raw, re.S | re.I)
    artists = re.findall(r'class=["\'][^"\']*(?:artist_name|artist)[^"\']*["\'][^>]*>.*?<a[^>]*>(.*?)</a>', raw, re.S | re.I)
    if not titles:
        titles = re.findall(r'goSongDetail\(["\']?(\d+)["\']?\)', raw)
        for song_id in titles:
            tracks.append({"rank": len(tracks)+1, "title": f"멜론 곡 {song_id}", "artist": "", "query": song_id, "thumbnail": ""})
        return tracks[:limit]
    for i, title in enumerate(titles[:limit]):
        title = _clean_chart_text(title)
        artist = _clean_chart_text(artists[i]) if i < len(artists) else ""
        if title and (title, artist) not in seen:
            seen.add((title, artist))
            tracks.append({"rank": len(tracks)+1, "title": title, "artist": artist, "query": f"{title} {artist}", "thumbnail": ""})
    if not tracks:
        raise RuntimeError("플레이리스트에서 곡을 찾지 못했어요.")
    return tracks

def _search_melon_playlists(keyword, limit=5):
    url = "https://www.melon.com/search/total/index.htm?q=" + quote(keyword)
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "ko-KR,ko;q=0.9"}
    raw = urlopen(Request(url, headers=headers), timeout=25).read().decode("utf-8", errors="ignore")
    found, seen = [], set()
    for m in re.finditer(r"goPlaylistDetail\([\"']?(\d+)[\"']?\)", raw, re.I):
        pid = m.group(1)
        if pid in seen: continue
        seen.add(pid)
        chunk = raw[max(0, m.start()-1200):m.start()+500]
        names = re.findall(r'<a[^>]*>(.*?)</a>', chunk, re.S | re.I)
        name = _clean_chart_text(names[-1]) if names else f"플레이리스트 {pid}"
        found.append({"id": pid, "name": name[:80]})
        if len(found) >= limit: break
    return found

async def _play_playlist(interaction, playlist_id, label="플레이리스트"):
    if not interaction.user.voice:
        return await interaction.response.send_message("❌ 먼저 음성채널에 들어가 주세요.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    try:
        if not guild.voice_client:
            await interaction.user.voice.channel.connect(timeout=60.0, reconnect=True)
        tracks = await asyncio.to_thread(_fetch_melon_playlist, playlist_id, 100)
        await interaction.followup.send(f"⏳ **{label}**을 준비하고 있어요. 곡을 순서대로 추가합니다.", ephemeral=True)
        asyncio.create_task(MusicChartButtonView(guild.id)._download_chart_in_background(guild, interaction.channel, tracks, "playlist"))
    except Exception as e:
        await interaction.followup.send(f"❌ 플레이리스트를 재생하지 못했어요: {e}", ephemeral=True)

def _resolve_melon_playlist_id(value):
    """멜론 정식 링크, 숫자 번호, kko.to 단축 링크를 모두 플리 번호로 변환합니다."""
    value = str(value).strip()
    if value.isdigit():
        return value

    # 정식 멜론 링크에 이미 plId가 있는 경우
    parsed = urlparse(value)
    query_id = parse_qs(parsed.query).get("plId", [None])[0]
    if query_id and str(query_id).isdigit():
        return str(query_id)

    # kko.to 같은 단축 링크는 리다이렉트를 따라가 최종 멜론 주소를 확인합니다.
    if parsed.scheme in ("http", "https") and parsed.netloc.lower().endswith("kko.to"):
        headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "ko-KR,ko;q=0.9"}
        response = urlopen(Request(value, headers=headers), timeout=20)
        final_url = response.geturl()
        final_parsed = urlparse(final_url)
        final_id = parse_qs(final_parsed.query).get("plId", [None])[0]
        if final_id and str(final_id).isdigit():
            return str(final_id)
        match = re.search(r"(?:plId=|playlist/detail/view/(?:\?plId=)?)(\d+)", final_url, re.I)
        if match:
            return match.group(1)

    # 주소 안에 plId가 포함된 변형 링크도 지원
    m = re.search(r"(?:plId=|playlist/)(\d+)", value, re.I)
    return m.group(1) if m else None


class MelonPlaylistModal(discord.ui.Modal, title="멜론 플레이리스트 재생"):
    playlist = discord.ui.TextInput(label="멜론 플리 링크 또는 플리 번호", placeholder="https://kko.to/예시링크 또는 123456", required=True)
    async def on_submit(self, interaction: discord.Interaction):
        value = str(self.playlist.value).strip()
        try:
            playlist_id = await asyncio.to_thread(_resolve_melon_playlist_id, value)
        except Exception:
            playlist_id = None
        if not playlist_id:
            return await interaction.response.send_message("❌ 멜론 플레이리스트 링크를 확인하지 못했어요. kko.to 단축 링크나 멜론 플리 번호를 넣어 주세요.", ephemeral=True)
        await _play_playlist(interaction, playlist_id, "내 멜론 플레이리스트")

class MelonPlaylistSearchModal(discord.ui.Modal, title="멜론 플레이리스트 검색"):
    keyword = discord.ui.TextInput(label="검색할 플레이리스트", placeholder="예: 여름 노래, 발라드, 운동할 때", required=True)
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            results = await asyncio.to_thread(_search_melon_playlists, str(self.keyword.value).strip(), 5)
            if not results:
                return await interaction.followup.send("❌ 공개 플레이리스트를 찾지 못했어요.", ephemeral=True)
            embed = discord.Embed(title=f"🎶 멜론 플리 검색: {self.keyword.value}", color=discord.Color.green())
            embed.description = "아래 버튼을 누르면 해당 플레이리스트를 바로 재생합니다."
            view = MelonPlaylistResultView(results)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 플리 검색 실패: {e}", ephemeral=True)

class MelonPlaylistResultView(discord.ui.View):
    def __init__(self, results):
        super().__init__(timeout=300)
        for item in results[:5]:
            self.add_item(MelonPlaylistResultButton(item["id"], item["name"]))

class MelonPlaylistResultButton(discord.ui.Button):
    def __init__(self, playlist_id, name):
        super().__init__(label=name[:80], style=discord.ButtonStyle.secondary)
        self.playlist_id = playlist_id
        self.name = name
    async def callback(self, interaction: discord.Interaction):
        await _play_playlist(interaction, self.playlist_id, self.name)

class MusicChartButtonView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=300)
        self.guild_id = guild_id

    async def _play_all(self, interaction, chart_type):
        """선택창 없이 차트 곡을 순서대로 대기열에 넣고 자동 재생합니다."""
        if not interaction.user.voice:
            return await interaction.response.send_message("❌ 먼저 음성채널에 들어가 주세요.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        try:
            if not guild.voice_client:
                await interaction.user.voice.channel.connect(timeout=60.0, reconnect=True)
            tracks = music_chart_cache.get(_chart_key(self.guild_id, chart_type))
            if not tracks:
                tracks = await asyncio.to_thread(_fetch_melon_chart, chart_type, 100)
                music_chart_cache[_chart_key(self.guild_id, chart_type)] = tracks
                if chart_type == "top100":
                    music_chart_week[_chart_key(self.guild_id, chart_type)] = _current_chart_week()
            await interaction.followup.send(
                f"⏳ **{('멜론 TOP100' if chart_type == 'top100' else '최신곡 100') }**을 준비하고 있어요. 곡을 순서대로 추가합니다.",
                ephemeral=True,
            )
            asyncio.create_task(self._download_chart_in_background(guild, interaction.channel, tracks, chart_type))
        except Exception as e:
            await interaction.followup.send(f"❌ 차트를 시작하지 못했어요: {e}", ephemeral=True)

    async def _download_chart_in_background(self, guild, channel, tracks, chart_type):
        gid = guild.id
        queues.setdefault(gid, deque())
        added = 0
        for track in tracks[:100]:
            try:
                filepath, title, thumbnail, webpage_url = await asyncio.to_thread(
                    download_song, track["query"], gid
                )
                song = {
                    "filepath": filepath,
                    "title": title or track["title"],
                    "query": track["query"],
                    "thumbnail": thumbnail or track.get("thumbnail", ""),
                    "webpage_url": webpage_url,
                }
                if not guild.voice_client:
                    _cleanup_file(filepath)
                    break
                if guild.voice_client.is_playing() or guild.voice_client.is_paused() or music_current_song.get(gid):
                    queues[gid].append(song)
                else:
                    _play_song_now(guild, song, channel)
                added += 1
                if added % 10 == 0:
                    print(f"🎵 {chart_type} 차트 {added}곡 준비 완료")
            except Exception as e:
                print(f"⚠️ 차트 곡 건너뜀: {track.get('title', '')} / {e!r}")
        await update_music_status(guild, channel)
        print(f"✅ {chart_type} 차트 자동 재생 준비 완료: {added}곡")

    async def _show(self, interaction, chart_type):
        await interaction.response.defer(ephemeral=True)
        try:
            cache_key = _chart_key(self.guild_id, chart_type)
            current_week = _current_chart_week()
            tracks = music_chart_cache.get(cache_key)

            # TOP100은 같은 주에는 기존 목록을 사용하고,
            # 주차가 바뀌었을 때만 국내 차트를 다시 가져옵니다.
            if chart_type == "top100":
                if not tracks or music_chart_week.get(cache_key) != current_week:
                    tracks = await asyncio.to_thread(_fetch_melon_chart, chart_type, 100)
                    music_chart_cache[cache_key] = tracks
                    music_chart_week[cache_key] = current_week
            else:
                tracks = await asyncio.to_thread(_fetch_melon_chart, chart_type, 100)
                music_chart_cache[cache_key] = tracks

            view = ChartView(self.guild_id, chart_type, tracks, 0)
            await interaction.followup.send(
                embed=_chart_embed(chart_type, tracks, 0),
                view=view,
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(f"❌ 차트를 불러오지 못했어요: {e}", ephemeral=True)

    @discord.ui.button(label="멜론 TOP100 자동재생", emoji="🏆", style=discord.ButtonStyle.success)
    async def top100(self, interaction, button):
        await self._play_all(interaction, "top100")

    @discord.ui.button(label="최신곡 100 자동재생", emoji="🆕", style=discord.ButtonStyle.success)
    async def latest(self, interaction, button):
        await self._play_all(interaction, "latest")

    @discord.ui.button(label="내 멜론 플리 재생", emoji="🎵", style=discord.ButtonStyle.primary, row=1)
    async def my_melon_playlist(self, interaction, button):
        await interaction.response.send_modal(MelonPlaylistModal())

    @discord.ui.button(label="멜론 플리 검색", emoji="🔎", style=discord.ButtonStyle.secondary, row=1)
    async def search_melon_playlist(self, interaction, button):
        await interaction.response.send_modal(MelonPlaylistSearchModal())

    @discord.ui.button(label="즐겨찾기", emoji="⭐", style=discord.ButtonStyle.secondary, row=2)
    async def favorites(self, interaction, button):
        favorites = music_favorites.get((self.guild_id, interaction.user.id), [])
        if not favorites:
            return await interaction.response.send_message("❌ 저장된 즐겨찾기가 없어요.", ephemeral=True)
        await interaction.response.send_message(
            embed=_chart_embed("latest", favorites, 0),
            view=ChartView(self.guild_id, "favorites", favorites, 0),
            ephemeral=True,
        )

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
        # 정지한 곡은 별도로 기억해 두어 ⏯️ 버튼으로 다시 재생할 수 있게 합니다.
        stopped = music_current_song.get(guild_id)
        if stopped:
            music_stopped_song[guild_id] = dict(stopped)
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
            filepath, title, thumbnail, webpage_url = await loop.run_in_executor(None, lambda: download_song(query, guild.id))
            song = {'filepath': filepath, 'title': title, 'query': query, 'thumbnail': thumbnail, 'webpage_url': webpage_url}
            music_stopped_song.pop(guild.id, None)
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
            # 정지된 마지막 곡이 있으면 같은 버튼으로 다시 재생합니다.
            stopped = music_stopped_song.get(interaction.guild.id)
            if not stopped or not stopped.get('query'):
                msg = "❌ 다시 재생할 곡이 없어요."
            else:
                await interaction.response.defer(ephemeral=True)
                try:
                    loop = asyncio.get_event_loop()
                    filepath, title, thumbnail, webpage_url = await loop.run_in_executor(
                        None, lambda: download_song(stopped['query'], interaction.guild.id)
                    )
                    song = {
                        'filepath': filepath,
                        'title': title,
                        'query': stopped.get('query', ''),
                        'thumbnail': thumbnail or stopped.get('thumbnail', ''),
                        'webpage_url': webpage_url or stopped.get('webpage_url', '')
                    }
                    _play_song_now(interaction.guild, song, interaction.channel)
                    music_stopped_song.pop(interaction.guild.id, None)
                    await update_music_status(interaction.guild, interaction.channel)
                    await interaction.followup.send(f"▶️ **{title}** 다시 재생했어요!", ephemeral=True)
                except Exception as e:
                    await interaction.followup.send(f"❌ 다시 재생 실패: {e}", ephemeral=True)
                return
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

    @discord.ui.button(label="", emoji="🏆", style=discord.ButtonStyle.success, custom_id="music_top100", row=2)
    async def top100_chart(self, interaction: discord.Interaction, button: discord.ui.Button):
        await MusicChartButtonView(interaction.guild.id)._play_all(interaction, "top100")

    @discord.ui.button(label="", emoji="🆕", style=discord.ButtonStyle.success, custom_id="music_latest100", row=2)
    async def latest_chart(self, interaction: discord.Interaction, button: discord.ui.Button):
        await MusicChartButtonView(interaction.guild.id)._play_all(interaction, "latest")

    @discord.ui.button(label="", emoji="⭐", style=discord.ButtonStyle.secondary, custom_id="music_favorites", row=2)
    async def favorites_chart(self, interaction: discord.Interaction, button: discord.ui.Button):
        await MusicChartButtonView(interaction.guild.id).favorites(interaction, button)

    @discord.ui.button(label="", emoji="🎵", style=discord.ButtonStyle.primary, custom_id="music_my_melon_playlist", row=3)
    async def my_melon_playlist(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(MelonPlaylistModal())

    @discord.ui.button(label="", emoji="🔎", style=discord.ButtonStyle.secondary, custom_id="music_search_melon_playlist", row=3)
    async def search_melon_playlist(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(MelonPlaylistSearchModal())

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
        music_stopped_song.pop(interaction.guild.id, None)
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
        filepath, title, thumbnail, webpage_url = await loop.run_in_executor(None, lambda: download_song(search, guild.id))
        song = {'filepath': filepath, 'title': title, 'query': search, 'thumbnail': thumbnail, 'webpage_url': webpage_url}
        music_stopped_song.pop(guild.id, None)
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
        filepath, title, thumbnail, webpage_url = await loop.run_in_executor(None, lambda: download_song(search, guild.id))
        song = {'filepath': filepath, 'title': title, 'query': search, 'thumbnail': thumbnail, 'webpage_url': webpage_url}
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
@app_commands.checks.has_permissions(manage_messages=True)
async def 청소(interaction: discord.Interaction, amount: str):
    """메시지를 삭제합니다. 긴 삭제 작업 때문에 무한 로딩처럼 보이지 않도록 즉시 응답합니다."""
    if amount == "전부":
        limit = 999
    else:
        try:
            limit = int(amount)
            if limit <= 0:
                return await interaction.response.send_message("❌ 1개 이상의 숫자를 입력해야 합니다.", ephemeral=True)
            limit = min(limit, 999)
        except ValueError:
            return await interaction.response.send_message("❌ 숫자를 입력하거나 '전부'라고 입력해 주세요.", ephemeral=True)

    # 먼저 바로 응답해서 Discord의 로딩 표시가 오래 붙어 있지 않게 합니다.
    await interaction.response.send_message("🧹 **청소 중...** 잠시만 기다려 주세요!", ephemeral=True)

    try:
        deleted_total = 0
        remaining = limit

        # Discord bulk delete는 100개 단위가 가장 안정적입니다.
        while remaining > 0:
            batch = min(100, remaining)
            deleted = await interaction.channel.purge(limit=batch)
            deleted_total += len(deleted)

            if len(deleted) < batch:
                break
            remaining -= len(deleted)

            # 너무 빠르게 반복 요청하지 않도록 아주 짧게 쉬어 줍니다.
            if remaining > 0:
                await asyncio.sleep(0.3)

        await interaction.edit_original_response(
            content=f"🧹 **{deleted_total}개**의 메시지를 깨끗하게 치웠어요!"
        )
    except discord.Forbidden:
        await interaction.edit_original_response(
            content="❌ 메시지를 삭제할 권한이 없어요. 봇에게 **메시지 관리** 권한을 확인해 주세요."
        )
    except discord.HTTPException as e:
        await interaction.edit_original_response(
            content=f"❌ Discord에서 삭제 요청이 제한됐어요. 잠시 후 다시 시도해 주세요.\n`{e}`"
        )
    except Exception as e:
        print(f"[야청소해 오류] {e}")
        await interaction.edit_original_response(
            content="❌ 메시지 삭제 중 오류가 발생했어요. Railway 로그를 확인해 주세요."
        )

# 권한 부족 시 에러 처리 (슬래시 커맨드용)
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        if interaction.response.is_done():
            await interaction.followup.send("🚫 이 명령어를 사용하려면 **메시지 관리** 권한이 필요합니다!", ephemeral=True)
        else:
            await interaction.response.send_message("🚫 이 명령어를 사용하려면 **메시지 관리** 권한이 필요합니다!", ephemeral=True)
    else:
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
              "`/야멈춰`: 중지 / `/야넘겨`: 다음 곡 / `/야꺼져`: 퇴장\n"
              "음악 패널에서 멜론 TOP100·최신곡·즐겨찾기도 사용할 수 있어요.",
        inline=False
    )

    # 푸터 설정
    embed.set_footer(
        text=f"요청자: {interaction.user.display_name} | 데이터는 서버별로 저장됩니다.", 
        icon_url=interaction.user.display_avatar.url
    )
    
    await interaction.response.send_message(embed=embed)


# =====================

# =====================
# 🎡 결정 룰렛
# =====================
roulette_data = {}

def make_roulette_embed(options, result=None, owner_name=""):
    colors = ["🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "🩷", "🟤"]
    lines = [
        f"{colors[i % len(colors)]} **{i + 1}.** {option}"
        for i, option in enumerate(options)
    ]
    description = "\n".join(lines)
    if result:
        description += f"\n\n🎉 **결과: {result}**"
    else:
        description += "\n\n🎯 아래 버튼으로 선택지를 설정하고 돌려보세요!"

    embed = discord.Embed(
        title="🎡 결정 룰렛",
        description=description,
        color=0x5865F2
    )
    embed.set_footer(text=f"{owner_name}님의 룰렛")
    return embed


class RouletteSetupModal(discord.ui.Modal, title="🎡 룰렛 설정"):
    options_input = discord.ui.TextInput(
        label="선택지 입력",
        placeholder="치킨\n피자\n햄버거\n떡볶이\n라면",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        raw = str(self.options_input.value)
        options = [item.strip() for item in raw.splitlines() if item.strip()]

        if len(options) < 2 and "," in raw:
            options = [item.strip() for item in raw.split(",") if item.strip()]

        if len(options) < 2:
            return await interaction.response.send_message(
                "❌ 선택지는 최소 2개 입력해 주세요.",
                ephemeral=True
            )

        if len(options) > 20:
            return await interaction.response.send_message(
                "❌ 선택지는 최대 20개까지 입력할 수 있어요.",
                ephemeral=True
            )

        roulette_data[interaction.user.id] = options
        await interaction.response.edit_message(
            embed=make_roulette_embed(
                options,
                owner_name=interaction.user.display_name
            ),
            view=RouletteView(interaction.user.id)
        )


class RouletteView(discord.ui.View):
    def __init__(self, owner_id):
        super().__init__(timeout=900)
        self.owner_id = owner_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "🔒 이 룰렛은 만든 사람만 조작할 수 있어요.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="🎡 설정", style=discord.ButtonStyle.secondary, row=0)
    async def setup_button(self, interaction, button):
        await interaction.response.send_modal(RouletteSetupModal())

    @discord.ui.button(label="🎲 돌리기", style=discord.ButtonStyle.primary, row=0)
    async def spin_button(self, interaction, button):
        import random
        options = roulette_data.get(self.owner_id, [])
        if len(options) < 2:
            return await interaction.response.send_message(
                "❌ 먼저 🎡 설정을 눌러 선택지를 입력해 주세요.",
                ephemeral=True
            )

        result = random.choice(options)
        await interaction.response.edit_message(
            embed=make_roulette_embed(
                options,
                result=result,
                owner_name=interaction.user.display_name
            ),
            view=self
        )

    @discord.ui.button(label="🔄 다시 돌리기", style=discord.ButtonStyle.success, row=1)
    async def again_button(self, interaction, button):
        await self.spin_button(interaction, button)


@bot.tree.command(name="룰렛", description="선택하기 어려울 때 돌리는 결정 룰렛입니다.")
async def 룰렛(interaction: discord.Interaction):
    options = roulette_data.get(interaction.user.id, [])

    if options:
        embed = make_roulette_embed(
            options,
            owner_name=interaction.user.display_name
        )
    else:
        embed = discord.Embed(
            title="🎡 결정 룰렛",
            description=(
                "선택하기 어려울 때 사용하는 결정 룰렛이에요!\n\n"
                "아래 **🎡 설정** 버튼을 눌러 선택지를 입력해 주세요."
            ),
            color=0x5865F2
        )

    await interaction.response.send_message(
        embed=embed,
        view=RouletteView(interaction.user.id)
    )

# 🎨 웹 그림판
# =====================
app = Flask(__name__)
draw_sessions = {}
DRAW_SESSION_TTL = 12 * 60 * 60
DRAW_MAX_BYTES = 8 * 1024 * 1024

DRAW_HTML = """
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Discord 그림판</title>
<style>
body{margin:0;background:#f3f4f6;font-family:Arial,sans-serif}
#bar{position:sticky;top:0;background:white;padding:10px;border-bottom:1px solid #ddd;z-index:2;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
button,input{margin:2px;padding:7px}
button.active{background:#5865f2;color:white;border-color:#5865f2}
#wrap{padding:12px}
#c{display:block;background-color:white;background-image:linear-gradient(45deg,#eee 25%,transparent 25%),linear-gradient(-45deg,#eee 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#eee 75%),linear-gradient(-45deg,transparent 75%,#eee 75%);background-size:20px 20px;background-position:0 0,0 10px,10px -10px,-10px 0;border:1px solid #ccc;margin:0 auto;max-width:100%;touch-action:none}
#hint{font-size:12px;color:#666}
</style>
</head>
<body>
<div id="bar">
<b>🎨 Discord 그림판</b>
<button id="brushBtn" onclick="setTool('brush')">브러쉬</button>
<button id="neonBtn" onclick="setTool('neon')">✨ 네온</button>
<button id="eraserBtn" onclick="setTool('eraser')">지우개</button>
<button id="bucketBtn" onclick="setTool('bucket')">🪣 페인트통</button>
<button id="pixelBtn" onclick="setTool('pixel')">▦ 픽셀아트</button>
<label>색 <input id="color" type="color" value="#000000"></label>
<label>굵기 <input id="size" type="range" min="1" max="60" value="6"></label>
<label>투명도 <input id="alpha" type="range" min="1" max="100" value="100"></label>
<label><input id="transparent" type="checkbox" checked> 투명 배경</label>
<label><input id="pixelMode" type="checkbox"> 픽셀아트 체크</label>
<label>픽셀 크기 <select id="pixelSize"><option value="8">8px</option><option value="12" selected>12px</option><option value="16">16px</option><option value="24">24px</option></select></label>
<button onclick="undo()">↩ 실행취소</button>
<button onclick="redo()">↪ 다시실행</button>
<button onclick="clearCanvas()">🗑 초기화</button>
<button onclick="finish()">📤 Discord에 올리기</button>
<span id="hint">투명 배경은 체크된 상태로 시작해요.</span>
</div>
<div id="wrap"><canvas id="c" width="1000" height="700"></canvas></div>
<script>
const sid={{sid|tojson}}, c=document.getElementById('c'), x=c.getContext('2d',{willReadFrequently:true});
let tool='brush',down=false,sx=0,sy=0,lx=0,ly=0,h=[],f=[];
const $=id=>document.getElementById(id);

function clearToBackground(){
  x.clearRect(0,0,c.width,c.height);
  if(!$('transparent').checked){
    x.save();x.globalAlpha=1;x.fillStyle='#ffffff';x.fillRect(0,0,c.width,c.height);x.restore();
  }
}
function state(){return c.toDataURL('image/png')}
function restore(s){
  let i=new Image();
  i.onload=()=>{x.clearRect(0,0,c.width,c.height);x.drawImage(i,0,0)};
  i.src=s;
}
function setTool(t){
  tool=t;
  ['brush','neon','eraser','bucket','pixel'].forEach(k=>$(''+k+'Btn').classList.toggle('active',k===t));
}
function pos(e){
  let r=c.getBoundingClientRect();
  return{x:(e.clientX-r.left)*c.width/r.width,y:(e.clientY-r.top)*c.height/r.height};
}
function setup(){
  x.lineWidth=+$('size').value;
  x.globalAlpha=+$('alpha').value/100;
  x.lineCap='round';
  x.lineJoin='round';
  x.strokeStyle=$('color').value;
  x.fillStyle=$('color').value;
}
function drawPixel(px,py){
  setup();
  const grid=+$('pixelSize').value;
  const gx=Math.floor(px/grid)*grid;
  const gy=Math.floor(py/grid)*grid;
  x.globalCompositeOperation='source-over';
  x.globalAlpha=+$('alpha').value/100;
  x.fillStyle=$('color').value;
  x.fillRect(gx,gy,grid,grid);
}
function drawNeon(px,py,qx,qy){
  setup();
  x.globalCompositeOperation='source-over';
  x.save();
  x.shadowBlur=Math.max(8,+$('size').value*2);
  x.shadowColor=$('color').value;
  x.strokeStyle=$('color').value;
  x.beginPath();x.moveTo(px,py);x.lineTo(qx,qy);x.stroke();
  x.restore();
}
function floodFill(px,py){
  const w=c.width,hg=c.height;
  const image=x.getImageData(0,0,w,hg),data=image.data;
  const sx=Math.floor(px),sy=Math.floor(py);
  const start=(sy*w+sx)*4;
  const target=[data[start],data[start+1],data[start+2],data[start+3]];
  const fillHex=$('color').value;
  const rr=parseInt(fillHex.slice(1,3),16),gg=parseInt(fillHex.slice(3,5),16),bb=parseInt(fillHex.slice(5,7),16);
  const aa=Math.round(+$('alpha').value*255/100);
  if(target[0]===rr&&target[1]===gg&&target[2]===bb&&target[3]===aa)return;
  const same=(i)=>data[i]===target[0]&&data[i+1]===target[1]&&data[i+2]===target[2]&&data[i+3]===target[3];
  const stack=[[sx,sy]];
  while(stack.length){
    const [px2,py2]=stack.pop();
    if(px2<0||py2<0||px2>=w||py2>=hg)continue;
    let i=(py2*w+px2)*4;
    if(!same(i))continue;
    data[i]=rr;data[i+1]=gg;data[i+2]=bb;data[i+3]=aa;
    stack.push([px2+1,py2],[px2-1,py2],[px2,py2+1],[px2,py2-1]);
  }
  x.putImageData(image,0,0);
}
function start(e){
  e.preventDefault();
  h.push(state());if(h.length>30)h.shift();f=[];
  if(c.setPointerCapture){c.setPointerCapture(e.pointerId);}
  let p=pos(e);sx=lx=p.x;sy=ly=p.y;down=true;
  if(tool==='bucket'){floodFill(p.x,p.y);down=false;}
  else if(tool==='pixel' || $('pixelMode').checked){drawPixel(p.x,p.y);}
}
function move(e){
  if(!down)return;
  e.preventDefault();
  let p=pos(e);setup();
  if(tool==='eraser'){
    x.globalCompositeOperation='destination-out';
    x.beginPath();x.moveTo(lx,ly);x.lineTo(p.x,p.y);x.stroke();
    x.globalCompositeOperation='source-over';
  }else if(tool==='neon'){
    drawNeon(lx,ly,p.x,p.y);
  }else if(tool==='pixel' || $('pixelMode').checked){
    drawPixel(p.x,p.y);
  }else{
    x.globalCompositeOperation='source-over';
    x.beginPath();x.moveTo(lx,ly);x.lineTo(p.x,p.y);x.stroke();
  }
  lx=p.x;ly=p.y;
}
function end(e){down=false;if(e&&c.releasePointerCapture){try{c.releasePointerCapture(e.pointerId);}catch(_){}}}
function undo(){
  if(!h.length)return;
  f.push(state());
  let s=h.pop();
  if(h.length)restore(s);else clearToBackground();
}
function redo(){if(!f.length)return;h.push(state());restore(f.pop())}
function clearCanvas(){h.push(state());f=[];clearToBackground()}
async function finish(){
  let r=await fetch('/draw/'+sid+'/finish',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({image:state()})
  });
  let j=await r.json();
  alert(j.ok?'Discord 채널에 업로드했습니다!':(j.error||'업로드 실패'));
}
$('transparent').addEventListener('change',()=>{
  if(!$('transparent').checked){
    h.push(state());f=[];
    const old=state();clearToBackground();
    restore(old);
  }
});
setTool('brush');
$('pixelMode').addEventListener('change',()=>{
  if($('pixelMode').checked){setTool('pixel');}
  else{setTool('brush');}
});
clearToBackground();
c.addEventListener('pointerdown',start);
c.addEventListener('pointermove',move);
c.addEventListener('pointerup',end);
c.addEventListener('pointercancel',end);
</script>
</body>
</html>
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
        # 이전에 만들어진 서버 전용 명령어를 먼저 정리해 중복 표시를 막습니다.
        cleared = 0
        for guild in bot.guilds:
            try:
                bot.tree.clear_commands(guild=guild)
                await bot.tree.sync(guild=guild)
                cleared += 1
            except Exception as guild_error:
                print(f"⚠️ {guild.name} 서버 명령어 정리 실패: {guild_error}")

        synced = await bot.tree.sync()
        print(
            f"✅ {bot.user} 연결 완료! "
            f"기존 서버 명령어 {cleared}개 정리 / "
            f"전역 명령어 {len(synced)}개 동기화"
        )
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
    if not refresh_latest_chart_daily.is_running():
        refresh_latest_chart_daily.start()

# =====================
# 실행
# =====================
bot.run(TOKEN)
