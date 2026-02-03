# matchmaking_v5.py
# Athena Hybrid Engine v15.0
import discord
from discord import app_commands
from discord.ext import commands
from google import genai
from google.genai import types
import re
import difflib
import math
import json
import os
import time
import logging
import asyncio
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------- CONFIG ----------------
DEBUG = False
SYNONYMS_FILE = "synonyms.json"
FEEDBACK_LOG_FILE = "feedback_log.json"

# ---------------- CLEANING ----------------
NOISE_WORDS = {
    "playing", "listening", "watching", "reading", "making", "creating", "doing",
    "to", "the", "in", "on", "at", "a", "an", "my", "i", "like", "love", "enjoy",
    "baking", "cooking", "practice", "practicing", "id", "im", "you", "your",
    "nice", "good", "stuff", "things", "always", "sure", "can", "do", "any",
    "similar", "mine", "same"
}

def clean_interest_token(text: str) -> str:
    if not text: return ""
    s = text.lower()
    s = re.sub(r'\(.*?\)', '', s) 
    s = re.sub(r'\[.*?\]', '', s)
    s = re.sub(r'\*.*?\*', '', s) 
    s = re.sub(r'[^\w\s]', ' ', s)
    words = s.split()
    clean_words = [w for w in words if w not in NOISE_WORDS]
    return " ".join(clean_words).strip()

def split_interest_text(raw: str) -> List[str]:
    if not raw: return []
    s = re.sub(r'\s+(?:and|&|plus|with)\s+', ',', raw, flags=re.IGNORECASE)
    s = s.replace('\n', ',')
    parts = re.split(r'[;,\/|•]+', s)
    tokens = []
    for p in parts:
        cleaned = clean_interest_token(p)
        if cleaned and len(cleaned) > 1:
            tokens.append(cleaned)
    return tokens

# ---------------- DATA ----------------
INTEREST_SYNONYMS = {
    "video_games": {"gaming", "video games", "genshin", "gacha", "pjsk", "hsr", "hoyo", "minecraft", "fnaf", "roblox", "fortnite", "valorant", "rivals", "games", "console", "ps5", "pc", "steam", "nintendo", "cod", "overwatch", "league", "sims", "stardew", "osu", "splatoon", "apex", "r6"},
    "anime_manga": {"anime", "manga", "jjk", "kny", "one piece", "death note", "manhwa", "webtoon", "naruto", "bleach", "ghibli", "aot", "demon slayer", "csm", "chainsaw man", "bungan", "bsd"},
    "music": {"music", "citypop", "indie music", "kpop", "rap", "r&b", "tyler", "kanye", "pop", "songs", "singing", "instruments", "piano", "violin", "guitar", "drums", "band", "concerts", "spotify", "playlists"},
    "reading_writing": {"reading", "books", "fanfiction", "ff", "writing", "poems", "poetry", "journaling", "novels", "literature", "ao3", "wattpad"},
    "arts_crafts": {"art", "drawing", "graphic design", "graphics", "editing", "sketching", "crochet", "knitting", "painting", "digital art", "traditional art", "doodling", "sculpting", "pottery", "sewing"},
    "photography": {"photography", "pfp", "matching pfps", "photos", "cameras", "editing"},
    "cooking_baking": {"cooking", "baking", "cakes", "brownies", "food", "culinary", "sweets"},
    "vehicles": {"bike", "bikes", "car", "cars", "biker", "motorcycles", "racing", "f1", "driving"},
    "movies_tv": {"movies", "films", "documentaries", "the boys", "lucifer", "marvel", "spiderman", "sitcoms", "kdrama", "drama", "series", "youtube", "netflix", "shows", "tv", "cinema", "horror movies", "cartoons"},
    "true_crime_paranormal": {"true crime", "creepypasta", "analog horror", "horror", "mystery", "ghosts", "paranormal", "supernatural", "thriller"},
    "social_communication": {"vc", "voice chat", "vcing", "chatting", "texting", "yapping", "calling", "talking", "hanging out", "socializing", "calls"},
    "sports": {"badminton", "volleyball", "figure skater", "sports", "basketball", "gym", "football", "soccer", "skating", "tennis", "swimming", "working out", "fitness", "hockey", "boxing"},
    "animals": {"cats", "dogs", "pets", "animals", "bunnies", "reptiles", "birds"},
    "fashion_beauty": {"fashion", "makeup", "skincare", "clothes", "shopping", "style", "dress up"},
    "programming_tech": {"coding", "programming", "tech", "computers", "linux", "python", "keyboards"}
}

