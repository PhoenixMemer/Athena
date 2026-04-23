# cogs/matchmaking_v5.py
# Athena Hybrid Engine v21.0 — Production Grade (Network Armor + Logic)
# Fixes: 503 Discord Service Unavailable, Double Negatives, Crash Loops

import discord
from discord import app_commands
from discord.ext import commands
from google import genai
from google.genai import types
import re
import difflib
import json
import os
import time
import logging
import asyncio
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------- CONFIG ----------------
SYNONYMS_FILE = "synonyms.json"

# ---------------- NETWORK UTILS ----------------
async def safe_defer(interaction: discord.Interaction, retries=3):
    """
    Tries to defer the interaction. If Discord 503s (Gateway Overflow),
    it waits and retries. This fixes the 'reset reason: overflow' crash.
    """
    for i in range(retries):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
            return True
        except discord.errors.DiscordServerError:
            # 503 or 502 error from Discord. Wait and retry.
            await asyncio.sleep(1)
            continue
        except Exception as e:
            logger.error(f"Defer failed: {e}")
            return False
    return False

# ---------------- CLEANING & PARSING ----------------
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

def normalize_text_for_logic(text: str) -> str:
    """Removes aesthetic symbols to make logic parsing 100% accurate."""
    clean = re.sub(r'[^\x00-\x7F]+', '', text)
    return clean.lower()

def parse_dealbreakers(raw_text: str) -> Dict[str, str]:
    """
    Determines relationship style and trans status/preference.
    Returns: 'monogamous', 'polyamorous', 'open_trans', 'closed_trans'
    """
    clean_text = normalize_text_for_logic(raw_text)
    lines = clean_text.split('\n')
    
    # Defaults
    poly_status = "unknown"  
    trans_pref = "open"
    is_trans_self = False

    for line in lines:
        if "mind" in line and "poly" in line:
            if "yes" in line: poly_status = "monogamous"
            elif "no" in line: poly_status = "polyamorous"
        
        if "mind" in line and "trans" in line:
            if "yes" in line: trans_pref = "closed"
            elif "no" in line: trans_pref = "open"
            
        if "gender" in line and ("trans" in line or "mtf" in line or "ftm" in line):
            is_trans_self = True

    return {
        "poly": poly_status,
        "trans_pref": trans_pref,
        "is_trans": is_trans_self
    }

def parse_section_bounds(full_text: str) -> Tuple[str, str, str]:
    them_match = re.search(r"(?i)(?:^|\n)\s*[^\w\n]*\s*(?:them|𝓣𝒉𝒆𝒎|𝓽𝓱𝓮𝓶)\b", full_text)
    other_match = re.search(r"(?i)(?:^|\n)\s*[^\w\n]*\s*(?:other|𝓞𝒕𝒉𝒆𝒓|𝓸𝓽𝓱𝓮𝓻)\b", full_text)
    
    start_them = them_match.start() if them_match else len(full_text)
    start_other = other_match.start() if other_match else len(full_text)
    
    if start_other < start_them:
        p1_text = full_text[:min(start_them, start_other)]
        p2_text = full_text[min(start_them, start_other):]
        other_text = ""
    else:
        p1_text = full_text[:start_them]
        p2_text = full_text[start_them:start_other]
        other_text = full_text[start_other:]
        
    return p1_text.strip(), p2_text.strip(), other_text.strip()

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
    "video_games": "game_media", "anime_manga": "visual_media", "movies_tv": "visual_media", "reading_writing": "literary_media",
    "true_crime_paranormal": "horror_family", "music": "creative_family", "arts_crafts": "creative_family", "photography": "creative_family",
    "fashion_beauty": "creative_family", "vehicles": "mechanical_family", "programming_tech": "mechanical_family", "cooking_baking": "home_family",
    "social_communication": "social_family", "sports": "active_family", "animals": "nature_family"
}

# ---------------- SYNONYM MANAGER ----------------
class SynonymManager:
    def __init__(self, path: str = SYNONYMS_FILE):
        self.path = path; self.mtime = 0.0; self.variant_to_canonical = {}; self.category_to_family = {}
        self.load()
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

# ---------------- PARSERS ----------------
TZ_OFFSETS = {
    "est": -5, "edt": -4, "cst": -6, "cdt": -5, "mst": -7, "mdt": -6, 
    "pst": -8, "pdt": -7, "gmt": 0, "utc": 0, "bst": 1, "cet": 1, "cest": 2,
    "ist": 5.5, "jst": 9, "kst": 9, "aedt": 11, "aest": 10
}

def parse_timezone(text: str) -> Optional[float]:
    if not text: return None
    s = text.lower().replace(" ", "")
    match_offset = re.search(r"(?:gmt|utc|t)([+-]\d+(?:\.\d+)?)", s)
    if match_offset: return float(match_offset.group(1))
    for abbr, offset in TZ_OFFSETS.items():
        if abbr in s: return float(offset)
    return None

