#!/usr/bin/env python3
"""Domestic music metadata, lyrics, and cover scraper for Chinese network environments.

Features:
- Dual-engine architecture: QQ Music (Tencent) + NetEase Cloud Music
- Strict artist and variant validation to prevent cover-version contamination
- Direct-connection network client (Proxy Bypass) ensuring domestic APIs are
  never blocked by overseas proxies
- High-precision synchronized LRC lyrics and 800x800 high-resolution album covers
"""
from __future__ import annotations

import base64
import html
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

try:
    import mediafile
except ImportError:
    mediafile = None

try:  # Full traditional→simplified table when the image ships it.
    import zhconv
except ImportError:
    zhconv = None

TIMEOUT = 6
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Dedicated direct-connection opener that bypasses any HTTP_PROXY / HTTPS_PROXY
_DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def _log(msg: str) -> None:
    """Print debug log message only when verbose logging is enabled."""
    if os.environ.get("MUSIC_DEBUG") == "1":
        import sys
        print(msg, file=sys.stderr, flush=True)

_TRAD_TO_SIMP = {
    "東": "东", "風": "风", "破": "破", "倫": "伦", "傑": "杰", "雙": "双", "節": "节", "棍": "棍", "晴": "晴", "天": "天",
    "愛": "爱", "開": "开", "學": "学", "會": "会", "說": "说", "時": "时", "對": "对", "長": "长", "門": "门", "問": "问",
    "關": "关", "電": "电", "動": "动", "點": "点", "華": "华", "國": "国", "書": "书", "見": "见", "車": "车", "話": "话",
    "飛": "飞", "馬": "马", "魚": "鱼", "鳥": "鸟", "龍": "龙", "樂": "乐", "聽": "听", "記": "记", "語": "语", "號": "号",
    "歲": "岁", "廣": "广", "達": "达", "園": "园", "裡": "里", "發": "发", "夢": "梦", "經": "经", "頭": "头", "歡": "欢",
    "讓": "让", "認": "认", "遠": "远", "運": "运", "選": "选", "還": "还", "進": "进", "邊": "边", "過": "过", "麼": "么",
    "燈": "灯", "練": "练", "離": "离", "難": "难", "響": "响", "雲": "云", "個": "个", "專": "专", "當": "当", "戀": "恋",
    "機": "机", "張": "张", "傳": "传", "紅": "红", "綠": "绿", "線": "线", "藍": "蓝", "陽": "阳", "陰": "阴", "體": "体",
    "輕": "轻", "鐵": "铁", "結": "结", "親": "亲", "熱": "热", "無": "无", "從": "从", "帶": "带", "態": "态", "給": "给",
    "論": "论", "請": "请", "覺": "觉", "變": "变", "讀": "读", "價": "价", "義": "义", "滿": "满", "實": "实", "現": "现",
    "應": "应", "產": "产", "連": "连", "類": "类", "誰": "谁", "總": "总", "壞": "坏", "單": "单", "塊": "块", "歷": "历",
    "聲": "声", "觀": "观", "買": "买", "條": "条", "極": "极", "斷": "断", "環": "环", "異": "异", "傷": "伤", "歸": "归",
    "淚": "泪", "憶": "忆", "戲": "戏", "殘": "残", "處": "处", "盡": "尽", "寫": "写", "瘋": "疯", "終": "终", "轉": "转",
    "葉": "叶", "惠": "惠", "靜": "静", "優": "优", "約": "约", "稱": "称", "將": "将", "數": "数", "復": "复", "開": "开",
    "詞": "词", "歌": "歌", "演": "演", "劇": "剧", "區": "区", "創": "创", "鈴": "铃",
    "萬": "万", "與": "与", "醜": "丑", "業": "业", "叢": "丛", "絲": "丝", "丟": "丢", "兩": "两", "嚴": "严",
    "喪": "丧", "豐": "丰", "臨": "临", "麗": "丽", "舉": "举", "烏": "乌", "喬": "乔", "習": "习", "鄉": "乡", 
    "亂": "乱", "爭": "争", "於": "于", "虧": "亏", "亞": "亚", "畝": "亩", "褻": "亵", "億": "亿", "僅": "仅", 
    "侖": "仑", "倉": "仓", "儀": "仪", "們": "们", "眾": "众", "夥": "伙", "傘": "伞", "偉": "伟", "倀": "伥", 
    "傖": "伧", "偽": "伪", "佇": "伫", "餘": "余", "傭": "佣", "僉": "佥", "圖": "图", "網": "网", "錄": "录"
}