CATEGORY_TO_FAMILY_FALLBACK = {
    # SEPARATE FAMILIES
    "video_games": "game_media", 
    "anime_manga": "visual_media", 
    "movies_tv": "visual_media", # Movies & Anime can still match (both are watching stuff)
    "reading_writing": "literary_media",
    
    # KEEP OTHERS THE SAME
    "true_crime_paranormal": "horror_family", 
    "music": "creative_family", 
    "arts_crafts": "creative_family", 
    "photography": "creative_family",
    "fashion_beauty": "creative_family", 
    "vehicles": "mechanical_family", 
    "programming_tech": "mechanical_family", 
    "cooking_baking": "home_family",
    "social_communication": "social_family", 
    "sports": "active_family", 
    "animals": "nature_family"
}

ENERGY_KEYWORDS_FALLBACK = {
    "shy": 0.2, "introverted": 0.2, "calm": 0.3, "quiet": 0.3, "tired": 0.3, "listener": 0.3,
    "chill": 0.4, "relaxed": 0.4, "mature": 0.4,
    "talkative": 0.7, "chatty": 0.7, "engaging": 0.7,
    "bubbly": 0.85, "energetic": 0.9, "hyper": 0.95, "chaotic": 0.95, "loud": 0.95, "ragebaiter": 0.95
}

class SynonymManager:
    def __init__(self, path: str = SYNONYMS_FILE):
        self.path = path; self.mtime = 0.0; self.variant_to_canonical = {}; self.category_to_family = {}
        self.energy_map = ENERGY_KEYWORDS_FALLBACK.copy(); self.load()
    def load(self):
        self.category_to_family = CATEGORY_TO_FAMILY_FALLBACK.copy()
        for canon, vs in INTEREST_SYNONYMS.items():
            for v in vs: self.variant_to_canonical[v.lower()] = canon
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "categories" in data:
                    for c, vs in data["categories"].items():
                        for v in vs: self.variant_to_canonical[v.lower()] = c
                if "families" in data: self.category_to_family.update(data["families"])
                self.mtime = os.path.getmtime(self.path)
        except: pass
    def reload_if_needed(self):
        if os.path.exists(self.path) and os.path.getmtime(self.path) != self.mtime: self.load()
    def get_canonical(self, token: str) -> Optional[str]:
        if not token: return None
        t = token.lower().strip()
        if t in self.variant_to_canonical: return self.variant_to_canonical[t]
        best_match = None; best_len = 0
        for v, c in self.variant_to_canonical.items():
            if len(v) > 3 and v in t:
                if len(v) > best_len: best_match = c; best_len = len(v)
        return best_match if best_match else f"custom::{t}"
    def family_of(self, c: str) -> Optional[str]:
        if not c: return None
        if c.startswith("custom::"):
            raw = c.split("::",1)[1]
            for v, canon in self.variant_to_canonical.items():
                if v in raw: return self.category_to_family.get(canon)
            return None
        return self.category_to_family.get(c)

SYNMAN = SynonymManager()

# ---------------- PARSERS (REGEX UPGRADE) ----------------
def parse_timezone_offset(tz_raw: str) -> Optional[float]:
    if not tz_raw: return None
    s = tz_raw.lower()
    map_tz = {"est":-5, "edt":-4, "pst":-8, "pdt":-7, "cst":-6, "mst":-7, "gmt":0, "utc":0, "ist":5.5, "cet":1, "bst":1}
    for k, v in map_tz.items():
        if k in s: return float(v)
    return None

def parse_age_field(age_text: str) -> Tuple[Optional[int], Optional[Tuple]]:
    if not age_text: return None, None
    s = age_text.lower()
    m = re.search(r'\b(\d{1,2})\b', s)
    age_val = int(m.group(1)) if m else None
    m_range = re.search(r'(\d{1,2})\s*[-to]+\s*(\d{1,2})', s)
    if m_range: return age_val, (int(m_range.group(1)), int(m_range.group(2)))
    m_plus = re.search(r'(\d{1,2})\s*\+', s)
    if m_plus: return age_val, (int(m_plus.group(1)), 99)
    return age_val, None

