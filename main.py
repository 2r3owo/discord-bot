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
# 서버별 음악 플레이어 상태
music_states = {}

# YDL 및 FFMPEG 옵션
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn', # 비디오는 빼고 오디오만!
}

# =====================
# YouTube 쿠키 설정
# Railway 환경변수(YOUTUBE_COOKIES_B64_1 ~ _13)를
# 실제 cookies.txt 파일로 복원합니다.
# =====================
YT_COOKIE_FILE = None

def setup_youtube_cookies():
    global YT_COOKIE_FILE

    # 1) 분할된 Base64 쿠키 우선
    chunks = []
    i = 1
    while True:
        value = os.getenv(f"YOUTUBE_COOKIES_B64_{i}")
        if value is None:
            break
        chunks.append(value)
        i += 1

    # 2) 분할 변수가 없으면 단일 Base64 사용
    b64 = "".join(chunks) if chunks else os.getenv("YOUTUBE_COOKIES_B64", "")

    cookie_text = None

    if b64:
        try:
            cookie_text = base64.b64decode(b64).decode("utf-8")
        except Exception as e:
            print(f"⚠️ YouTube 쿠키 Base64 복원 실패: {e}")

    # 3) Base64가 없으면 일반 문자열 환경변수 사용
    if not cookie_text:
        raw = os.getenv("YOUTUBE_COOKIES", "")
        if raw.strip():
            cookie_text = raw

    # 4) 로컬 cookies.txt가 있으면 마지막 fallback
    if not cookie_text and os.path.exists("cookies.txt"):
        try:
            with open("cookies.txt", "r", encoding="utf-8") as f:
                cookie_text = f.read()
        except Exception as e:
            print(f"⚠️ 로컬 cookies.txt 읽기 실패: {e}")

    if cookie_text:
        path = "/tmp/youtube_cookies.txt"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(cookie_text)
            YT_COOKIE_FILE = path
            print("🍪 YouTube 쿠키 로드 완료")
        except Exception as e:
            print(f"⚠️ YouTube 쿠키 파일 생성 실패: {e}")
    else:
        print("⚠️ YouTube 쿠키가 없습니다.")

setup_youtube_cookies()

YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'nocheckcertificate': True,
    'remote_components': {'ejs:github'},
    'js_runtimes': {'deno': {}},
}

if YT_COOKIE_FILE:
    YDL_OPTIONS['cookiefile'] = YT_COOKIE_FILE


# =====================
# 보조 함수 (대기열 관리)
# =====================

def _yt_search_target(search):
    return search if search.startswith(("https://", "http://")) else f"ytsearch:{search}"

def _download_youtube(search, guild_id):
    """YouTube 오디오를 /tmp에 다운로드하고 제목/썸네일/URL을 반환합니다."""
    target = _yt_search_target(search)
    output_base = f"/tmp/discord_music_{guild_id}_{secrets.token_hex(8)}"
    output_template = output_base + ".%(ext)s"

    options = dict(YDL_OPTIONS)
    options["outtmpl"] = output_template
    options["format"] = "bestaudio/best"
    options["noplaylist"] = True
    options["quiet"] = True
    options["no_warnings"] = True

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(target, download=True)
        if not info:
            raise RuntimeError("YouTube 정보를 가져오지 못했습니다.")

        if "entries" in info:
            entries = [e for e in info["entries"] if e]
            if not entries:
                raise RuntimeError("검색 결과가 없습니다.")
            info = entries[0]

        title = info.get("title", "알 수 없는 곡")
        thumbnail = info.get("thumbnail")
        webpage_url = info.get("webpage_url") or info.get("original_url") or ""

        requested = info.get("requested_downloads") or []
        candidates = []
        for item in requested:
            fp = item.get("filepath")
            if fp:
                candidates.append(fp)

        try:
            candidates.append(ydl.prepare_filename(info))
        except Exception:
            pass

        candidates.extend([
            p for p in [
                output_base + ".webm",
                output_base + ".m4a",
                output_base + ".mp4",
                output_base + ".opus",
            ] if os.path.exists(p)
        ])

        filepath = next((fp for fp in candidates if fp and os.path.isfile(fp)), None)
        if not filepath:
            import glob
            matches = glob.glob(output_base + ".*")
            filepath = next((fp for fp in matches if os.path.isfile(fp)), None)

        if not filepath:
            raise RuntimeError("오디오 파일 다운로드는 되었지만 파일을 찾지 못했습니다.")

        return {
            "path": filepath,
            "title": title,
            "thumbnail": thumbnail,
            "url": webpage_url,
        }