# Second batch: high-frequency characters in song titles and artist names that
# the compact first table misses (來/爲/間/樣/這/別/沒 …).
_TRAD_TO_SIMP.update({
    "來": "来", "爲": "为", "為": "为", "間": "间", "樣": "样", "這": "这", "別": "别", "沒": "没",
    "題": "题", "隻": "只", "兒": "儿", "幾": "几", "繼": "继", "續": "续", "場": "场", "員": "员",
    "師": "师", "灣": "湾", "島": "岛", "鄧": "邓", "衛": "卫", "蕭": "萧", "蘇": "苏", "韓": "韩",
    "孫": "孙", "趙": "赵", "劉": "刘", "楊": "杨", "吳": "吴", "許": "许", "謝": "谢", "羅": "罗",
    "鄭": "郑", "黃": "黄", "錢": "钱", "遲": "迟", "錦": "锦", "榮": "荣", "齊": "齐", "鞏": "巩",
    "鳳": "凤", "鳴": "鸣", "濤": "涛", "剛": "刚", "樺": "桦", "樑": "梁", "潔": "洁", "瑩": "莹",
    "巖": "岩", "輯": "辑", "譜": "谱", "彈": "弹", "鋼": "钢", "簫": "箫", "鑼": "锣", "鈸": "钹",
    "準": "准", "塗": "涂", "塵": "尘", "墊": "垫", "墳": "坟", "壯": "壮", "壽": "寿", "夢": "梦",
    "夠": "够", "媽": "妈", "嫵": "妩", "嫋": "袅", "嬌": "娇", "宮": "宫", "寬": "宽", "寶": "宝",
    "寵": "宠", "尋": "寻", "屆": "届", "崗": "岗", "嶺": "岭", "巔": "巅", "幟": "帜", "幾": "几",
    "廈": "厦", "廚": "厨", "徹": "彻", "恆": "恒", "恥": "耻", "悅": "悦", "懸": "悬", "憲": "宪",
    "懶": "懒", "戰": "战", "戲": "戏", "戶": "户", "執": "执", "掃": "扫", "揚": "扬", "損": "损",
    "搖": "摇", "搶": "抢", "攝": "摄", "敗": "败", "敵": "敌", "斃": "毙", "斷": "断", "曆": "历",
    "曉": "晓", "會": "会", "東": "东", "樸": "朴", "權": "权", "歐": "欧", "歲": "岁", "殺": "杀",
    "殼": "壳", "氣": "气", "溝": "沟", "滅": "灭", "滄": "沧", "滅": "灭", "滾": "滚", "漢": "汉",
    "漸": "渐", "濕": "湿", "濤": "涛", "瀟": "潇", "瀾": "澜", "災": "灾", "烏": "乌", "煙": "烟",
    "煥": "焕", "煩": "烦", "燦": "灿", "營": "营", "燭": "烛", "牆": "墙", "犧": "牺", "狀": "状",
    "猶": "犹", "獄": "狱", "獸": "兽", "獻": "献", "瑪": "玛", "環": "环", "瓊": "琼", "甦": "苏",
    "疊": "叠", "療": "疗", "癡": "痴", "發": "发", "監": "监", "盤": "盘", "矚": "瞩", "礦": "矿",
    "碼": "码", "礎": "础", "禮": "礼", "禱": "祷", "積": "积", "穩": "稳", "窮": "穷", "競": "竞",
    "筆": "笔", "節": "节", "範": "范", "築": "筑", "簡": "简", "籃": "篮", "紀": "纪", "純": "纯",
    "紙": "纸", "級": "级", "紛": "纷", "細": "细", "組": "组", "終": "终", "絕": "绝", "統": "统",
    "綁": "绑", "經": "经", "繪": "绘", "纜": "缆", "罰": "罚", "罷": "罢", "羨": "羡", "翹": "翘",
    "聯": "联", "聰": "聪", "肅": "肃", "腎": "肾", "臉": "脸", "臘": "腊", "臨": "临", "舉": "举",
    "艦": "舰", "蘇": "苏", "虛": "虚", "蟲": "虫", "衝": "冲", "補": "补", "裝": "装", "褲": "裤",
    "覆": "覆", "見": "见", "規": "规", "視": "视", "覽": "览", "訂": "订", "計": "计", "訊": "讯",
    "討": "讨", "訓": "训", "訪": "访", "設": "设", "診": "诊", "註": "注", "評": "评", "試": "试",
    "詩": "诗", "詳": "详", "誇": "夸", "誌": "志", "誠": "诚", "誕": "诞", "誘": "诱", "調": "调",
    "談": "谈", "誼": "谊", "謀": "谋", "謎": "谜", "謙": "谦", "講": "讲", "謝": "谢", "證": "证",
    "識": "识", "譜": "谱", "警": "警", "譯": "译", "護": "护", "讀": "读", "讚": "赞", "貝": "贝",
    "負": "负", "財": "财", "貧": "贫", "貨": "货", "貴": "贵", "費": "费", "賀": "贺", "資": "资",
    "賈": "贾", "賊": "贼", "賜": "赐", "賞": "赏", "贈": "赠", "趕": "赶", "蹤": "踪", "軀": "躯",
    "車": "车", "軌": "轨", "軍": "军", "軟": "软", "載": "载", "輪": "轮", "輝": "辉", "輩": "辈",
    "農": "农", "迴": "回", "逢": "逢", "遞": "递", "遲": "迟", "遺": "遗", "邁": "迈", "鄰": "邻",
    "醜": "丑", "醞": "酝", "釀": "酿", "釋": "释", "鐘": "钟", "鑄": "铸", "鏡": "镜", "鐘": "钟",
    "閃": "闪", "閉": "闭", "閏": "闰", "閱": "阅", "闆": "板", "陣": "阵", "陸": "陆", "險": "险",
    "隱": "隐", "雖": "虽", "霧": "雾", "靈": "灵", "韻": "韵", "響": "响", "頁": "页", "頂": "顶",
    "項": "项", "順": "顺", "須": "须", "預": "预", "頑": "顽", "領": "领", "頻": "频", "顆": "颗",
    "願": "愿", "顯": "显", "飄": "飘", "飯": "饭", "飲": "饮", "飾": "饰", "飽": "饱", "餓": "饿",
    "館": "馆", "驅": "驱", "驗": "验", "驚": "惊", "骯": "肮", "鬥": "斗", "魯": "鲁", "鮮": "鲜",
    "鯨": "鲸", "鱷": "鳄", "鳴": "鸣", "鴉": "鸦", "鴻": "鸿", "鵲": "鹊", "鷹": "鹰", "麥": "麦",
    "點": "点", "黨": "党", "齊": "齐", "齒": "齿", "齡": "龄", "龍": "龙", "龜": "龟",
    "濛": "蒙", "紥": "扎", "攞": "拿", "喺": "在", "瞓": "睡", "睇": "看", "靚": "靓", "糉": "粽", "搵": "找",
    "咗": "了", "哋": "们", "嘅": "的", "嗰": "那", "嘞": "了", "諗": "想", "講": "讲", "嘢": "东西",
})