def find_section_bounds(full_text: str) -> Tuple[str, Optional[str]]:
    # Unicode search first, then Regex
    if "𝓣𝒉𝒆𝒎" in full_text:
        idx = full_text.find("𝓣𝒉𝒆𝒎")
        return full_text[:idx].strip(), full_text[idx:].strip()
    match = re.search(r'(?m)^\s*thems?\b', full_text, re.IGNORECASE)
    if match: return full_text[:match.start()].strip(), full_text[match.start():].strip()
    match_fallback = re.search(r'(?i)\bthems?\b', full_text)
    if match_fallback:
        idx = match_fallback.start()
        if 10 < idx < len(full_text) - 10: return full_text[:idx].strip(), full_text[idx:].strip()
    return full_text.strip(), None

def parse_profile_block(block: str) -> Dict:
    profile = {
        'name': None, 'age': None, 'age_pref': None, 'gender': None, 'sexuality': None, 
        'tz_offset': None, 'dislikes': [], 'likes': [], 'hobbies': [], 'traits': [], 'other': {},
        'raw_text': block 
    }
    
    # 1. Clean Unicode
    text = block.replace('╰', '\n').replace('꒰', ' ').replace('୧', ' ').replace('𐔌', '\n')
    text = re.sub(r'[^\x00-\x7F]+', ' ', text) # Strip non-ascii chars to fix parser failure
    
    # 2. Extract Fields using Regex (More robust than startswith)
    def extract_line(key_pattern):
        # Looks for: Pattern + optional colon/dash + capture group
        m = re.search(rf'(?i)^\s*{key_pattern}\s*[:\-]?\s*(.+)', text, re.MULTILINE)
        return m.group(1).strip() if m else None

    profile['name'] = extract_line(r'name')
    
    age_raw = extract_line(r'(?:age|ag)')
    if age_raw:
        val, pref = parse_age_field(age_raw)
        profile['age'] = val; profile['age_pref'] = pref
        
    profile['gender'] = (extract_line(r'(?:gender|sex)') or '').lower()
    profile['sexuality'] = (extract_line(r'(?:sexuality|orientation)') or '').lower()
    
    tz_raw = extract_line(r'(?:time zone|timezone|time)')
    profile['tz_offset'] = parse_timezone_offset(tz_raw)

    # 3. List Parsing
    for field, pat in [('likes', r'likes?'), ('hobbies', r'hobb(?:ies|y)'), ('dislikes', r'dislikes?'), ('traits', r'(?:your |their )?traits?')]:
        raw = extract_line(pat)
        if raw:
            clean_tokens = split_interest_text(raw)
            final = []
            for t in clean_tokens:
                if field in ['likes', 'hobbies']:
                    c = SYNMAN.get_canonical(t)
                    if c: final.append(c)
                    else: final.append(f"custom::{t}")
                else:
                    if t: final.append(t)
            profile[field] = list(dict.fromkeys(final))
            
    return profile

# ---------------- COMPATIBILITY ENGINE ----------------
def check_gender_compatibility(p1: Dict, p2: Dict) -> float:
    g1 = p1['gender']; s1 = p1['sexuality']
    g2 = p2['gender']; s2 = p2['sexuality']
    
    if not g1 or not g2 or not s1 or not s2: return 1.0 # Fail safe
    
    is_gay_1 = 'gay' in s1 or 'lesbian' in s1
    is_straight_1 = 'straight' in s1 or 'stright' in s1 or 'striaght' in s1
    
    is_gay_2 = 'gay' in s2 or 'lesbian' in s2
    is_straight_2 = 'straight' in s2 or 'stright' in s2 or 'striaght' in s2
    
    # Simple logic: If strict mismatch found, return 0
    if is_straight_1 and g1 == g2: return 0.0
    if is_straight_2 and g1 == g2: return 0.0
    if is_gay_1 and g1 != g2: return 0.0
    if is_gay_2 and g1 != g2: return 0.0
    
    return 1.0

def fuzzy_match_score(a: str, b: str) -> float:
    clean_a = a.replace("custom::", "").strip()
    clean_b = b.replace("custom::", "").strip()
    if not clean_a or not clean_b: return 0.0
    if clean_a == clean_b: return 1.0
    
    len_ratio = min(len(clean_a), len(clean_b)) / max(len(clean_a), len(clean_b))
    if len_ratio < 0.7: return 0.0
    if len(clean_a) > 3 and len(clean_b) > 3:
        if clean_a in clean_b or clean_b in clean_a: return 0.95
    return difflib.SequenceMatcher(a=clean_a, b=clean_b).ratio()

