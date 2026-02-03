# matchmaking.py
# Athena Hybrid Engine v6.0 — Professional Grade
# Features: Google GenAI v1.0 SDK, Unicode Parsing, Strict Filtering, Full Fallback Data

import discord
from discord import app_commands
from discord.ext import commands
from google import genai
import re
import difflib
import math
import json
import os
import time
import logging
import asyncio
from typing import Dict, List, Tuple, Optional

# Configure Logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------- CONFIGURATION ----------------
DEBUG = False
SYNONYMS_FILE = "synonyms.json"
FEEDBACK_LOG_FILE = "feedback_log.json"

# AI Model Configuration
# Using 'gemini-2.0-flash' as verified by your available models list.
# This model is faster and more capable than 1.5-flash.
AI_MODEL_NAME = "gemini-2.0-flash"

# ---------------- TEXT CLEANING & TOKENIZATION ----------------
NOISE_WORDS = {
    "playing", "listening", "watching", "reading", "making", "creating", "doing",
    "to", "the", "in", "on", "at", "a", "an", "my", "i", "like", "love", "enjoy",
    "baking", "cooking", "practice", "practicing", "id", "im", "and", "but", "or"
}

def clean_interest_token(text: str) -> str:
    """
    Normalizes a token by removing noise words, punctuation, and bracketed content.
    Returns the cleaned string or empty string if invalid.
    """
    if not text: return ""
    s = text.lower()
    # Remove content inside brackets/parentheses (e.g., "(Genshin impact)")
    s = re.sub(r'\(.*?\)', '', s) 
    s = re.sub(r'\[.*?\]', '', s)
    s = re.sub(r'\*.*?\*', '', s) 
    # Remove punctuation/symbols
    s = re.sub(r'[^\w\s]', ' ', s)
    # Tokenize and filter noise words
    words = s.split()
    clean_words = [w for w in words if w not in NOISE_WORDS]
    return " ".join(clean_words).strip()

def split_interest_text(raw: str) -> List[str]:
    """
    Splits raw text fields into individual tokens.
    Includes logic to ignore long sentences that often appear in 'Likes' fields incorrectly.
    """
    if not raw: return []
    
    # Heuristic: If a "Like" is a sentence longer than 12 words, it's likely a bio description, not a tag.
    if len(raw.split()) > 12: 
        return [] 

    # Split by common delimiters
    s = re.sub(r'\band\b', ',', raw, flags=re.IGNORECASE)
    parts = re.split(r'[,\n;/|•\u2022\-!]+', s)
    
    tokens = []
    for p in parts:
        cleaned = clean_interest_token(p)
        # Filter out 1-2 letter garbage tokens unless strictly valid
        if cleaned and len(cleaned) > 2:
            tokens.append(cleaned)
    return tokens

# ---------------- FALLBACK DATA DICTIONARIES ----------------
# Comprehensive fallback lists to ensure functionality without external JSON files.