def to_simplified(text: str) -> str:
    """Normalise traditional Chinese so the domestic search APIs can match it.

    QQ/NetEase return nothing for queries such as 周杰倫 東風破; the simplified form
    周杰伦 东风破 matches the original release.  zhconv carries the full table, the
    built-in map below is the offline fallback.
    """
    if not text:
        return text
    if zhconv is not None:
        try:
            return zhconv.convert(text, "zh-cn")
        except Exception:
            pass
    return "".join(_TRAD_TO_SIMP.get(c, c) for c in text)

def _http_get_json(url: str, headers: dict | None = None, timeout: int = TIMEOUT) -> dict | None:
    try:
        h = {"User-Agent": USER_AGENT}
        if headers:
            h.update(headers)
        req = urllib.request.Request(url, headers=h)
        with _DIRECT_OPENER.open(req, timeout=timeout) as resp:
            if resp.status == 200:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw)
    except Exception:
        pass
    return None

def _http_get_bytes(url: str, headers: dict | None = None, timeout: int = TIMEOUT) -> bytes | None:
    try:
        h = {"User-Agent": USER_AGENT}
        if headers:
            h.update(headers)
        req = urllib.request.Request(url, headers=h)
        with _DIRECT_OPENER.open(req, timeout=timeout) as resp:
            if resp.status == 200:
                return resp.read()
    except Exception:
        pass
    return None