def compute_interest_score(list_a: List[str], list_b: List[str]) -> Tuple[float, List[Tuple[str,str,float]]]:
    if not list_a and not list_b: return 0.5, []
    matches = []; score_sum = 0.0
    for a in list_a:
        best_s = 0.0; best_b = None
        for b in list_b:
            s = fuzzy_match_score(a, b)
            if s < 0.7:
                fam_a = SYNMAN.family_of(a); fam_b = SYNMAN.family_of(b)
                if fam_a and fam_b and fam_a == fam_b: s = max(s, 0.8)
            if s > best_s: best_s = s; best_b = b
        if best_s > 0.75: score_sum += best_s; matches.append((a, best_b, best_s))
    denom = max(len(list_a), 1)
    return min(1.0, score_sum / denom), matches

# ---------------- AI JUDGE (ANTI-YAP PROMPT) ----------------
async def ask_athena_ai(p1_raw: str, p2_raw: str) -> Tuple[int, str]:
    api_key = os.getenv("AI_API_KEY")
    if not api_key: return 50, "AI Key missing - using math only."

    CANDIDATE_MODELS = ["gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-1.5-pro"]
    safety = [types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE")]
    client = genai.Client(api_key=api_key)
    
    # STRICT ANTI-YAP PROMPT
    prompt = f"""
    Role: Professional Matchmaker.
    Task: Rate compatibility (0-100).
    CRITICAL RULE: If gender/orientation conflict (e.g. 2 straight males), Score MUST be 0-10.
    
    P1: {p1_raw}
    P2: {p2_raw}
    
    Output exactly in this format. Max 3-4 sentences for REASON.
    SCORE: [number]
    REASON: [Short explanation]
    """

    loop = asyncio.get_running_loop()
    for model in CANDIDATE_MODELS:
        try:
            res = await loop.run_in_executor(None, lambda: client.models.generate_content(
                model=model, contents=prompt, config=types.GenerateContentConfig(safety_settings=safety)
            ))
            if not res.text: continue
            text = res.text.strip()
            
            score = 50; reason = "AI analysis inconclusive."
            m_s = re.search(r'SCORE:\s*(\d+)', text)
            if m_s: score = int(m_s.group(1))
            m_r = re.search(r'REASON:\s*(.*)', text, re.DOTALL)
            if m_r: reason = re.sub(r'SCORE:\s*\d+', '', m_r.group(1)).strip()[:1000] # Truncate safety
            
            return score, reason
        except: continue
    return 50, "AI unavailable."

# ---------------- COG ----------------
class FeedbackView(discord.ui.View):
    def __init__(self, match_id: str): super().__init__(timeout=None); self.match_id = match_id
    @discord.ui.button(emoji="👍", style=discord.ButtonStyle.green, custom_id="match_approve")
    async def approve(self, interaction, button): await interaction.response.send_message("💚 Recorded!", ephemeral=True)
    @discord.ui.button(emoji="👎", style=discord.ButtonStyle.red, custom_id="match_deny")
    async def deny(self, interaction, button): await interaction.response.send_message("💔 Recorded!", ephemeral=True)

class Matchmaking(commands.Cog):
    def __init__(self, bot): self.bot = bot

    def get_friction(self, p1, p2, scores):
        points = []
        if scores['gender'] == 0.0:
            points.append(f"• **Incompatible Orientation:** {p1['gender'].title()}/{p1['sexuality']} ↔ {p2['gender'].title()}/{p2['sexuality']}")
        if scores['age'] < 1.0:
            if p1['age'] and p2['age_pref'] and (p1['age'] < p2['age_pref'][0] or p1['age'] > p2['age_pref'][1]):
                points.append(f"• **Age Mismatch:** {p1['name']} ({p1['age']}) outside range.")
            if p2['age'] and p1['age_pref'] and (p2['age'] < p1['age_pref'][0] or p2['age'] > p1['age_pref'][1]):
                points.append(f"• **Age Mismatch:** {p2['name']} ({p2['age']}) outside range.")
        if scores['tz'] < 0.6 and p1['tz_offset'] is not None and p2['tz_offset'] is not None:
            points.append(f"• **Time Difference:** {abs(p1['tz_offset'] - p2['tz_offset'])} hours.")
        
        # Conflict Check (Limited to 5)
        p1_likes = set(p1['likes'] + p1['hobbies'])
        p2_dislikes = {clean_interest_token(d) for d in p2['dislikes']}
        count = 0
        for item in p1_likes:
            base = item.replace("custom::", "")
            if base in p2_dislikes and count < 5:
                points.append(f"• **Conflict:** {p1['name']} likes **{base}**, which {p2['name']} dislikes.")
                count += 1
        return points

    @app_commands.command(name="analyze_compatibility")
    async def analyze_compatibility(self, interaction: discord.Interaction, form1: str, form2: str, engine: str = "f22"):
        await interaction.response.defer()
        SYNMAN.reload_if_needed()
        p1 = parse_profile_block(form1); p2 = parse_profile_block(form2)

        i1 = p1['likes'] + p1['hobbies']; i2 = p2['likes'] + p2['hobbies']
        s1, m1 = compute_interest_score(i1, i2); s2, m2 = compute_interest_score(i2, i1)
        math_interest = max(s1, s2) * 0.7 + min(s1, s2) * 0.3
        
        def age_compat(age, pref): return 1.0 if age and pref and pref[0] <= age <= pref[1] else 0.5
        age_score = (age_compat(p1['age'], p2['age_pref']) + age_compat(p2['age'], p1['age_pref'])) / 2.0
        gender_score = check_gender_compatibility(p1, p2)
        tz_score = 1.0
        if p1['tz_offset'] is not None and p2['tz_offset'] is not None:
            diff = abs(p1['tz_offset'] - p2['tz_offset'])
            if diff > 4: tz_score = 0.6
            if diff > 8: tz_score = 0.3
        
        if gender_score == 0.0: math_total = 0.0
        else: math_total = (math_interest * 0.55) + ((age_score*0.6 + tz_score*0.4) * 0.30) + 0.15
        
        ai_score_raw, ai_reason = await ask_athena_ai(p1['raw_text'], p2['raw_text'])
        final_pct = int(((math_total * 0.6) + (ai_score_raw/100.0 * 0.4)) * 100)

        color = 0xffffff if final_pct > 50 else 0xff0000
        desc = "➤ Excellent Match" if final_pct > 75 else "➤ Good Potential" if final_pct > 50 else "➤ Low Compatibility"
        
        embed = discord.Embed(title="<:s_white2:1382052523166142486> 𝐴𝑡ℎ𝑒𝑛𝑎 𝑀𝑎𝑡𝑐ℎ𝑚𝑎𝑘𝑖𝑛𝑔 <:s_white2:1382052523166142486>", description=desc, color=color)
        embed.add_field(name="<:p_hearts:1378053399525982288> Hybrid Score", value=f"**{final_pct}%**", inline=False)
        embed.add_field(name="<:p_hearts:1378053399525982288> Engine Breakdown", value=f"• **Algorithm**: {int(math_total*100)}%\n• **AI Vibe Check**: {ai_score_raw}%", inline=False)
        
        shared_list = []
        combined = m1 + m2; combined.sort(key=lambda x: x[2], reverse=True)
        seen = set()
        for a, b, s in combined:
            if not a or not b: continue
            pair = tuple(sorted((a, b)))
            if pair in seen: continue
            seen.add(pair)
            ca = str(a).replace("custom::","").title(); cb = str(b).replace("custom::","").title()
            if ca == cb: shared_list.append(f"• **{ca}**")
            elif s > 0.85: shared_list.append(f"• **{ca}** (Match)")
            else: shared_list.append(f"• {ca} ↔ {cb}")
            
        embed.add_field(name="<:p_hearts:1378053399525982288> Shared Interests", value="\n".join(shared_list[:6]) or "None detected", inline=False)
        
        frictions = self.get_friction(p1, p2, {'age': age_score, 'tz': tz_score, 'gender': gender_score})
        if frictions: 
            val = "\n".join(frictions)
            if len(val) > 1024: val = val[:1020] + "..."
            embed.add_field(name="⚠️ Friction Points", value=val, inline=False)
        
        ai_val = f"*{ai_reason}*"
        if len(ai_val) > 1024: ai_val = ai_val[:1020] + "..."
        embed.add_field(name="𝐴𝑡ℎ𝑒𝑛𝑎'𝑠 𝐴𝐼 𝑂𝑝𝑖𝑛𝑖𝑜𝑛", value=ai_val, inline=False)

        await interaction.followup.send(embed=embed, view=FeedbackView(str(int(time.time()))))

async def setup(bot): await bot.add_cog(Matchmaking(bot))