INTEREST_SYNONYMS = {
    "video_games": {
        "gaming", "video games", "genshin", "gacha", "pjsk", "hsr", "hoyo", 
        "minecraft", "fnaf", "hollow knight", "roblox", "fortnite", "valorant", 
        "rivals", "games", "console", "ps5", "pc", "steam", "nintendo", "cod",
        "overwatch", "league", "sims", "stardew", "osu", "splatoon", "apex", "r6"
    },
    "anime_manga": {
        "anime", "manga", "jjk", "kny", "one piece", "death note", "manhwa", 
        "webtoon", "naruto", "bleach", "ghibli", "aot", "demon slayer", "csm",
        "chainsaw man", "bungan", "bsd"
    },
    "music": {
        "music", "citypop", "indie music", "kpop", "rap", "r&b", "tyler", "kanye", 
        "pop", "songs", "singing", "instruments", "piano", "violin", "guitar", 
        "drums", "band", "concerts", "spotify", "playlists"
    },
    "reading_writing": {
        "reading", "books", "fanfiction", "ff", "writing", "poems", "poetry", 
        "journaling", "novels", "literature", "ao3", "wattpad"
    },
    "arts_crafts": {
        "art", "drawing", "graphic design", "graphics", "editing", "sketching", 
        "crochet", "knitting", "painting", "digital art", "traditional art", 
        "doodling", "sculpting", "pottery", "sewing"
    },
    "photography": {
        "photography", "pfp", "matching pfps", "photos", "cameras", "editing"
    },
    "cooking_baking": {
        "cooking", "baking", "cakes", "brownies", "food", "culinary", "sweets"
    },
    "vehicles": {
        "bike", "bikes", "car", "cars", "biker", "motorcycles", "racing", "f1", 
        "driving"
    },
    "movies_tv": {
        "movies", "films", "documentaries", "the boys", "lucifer", "marvel", 
        "spiderman", "sitcoms", "kdrama", "drama", "series", "youtube", "netflix",
        "shows", "tv", "cinema", "horror movies", "cartoons"
    },
    "true_crime_paranormal": {
        "true crime", "creepypasta", "analog horror", "horror", "mystery", 
        "ghosts", "paranormal", "supernatural", "thriller"
    },
    "social_communication": {
        "vc", "voice chat", "vcing", "chatting", "texting", "yapping", 
        "calling", "talking", "hanging out", "socializing", "calls"
    },
    "sports": {
        "badminton", "volleyball", "figure skater", "sports", "basketball", 
        "gym", "football", "soccer", "skating", "tennis", "swimming", 
        "working out", "fitness", "hockey"
    },
    "animals": {
        "cats", "dogs", "pets", "animals", "bunnies", "reptiles", "birds"
    },
    "fashion_beauty": {
        "fashion", "makeup", "skincare", "clothes", "shopping", "style", "dress up"
    },
    "programming_tech": {
        "coding", "programming", "tech", "computers", "linux", "python", "keyboards"
    }
}