def _clean_str(s: str) -> str:
    s = to_simplified(s)
    s = re.sub(r"[,/&、+;]|(?:\s+(?:feat\.?|ft\.?|and|vs\.?)\s+)", " ", s.casefold())
    s = re.sub(r"[^\w\u4e00-\u9fff]", "", s)
    return s.strip()

def artist_matches(candidate_artists: list[str], target_artist: str) -> bool:
    if not target_artist:
        return True
    t_norm = _clean_str(target_artist)
    if not t_norm:
        return True
    target_has_cover = any(w in target_artist.lower() for w in ("cover", "翻唱"))
    for cand in candidate_artists:
        cand_lower = cand.lower()
        cand_has_cover = any(w in cand_lower for w in ("cover", "翻唱"))
        if cand_has_cover and not target_has_cover:
            # Candidate explicitly indicates a cover artist, e.g. "周杰伦 (Cover: 张三)"
            continue
        c_norm = _clean_str(cand)
        if not c_norm:
            continue
        if c_norm == t_norm or c_norm in t_norm or t_norm in c_norm:
            return True
    return False

def title_matches(candidate_name: str, target_title: str) -> bool:
    """Normalised comparison of a search hit against the title we are looking for."""
    candidate = _clean_str(candidate_name)
    target = _clean_str(target_title)
    if not candidate or not target:
        return False
    return candidate == target or candidate in target or target in candidate


def _prefer_title_match(current: dict | None, candidate: dict, target_title: str) -> dict:
    """Keep the first fallback, but let a candidate whose title actually matches win.

    Files named after the song alone ("一直很安静.wav") give the search engines no
    artist to filter on, so the first hit is often an unrelated track.
    """
    if current is None:
        return candidate
    if title_matches(candidate.get("name", ""), target_title) and not title_matches(current.get("name", ""), target_title):
        return candidate
    return current


UNWANTED_VARIANTS = [
    # 伴奏与纯音乐类
    "伴奏", "伴奏版", "伴奏带", "原版伴奏", "消音伴奏", "消音版", "纯音乐",
    "instrumental", "inst", "inst.", "karaoke", "卡拉ok", "卡拉 ok",
    "backing track", "minus one", "off vocal", "tv size",
    # 翻唱与声线变体
    "翻唱", "翻唱版", "cover", "cover版", "cv版", "女声版", "男声版", "童声版",
    # 改编与特殊演奏版本
    "深情版", "钢琴版", "吉他版", "古筝版", "萨克斯版", "二胡版", "琵琶版",
    "dj版", "dj", "remix", "慢摇", "电音版", "车载版", "嗨唱版", "热播版", "高潮版",
    "片段", "铃声", "变奏", "降调版", "升调版", "变调版", "变速版", "加速版", "减速版",
    "acoustic", "piano version", "guitar version",
]

def is_unwanted_variant(song_name: str, target_title: str, album_name: str = "", artist_name: str = "") -> bool:
    """Check if the candidate song is an unwanted variant (instrumental, cover, karaoke, etc.)

    Checks title, album, and artist fields against unwanted keywords, unless the target title
    itself explicitly asked for that variant.
    """
    s_lower = song_name.lower()
    t_lower = target_title.lower()
    a_lower = album_name.lower() if album_name else ""
    art_lower = artist_name.lower() if artist_name else ""
    for w in UNWANTED_VARIANTS:
        if w in t_lower:
            continue
        # Check title
        if w in s_lower:
            if len(w) <= 4 and w.isascii():
                if re.search(r'(?:\b|[\(\[\{_\s\-])' + re.escape(w) + r'(?:\b|[\)\]\}\s\-_])', s_lower):
                    return True
            else:
                return True
        # Check album for instrumental/cover indicators
        if a_lower and w in ("伴奏", "纯音乐", "instrumental", "karaoke", "cover", "翻唱"):
            if len(w) <= 4 and w.isascii():
                if re.search(r'(?:\b|[\(\[\{_\s\-])' + re.escape(w) + r'(?:\b|[\)\]\}\s\-_])', a_lower):
                    return True
            else:
                if w in a_lower:
                    return True
        # Check artist for cover/instrumental indicators
        if art_lower and w in ("cover", "翻唱", "伴奏", "instrumental"):
            if w in art_lower:
                return True
    return False