def _state(guild_id):
    return music_states.setdefault(guild_id, {
        "current": None,
        "player_message": None,
        "channel_id": None,
        "repeat": "off",       # off / one / all
        "shuffle": False,
        "paused": False,
        "last_channel": None,
    })

def _cleanup_file(song):
    if not song:
        return
    fp = song.get("path")
    if fp:
        try:
            if os.path.exists(fp):
                os.remove(fp)
        except Exception:
            pass

def _repeat_text(mode):
    return {"off": "반복 꺼짐", "one": "한 곡 반복", "all": "전체 반복"}.get(mode, "반복 꺼짐")

async def _find_channel(guild, channel_id=None):
    cid = channel_id
    if cid:
        ch = guild.get_channel(cid)
        if ch:
            return ch
    st = music_states.get(guild.id, {})
    cid = st.get("channel_id")
    if cid:
        ch = guild.get_channel(cid)
        if ch:
            return ch
    return None

def _play_local(guild, song, channel):
    """로컬 오디오 파일을 재생합니다."""
    vc = guild.voice_client
    if not vc:
        raise RuntimeError("음성 채널에 연결되어 있지 않습니다.")

    source = discord.FFmpegPCMAudio(song["path"], executable="ffmpeg", options="-vn")
    vc.play(
        source,
        after=lambda e: asyncio.run_coroutine_threadsafe(
            _after_song(guild.id, channel.id, e), bot.loop
        )
    )
    st = _state(guild.id)
    st["current"] = song
    st["channel_id"] = channel.id
    st["paused"] = False
    return source

def _queue_text(guild_id):
    q = queues.get(guild_id, deque())
    if not q:
        return "아직 대기 중인 곡이 없어요."
    lines = []
    for i, song in enumerate(list(q)[:8], 1):
        lines.append(f"`{i:02}` {song['title']}")
    if len(q) > 8:
        lines.append(f"… 외 {len(q)-8}곡")
    return "\n".join(lines)

def _player_embed(guild_id):
    st = _state(guild_id)
    song = st.get("current")
    repeat = _repeat_text(st.get("repeat", "off"))
    if song:
        title = song.get("title", "알 수 없는 곡")
        status = "⏸️ 일시정지" if st.get("paused") else "▶️ 재생 중"
        desc = f"**{title}**\n{status}\n\n📥 **다음 곡**\n{_queue_text(guild_id)}\n\n대기열 {len(queues.get(guild_id, deque()))}곡  ·  🔁 {repeat}"
        embed = discord.Embed(title="🎵 하치와래 MUSIC", description=desc, color=0x5865F2)
        thumb = song.get("thumbnail")
        if thumb:
            embed.set_thumbnail(url=thumb)
    else:
        embed = discord.Embed(
            title="🎵 하치와래 MUSIC",
            description="재생할 곡이 없어요.\n\n📥 **다음 곡**\n아직 대기 중인 곡이 없어요.\n\n대기열 0곡  ·  🔁 꺼짐",
            color=0x5865F2,
        )
    return embed

