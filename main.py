import os
import sys
import subprocess
import importlib

# ══════════════════════════════════════════════
# Windows: 注入 GTK3 路径（仅 cairosvg 降级时用到）
# ══════════════════════════════════════════════
if sys.platform == "win32":
    for _p in [r"C:\Program Files\GTK3-Runtime Win64\bin",
               r"C:\Program Files (x86)\GTK3-Runtime Win64\bin"]:
        if os.path.isdir(_p):
            os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(_p)
                except Exception:
                    pass
            break

# ══════════════════════════════════════════════
# 依赖自检
# ══════════════════════════════════════════════
_REQUIRED_PACKAGES = [
    ("httpx", "httpx"),
    ("PIL",   "Pillow"),
]


def _check_and_install_deps():
    missing = []
    for import_name, pip_name in _REQUIRED_PACKAGES:
        try:
            importlib.import_module(import_name)
        except Exception:
            missing.append(pip_name)
    if not missing:
        return []
    print(f"⚠️ [Phi猜歌] 检测到缺失依赖：{', '.join(missing)}，正在自动安装...")
    for pkg in missing:
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", pkg,
                 "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"],
                stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
            )
            print(f"✅ [Phi猜歌] 已安装 {pkg}")
        except Exception as e:
            print(f"❌ [Phi猜歌] 安装 {pkg} 失败: {e}")
    return missing


_check_and_install_deps()

import json
import re
import time
import random
import tempfile
import httpx
from io import BytesIO
from urllib.parse import quote
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger

# ══════════════════════════════════════════════
# 常量
# ══════════════════════════════════════════════
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
SCORE_DB = os.path.join(DATA_DIR, "guess_scores.json")
SONG_POOL_FILE = os.path.join(DATA_DIR, "song_pool.json")

# ★ 兄弟插件（查分插件）的别名库路径
SIBLING_PLUGIN_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "astrbot_plugin_phi_custom",
)
SIBLING_ALIAS_FILE = os.path.join(SIBLING_PLUGIN_DIR, "data", "aliases.json")
SIBLING_DEFAULT_ALIAS_FILE = os.path.join(SIBLING_PLUGIN_DIR, "default_aliases.json")

ILLUSTRATION_CDN = "https://somnia.xtower.site/lilith/ill"

ROUND_SIZE = 10
GAME_TIMEOUT = 600
CONFIRM_TIMEOUT = 30


def load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载 {path} 失败: {e}")
    return default if default is not None else {}


def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"保存 {path} 失败: {e}")