def _smartbox_to_song(item: dict) -> dict:
    """Convert a Smartbox result item into a song dict compatible with get_qq_details().

    Smartbox itself only carries mid/name/singer, and the follow-up
    fcg_play_single_song.fcg answers in the *new* field layout
    (mid / name / title / album.mid / album.name).  Every consumer downstream
    (get_qq_details, enrich_domestic) reads the *classic* layout
    (songmid / songname / albummid / albumname), so the reply is mapped here —
    handing the raw payload back would silently yield no lyrics and no cover.
    """
    songmid = str(item.get("mid", "") or "")
    song = {
        "songmid": songmid,
        "songname": str(item.get("name", "") or ""),
        "singer": [{"name": name.strip()} for name in str(item.get("singer", "")).split("、") if name.strip()],
        "albummid": "",
        "albumname": "",
    }
    if not songmid:
        return song

    detail = _http_get_json(f"https://c.y.qq.com/v8/fcg-bin/fcg_play_single_song.fcg?songmid={songmid}&format=json")
    rows = detail.get("data") if isinstance(detail, dict) else None
    if not (isinstance(rows, list) and rows and isinstance(rows[0], dict)):
        return song
    row = rows[0]
    album = row.get("album") if isinstance(row.get("album"), dict) else {}
    name = row.get("name") or row.get("title")
    if name:
        song["songname"] = str(name)
    song["songmid"] = str(row.get("songmid") or row.get("mid") or songmid)
    singers = [entry.get("name") for entry in row.get("singer", []) if isinstance(entry, dict) and entry.get("name")]
    if singers:
        song["singer"] = [{"name": name} for name in singers]
    song["albummid"] = str(album.get("mid") or row.get("albummid") or "")
    song["albumname"] = str(album.get("name") or row.get("albumname") or "")
    return song

def search_qq_music(title: str, artist: str = "") -> dict | None:
    """Search QQ Music using the Smartbox API which handles traditional Chinese natively."""
    if not title:
        return None
    clean_title = re.sub(r"[\[\(].*?[\]\)]", "", title).strip()
    query = f"{clean_title} {artist}".strip() if artist else clean_title
    # Smartbox handles trad→simp internally, but we also convert for reliability
    query_simp = to_simplified(query)
    encoded = urllib.parse.quote(query_simp)
    url = f"https://c.y.qq.com/splcloud/fcgi-bin/smartbox_new.fcg?key={encoded}&format=json"
    data = _http_get_json(url, headers={"Referer": "https://y.qq.com/"})
    if not data or not isinstance(data.get("data"), dict):
        return None
    
    # Smartbox returns results in data.data.song.itemlist
    song_items = []
    song_data = data["data"].get("song", {})
    if isinstance(song_data, dict):
        song_items = song_data.get("itemlist", [])
    if not song_items:
        return None
    
    # Filter by artist if provided
    target_artist_simp = to_simplified(artist) if artist else ""
    best = None
    for item in song_items:
        name = item.get("name", "")
        singer = item.get("singer", "")
        songmid = item.get("mid", "")
        if not songmid:
            continue
        cand_singers = [s.strip() for s in singer.split("、") if s.strip()] if singer else []
        if target_artist_simp and not artist_matches(cand_singers, target_artist_simp):
            best = _prefer_title_match(best, item, title)
            continue
        if is_unwanted_variant(name, title, artist_name=singer):
            best = _prefer_title_match(best, item, title)
            continue
        # Good match found — fetch full song details
        return _smartbox_to_song(item)

    # When artist was provided, do not fall back to an arbitrary singer/cover artist.
    # Only fall back to best title match if no artist was specified AND best is not an unwanted variant.
    if not artist and best:
        b_name = best.get("name", "")
        b_singer = best.get("singer", "")
        if not is_unwanted_variant(b_name, title, artist_name=b_singer):
            return _smartbox_to_song(best)
    return None

_LRC_LINE_RE = re.compile(r"^\[(\d{1,2}):(\d{1,2})(?:[\.:](\d{1,3}))?\](.*)$")

def _parse_lrc_time(m_str: str, s_str: str, ms_str: str | None) -> int:
    m = int(m_str)
    s = int(s_str)
    if ms_str:
        if len(ms_str) == 2:
            ms = int(ms_str) * 10
        elif len(ms_str) == 3:
            ms = int(ms_str)
        elif len(ms_str) == 1:
            ms = int(ms_str) * 100
        else:
            ms = int(ms_str[:3])
    else:
        ms = 0
    return m * 60000 + s * 1000 + ms