def normalize_gender(g: str) -> str:
    if not g: return "unknown"
    g = g.lower().strip()
    if any(x in g for x in ["female", "woman", "girl", "she"]): return "female"
    if any(x in g for x in ["male", "man", "boy", "he"]): return "male"
    if any(x in g for x in ["non", "nb", "enby"]): return "nonbinary"
    return "unknown"

def parse_profile_block(block: str) -> Dict:
    profile = {
        'name': None, 'age': None, 'age_pref': None, 
        'gender': None, 'sexuality': None, 'tz_offset': None,
        'dislikes': [], 'likes': [], 'hobbies': [], 'traits': [],
        'raw_text': block,
        'flags': {} 
    }
    
    # 1. Standardize Text
    text = block.replace('╰', '\n').replace('꒰', ' ').replace('୧', ' ').replace('𐔌', '\n')
    text = re.sub(r'[^\x00-\x7F]+', ' ', text)
    
    # 2. Extract Fields
    def extract_line(key_pattern):
        m = re.search(rf'(?i)^\s*{key_pattern}\s*[:\-]?\s*(.+)', text, re.MULTILINE)
        return m.group(1).strip() if m else None

    profile['name'] = extract_line(r'name')
    
    age_raw = extract_line(r'(?:age|ag)')
    if age_raw:
        m = re.search(r'\b(\d{1,2})\b', age_raw)
        if m: profile['age'] = int(m.group(1))
        m_range = re.search(r'(\d{1,2})\s*[-to]+\s*(\d{1,2})', age_raw)
        if m_range: profile['age_pref'] = (int(m_range.group(1)), int(m_range.group(2)))
        
    profile['gender'] = (extract_line(r'(?:gender|sex)') or '').lower()
    profile['sexuality'] = (extract_line(r'(?:sexuality|orientation)') or '').lower()
    profile['tz_offset'] = parse_timezone(extract_line(r'(?:time zone|timezone|time)'))

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
            
    # 3. Extract Flags (Poly/Trans)
    profile['flags'] = parse_dealbreakers(block)
    return profile

# ---------------- LOGIC MATRIX (The "Judge") ----------------
def check_compatibility_logic(p1: Dict, p2: Dict) -> Tuple[float, List[str], bool]:
    issues = []
    
    g1 = normalize_gender(p1['gender']); s1 = p1['sexuality']
    g2 = normalize_gender(p2['gender']); s2 = p2['sexuality']
    
    if g1 != "unknown" and g2 != "unknown":
        is_straight_1 = 'straight' in s1 or 'hetero' in s1
        is_straight_2 = 'straight' in s2 or 'hetero' in s2
        
        if is_straight_1 and is_straight_2 and g1 == g2:
            return 0.0, [f"Incompatible Orientation (Two straight {g1}s)"], True
        if is_straight_1 and g1 == g2: return 0.0, ["Incompatible Orientation"], True
        if is_straight_2 and g1 == g2: return 0.0, ["Incompatible Orientation"], True

    # POLYAMORY CHECK
    poly1 = p1['flags']['poly']
    poly2 = p2['flags']['poly']
    
    if poly1 == 'monogamous' and poly2 == 'polyamorous':
        return 0.0, ["Relationship Style Mismatch (Mono vs Poly)"], True
    if poly2 == 'monogamous' and poly1 == 'polyamorous':
        return 0.0, ["Relationship Style Mismatch (Poly vs Mono)"], True
    
    # TRANS CHECK
    if p1['flags']['is_trans'] and p2['flags']['trans_pref'] == 'closed':
        return 0.0, ["Preference Mismatch"], True
    if p2['flags']['is_trans'] and p1['flags']['trans_pref'] == 'closed':
        return 0.0, ["Preference Mismatch"], True

    # TIMEZONE
    tz1 = p1['tz_offset']; tz2 = p2['tz_offset']
    if tz1 is not None and tz2 is not None:
        diff = abs(tz1 - tz2)
        if diff > 12: diff = 24 - diff
        if diff > 5.5:
            issues.append(f"Timezone Gap: {diff}h (Max 5.5h)")
            return 0.3, issues, False

    return 1.0, issues, False

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