class MusicAddModal(discord.ui.Modal, title="🎵 노래 추가"):
    search = discord.ui.TextInput(
        label="노래 제목 또는 YouTube 링크",
        placeholder="예: SEVENTEEN - 예쁘다",
        required=True,
        max_length=200,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.user.voice:
            return await interaction.response.send_message("❌ 먼저 음성채널에 들어가 주세요.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild.voice_client:
            await interaction.user.voice.channel.connect(timeout=60.0, reconnect=True)
        try:
            loop = asyncio.get_running_loop()
            song = await loop.run_in_executor(None, lambda: _download_youtube(str(self.search), guild.id))
            q = queues.setdefault(guild.id, deque())
            vc = guild.voice_client
            if vc.is_playing() or vc.is_paused():
                q.append(song)
                await update_music_player(guild)
                await interaction.followup.send(f"✅ 대기열에 추가했어요.\n**{song['title']}**", ephemeral=True)
            else:
                channel = await _find_channel(guild) or interaction.channel
                _play_local(guild, song, channel)
                await update_music_player(guild, channel)
                await interaction.followup.send("🎶 재생을 시작했어요.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 노래 추가 실패: {e}", ephemeral=True)

class MusicPlayerView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    async def _ensure_channel(self, interaction):
        st = _state(self.guild_id)
        return await _find_channel(interaction.guild, interaction.channel.id) or interaction.channel

    @discord.ui.button(label="⏹️", style=discord.ButtonStyle.danger, row=0)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        st = _state(self.guild_id)
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            st["paused"] = False
            await update_music_player(interaction.guild)
            await interaction.response.send_message("⏹️ 재생을 멈췄어요. 현재 곡은 플레이어에 남아 있어요.", ephemeral=True)
        else:
            await interaction.response.send_message("이미 멈춰 있어요.", ephemeral=True)

    @discord.ui.button(label="⏮️", style=discord.ButtonStyle.secondary, row=0)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = _state(self.guild_id)
        song = st.get("previous")
        if not song:
            return await interaction.response.send_message("⏮️ 이전 곡이 없어요.", ephemeral=True)
        if interaction.guild.voice_client and (interaction.guild.voice_client.is_playing() or interaction.guild.voice_client.is_paused()):
            interaction.guild.voice_client.stop()
        channel = await self._ensure_channel(interaction)
        _play_local(interaction.guild, song, channel)
        await update_music_player(interaction.guild, channel)
        await interaction.response.defer()

    @discord.ui.button(label="⏯️", style=discord.ButtonStyle.secondary, row=0)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        st = _state(self.guild_id)
        if not vc:
            return await interaction.response.send_message("❌ 음성채널에 있지 않아요.", ephemeral=True)
        if vc.is_paused():
            vc.resume()
            st["paused"] = False
        elif vc.is_playing():
            vc.pause()
            st["paused"] = True
        elif st.get("current"):
            channel = await self._ensure_channel(interaction)
            try:
                _play_local(interaction.guild, st["current"], channel)
            except Exception as e:
                return await interaction.response.send_message(f"❌ 다시 재생하지 못했어요: {e}", ephemeral=True)
        else:
            return await interaction.response.send_message("❌ 재생할 곡이 없어요.", ephemeral=True)
        await update_music_player(interaction.guild)
        await interaction.response.defer()

    @discord.ui.button(label="⏭️", style=discord.ButtonStyle.success, row=0)
    async def next_song(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc or not (vc.is_playing() or vc.is_paused()):
            return await interaction.response.send_message("❌ 재생 중인 곡이 없어요.", ephemeral=True)
        vc.stop()
        await interaction.response.defer()

    @discord.ui.button(label="🔀", style=discord.ButtonStyle.secondary, row=0)
    async def shuffle(self, interaction: discord.Interaction, button: discord.ui.Button):
        import random
        q = queues.get(self.guild_id)
        if q and len(q) > 1:
            items = list(q)
            random.shuffle(items)
            queues[self.guild_id] = deque(items)
            _state(self.guild_id)["shuffle"] = True
            await update_music_player(interaction.guild)
            await interaction.response.send_message("🔀 대기열을 섞었어요.", ephemeral=True)
        else:
            await interaction.response.send_message("🔀 섞을 대기열이 없어요.", ephemeral=True)

    @discord.ui.button(label="🔁", style=discord.ButtonStyle.secondary, row=1)
    async def repeat(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = _state(self.guild_id)
        st["repeat"] = {"off": "one", "one": "all", "all": "off"}.get(st.get("repeat", "off"), "off")
        await update_music_player(interaction.guild)
        await interaction.response.send_message(f"🔁 {_repeat_text(st['repeat'])}", ephemeral=True)

    @discord.ui.button(label="📋", style=discord.ButtonStyle.secondary, row=1)
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            f"📋 **현재 대기열**\n{_queue_text(self.guild_id)}", ephemeral=True
        )

    @discord.ui.button(label="➕", style=discord.ButtonStyle.primary, row=1)
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(MusicAddModal())

    @discord.ui.button(label="🗑️", style=discord.ButtonStyle.secondary, row=1)
    async def clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        q = queues.pop(self.guild_id, deque())
        for song in q:
            _cleanup_file(song)
        await update_music_player(interaction.guild)
        await interaction.response.send_message("🗑️ 대기열을 비웠어요.", ephemeral=True)

    @discord.ui.button(label="⭐", style=discord.ButtonStyle.secondary, row=1)
    async def info(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("⭐ 즐겨찾기 기능은 다음 단계에서 붙일 수 있어요.", ephemeral=True)

async def update_music_player(guild, channel=None):
    st = _state(guild.id)
    if channel:
        st["channel_id"] = channel.id
    ch = await _find_channel(guild, st.get("channel_id"))
    if ch is None:
        return

    embed = _player_embed(guild.id)
    view = MusicPlayerView(guild.id)
    msg = st.get("player_message")

    try:
        if msg:
            await msg.edit(embed=embed, view=view)
            return
    except Exception:
        st["player_message"] = None

    # 봇이 재시작했어도 최근 메시지에서 기존 플레이어를 재사용
    try:
        async for m in ch.history(limit=30):
            if m.author.id == bot.user.id and m.embeds and m.embeds[0].title == "🎵 하치와래 MUSIC":
                st["player_message"] = m
                await m.edit(embed=embed, view=view)
                return
    except Exception:
        pass

    st["player_message"] = await ch.send(embed=embed, view=view)

async def _after_song(guild_id, channel_id, error=None):
    guild = bot.get_guild(guild_id)
    if not guild:
        return
    st = _state(guild_id)
    current = st.get("current")

    if error:
        print(f"❌ FFmpeg 재생 오류: {error}")

    # 반복 한 곡: 같은 파일을 다시 재생
    if st.get("repeat") == "one" and current:
        channel = await _find_channel(guild, channel_id)
        if channel:
            try:
                _play_local(guild, current, channel)
                await update_music_player(guild, channel)
                return
            except Exception as e:
                print(f"❌ 한 곡 반복 오류: {e}")

    # 전체 반복: 현재 곡을 대기열 끝에 넣음
    if current and st.get("repeat") == "all":
        queues.setdefault(guild_id, deque()).append(current)

    # 다음 곡
    q = queues.get(guild_id)
    if q:
        next_song = q.popleft()
        st["previous"] = current
        channel = await _find_channel(guild, channel_id)
        if channel:
            try:
                _play_local(guild, next_song, channel)
                await update_music_player(guild, channel)
                return
            except Exception as e:
                print(f"❌ 다음 곡 재생 오류: {e}")
                _cleanup_file(next_song)
                await _after_song(guild_id, channel_id, e)
                return

    # 재생이 끝났으면 현재 곡은 유지하되 상태만 종료
    st["paused"] = False
    await update_music_player(guild)

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
    # 퇴장할 때 남아있는 임시 오디오 파일 정리
    q = queues.pop(interaction.guild.id, deque())
    for song in q:
        try:
            os.remove(song["path"])
        except Exception:
            pass

    if interaction.guild.voice_client:
        if interaction.guild.voice_client.is_playing() or interaction.guild.voice_client.is_paused():
            interaction.guild.voice_client.stop()
        await interaction.guild.voice_client.disconnect()
        st = _state(interaction.guild.id)
        st["current"] = None
        st["paused"] = False
        await update_music_player(interaction.guild, interaction.channel)
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

    guild = interaction.guild
    old_queue = queues.pop(guild.id, deque())
    for song in old_queue:
        _cleanup_file(song)

    try:
        loop = asyncio.get_running_loop()
        song = await loop.run_in_executor(None, lambda: _download_youtube(search, guild.id))

        if guild.voice_client.is_playing() or guild.voice_client.is_paused():
            guild.voice_client.stop()

        st = _state(guild.id)
        st["previous"] = st.get("current")
        _play_local(guild, song, interaction.channel)
        await update_music_player(guild, interaction.channel)
        await interaction.followup.send("🎶 플레이어를 업데이트했어요.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ 재생 중 오류 발생: {e}", ephemeral=True)

@bot.tree.command(name="야기다려", description="노래를 대기열에 추가합니다.")
async def 야기다려(interaction: discord.Interaction, search: str):
    if not interaction.user.voice:
        return await interaction.response.send_message("❌ 음성채널에 먼저 들어가 주세요", ephemeral=True)

    await interaction.response.defer(ephemeral=True)

    if not interaction.guild.voice_client:
        await interaction.user.voice.channel.connect(timeout=60.0, reconnect=True)

    try:
        loop = asyncio.get_running_loop()
        song = await loop.run_in_executor(None, lambda: _download_youtube(search, interaction.guild.id))
        q = queues.setdefault(interaction.guild.id, deque())

        if interaction.guild.voice_client.is_playing() or interaction.guild.voice_client.is_paused():
            q.append(song)
            await update_music_player(interaction.guild, interaction.channel)
            await interaction.followup.send("📥 대기열에 추가했어요.", ephemeral=True)
        else:
            _play_local(interaction.guild, song, interaction.channel)
            await update_music_player(interaction.guild, interaction.channel)
            await interaction.followup.send("🎶 재생을 시작했어요.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ 대기열 추가 중 오류 발생: {e}", ephemeral=True)

@bot.tree.command(name="야멈춰", description="재생 중인 노래를 중지합니다.")
async def 야멈춰(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and (vc.is_playing() or vc.is_paused()):
        vc.stop()
        await update_music_player(interaction.guild, interaction.channel)
        await interaction.response.send_message("⏹️ 재생을 멈췄어요.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ 재생 중인 노래가 없어요.", ephemeral=True)

@bot.tree.command(name="야넘겨", description="현재 노래를 건너뛰고 다음 곡을 재생합니다.")
async def 야넘겨(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and (vc.is_playing() or vc.is_paused()):
        vc.stop()
        await interaction.response.send_message("⏭️ 다음 곡으로 넘겼어요.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ 넘길 노래가 없습니다.", ephemeral=True)

@bot.tree.command(name="야목록", description="현재 노래 대기열을 확인합니다.")
async def 야목록(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"📋 **현재 대기열**\n{_queue_text(interaction.guild.id)}",
        ephemeral=True
    )

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
# 🎡 결정장애용 룰렛
# =====================
roulette_data = {}

class RouletteSetupModal(discord.ui.Modal, title="🎡 룰렛 설정"):
    options_input = discord.ui.TextInput(
        label="선택지를 입력하세요",
        placeholder="치킨\n피자\n햄버거\n떡볶이\n라면\n초밥",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        raw = str(self.options_input.value)
        options = [x.strip() for x in raw.splitlines() if x.strip()]

        # 쉼표로 적어도 사용할 수 있게 보조 지원
        if len(options) <= 1 and "," in raw:
            options = [x.strip() for x in raw.split(",") if x.strip()]

        if len(options) < 2:
            return await interaction.response.send_message(
                "❌ 선택지는 최소 2개를 입력해 주세요.",
                ephemeral=True
            )

        if len(options) > 20:
            return await interaction.response.send_message(
                "❌ 선택지는 최대 20개까지 입력할 수 있어요.",
                ephemeral=True
            )

        roulette_data[interaction.user.id] = options

        embed = make_roulette_embed(
            options,
            result=None,
            owner_name=interaction.user.display_name
        )
        await interaction.response.edit_message(
            embed=embed,
            view=RouletteView(interaction.user.id)
        )


def make_roulette_embed(options, result=None, owner_name=""):
    # Discord 메시지에서는 실제 원판 애니메이션 대신 색상 원형 이모지로
    # 선택지를 보기 쉽게 표시하고, 돌리기 버튼으로 랜덤 결과를 뽑습니다.
    wheel = ["🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "🩷", "🟤"]
    lines = []
    for i, option in enumerate(options):
        lines.append(f"{wheel[i % len(wheel)]} **{i + 1}.** {option}")

    description = "\n".join(lines)

    if result:
        result_text = f"\n\n🎉 **결과: {result}**"
    else:
        result_text = "\n\n🎯 **아래 버튼으로 선택지를 설정한 뒤 돌려보세요!**"

    embed = discord.Embed(
        title="🎡 룰렛",
        description=description + result_text,
        color=0x5865F2
    )
    embed.set_footer(text=f"{owner_name}님의 결정 룰렛")
    return embed


class RouletteView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=900)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "🔒 이 룰렛은 만든 사람만 조작할 수 있어요.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="🎡 설정", style=discord.ButtonStyle.secondary, row=0)
    async def setup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RouletteSetupModal())

    @discord.ui.button(label="🎲 돌리기", style=discord.ButtonStyle.primary, row=0)
    async def spin_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        options = roulette_data.get(self.owner_id, [])
        if len(options) < 2:
            return await interaction.response.send_message(
                "❌ 먼저 **🎡 설정** 버튼으로 선택지를 2개 이상 넣어 주세요.",
                ephemeral=True
            )

        import random
        result = random.choice(options)

        # 결과는 버튼을 누른 사람에게만 표시하지 않고 룰렛 메시지 자체를 갱신합니다.
        # 같은 메시지를 업데이트하므로 채널에 메시지가 계속 쌓이지 않습니다.
        embed = make_roulette_embed(
            options,
            result=result,
            owner_name=interaction.user.display_name
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🔄 다시 돌리기", style=discord.ButtonStyle.success, row=1)
    async def again_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        options = roulette_data.get(self.owner_id, [])
        if len(options) < 2:
            return await interaction.response.send_message(
                "❌ 먼저 선택지를 설정해 주세요.",
                ephemeral=True
            )

        import random
        result = random.choice(options)
        embed = make_roulette_embed(
            options,
            result=result,
            owner_name=interaction.user.display_name
        )
        await interaction.response.edit_message(embed=embed, view=self)


@bot.tree.command(name="룰렛", description="선택하기 어려울 때 돌리는 결정 룰렛을 엽니다.")
async def 룰렛(interaction: discord.Interaction):
    options = roulette_data.get(interaction.user.id, [])

    if options:
        embed = make_roulette_embed(
            options,
            result=None,
            owner_name=interaction.user.display_name
        )
    else:
        embed = discord.Embed(
            title="🎡 룰렛",
            description=(
                "선택하기 어려울 때 사용하는 결정 룰렛이에요!\n\n"
                "아래 **🎡 설정** 버튼을 눌러 선택지를 넣어 주세요.\n\n"
                "예시\n"
                "🔴 1. 치킨\n"
                "🟠 2. 피자\n"
                "🟡 3. 햄버거\n"
                "🟢 4. 떡볶이"
            ),
            color=0x5865F2
        )
        embed.set_footer(text=f"{interaction.user.display_name}님의 결정 룰렛")

    await interaction.response.send_message(
        embed=embed,
        view=RouletteView(interaction.user.id)
    )

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
button,input{margin:3px;padding:7px}
button{border:1px solid #ccc;border-radius:7px;background:#fff;cursor:pointer}
button:hover{background:#f1f3f5}
button.active{background:#5865f2;color:#fff;border-color:#5865f2}
.tools{display:flex;align-items:center;flex-wrap:wrap;gap:4px;margin-top:8px}
.colorWrap,.sizeWrap{display:flex;align-items:center;gap:5px;margin:3px;padding:0 5px}
#color{width:42px;height:34px;padding:2px}
#size{width:130px;padding:0}
#sizeValue{min-width:20px;text-align:center;font-weight:bold}
canvas{display:block;background:white;border:1px solid #ccc;margin:12px auto;max-width:calc(100% - 24px);touch-action:none}
</style></head><body>
<div id="bar">
<b>🎨 Discord 그림판</b>
<div class="tools">
  <button id="brushBtn" class="active" onclick="setTool('brush')">🖌️ 브러쉬</button>
  <button id="eraserBtn" onclick="setTool('eraser')">🧽 지우개</button>

  <label class="colorWrap">
    🎨 색
    <input id="color" type="color" value="#000000">
  </label>

  <label class="sizeWrap">
    굵기
    <input id="size" type="range" min="1" max="60" value="6">
    <span id="sizeValue">6</span>
  </label>

  <button onclick="undo()">↩️ 실행취소</button>
  <button onclick="redo()">↪️ 다시실행</button>
  <button onclick="clearCanvas()">🗑️ 초기화</button>
  <button onclick="finish()">📤 Discord에 올리기</button>
</div>
</div>
<canvas id="c" width="1000" height="700"></canvas>
<script>
const sid={{sid|tojson}}, c=document.getElementById('c'), x=c.getContext('2d');
let tool='brush',down=false,lx=0,ly=0,h=[],f=[];
x.fillStyle='#fff';x.fillRect(0,0,c.width,c.height);

function pos(e){
  let r=c.getBoundingClientRect();
  return {
    x:(e.clientX-r.left)*c.width/r.width,
    y:(e.clientY-r.top)*c.height/r.height
  };
}
function state(){return c.toDataURL('image/png')}
function restore(s){
  let i=new Image();
  i.onload=()=>{
    x.clearRect(0,0,c.width,c.height);
    x.drawImage(i,0,0);
  };
  i.src=s;
}
function setup(){
  x.lineWidth=+size.value;
  x.globalAlpha=1;
  x.lineCap='round';
  x.lineJoin='round';
  x.strokeStyle=color.value;
}
function setTool(t){
  tool=t;
  document.getElementById('brushBtn').classList.toggle('active',t==='brush');
  document.getElementById('eraserBtn').classList.toggle('active',t==='eraser');
  c.style.cursor=t==='eraser'?'cell':'crosshair';
}
function start(e){
  e.preventDefault();
  h.push(state());
  if(h.length>50)h.shift();
  f=[];
  let p=pos(e);
  lx=p.x;ly=p.y;down=true;

  // 클릭만 해도 점이 찍히도록 처리
  setup();
  x.globalCompositeOperation=tool==='eraser'?'destination-out':'source-over';
  x.beginPath();
  x.arc(lx,ly,Math.max(0.5,+size.value/2),0,Math.PI*2);
  x.fillStyle=tool==='eraser'?'rgba(0,0,0,1)':color.value;
  x.fill();
  x.globalCompositeOperation='source-over';
}
function move(e){
  if(!down)return;
  e.preventDefault();
  let p=pos(e);
  setup();
  x.globalCompositeOperation=tool==='eraser'?'destination-out':'source-over';
  x.beginPath();
  x.moveTo(lx,ly);
  x.lineTo(p.x,p.y);
  x.stroke();
  x.globalCompositeOperation='source-over';
  lx=p.x;ly=p.y;
}
function end(){down=false}
function undo(){
  if(!h.length)return;
  f.push(state());
  let s=h.pop();
  if(h.length)restore(s);
  else{
    x.clearRect(0,0,c.width,c.height);
    x.globalCompositeOperation='source-over';
    x.fillStyle='#fff';
    x.fillRect(0,0,c.width,c.height);
  }
}
function redo(){
  if(!f.length)return;
  h.push(state());
  restore(f.pop());
}
function clearCanvas(){
  h.push(state());
  f=[];
  x.globalCompositeOperation='source-over';
  x.clearRect(0,0,c.width,c.height);
  x.fillStyle='#fff';
  x.fillRect(0,0,c.width,c.height);
}
size.addEventListener('input',()=>sizeValue.textContent=size.value);
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

@bot.tree.command(name="그림대회",description="그림대회용 그림판을 엽니다.")
async def 그림대회(interaction: discord.Interaction):
    if interaction.guild is None:
        return await interaction.response.send_message("❌ 서버에서 사용해 주세요.",ephemeral=True)
    cleanup_draw_sessions()
    sid=secrets.token_urlsafe(32)
    draw_sessions[sid]={"guild_id":interaction.guild.id,"channel_id":interaction.channel.id,"user_id":interaction.user.id,"created":time.time()}
    view=discord.ui.View()
    view.add_item(discord.ui.Button(label="🏆 그림대회 그림판 열기",style=discord.ButtonStyle.link,url=f"{DRAW_URL}/draw/{sid}"))
    await interaction.response.send_message(f"🏆 {interaction.user.mention}님, 그림대회 그림판을 열었어요!",view=view)

@bot.event
async def on_ready():
    try:
        synced=await bot.tree.sync()
        print(f"✅ {bot.user} 연결 완료! {len(synced)}개 명령어 동기화됨")
    except Exception as e:
        print(f"❌ 명령어 동기화 오류: {e}")
    if not getattr(bot,"_draw_started",False):
        bot._draw_started=True
        threading.Thread(target=run_draw_server,daemon=True).start()
        print(f"🎨 그림판 서버 시작: {DRAW_URL}")

# =====================
# 실행
# =====================
bot.run(TOKEN)