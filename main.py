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
    """
    YouTube에서 오디오를 Railway 서버의 /tmp로 먼저 다운로드합니다.
    FFmpeg가 googlevideo 주소를 직접 열지 않도록 하는 방식입니다.
    """
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

        # yt-dlp가 실제로 만든 파일 찾기
        requested = info.get("requested_downloads") or []
        candidates = []

        for item in requested:
            fp = item.get("filepath")
            if fp:
                candidates.append(fp)

        # prepare_filename fallback
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
            # 혹시 확장자가 예상과 다른 경우 glob으로 찾기
            import glob
            matches = glob.glob(output_base + ".*")
            filepath = next((fp for fp in matches if os.path.isfile(fp)), None)

        if not filepath:
            raise RuntimeError("오디오 파일 다운로드는 되었지만 파일을 찾지 못했습니다.")

        return filepath, title

def _play_local(guild, filepath, title, channel):
    source = discord.FFmpegPCMAudio(filepath, executable="ffmpeg", options="-vn")
    guild.voice_client.play(
        source,
        after=lambda e: check_queue(guild.id, channel)
    )
    return source

def check_queue(guild_id, channel):
    """현재 곡이 끝나면 다음 곡을 재생합니다."""
    if guild_id in queues and queues[guild_id]:
        next_song = queues[guild_id].popleft()
        guild = channel.guild

        try:
            _play_local(guild, next_song["path"], next_song["title"], channel)
            coro = channel.send(f"🎶 다음 곡 재생: **{next_song['title']}**")
            asyncio.run_coroutine_threadsafe(coro, bot.loop)
        except Exception as e:
            print(f"❌ 다음 곡 재생 오류: {e}")
            try:
                os.remove(next_song["path"])
            except Exception:
                pass
            check_queue(guild_id, channel)
    else:
        queues.pop(guild_id, None)

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
        if interaction.guild.voice_client.is_playing():
            interaction.guild.voice_client.stop()
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

    old_queue = queues.pop(interaction.guild.id, deque())
    for song in old_queue:
        try:
            os.remove(song["path"])
        except Exception:
            pass

    old_source = getattr(interaction.guild.voice_client, "source", None)

    try:
        loop = asyncio.get_running_loop()
        filepath, title = await loop.run_in_executor(
            None,
            lambda: _download_youtube(search, interaction.guild.id)
        )

        if interaction.guild.voice_client.is_playing():
            interaction.guild.voice_client.stop()

        _play_local(interaction.guild, filepath, title, interaction.channel)
        await interaction.followup.send(f"🎶 즉시 재생 시작: **{title}**")

    except Exception as e:
        await interaction.followup.send(f"❌ 재생 중 오류 발생: {e}")

@bot.tree.command(name="야기다려", description="노래를 대기열에 추가합니다.")
async def 야기다려(interaction: discord.Interaction, search: str):
    if not interaction.user.voice:
        return await interaction.response.send_message("❌ 음성채널에 먼저 들어가 주세요", ephemeral=True)

    await interaction.response.defer()

    if not interaction.guild.voice_client:
        await interaction.user.voice.channel.connect(timeout=60.0, reconnect=True)

    try:
        loop = asyncio.get_running_loop()
        filepath, title = await loop.run_in_executor(
            None,
            lambda: _download_youtube(search, interaction.guild.id)
        )

        if interaction.guild.id not in queues:
            queues[interaction.guild.id] = deque()

        if interaction.guild.voice_client.is_playing():
            queues[interaction.guild.id].append({
                "path": filepath,
                "title": title
            })
            await interaction.followup.send(f"✅ 대기열에 추가됨: **{title}**")
        else:
            _play_local(interaction.guild, filepath, title, interaction.channel)
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