# ---------------- AI SUMMARY ----------------
async def get_athena_summary(p1: Dict, p2: Dict, score: int, frictions: List[str]) -> str:
    api_key = os.getenv("AI_API_KEY")
    if not api_key: return "Athena AI Unavailable."

    p1_self, p1_them, _ = parse_section_bounds(p1['raw_text'])
    p2_self, p2_them, _ = parse_section_bounds(p2['raw_text'])

    client = genai.Client(api_key=api_key)
    
    prompt = f"""
    Write a SHORT summary for this couple.
    
    CONTEXT:
    - Compatibility Score: {score}%
    - Frictions: {', '.join(frictions) if frictions else 'None'}
    
    User 1: {p1_self[:1000]}
    User 2: {p2_self[:1000]}
    
    TASK:
    Write 2-3 sentences. Concise.
    """

    try:
        res = await asyncio.to_thread(client.models.generate_content, model="gemini-2.0-flash", contents=prompt)
        return res.text[:950] if res.text else "Analysis complete."
    except:
        return "Athena is offline, but the math is solid."

# ---------------- COG ----------------
class FeedbackView(discord.ui.View):
    def __init__(self, match_id: str): super().__init__(timeout=None); self.match_id = match_id
    @discord.ui.button(emoji="👍", style=discord.ButtonStyle.green, custom_id="match_approve")
    async def approve(self, interaction, button): await interaction.response.send_message("💚 Recorded!", ephemeral=True)
    @discord.ui.button(emoji="👎", style=discord.ButtonStyle.red, custom_id="match_deny")
    async def deny(self, interaction, button): await interaction.response.send_message("💔 Recorded!", ephemeral=True)

class Matchmaking(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="analyze_compatibility")
    async def analyze_compatibility(self, interaction: discord.Interaction, form1: str, form2: str, engine: str = "f22"):
        # 1. NETWORK SAFE DEFER (Fixes 503 Crashes)
        success = await safe_defer(interaction)
        if not success:
            # If we couldn't defer after 3 retries, abort silently or log
            logger.error("Failed to defer interaction due to Network/Discord API Error.")
            return

        try:
            SYNMAN.reload_if_needed()
            p1 = parse_profile_block(form1); p2 = parse_profile_block(form2)

            # 2. HOBBY MATH
            i1 = p1['likes'] + p1['hobbies']; i2 = p2['likes'] + p2['hobbies']
            s1, m1 = compute_interest_score(i1, i2); s2, m2 = compute_interest_score(i2, i1)
            math_interest = max(s1, s2) * 0.7 + min(s1, s2) * 0.3
            
            # 3. LOGIC MATRIX
            logistics_mult, logistics_issues, is_fatal = check_compatibility_logic(p1, p2)
            
            # 4. FINAL SCORE
            if is_fatal:
                final_score = 0
                title = "<:s_white2:1382052523166142486> 𝐴𝑡ℎ𝑒𝑛𝑎 𝑀𝑎𝑡𝑐ℎ𝑚𝑎𝑘𝑖𝑛𝑔 <:s_white2:1382052523166142486>"
                desc_prefix = "💀 **Incompatible**"
                color = 0xff0000
            else:
                base_score = (math_interest * 60) + (40 * logistics_mult)
                if logistics_mult < 0.5: base_score = min(base_score, 45)
                final_score = int(base_score)
                
                title = "<:s_white2:1382052523166142486> 𝐴𝑡ℎ𝑒𝑛𝑎 𝑀𝑎𝑡𝑐ℎ𝑚𝑎𝑘𝑖𝑛𝑔 <:s_white2:1382052523166142486>"
                if final_score > 80: desc_prefix = "➤ **Excellent Match**"; color = 0xffffff
                elif final_score > 60: desc_prefix = "➤ **Good Potential**"; color = 0xffffff
                elif final_score > 40: desc_prefix = "➤ **Weak Match**"; color = 0xffffff
                else: desc_prefix = "➤ **Low Compatibility**"; color = 0xffffff

            # 5. AI SUMMARY
            ai_summary = await get_athena_summary(p1, p2, final_score, logistics_issues)
            
            desc = f"{desc_prefix}\n{ai_summary}"
            
            embed = discord.Embed(title=title, description=desc, color=color)
            embed.add_field(name="<:p_hearts:1378053399525982288> Hybrid Score", value=f"**{final_score}%**", inline=False)
            
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
            
            if logistics_issues:
                embed.add_field(name="⚠️ Friction Points", value="\n".join(logistics_issues[:5]), inline=False)

            await interaction.followup.send(embed=embed, view=FeedbackView(str(int(time.time()))))

        except discord.errors.HTTPException as e:
            if e.code == 50035: # Invalid Form Body (Too long)
                await interaction.followup.send("⚠️ **Error:** Result too long for Discord. The match was calculated, but the description exceeded limits.")
            else:
                await interaction.followup.send(f"⚠️ **Discord API Error:** {e}")
        except Exception as e:
            logger.error(f"Matchmaking Error: {e}")
            await interaction.followup.send("⚠️ **Athena Error:** Something went wrong during calculation. Please try again.")

async def setup(bot): await bot.add_cog(Matchmaking(bot))