CATEGORY_TO_FAMILY_FALLBACK = {
    "video_games": "fiction_media",
    "anime_manga": "fiction_media",
    "movies_tv": "fiction_media",
    "reading_writing": "fiction_media",
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

TRAIT_CLUSTERS_FALLBACK = {
    "empathic": {"empathetic", "caring", "kind", "supportive", "understanding", "sweet", "nice", "patient", "loyal", "gentle"},
    "communicative": {"talkative", "chatty", "yapper", "communicative", "good listener", "social", "outgoing", "engaging"},
    "introverted": {"shy", "introverted", "reserved", "quiet", "calm", "anxious", "loner", "listener"},
    "energetic": {"bubbly", "energetic", "hyper", "playful", "funny", "chaotic", "loud", "silly", "ragebaiter"},
    "analytical": {"observant", "analytical", "practical", "smart", "intelligent", "nerd", "logical", "serious", "mature"},
    "passionate": {"affectionate", "clingy", "flirty", "freaky", "passionate", "romantic", "obsessive"}
}

ENERGY_KEYWORDS_FALLBACK = {
    "shy": 0.2, "introverted": 0.2, "calm": 0.3, "quiet": 0.3, "tired": 0.3, "listener": 0.3,
    "chill": 0.4, "relaxed": 0.4, "mature": 0.4,
    "talkative": 0.7, "chatty": 0.7, "engaging": 0.7,
    "bubbly": 0.85, "energetic": 0.9, "hyper": 0.95, "chaotic": 0.95, "loud": 0.95, "ragebaiter": 0.95
}

# ---------------- SYNONYM MANAGER ----------------
class SynonymManager:
    def __init__(self, path: str = SYNONYMS_FILE):
        self.path = path
        self.mtime = 0.0
        self.raw = {}
        self.variant_to_canonical = {}
        self.category_to_family = {}
        self.trait_clusters = {}
        self.energy_map = {}
        self.load()

    def load(self):
        # Reset to internal fallbacks
        self.variant_to_canonical = {}
        self.category_to_family = CATEGORY_TO_FAMILY_FALLBACK.copy()
        self.trait_clusters = TRAIT_CLUSTERS_FALLBACK.copy()
        self.energy_map = ENERGY_KEYWORDS_FALLBACK.copy()

        # Load internal synonyms
        for canon, vs in INTEREST_SYNONYMS.items():
            for v in vs:
                self.variant_to_canonical[v.lower()] = canon

        # Attempt to load external JSON overlay
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                if "categories" in data:
                    for canon, variants in data["categories"].items():
                        for v in variants:
                            self.variant_to_canonical[v.lower()] = canon
                if "families" in data:
                    self.category_to_family.update(data["families"])
                
                self.mtime = os.path.getmtime(self.path)
                logger.info("synonyms.json loaded successfully.")
        except Exception:
            logger.warning("Could not load synonyms.json, using internal fallback only.")

    def reload_if_needed(self):
        if not os.path.exists(self.path): return
        try:
            if os.path.getmtime(self.path) != self.mtime: self.load()
        except: pass

    def get_canonical(self, token: str) -> Optional[str]:
        if not token: return None
        t = token.lower().strip()
        
        # 1. Exact match
        if t in self.variant_to_canonical: 
            return self.variant_to_canonical[t]
            
        # 2. Substring match (Prioritize longer matches to avoid false positives)
        best_match = None
        best_len = 0
        for variant, canon in self.variant_to_canonical.items():
            if len(variant) > 3 and variant in t:
                if len(variant) > best_len:
                    best_match = canon
                    best_len = len(variant)
        if best_match: return best_match
        
        # 3. Custom token
        return f"custom::{t}"

    def family_of(self, canonical: str) -> Optional[str]:
        if not canonical: return None
        if canonical.startswith("custom::"):
            # Attempt to deduce family from custom token substring
            raw = canonical.split("::",1)[1]
            for variant, canon in self.variant_to_canonical.items():
                if variant in raw:
                    return self.category_to_family.get(canon)
            return None
        return self.category_to_family.get(canonical)

SYNMAN = SynonymManager()

# ---------------- FORM PARSERS ----------------
def parse_timezone_offset(tz_raw: str) -> Optional[float]:
    if not tz_raw: return None
    s = tz_raw.lower()
    map_tz = {
        "est": -5, "edt": -4, "pst": -8, "pdt": -7, "cst": -6, "mst": -7, 
        "gmt": 0, "utc": 0, "ist": 5.5, "cet": 1, "bst": 1, "mdt": -6, "cdt": -5,
        "bst": 1 # British Summer Time
    }
    for k, v in map_tz.items():
        if k in s: return float(v)
    return None

def parse_age_field(age_text: str) -> Tuple[Optional[int], Optional[Tuple]]:
    if not age_text: return None, None
    s = age_text.lower()
    
    # Extract precise age
    m = re.search(r'\b(\d{1,2})\b', s)
    age_val = int(m.group(1)) if m else None
    
    # Extract age preference range (e.g., 18-22)
    m_range = re.search(r'(\d{1,2})\s*[-to]+\s*(\d{1,2})', s)
    if m_range: 
        return age_val, (int(m_range.group(1)), int(m_range.group(2)))
    
    # Extract open-ended preference (e.g., 18+)
    m_plus = re.search(r'(\d{1,2})\s*\+', s)
    if m_plus:
        return age_val, (int(m_plus.group(1)), 99)

    return age_val, None

def find_section_bounds(full_text: str) -> Tuple[str, Optional[str]]:
    """
    Splits the profile into 'You' (Bio) and 'Them' (Preferences).
    Uses Unicode literal matching for high precision.
    """
    # 1. Direct Search for Fancy Header
    header_idx = full_text.find("𝓣𝒉𝒆𝒎")
    
    if header_idx != -1:
         return full_text[:header_idx].strip(), full_text[header_idx:].strip()
    
    # 2. Strict Regex Fallback (Newline + Them)
    match = re.search(r'(?m)^\s*thems?\b', full_text, re.IGNORECASE)
    if match:
        idx = match.start()
        return full_text[:idx].strip(), full_text[idx:].strip()

    # 3. Last Resort Fallback (Only split if in the middle of text)
    match_fallback = re.search(r'(?i)\bthems?\b', full_text)
    if match_fallback:
        idx = match_fallback.start()
        if 10 < idx < len(full_text) - 10:
             return full_text[:idx].strip(), full_text[idx:].strip()
        
    return full_text.strip(), None

def parse_profile_block(block: str) -> Dict:
    profile = {
        'name': None, 'age': None, 'age_pref': None, 
        'gender': None, 'sexuality': None, 'tz_offset': None,
        'dislikes': [], 'likes': [], 'hobbies': [], 'traits': [], 'other': {},
        'raw_text': block 
    }
    
    # Normalize unicode fancy text
    text = block.replace('╰', '\n').replace('꒰', ' ').replace('୧', ' ').replace('𐔌', '\n')
    text = re.sub(r'[^\x00-\x7F]+', ' ', text)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    label_map = {
        'name': ['name'], 
        'age': ['age', 'ag ', 'ag:', 'ages'], 
        'gender': ['gender', 'sex'], 
        'sexuality': ['sexuality', 'orientation'],
        'time_zone': ['time zone', 'timezone', 'time'], 
        'dislikes': ['dislikes', 'dislike'],
        'likes': ['likes', 'like'], 
        'hobbies': ['hobbies', 'hobby'],
        'traits': ['your traits', 'their traits', 'traits']
    }

    current = None
    accum = {}

    for ln in lines:
        lower_ln = ln.lower()
        found = False
        
        # Check for labels
        for key, variants in label_map.items():
            for v in variants:
                if lower_ln.startswith(v):
                    after = lower_ln[len(v):]
                    if not after or not after[0].isalpha():
                        content = ln[len(v):].lstrip(' :-').strip()
                        current = key
                        accum.setdefault(key, [])
                        if content: accum[key].append(content)
                        found = True
                        break
            if found: break
        
        # Accumulate content
        if not found:
            if current:
                accum[current].append(ln)
            elif '?' in ln:
                q, _, a = ln.partition('?')
                profile['other'][q.strip().lower()] = a.strip().lower()

    def get_val(k): return " ".join(accum[k]) if k in accum else None

    profile['name'] = get_val('name')
    age_raw = get_val('age')
    if age_raw:
        val, pref = parse_age_field(age_raw)
        profile['age'] = val
        profile['age_pref'] = pref
    
    profile['gender'] = (get_val('gender') or '').lower()
    profile['sexuality'] = (get_val('sexuality') or '').lower()
    profile['tz_offset'] = parse_timezone_offset(get_val('time_zone'))

    # Process lists (Likes, Hobbies, etc.)
    for field in ['likes', 'hobbies', 'dislikes', 'traits']:
        raw = get_val(field)
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

# ---------------- MATCHING ENGINE (SCORING) ----------------
def fuzzy_match_score(a: str, b: str) -> float:
    # 1. Clean input
    clean_a = a.replace("custom::", "").strip()
    clean_b = b.replace("custom::", "").strip()
    
    if not clean_a or not clean_b: return 0.0
    if clean_a == clean_b: return 1.0
    
    # 2. Length Disparity Check (Crucial Garbage Filter)
    # If len ratio < 0.7, assume unrelated (e.g. "Sentence" vs "Tag")
    len_ratio = min(len(clean_a), len(clean_b)) / max(len(clean_a), len(clean_b))
    if len_ratio < 0.7: 
        return 0.0

    # 3. Substring Match (High Confidence)
    if len(clean_a) > 3 and len(clean_b) > 3:
        if clean_a in clean_b or clean_b in clean_a: return 0.95

    return difflib.SequenceMatcher(a=clean_a, b=clean_b).ratio()

def compute_interest_score(list_a: List[str], list_b: List[str]) -> Tuple[float, List[Tuple[str,str,float]]]:
    if not list_a and not list_b: return 0.5, []
    matches = []
    score_sum = 0.0
    
    for a in list_a:
        best_s = 0.0
        best_b = None
        for b in list_b:
            s = fuzzy_match_score(a, b)
            
            # Category/Family Boost
            if s < 0.7:
                fam_a = SYNMAN.family_of(a)
                fam_b = SYNMAN.family_of(b)
                if fam_a and fam_b and fam_a == fam_b:
                    s = max(s, 0.8) # 80% Match for same family
            
            if s > best_s:
                best_s = s; best_b = b
        
        # Threshold: 75% minimum confidence to count as a match
        if best_s > 0.75:
            score_sum += best_s
            matches.append((a, best_b, best_s))
            
    denom = max(len(list_a), 1)
    return min(1.0, score_sum / denom), matches

def get_trait_energy(traits: List[str]) -> float:
    blob = " ".join(traits).lower()
    score = 0.5
    for w, val in SYNMAN.energy_map.items():
        if w in blob:
            score = (score + val) / 2
    return score

# ---------------- AI JUDGE (GOOGLE GENAI v1.0) ----------------
async def ask_athena_ai(p1_raw: str, p2_raw: str) -> Tuple[int, str]:
    """
    Uses Google's new GenAI SDK to judge compatibility.
    """
    api_key = os.getenv("AI_API_KEY")
    if not api_key:
        return 50, "AI Key missing - using math only."

    # Init Client
    client = genai.Client(api_key=api_key)
    
    prompt = f"""
    You are Athena, a professional matchmaker. Analyze these two profiles.
    
    PROFILE 1:
    {p1_raw}
    
    PROFILE 2:
    {p2_raw}
    
    Task:
    1. Ignore typos.
    2. Look for "Vibe" compatibility (e.g. golden retriever vs black cat).
    3. Look for subtle dealbreakers.
    4. Provide a compatibility score (0-100).
    5. Provide a 1-sentence explanation.
    
    Output Format:
    SCORE: [number]
    REASON: [text]
    """

    try:
        loop = asyncio.get_running_loop()
        # Use executor to prevent blocking
        response = await loop.run_in_executor(None, lambda: client.models.generate_content(
            model=AI_MODEL_NAME, contents=prompt
        ))
        
        text = response.text.strip()
        
        score = 50
        reason = "AI analysis inconclusive."
        
        m_score = re.search(r'SCORE:\s*(\d+)', text)
        if m_score: score = int(m_score.group(1))
        
        m_reason = re.search(r'REASON:\s*(.*)', text, re.DOTALL)
        if m_reason: reason = m_reason.group(1).strip()
        
        return score, reason

    except Exception as e:
        logger.error(f"AI Error: {e}")
        return 50, f"AI Error: {str(e)[:50]}"

# ---------------- DISCORD UI & COG ----------------
class FeedbackView(discord.ui.View):
    def __init__(self, match_id: str):
        super().__init__(timeout=None)
        self.match_id = match_id

    @discord.ui.button(emoji="👍", style=discord.ButtonStyle.green, custom_id="match_approve")
    async def approve(self, interaction, button):
        await interaction.response.send_message("💚 Feedback recorded!", ephemeral=True)
    
    @discord.ui.button(emoji="👎", style=discord.ButtonStyle.red, custom_id="match_deny")
    async def deny(self, interaction, button):
        await interaction.response.send_message("💔 Feedback recorded!", ephemeral=True)

class Matchmaking(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_friction(self, p1, p2, scores):
        points = []
        # Age
        if scores['age'] < 1.0:
            if p1['age'] and p2['age_pref']:
                if (p1['age'] < p2['age_pref'][0] or p1['age'] > p2['age_pref'][1]):
                    points.append(f"• **Age Mismatch:** {p1['name'] or 'P1'} ({p1['age']}) is outside {p2['name'] or 'P2'}'s range.")
            if p2['age'] and p1['age_pref']:
                if (p2['age'] < p1['age_pref'][0] or p2['age'] > p1['age_pref'][1]):
                    points.append(f"• **Age Mismatch:** {p2['name'] or 'P2'} ({p2['age']}) is outside {p1['name'] or 'P1'}'s range.")
        
        # Timezone
        if scores['tz'] < 0.6 and p1['tz_offset'] is not None and p2['tz_offset'] is not None:
            diff = abs(p1['tz_offset'] - p2['tz_offset'])
            points.append(f"• **Time Difference:** {diff} hours.")
            
        # Conflict (Likes vs Dislikes)
        p1_likes = set(p1['likes'] + p1['hobbies'])
        p2_dislikes = {clean_interest_token(d) for d in p2['dislikes']}
        
        for item in p1_likes:
            base = item.replace("custom::", "")
            if base in p2_dislikes:
                points.append(f"• **Conflict:** {p1['name']} likes **{base}**, which {p2['name']} dislikes.")
        return points

    @app_commands.command(name="analyze_compatibility", description="Analyze two forms with F-22 Hybrid Engine")
    async def analyze_compatibility(self, interaction: discord.Interaction, form1: str, form2: str, engine: str = "f22"):
        await interaction.response.defer()
        
        SYNMAN.reload_if_needed()
        p1 = parse_profile_block(form1)
        p2 = parse_profile_block(form2)

        # 1. Math Scoring
        i1 = p1['likes'] + p1['hobbies']
        i2 = p2['likes'] + p2['hobbies']
        s1, m1 = compute_interest_score(i1, i2)
        s2, m2 = compute_interest_score(i2, i1)
        
        # Interest score: weighted average
        math_interest_score = max(s1, s2) * 0.7 + min(s1, s2) * 0.3
        
        # Practical Scoring (Age + TZ)
        def age_compat(age, pref):
            if not age or not pref: return 0.5
            return 1.0 if pref[0] <= age <= pref[1] else 0.0
            
        age_score = (age_compat(p1['age'], p2['age_pref']) + age_compat(p2['age'], p1['age_pref'])) / 2.0
        
        tz_score = 1.0
        if p1['tz_offset'] is not None and p2['tz_offset'] is not None:
            diff = abs(p1['tz_offset'] - p2['tz_offset'])
            if diff > 4: tz_score = 0.6
            if diff > 8: tz_score = 0.3

        practical = (age_score * 0.6) + (tz_score * 0.4)
        math_total = (math_interest_score * 0.55) + (practical * 0.30) + 0.15
        math_total = min(0.99, math_total)

        # 2. AI Scoring
        ai_score_raw, ai_reason = await ask_athena_ai(p1['raw_text'], p2['raw_text'])
        ai_score_norm = ai_score_raw / 100.0

        # 3. Hybrid Combination (60% Math, 40% AI)
        final_score = (math_total * 0.6) + (ai_score_norm * 0.4)
        final_pct = int(final_score * 100)

        # Embed Generation
        if final_pct > 75: desc = "➤ Excellent Match"
        elif final_pct > 50: desc = "➤ Good Potential"
        else: desc = "➤ Low Compatibility"
        
        embed = discord.Embed(title="<:s_white2:1382052523166142486> 𝐴𝑡ℎ𝑒𝑛𝑎 𝑀𝑎𝑡𝑐ℎ𝑚𝑎𝑘𝑖𝑛𝑔 <:s_white2:1382052523166142486>", description=desc, color=0xffffff)
        embed.add_field(name="<:p_hearts:1378053399525982288> Hybrid Score", value=f"**{final_pct}%**", inline=False)
        embed.add_field(name="<:p_hearts:1378053399525982288> Engine Breakdown", 
                        value=f"• **Algorithm**: {int(math_total*100)}%\n• **AI Vibe Check**: {ai_score_raw}%", inline=False)
        
        # Display Matches
        shared_list = []
        seen = set()
        combined = m1 + m2
        combined.sort(key=lambda x: x[2], reverse=True)
        
        for a, b, s in combined:
            if a is None or b is None: continue 
            
            pair = tuple(sorted((a, b)))
            if pair in seen: continue
            seen.add(pair)
            
            clean_a = str(a).replace("custom::", "").replace("_", " ").title()
            clean_b = str(b).replace("custom::", "").replace("_", " ").title()
            
            if clean_a == clean_b:
                shared_list.append(f"• **{clean_a}**")
            elif s > 0.85:
                shared_list.append(f"• **{clean_a}** (Match)")
            else:
                shared_list.append(f"• {clean_a} ↔ {clean_b}")

        embed.add_field(name="<:p_hearts:1378053399525982288> Shared Interests", value="\n".join(shared_list[:6]) or "None detected", inline=False)

        if frictions := self.get_friction(p1, p2, {'age': age_score, 'tz': tz_score}):
            embed.add_field(name="⚠️ Friction Points", value="\n".join(frictions), inline=False)

        embed.add_field(name="𝐴𝑡ℎ𝑒𝑛𝑎'𝑠 𝐴𝐼 𝑂𝑝𝑖𝑛𝑖𝑜𝑛", value=f"*{ai_reason}*", inline=False)

        match_id = str(int(time.time()*1000))
        await interaction.followup.send(embed=embed, view=FeedbackView(match_id))

async def setup(bot):
    await bot.add_cog(Matchmaking(bot))