def _normalize(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def is_valid_image(data: bytes, min_size: int = 500) -> bool:
    return bool(data) and len(data) >= min_size


class PhiGuessPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}
        self.api_url = self.config.get("phi_api_url", "https://r0semi.xtower.site").rstrip("/")
        self.api_key = self.config.get("lilith_api_key", "")
        self.proxy = self.config.get("proxy_url", "")
        self.timeout = self.config.get("timeout", 30)

        self._games = {}
        self._pending_stop = {}
        self._song_pool = []
        self._pool_loaded = False

        self.aliases = {}
        self._load_aliases_from_sibling()

        logger.info(f"✅ Phi 猜歌插件已加载！别名库：{len(self.aliases)} 条")

    def _load_aliases_from_sibling(self):
        aliases = load_json(SIBLING_ALIAS_FILE, None)
        if aliases:
            self.aliases = aliases
            logger.info(f"📚 已从查分插件 aliases.json 加载 {len(aliases)} 条别名")
            return
        defaults = load_json(SIBLING_DEFAULT_ALIAS_FILE, None)
        if defaults:
            self.aliases = defaults
            logger.info(f"📚 已从查分插件 default_aliases.json 加载 {len(defaults)} 条别名")
            return
        logger.warning("⚠️ 未找到查分插件的别名库，猜歌仅支持精确匹配")

    def _reload_aliases(self):
        self._load_aliases_from_sibling()

    def _headers(self):
        return {
            "X-OpenApi-Token": self.api_key,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

    # ══════════════════════════════════════════════
    # 遮罩逻辑
    # ══════════════════════════════════════════════
    @staticmethod
    def _is_maskable(ch: str) -> bool:
        if ch.isalnum():
            return True
        if '\u4e00' <= ch <= '\u9fff':
            return True
        return False

    def _mask_with_revealed(self, name: str, revealed: set) -> str:
        out = []
        for i, ch in enumerate(name):
            if self._is_maskable(ch):
                out.append(ch if i in revealed else '*')
            else:
                out.append(ch)
        return "".join(out)

    def _render_board(self, game: dict) -> str:
        lines = [f"📋 **猜歌列表**（{len(game['songs'])} 首）\n━━━━━━━━━━━━━━━━"]
        for i, s in enumerate(game["songs"], 1):
            if s["solved"]:
                lines.append(f"{i}. **{s['name']}** ✅ {s.get('solver_name', '?')}")
            else:
                lines.append(f"{i}. {self._mask_with_revealed(s['name'], s['revealed'])}")
        solved_count = sum(1 for s in game["songs"] if s["solved"])
        lines.append("━━━━━━━━━━━━━━━━")
        lines.append(f"📊 进度：{solved_count}/{len(game['songs'])}")
        return "\n".join(lines)

    # ══════════════════════════════════════════════
    # 歌曲池
    # ══════════════════════════════════════════════
    async def _fetch_songs(self, keyword: str) -> list:
        try:
            async with httpx.AsyncClient(
                proxy=self.proxy if self.proxy else None,
                timeout=self.timeout
            ) as client:
                resp = await client.get(
                    f"{self.api_url}/api/v1/open/songs/search",
                    params={"q": keyword},
                    headers=self._headers()
                )
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("items", [])
                    return [s for s in items if s.get("name") and s.get("id")]
                logger.warning(f"songs/search [{keyword}] 返回 {resp.status_code}")
        except Exception as e:
            logger.error(f"songs/search 异常: {e}")
        return []

    async def _load_song_pool(self) -> list:
        if self._pool_loaded and self._song_pool:
            return self._song_pool

        cached = load_json(SONG_POOL_FILE, [])
        if cached:
            self._song_pool = cached
            self._pool_loaded = True
            logger.info(f"📚 从缓存加载 {len(cached)} 首歌")
            return self._song_pool

        songs = await self._fetch_songs("")
        if not songs:
            logger.info("⚠️ 空查询无结果，改用字母组合查询...")
            seen = {}
            for kw in ["a", "e", "i", "o", "s", "r", "t", "n", "m", "k", "d", "c", "l", "p", "b", "u"]:
                batch = await self._fetch_songs(kw)
                for s in batch:
                    sid = s.get("id")
                    if sid and sid not in seen:
                        seen[sid] = s
            songs = list(seen.values())

        if songs:
            self._song_pool = songs
            self._pool_loaded = True
            save_json(SONG_POOL_FILE, songs)
            logger.info(f"📚 已缓存 {len(songs)} 首歌")

        return self._song_pool

    # ══════════════════════════════════════════════
    # 匹配判定（支持别名）
    # ══════════════════════════════════════════════
    def _matches(self, guess: str, correct_name: str) -> bool:
        g = _normalize(guess)
        c = _normalize(correct_name)

        if g == c:
            return True

        guess_resolved = self.aliases.get(guess.strip())
        if guess_resolved and _normalize(guess_resolved) == c:
            return True

        for alias, real in self.aliases.items():
            if _normalize(real) == c and _normalize(alias) == g:
                return True

        return False

    async def _get_illustration(self, song_id: str) -> bytes | None:
        encoded_id = quote(song_id, safe="")
        url = f"{ILLUSTRATION_CDN}/{encoded_id}.webp"
        try:
            async with httpx.AsyncClient(
                proxy=self.proxy if self.proxy else None,
                timeout=self.timeout
            ) as client:
                r = await client.get(url)
                if r.status_code == 200 and len(r.content) > 1000:
                    return r.content
        except Exception:
            pass
        return None

    async def _send_image(self, event: AstrMessageEvent, img_bytes: bytes):
        try:
            from PIL import Image
            img = Image.open(BytesIO(img_bytes))
            if img.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", img.size, (20, 24, 38))
                if img.mode == "P":
                    img = img.convert("RGBA")
                bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")
            if img.width > 800:
                ratio = 800 / img.width
                img = img.resize((800, int(img.height * ratio)), Image.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=85, optimize=True)
            data = buf.getvalue()
        except Exception as e:
            logger.error(f"曲绘处理失败: {e}")
            return None

        try:
            fd, path = tempfile.mkstemp(suffix=".jpg", prefix="phi_guess_")
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            return event.image_result(path)
        except Exception as e:
            logger.error(f"曲绘发送失败: {e}")
            return None

    # ══════════════════════════════════════════════
    # 游戏逻辑
    # ══════════════════════════════════════════════
    async def _start_game(self, event: AstrMessageEvent):
        group_id = event.get_group_id() or event.get_sender_id()

        if group_id in self._games:
            yield event.plain_result(f"⚠️ 本群已有进行中的猜歌！\n\n{self._render_board(self._games[group_id])}")
            return

        self._reload_aliases()

        pool = await self._load_song_pool()
        if not pool:
            yield event.plain_result("❌ 未能获取歌曲池，请检查 API 配置。")
            return

        candidates = [s for s in pool if 3 <= len(s["name"]) <= 30]
        if len(candidates) < ROUND_SIZE:
            candidates = pool

        picked = random.sample(candidates, min(ROUND_SIZE, len(candidates)))

        self._games[group_id] = {
            "songs": [
                {
                    "id": s["id"],
                    "name": s["name"],
                    "composer": s.get("composer", ""),
                    "solved": False,
                    "solver_id": None,
                    "solver_name": None,
                    "revealed": set(),
                }
                for s in picked
            ],
            "start_time": time.time(),
            "starter_id": event.get_sender_id(),
        }

        game = self._games[group_id]
        yield event.plain_result(
            f"🎵 **猜歌开始！**\n\n"
            f"{self._render_board(game)}\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"✅ 提交答案：`/猜歌 <编号> <曲名>`\n"
            f"🔓 揭字符：`/猜歌 开<字符>`（例如 `/猜歌 开d`）\n"
            f"🛑 结束游戏：`/猜歌 结束`\n"
            f"💡 支持别名（如「痉挛」对应 Spasmodic）\n"
            f"⏱️ 限时 {GAME_TIMEOUT // 60} 分钟"
        )

    # ★ 揭字符：在所有未猜对的歌曲中，把该字符全部揭开
    async def _reveal_char(self, event: AstrMessageEvent, char: str):
        group_id = event.get_group_id() or event.get_sender_id()
        game = self._games.get(group_id)
        if not game:
            yield event.plain_result("⚠️ 当前没有进行中的猜歌。")
            return

        char = char.strip()
        if len(char) != 1:
            yield event.plain_result("⚠️ 只能开一个字符，用法：`/猜歌 开<字符>`（例如 `/猜歌 开d`）")
            return

        if not self._is_maskable(char):
            yield event.plain_result(f"⚠️ 「{char}」不是可揭开的字符（只支持字母、数字、汉字）。")
            return

        ch_lower = char.lower()

        # 遍历所有未猜对的歌曲，找出包含该字符的位置，全部揭开
        affected = []
        total_hits = 0
        for idx, s in enumerate(game["songs"]):
            if s["solved"]:
                continue
            hits = []
            for i, c in enumerate(s["name"]):
                if c.lower() == ch_lower and i not in s["revealed"]:
                    hits.append(i)
            if hits:
                for i in hits:
                    s["revealed"].add(i)
                total_hits += len(hits)
                affected.append(idx + 1)

        if not affected:
            yield event.plain_result(f"💡 曲库中没有包含「{char}」的歌曲（或该字符已全部揭开）。")
            return

        yield event.plain_result(
            f"🔓 字符「{char}」已在 {len(affected)} 首歌中揭开，共 {total_hits} 处\n"
            f"涉及编号：{', '.join(str(x) for x in affected)}\n\n"
            f"{self._render_board(game)}"
        )

    async def _submit_answer(self, event: AstrMessageEvent, num: int, answer: str):
        group_id = event.get_group_id() or event.get_sender_id()
        game = self._games.get(group_id)
        if not game:
            yield event.plain_result("⚠️ 当前没有进行中的猜歌。")
            return

        if num < 1 or num > len(game["songs"]):
            yield event.plain_result(f"⚠️ 编号必须在 1~{len(game['songs'])} 之间。")
            return

        song = game["songs"][num - 1]

        if song["solved"]:
            yield event.plain_result(f"💡 这首歌已被 {song.get('solver_name', '?')} 猜对了。")
            return

        if self._matches(answer, song["name"]):
            song["solved"] = True
            song["solver_id"] = event.get_sender_id()
            song["solver_name"] = event.get_sender_name()

            scores = load_json(SCORE_DB, {})
            if group_id not in scores:
                scores[group_id] = {}
            uid = event.get_sender_id()
            scores[group_id][uid] = scores[group_id].get(uid, 0) + 1
            save_json(SCORE_DB, scores)

            solved_count = sum(1 for s in game["songs"] if s["solved"])

            yield event.plain_result(
                f"✅ **{event.get_sender_name()} 猜对了！**\n"
                f"🎵 {num}. **{song['name']}**\n\n"
                f"{self._render_board(game)}"
            )

            if solved_count == len(game["songs"]):
                yield event.plain_result("🎉 **本轮全部猜完，游戏结束！**")
                async for r in self._finalize_game(group_id, event):
                    yield r
                return
        else:
            yield event.plain_result(
                f"❌ 「{answer}」不对，再试试。\n"
                f"📊 当前进度：{sum(1 for s in game['songs'] if s['solved'])}/{len(game['songs'])}"
            )

    async def _confirm_stop(self, event: AstrMessageEvent):
        group_id = event.get_group_id() or event.get_sender_id()
        game = self._games.get(group_id)
        if not game:
            yield event.plain_result("⚠️ 当前没有进行中的猜歌。")
            return

        self._pending_stop[group_id] = {
            "user_id": event.get_sender_id(),
            "time": time.time()
        }
        yield event.plain_result(
            "⚠️ **确认要结束本轮猜歌吗？**\n"
            "回复 `确认` 立即结束，回复其他内容取消。\n"
            f"（{CONFIRM_TIMEOUT} 秒内有效）"
        )

    async def _do_stop(self, event: AstrMessageEvent):
        group_id = event.get_group_id() or event.get_sender_id()
        game = self._games.pop(group_id, None)
        self._pending_stop.pop(group_id, None)
        if not game:
            return
        lines = ["🛑 **本轮猜歌已结束。**\n━━━━━━━━━━━━━━━━"]
        for i, s in enumerate(game["songs"], 1):
            if s["solved"]:
                lines.append(f"{i}. {s['name']} ✅ {s.get('solver_name', '?')}")
            else:
                lines.append(f"{i}. {s['name']} ❌ 无人猜对")
        yield event.plain_result("\n".join(lines))

    async def _finalize_game(self, group_id: str, event: AstrMessageEvent):
        game = self._games.pop(group_id, None)
        if not game:
            return
        solved = [s for s in game["songs"] if s["solved"]]
        for s in solved[:3]:
            ill = await self._get_illustration(s["id"])
            if ill:
                result = await self._send_image(event, ill)
                if result is not None:
                    yield result

    # ══════════════════════════════════════════════
    # 主指令：/猜歌
    # ══════════════════════════════════════════════
    @filter.command("猜歌")
    async def cmd_guess(self, event: AstrMessageEvent):
        raw = event.message_str.strip()
        if raw.startswith("/"):
            raw = raw[1:]
        if raw.startswith("猜歌"):
            raw = raw[2:].strip()
        args = raw
        group_id = event.get_group_id() or event.get_sender_id()

        if group_id in self._pending_stop:
            pending = self._pending_stop[group_id]
            if time.time() - pending["time"] > CONFIRM_TIMEOUT:
                del self._pending_stop[group_id]
            elif event.get_sender_id() == pending["user_id"] and args.strip() == "确认":
                async for r in self._do_stop(event):
                    yield r
                return
            elif args.strip() and args.strip() != "确认":
                self._pending_stop.pop(group_id, None)

        if not args:
            if group_id in self._games:
                yield event.plain_result(self._render_board(self._games[group_id]))
            else:
                yield event.plain_result(
                    "🎵 **猜歌模块**\n"
                    "━━━━━━━━━━━━━━━━\n"
                    "`/猜歌 开始` - 开始一轮猜歌\n"
                    "`/猜歌 开<字符>` - 揭开该字符（例如 `/猜歌 开d`）\n"
                    "`/猜歌 <编号> <曲名>` - 猜某序号是什么歌\n"
                    "`/猜歌 结束` - 强制结束（需确认）\n"
                    "`/猜歌 rank` - 查看排行榜\n"
                    "`/猜歌 help` - 详细帮助"
                )
            return

        if args == "开始":
            async for r in self._start_game(event):
                yield r
            return

        if args == "结束":
            async for r in self._confirm_stop(event):
                yield r
            return

        if args.lower() in ("help", "帮助"):
            yield event.plain_result(
                "📖 **猜歌玩法**\n"
                "━━━━━━━━━━━━━━━━\n"
                "1. 发送 `/猜歌 开始` 开始一轮\n"
                "2. 系统随机出 10 首歌，名字用 `*` 遮住\n"
                "3. 用 `/猜歌 <编号> <曲名>` 提交答案\n"
                "4. 猜对则整首歌揭晓，并计分\n"
                "5. 用 `/猜歌 开<字符>` 揭开该字符，例如 `/猜歌 开d`，曲库中所有含 d 的歌曲都会揭开该字符\n"
                "6. 全部猜完自动结束\n"
                "━━━━━━━━━━━━━━━━\n"
                "💡 支持别名（与查分插件共享别名库）\n"
                "🔧 其他：`/猜歌 结束`、`/猜歌 rank`"
            )
            return

        if args.lower() in ("rank", "排行", "排行榜"):
            scores = load_json(SCORE_DB, {})
            if group_id not in scores or not scores[group_id]:
                yield event.plain_result("📊 本群暂无猜歌记录。")
                return
            sorted_scores = sorted(scores[group_id].items(), key=lambda x: x[1], reverse=True)
            lines = ["🏆 **猜歌排行榜**\n━━━━━━━━━━━━━━━━"]
            for i, (uid, score) in enumerate(sorted_scores[:10], 1):
                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                lines.append(f"{medal} {uid}：{score} 分")
            yield event.plain_result("\n".join(lines))
            return

        # ★ 揭字符
        if args.startswith("开"):
            ch = args[1:].strip()
            if not ch:
                yield event.plain_result("⚠️ 用法：`/猜歌 开<字符>`（例如 `/猜歌 开d`）")
                return
            async for r in self._reveal_char(event, ch):
                yield r
            return

        # /猜歌 <编号> <曲名>
        parts = args.split(None, 1)
        if len(parts) >= 2 and parts[0].isdigit():
            num = int(parts[0])
            answer = parts[1].strip()
            async for r in self._submit_answer(event, num, answer):
                yield r
            return

        yield event.plain_result("⚠️ 用法错误。发送 `/猜歌` 查看指令列表。")

    # ══════════════════════════════════════════════
    # 主指令：/随机选歌
    # ══════════════════════════════════════════════
    @filter.command("随机选歌")
    async def cmd_random(self, event: AstrMessageEvent):
        raw = event.message_str.strip()
        if raw.startswith("/"):
            raw = raw[1:]
        if raw.startswith("随机选歌"):
            raw = raw[4:].strip()
        args = raw

        difficulty = None
        level = None

        for part in args.split():
            upper = part.upper()
            if upper in ("EZ", "HD", "IN", "AT"):
                difficulty = upper
            else:
                try:
                    level = float(part)
                except ValueError:
                    pass

        if not difficulty:
            difficulty = "IN"

        pool = await self._load_song_pool()
        if not pool:
            yield event.plain_result("❌ 未能获取歌曲池，请检查配置。")
            return

        diff_key = difficulty.lower()
        filtered = []
        for s in pool:
            constants = s.get("chartConstants", {})
            const_val = constants.get(diff_key)
            if const_val is None:
                continue
            if level is not None:
                if abs(float(const_val) - level) < 0.05:
                    filtered.append(s)
            else:
                filtered.append(s)

        if not filtered:
            if level is not None:
                yield event.plain_result(f"⚠️ 未找到 {difficulty} {level} 难度的歌曲。")
            else:
                yield event.plain_result(f"⚠️ 未找到 {difficulty} 难度的歌曲。")
            return

        song = random.choice(filtered)
        constants = song.get("chartConstants", {})
        diff_val = constants.get(diff_key, "?")

        lines = [
            "🎲 **随机选歌**\n"
            "━━━━━━━━━━━━━━━━\n"
            f"🎵 **{song.get('name', '?')}**\n"
            f"🎤 曲师：{song.get('composer', '?')}\n"
            f"🎨 曲绘：{song.get('illustrator', '?')}\n"
            f"📊 难度：**{difficulty} {diff_val}**\n"
            f"🔢 全难度定数：EZ {constants.get('ez', '-')} / HD {constants.get('hd', '-')} "
            f"/ IN {constants.get('in', '-')} / AT {constants.get('at', '-')}\n"
            f"🎯 筛选结果：{len(filtered)} 首中随机一首"
        ]
        yield event.plain_result("\n".join(lines))

        ill = await self._get_illustration(song["id"])
        if ill:
            result = await self._send_image(event, ill)
            if result is not None:
                yield result

    # ══════════════════════════════════════════════
    # 消息监听：确认结束
    # ══════════════════════════════════════════════
    @filter.regex(r".+")
    async def on_message(self, event: AstrMessageEvent):
        uid = event.get_sender_id()
        group_id = event.get_group_id() or uid
        if group_id in self._pending_stop:
            pending = self._pending_stop[group_id]
            msg = event.message_str.strip()
            if (time.time() - pending["time"] <= CONFIRM_TIMEOUT
                    and uid == pending["user_id"]
                    and msg == "确认"):
                async for r in self._do_stop(event):
                    yield r
                return

    async def terminate(self):
        logger.info("❌ Phi 猜歌插件已卸载。")