def merge_bilingual_lrc(orig_lrc: str | None, trans_lrc: str | None) -> str | None:
    """Merge original lyrics and translated lyrics into a synchronized bilingual LRC."""
    if not orig_lrc:
        return trans_lrc
    if not trans_lrc:
        return orig_lrc

    trans_map: dict[int, str] = {}
    trans_times: list[int] = []
    for line in trans_lrc.strip().splitlines():
        line = line.strip()
        match = _LRC_LINE_RE.match(line)
        if match:
            ms = _parse_lrc_time(match.group(1), match.group(2), match.group(3))
            text = match.group(4).strip()
            if text:
                trans_map[ms] = text
                trans_times.append(ms)

    if not trans_map:
        return orig_lrc

    trans_times.sort()
    merged_lines: list[str] = []
    used_trans: set[int] = set()

    for line in orig_lrc.strip().splitlines():
        clean_line = line.strip()
        merged_lines.append(clean_line)
        match = _LRC_LINE_RE.match(clean_line)
        if match:
            orig_tag = clean_line[:match.end() - len(match.group(4))]
            orig_ms = _parse_lrc_time(match.group(1), match.group(2), match.group(3))
            orig_text = match.group(4).strip()

            best_t_ms = None
            min_diff = 350
            for t_ms in trans_times:
                diff = abs(t_ms - orig_ms)
                if diff < min_diff:
                    min_diff = diff
                    best_t_ms = t_ms

            if best_t_ms is not None and best_t_ms not in used_trans:
                trans_text = trans_map[best_t_ms]
                if trans_text and trans_text != orig_text:
                    merged_lines.append(f"{orig_tag}{trans_text}")
                    used_trans.add(best_t_ms)

    return "\n".join(merged_lines)

def get_qq_details(song: dict) -> tuple[str | None, str | None]:
    albummid = song.get("albummid", "")
    cover_url = f"https://y.gtimg.cn/music/photo_new/T002R800x800M000{albummid}.jpg" if albummid else None
    songmid = song.get("songmid", "")
    lyric_str = None
    if songmid:
        lyric_url = f"https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg?songmid={songmid}&format=json&nobase64=0"
        ldata = _http_get_json(lyric_url, headers={"Referer": "https://y.qq.com/"})
        if ldata and ldata.get("lyric"):
            try:
                raw_b64 = ldata["lyric"]
                decoded = base64.b64decode(raw_b64).decode("utf-8", errors="replace")
                lyric_str = html.unescape(decoded)
                if ldata.get("trans"):
                    trans_decoded = base64.b64decode(ldata["trans"]).decode("utf-8", errors="replace")
                    trans_str = html.unescape(trans_decoded)
                    lyric_str = merge_bilingual_lrc(lyric_str, trans_str)
            except Exception:
                pass
    return cover_url, lyric_str

def search_netease(title: str, artist: str = "") -> dict | None:
    if not title:
        return None
    clean_title = re.sub(r"[\[\(].*?[\]\)]", "", title).strip()
    query = f"{clean_title} {artist}".strip() if artist else clean_title
    query = to_simplified(query)
    encoded = urllib.parse.quote(query)
    url = f"http://music.163.com/api/search/get/web?s={encoded}&type=1&offset=0&total=true&limit=8"
    data = _http_get_json(url)
    if not data or not isinstance(data.get("result"), dict):
        return None
    songs = data["result"].get("songs", [])
    if not songs or not isinstance(songs, list):
        return None

    # 1. Best match: artist agrees (when known) and the title/album is not an unwanted variant
    best = None
    for song in songs:
        name = song.get("name", "")
        cand_artists = [a.get("name", "") for a in song.get("artists", []) if a.get("name")]
        album_name = song.get("album", {}).get("name", "") if isinstance(song.get("album"), dict) else ""
        singer_str = "/".join(cand_artists)

        if is_unwanted_variant(name, title, album_name=album_name, artist_name=singer_str):
            continue

        if artist and not artist_matches(cand_artists, artist):
            best = best or song
            continue

        # With no artist to filter on, require a title match
        if not artist and not title_matches(name, title):
            best = best or song
            continue
        return song

    # 2. When artist was specified, do NOT fall back to arbitrary other artists or unwanted variants!
    # Only fall back to best title match if no artist was specified AND best is clean.
    if not artist and best:
        b_name = best.get("name", "")
        b_album = best.get("album", {}).get("name", "") if isinstance(best.get("album"), dict) else ""
        b_singers = "/".join(a.get("name", "") for a in best.get("artists", []) if a.get("name"))
        if not is_unwanted_variant(b_name, title, album_name=b_album, artist_name=b_singers):
            return best
    return None

def get_netease_details(song_id: int) -> tuple[dict | None, str | None]:
    detail_url = f"http://music.163.com/api/song/detail/?id={song_id}&ids=%5B{song_id}%5D"
    lyric_url = f"http://music.163.com/api/song/lyric?id={song_id}&lv=1&kv=1&tv=-1"
    detail_data = _http_get_json(detail_url)
    lyric_data = _http_get_json(lyric_url)

    song_info = None
    if detail_data and detail_data.get("songs"):
        song_info = detail_data["songs"][0]

    lyric_str = None
    if lyric_data and isinstance(lyric_data.get("lrc"), dict):
        lyric_str = lyric_data["lrc"].get("lyric")
        tlyric = lyric_data.get("tlyric", {}).get("lyric") if isinstance(lyric_data.get("tlyric"), dict) else None
        if tlyric:
            lyric_str = merge_bilingual_lrc(lyric_str, tlyric)

    return song_info, lyric_str

def enrich_domestic(
    audio_path: Path,
    current_artist: str = "",
    current_title: str = "",
    current_album: str = "",
    need_metadata: bool = True,
    need_lyrics: bool = True,
    need_cover: bool = True,
) -> dict:
    """Fetches missing metadata, lyrics, or cover via dual engines (QQ Music + NetEase)

    Applies strict anti-contamination checks to preserve authenticity.
    Returns dict with keys: 'artist', 'album', 'title', 'lyrics', 'has_cover', 'applied_lyrics', 'applied_cover'.
    """
    result = {
        "artist": current_artist,
        "album": current_album,
        "title": current_title,
        "lyrics": "",
        "has_cover": False,
        "applied_lyrics": False,
        "applied_cover": False,
        "source": "",  # NEW: track which source provided data
    }
    if not need_metadata and not need_lyrics and not need_cover:
        return result

    # Convert to simplified Chinese for better search results
    title_to_search = to_simplified(current_title or audio_path.stem)
    artist_to_search = to_simplified(current_artist)
    cover_bytes: bytes | None = None
    lyric_str: str | None = None
    matched_title = current_title
    matched_artist = current_artist
    matched_album = current_album

    # Engine 1: QQ Music (Primary)
    qq_song = search_qq_music(title_to_search, artist_to_search)
    if qq_song:
        result["source"] = "qq_music"
        _log(f"[元数据源] {audio_path.name}: QQ音乐 Smartbox 命中 → songmid={qq_song.get('songmid', '?')}")
        cand_singers = [s.get("name", "") for s in qq_song.get("singer", []) if s.get("name")]
        if not current_artist or artist_matches(cand_singers, artist_to_search):
            matched_title = qq_song.get("songname") or matched_title
            if not matched_artist and cand_singers:
                matched_artist = "/".join(cand_singers)
            if not matched_album and qq_song.get("albumname"):
                matched_album = qq_song["albumname"]
            c_url, l_str = get_qq_details(qq_song)
            if need_cover and c_url:
                cover_bytes = _http_get_bytes(c_url)
            if need_lyrics and l_str:
                lyric_str = l_str
    else:
        _log(f"[元数据源] {audio_path.name}: QQ音乐无结果")

    # Engine 2: NetEase Cloud Music (Fallback)
    if (need_cover and not cover_bytes) or (need_lyrics and not lyric_str) or (need_metadata and not matched_title):
        ne_song = search_netease(title_to_search, artist_to_search)
        if ne_song:
            if not result["source"]:
                result["source"] = "netease"
            else:
                result["source"] += "+netease"
            _log(f"[元数据源] {audio_path.name}: 网易云音乐命中 → id={ne_song.get('id', '?')}")
            
            cand_artists = [a.get("name", "") for a in ne_song.get("artists", []) if a.get("name")]
            if not current_artist or artist_matches(cand_artists, artist_to_search):
                if not matched_title:
                    matched_title = ne_song.get("name") or matched_title
                if not matched_artist and cand_artists:
                    matched_artist = "/".join(cand_artists)
                if not matched_album and ne_song.get("album") and ne_song["album"].get("name"):
                    matched_album = ne_song["album"]["name"]
                song_id = ne_song.get("id")
                if song_id:
                    ne_detail, ne_lrc = get_netease_details(song_id)
                    if need_cover and not cover_bytes:
                        c_url = ""
                        if ne_detail and ne_detail.get("album") and ne_detail["album"].get("picUrl"):
                            c_url = ne_detail["album"]["picUrl"]
                        elif ne_song.get("album") and ne_song["album"].get("picUrl"):
                            c_url = ne_song["album"]["picUrl"]
                        if c_url:
                            cover_bytes = _http_get_bytes(f"{c_url}?param=800y800")
                    if need_lyrics and not lyric_str and ne_lrc:
                        lyric_str = ne_lrc
        else:
            _log(f"[元数据源] {audio_path.name}: 网易云音乐也无结果")

    # Stage 2: If searching with artist returned nothing, and the audio had no existing album,
    # try searching by title alone (handles cases like anime titles mistaken for artist names, e.g. "愛殺寶貝")
    if (not matched_album or not lyric_str) and current_artist and not matched_album:
        qq_song_title = search_qq_music(title_to_search, "")
        if qq_song_title and title_matches(qq_song_title.get("songname", ""), title_to_search):
            cand_singers = [s.get("name", "") for s in qq_song_title.get("singer", []) if s.get("name")]
            # CRITICAL: Only accept if the candidate singers actually match artist_to_search!
            # Never overwrite a known artist with an unknown cover artist or random singer.
            if cand_singers and artist_matches(cand_singers, artist_to_search):
                if not matched_album and qq_song_title.get("albumname"):
                    matched_album = qq_song_title["albumname"]
                    _log(f"[元数据源] {audio_path.name}: 纯歌名重试命中 QQ 专辑: {matched_album}")
                c_url, l_str = get_qq_details(qq_song_title)
                if need_cover and not cover_bytes and c_url:
                    cover_bytes = _http_get_bytes(c_url)
                if need_lyrics and not lyric_str and l_str:
                    lyric_str = l_str

    if not result["source"]:
        result["source"] = "none"

    result["artist"] = matched_artist
    result["album"] = matched_album
    result["title"] = matched_title
    if lyric_str:
        result["lyrics"] = lyric_str

    if mediafile is None:
        return result

    # Determine if format supports embedded lyrics
    ext = audio_path.suffix.lower()
    no_embed_lyrics_formats = {".wav", ".aiff", ".aif"}
    can_embed_lyrics = ext not in no_embed_lyrics_formats

    try:
        mf = mediafile.MediaFile(str(audio_path))
        modified = False
        if need_metadata:
            if not mf.title and matched_title:
                mf.title = matched_title
                modified = True
            if not mf.artist and matched_artist:
                mf.artist = matched_artist
                modified = True
            if not mf.album and matched_album:
                mf.album = matched_album
                modified = True

        if need_lyrics and lyric_str and not mf.lyrics and can_embed_lyrics:
            try:
                mf.lyrics = lyric_str
                result["applied_lyrics"] = True
                modified = True
            except Exception as exc:
                # The container refuses embedded lyrics — fall through to a sidecar
                # instead of reporting the lyrics as missing.
                can_embed_lyrics = False
                _log(f"[歌词] {audio_path.name}: 内嵌失败({exc})，改用同名外挂 .lrc")

        if need_cover and cover_bytes and not mf.images:
            mf.images = [mediafile.Image(data=cover_bytes, desc="cover", type=mediafile.ImageType.front)]
            result["applied_cover"] = True
            result["has_cover"] = True
            modified = True
        elif mf.images:
            result["has_cover"] = True

        if modified:
            mf.save()
    except Exception as exc:
        _log(f"[元数据] {audio_path.name}: mediafile 写入异常: {exc}")

    # Write sidecar .lrc file for formats (or failures) that can't embed lyrics
    if need_lyrics and lyric_str and not can_embed_lyrics:
        try:
            lrc_path = audio_path.with_suffix(".lrc")
            lrc_path.write_text(lyric_str, encoding="utf-8")
            result["applied_lyrics"] = True
            _log(f"[格式支持] {audio_path.name}: 格式 {ext} 以同名外挂 {lrc_path.name} 保存歌词")
        except Exception as exc:
            _log(f"[歌词] {audio_path.name}: 外挂 .lrc 写入失败: {exc}")

    return result
