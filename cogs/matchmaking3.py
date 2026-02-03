# matchmaking2.py
# F-35 Hybrid Engine — Algorithm + Gemini 2.5 Flash-Lite Analysis
import discord
from discord import app_commands
from discord.ext import commands
import google.generativeai as genai
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
FUZZY_HIGH = 0.82
FUZZY_MED = 0.55

# ---------------- FALLBACK DATA ----------------
INTEREST_SYNONYMS = {
    "video_games": {"gaming", "video games", "genshin", "gacha", "pjsk", "hsr", "hoyo", "minecraft", "fnaf", "hollow knight"},
    "anime_manga": {"anime", "manga", "jjk", "kny", "one piece", "death note"},
    "music": {"music", "citypop", "indie music", "kpop"},
    "reading_writing": {"reading", "books", "fanfiction", "ff"},
    "arts_crafts": {"art", "drawing", "graphic design", "graphics", "editing"},
    "photography": {"photography", "pfp", "matching pfps", "matching things"},
    "cooking_baking": {"cooking", "baking", "cakes", "brownies"},
    "vehicles": {"bike", "bikes", "car", "cars", "biker"},
    "movies_tv": {"movies", "films", "documentaries", "the boys", "lucifer"},
    "true_crime_paranormal": {"true crime", "creepypasta", "analog horror", "horror"},
    "social_communication": {"vc", "voice chat", "vcing", "chatting", "texting", "yapping"},
    "sports": {"badminton", "volleyball", "figure skater", "sports"}
}
VARIANT_TO_CANONICAL_FALLBACK = {}
for canon, vs in INTEREST_SYNONYMS.items():
    for v in vs:
        VARIANT_TO_CANONICAL_FALLBACK[v.lower()] = canon

CATEGORY_TO_FAMILY_FALLBACK = {
    "video_games": "fiction_media",
    "anime_manga": "fiction_media",
    "movies_tv": "fiction_media",
    "reading_writing": "fiction_media",
    "music": "creative_family",
    "arts_crafts": "creative_family",
    "photography": "creative_family",
    "vehicles": "mechanical_family",
    "cooking_baking": "home_family",
    "social_communication": "social_family",
    "sports": "active_family",
    "true_crime_paranormal": "horror_family"
}

TRAIT_CLUSTERS_FALLBACK = {
    "empathic": {"empathetic", "caring", "kind", "supportive", "understanding"},
    "communicative": {"talkative", "chatty", "yapper", "communicative", "good listener"},
    "introverted": {"shy", "introverted", "reserved", "quiet"},
    "energetic": {"bubbly", "energetic", "hyper", "playful"},
    "analytical": {"observant", "analytical", "practical", "smart", "intelligent"},
    "passionate": {"affectionate", "clingy", "flirty", "freaky"}
}

ENERGY_KEYWORDS_FALLBACK = {
    "shy": 0.2, "introverted": 0.2, "calm": 0.35, "chill": 0.4,
    "talkative": 0.75, "chatty": 0.75, "bubbly": 0.9, "energetic": 0.9
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
        self.tz_abbrev = {}
        self.load()

    def load(self):
        fallback = {
            "categories": {}, "families": {}, "trait_clusters": {},
            "energy_keywords": {}, "tz_abbreviations": {}
        }
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    self.raw = json.load(f)
                self.mtime = os.path.getmtime(self.path)
            else:
                self.raw = fallback
                self.mtime = 0.0
        except Exception:
            logger.exception("Error loading synonyms.json — using empty fallback.")
            self.raw = fallback
            self.mtime = 0.0

        self.variant_to_canonical = {}
        for canon, variants in self.raw.get("categories", {}).items():
            for v in variants:
                if isinstance(v, str):
                    self.variant_to_canonical[v.lower()] = canon
        self.category_to_family = self.raw.get("families", {})
        self.trait_clusters = self.raw.get("trait_clusters", {})
        self.energy_map = self.raw.get("energy_keywords", {})
        self.tz_abbrev = self.raw.get("tz_abbreviations", {})

    def reload_if_needed(self):
        if not os.path.exists(self.path):
            return
        try:
            mtime = os.path.getmtime(self.path)
            if mtime != self.mtime:
                logger.info("synonyms.json changed - reloading")
                self.load()
        except Exception:
            pass

    def get_canonical(self, token: str) -> Optional[str]:
        if not token: return None
        t = token.lower().strip()
        t = re.sub(r'[^\w\s\+\-]', ' ', t)
        t = re.sub(r'\s+', ' ', t).strip()
        if not t: return None
        if t in self.variant_to_canonical: return self.variant_to_canonical[t]
        for variant, canon in self.variant_to_canonical.items():
            if variant in t: return canon
        return None

    def family_of(self, canonical: str) -> Optional[str]:
        if not canonical: return None
        if canonical.startswith("custom::"):
            raw = canonical.split("::",1)[1]
            for variant, canon in self.variant_to_canonical.items():
                if variant in raw:
                    return self.category_to_family.get(canon) or CATEGORY_TO_FAMILY_FALLBACK.get(canon)
            return None
        return self.category_to_family.get(canonical) or CATEGORY_TO_FAMILY_FALLBACK.get(canonical)

SYNMAN = SynonymManager()

# ---------------- UTILITIES ----------------
def normalize_text_keep_lines(text: str) -> str:
    text = text.replace('╰', '\n').replace('꒰', ' ').replace('୧', ' ').replace('𐔌', '\n')
    text = re.sub(r'[^\x00-\x7F]+', ' ', text)
    text = text.replace('\r\n','\n').replace('\r','\n')
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join([ln for ln in lines if ln])

def split_interest_text(raw: str) -> List[str]:
    if not raw: return []
    s = re.sub(r'\band\b', ',', raw, flags=re.IGNORECASE)
    parts = re.split(r'[,\n;/|•\u2022\-]+', s)
    tokens = []
    for p in parts:
        p = p.strip()
        if not p: continue
        for sub in re.split(r'\s{2,}', p):
            if sub.strip(): tokens.append(sub.strip())
    return tokens

def canonicalize_interest(token: str) -> Optional[str]:
    SYNMAN.reload_if_needed()
    canon = SYNMAN.get_canonical(token)
    if canon: return canon
    t = token.lower().strip()
    t = re.sub(r'[^\w\s\+\-]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    if not t: return None
    if t in VARIANT_TO_CANONICAL_FALLBACK: return VARIANT_TO_CANONICAL_FALLBACK[t]
    for variant, canon in VARIANT_TO_CANONICAL_FALLBACK.items():
        if variant in t: return canon
    if len(t) <= 2: return None
    return f"custom::{t}"

def parse_timezone_offset(tz_raw: str) -> Optional[float]:
    if not tz_raw: return None
    s = tz_raw.lower()
    m = re.search(r'(utc|gmt)\s*([+-]\d+(\.\d+)?)', s)
    if m:
        try: return float(m.group(2))
        except: pass
    SYNMAN.reload_if_needed()
    for abbr, off in SYNMAN.tz_abbrev.items():
        if abbr in s: return float(off)
    for abbr, off in {"ist":5.5, "pkt":5, "est":-5, "pst":-8, "cet":1}.items():
        if abbr in s: return off
    return None

def fuzzy_match_score(a: str, b: str) -> float:
    if not a or not b: return 0.0
    return difflib.SequenceMatcher(a=a, b=b).ratio()

def parse_age_field(age_text: str) -> Tuple[Optional[int], Optional[Tuple[Optional[int], Optional[int]]]]:
    if not age_text: return None, None
    s = age_text.lower()
    m = re.search(r'\b(\d{1,2})\b', s)
    age_val = int(m.group(1)) if m else None
    m_range = re.search(r'(\d{1,2})\s*[-to]+\s*(\d{1,2})', s)
    if m_range: return age_val, (int(m_range.group(1)), int(m_range.group(2)))
    m_plus = re.search(r'(\d{1,2})\s*\+', s)
    if m_plus: return age_val, (int(m_plus.group(1)), None)
    return age_val, None

# ---------------- PARSER ----------------
def find_section_bounds(full_text: str) -> Tuple[str, Optional[str]]:
    mo = re.search(r'(?i)\bthems?\b|𝓣𝒉𝒆𝓂|𝓣𝒉𝒆𝒎', full_text)
    if mo:
        idx = mo.start()
        return full_text[:idx].strip(), full_text[idx:].strip()
    return full_text.strip(), None

def parse_profile_block(block: str) -> Dict:
    profile = {
        'name': None, 'age': None, 'age_pref': None, 'birthday': None,
        'gender': None, 'sexuality': None, 'timezone_raw': None, 'tz_offset': None,
        'dislikes': [], 'likes': [], 'hobbies': [], 'traits': [], 'other': {}
    }
    text = normalize_text_keep_lines(block)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    
    # Q/A extraction
    for i, ln in enumerate(lines):
        if '?' in ln:
            q, _, rest = ln.partition('?')
            ans = rest.strip()
            if not ans and i+1 < len(lines): ans = lines[i+1].strip()
            profile['other'][q.strip().lower()] = ans.strip().lower()

    # Field extraction
    accum = {}
    current = None
    label_map = {
        'name': ['name'], 'age': ['age'], 'birthday': ['birthday', 'bday'],
        'gender': ['gender', 'sex'], 'sexuality': ['sexuality', 'orientation'],
        'time_zone': ['time zone', 'timezone', 'time'], 'dislikes': ['dislikes', 'dislike'],
        'likes': ['likes', 'like'], 'hobbies': ['hobbies', 'hobby'],
        'traits': ['your traits', 'their traits', 'traits']
    }
    
    for ln in lines:
        if ':' in ln:
            left, _, right = ln.partition(':')
            found_lab = False
            for k, vs in label_map.items():
                if any(v in left.lower() for v in vs):
                    current = k; accum.setdefault(current, []).append(right.strip())
                    found_lab = True; break
            if found_lab: continue
        
        found_start = False
        for k, vs in label_map.items():
            for v in vs:
                if ln.lower().startswith(v):
                    current = k; accum.setdefault(current, []).append(ln[len(v):].lstrip(':').strip())
                    found_start = True; break
            if found_start: break
        
        if not found_start and current:
            accum[current].append(ln)

    def get_val(k): return " ".join(accum[k]) if k in accum else None
    
    profile['name'] = get_val('name')
    age_raw = get_val('age')
    if age_raw:
        val, pref = parse_age_field(age_raw)
        profile['age'] = val; profile['age_pref'] = pref
    
    profile['gender'] = (get_val('gender') or '').lower()
    profile['sexuality'] = (get_val('sexuality') or '').lower()
    profile['timezone_raw'] = get_val('time_zone')
    profile['tz_offset'] = parse_timezone_offset(profile['timezone_raw'])
    
    for f in ('likes', 'hobbies', 'dislikes', 'traits'):
        raw = get_val(f)
        if raw:
            toks = split_interest_text(raw)
            profile[f] = [canonicalize_interest(t) for t in toks if canonicalize_interest(t)]
    
    return profile

# ---------------- ALGORITHMIC SCORING ----------------
def interested_in(sub_sex: str, tgt_gen: str) -> bool:
    if not sub_sex or 'any' in sub_sex: return True
    s = sub_sex.lower(); t = (tgt_gen or "").lower()
    if 'bi' in s or 'pan' in s: return True
    if 'lesbian' in s: return any(w in t for w in ['female','woman','girl','fem'])
    if 'gay' in s: return any(w in t for w in ['male','man','boy','masc'])
    return True

def compute_interest_score(list_a: List[str], list_b: List[str]) -> Tuple[float, List[Tuple[str,str,float]]]:
    if not list_a and not list_b: return 0.5, []
    a_list = list(set(list_a)); b_list = list(set(list_b))
    matches = []; total_score = 0.0
    
    for a in a_list:
        best_score = 0.0; best_b = None
        for b in b_list:
            sim = fuzzy_match_score(a, b)
            if sim > best_score: best_score = sim; best_b = b
        
        if best_score < FUZZY_MED:
            fam_a = SYNMAN.family_of(a) or CATEGORY_TO_FAMILY_FALLBACK.get(a)
            for b in b_list:
                fam_b = SYNMAN.family_of(b) or CATEGORY_TO_FAMILY_FALLBACK.get(b)
                if fam_a and fam_b and fam_a == fam_b:
                    best_score = max(best_score, 0.75); best_b = b; break
        
        if best_score >= FUZZY_MED:
            matches.append((a, best_b, best_score))
            total_score += 1.0 if best_score >= FUZZY_HIGH else 0.6

    normalized = total_score / max(len(a_list), len(b_list), 1)
    return min(1.0, normalized), matches

def trait_similarity_score(traits_a: List[str], traits_b: List[str]) -> float:
    # Simplified vector overlap for the Hybrid Engine (LLM does the heavy lifting)
    set_a = set(traits_a); set_b = set(traits_b)
    if not set_a or not set_b: return 0.5
    overlap = len(set_a.intersection(set_b))
    return min(1.0, overlap / max(len(set_a), len(set_b), 1) * 2.0) # Bonus for any overlap

def age_compatibility(age_a: Optional[int], age_pref_b: Optional[Tuple[Optional[int], Optional[int]]]) -> float:
    if age_a is None or not age_pref_b: return 0.5
    min_a, max_a = age_pref_b
    if min_a is not None and max_a is not None: return 1.0 if min_a <= age_a <= max_a else 0.0
    if min_a is not None: return 1.0 if age_a >= min_a else 0.0
    if max_a is not None: return 1.0 if age_a <= max_a else 0.0
    return 0.5

def detect_dealbreaker(pA: Dict, pB: Dict) -> Tuple[bool, Optional[str]]:
    # Orientation
    if not interested_in(pA.get('sexuality'), pB.get('gender')) and not interested_in(pB.get('sexuality'), pA.get('gender')):
        return True, "Fundamental sexuality/gender mismatch."
    
    # Trans/Poly Logic
    other_a = pA.get('other', {}); other_b = pB.get('other', {})
    
    def check_conflict(mind_val, other_profile, keywords):
        if mind_val and 'yes' in mind_val: # "Do you mind?" -> "Yes" means they DO mind
            combo = str(other_profile).lower()
            if any(k in combo for k in keywords): return True
        return False

    if check_conflict(other_a.get('do you mind them being trans'), pB, ['trans', 'mtf', 'ftm']):
        return True, "Transgender preference conflict."
    if check_conflict(other_b.get('do you mind them being trans'), pA, ['trans', 'mtf', 'ftm']):
        return True, "Transgender preference conflict."
        
    return False, None

# ---------------- HYBRID COG ----------------
class Matchmaking(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Init Gemini Flash-Lite for high throughput analysis
        api_key = os.getenv('AI_API_KEY')
        if api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('models/gemini-2.5-flash-lite')
        else:
            self.model = None
            logger.warning("AI_API_KEY missing - F-35 Engine running in legacy mode.")

    async def get_ai_analysis(self, p1: Dict, p2: Dict, algo_score: int) -> Dict:
        """Ask Gemini to analyze the vibe and nuance, excluding icebreakers."""
        if not self.model:
            return {"nuance_score": 50, "summary": "AI Analysis Unavailable (Key Missing)"}

        prompt = f"""
        Analyze the romantic compatibility of these two profiles.
        
        Profile 1:
        Age: {p1.get('age')} | Gender: {p1.get('gender')}
        Interests: {', '.join(p1.get('likes', []) + p1.get('hobbies', []))}
        Traits: {', '.join(p1.get('traits', []))}
        
        Profile 2:
        Age: {p2.get('age')} | Gender: {p2.get('gender')}
        Interests: {', '.join(p2.get('likes', []) + p2.get('hobbies', []))}
        Traits: {', '.join(p2.get('traits', []))}
        
        Algorithmic Base Score: {algo_score}%
        
        Task:
        1. Determine a "Nuance Score" (0-100) based on emotional vibe and shared specific interests.
        2. Write a 2-sentence "Emotional Summary" of why they match or don't.
        3. DO NOT provide icebreakers or advice.
        
        Output JSON only:
        {{
            "nuance_score": 0,
            "summary": "text"
        }}
        """
        
        try:
            response = await self.bot.loop.run_in_executor(
                None, 
                lambda: self.model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
            )
            return json.loads(response.text)
        except Exception as e:
            logger.error(f"AI Analysis Failed: {e}")
            return {"nuance_score": algo_score, "summary": "AI Analysis unavailable due to connection error."}

    @app_commands.command(name="analyze_compatibility", description="F-35 Hybrid Compatibility Analysis")
    async def analyze_compatibility(self, interaction: discord.Interaction, form1: str, form2: str):
        await interaction.response.defer()
        
        try:
            # 1. PARSE
            p1 = parse_profile_block(find_section_bounds(form1)[0])
            p2 = parse_profile_block(find_section_bounds(form2)[0])
            
            # 2. HARD GATEKEEPING (Dealbreakers)
            is_dealbreaker, reason = detect_dealbreaker(p1, p2)
            if is_dealbreaker:
                embed = discord.Embed(title="🚫 𝐼𝑛𝑐𝑜𝑚𝑝𝑎𝑡𝑖𝑏𝑙𝑒 𝑀𝑎𝑡𝑐ℎ", description=f"**Reason:** {reason}", color=0xff0000)
                await interaction.followup.send(embed=embed)
                return

            # 3. ALGORITHMIC SCORING (The "Hard" Score)
            int_score, _ = compute_interest_score(p1['likes']+p1['hobbies'], p2['likes']+p2['hobbies'])
            age_score = (age_compatibility(p1['age'], p2['age_pref']) + age_compatibility(p2['age'], p1['age_pref'])) / 2
            
            # Base algo score (40% interests, 60% practical)
            base_algo_score = int((int_score * 0.4 + age_score * 0.6) * 100)

            # 4. AI ANALYSIS (The "Soft" Score)
            ai_result = await self.get_ai_analysis(p1, p2, base_algo_score)
            nuance_score = ai_result.get("nuance_score", base_algo_score)
            summary = ai_result.get("summary", "Analysis unavailable.")

            # 5. FINAL WEIGHTED SCORE
            # 60% Algorithm (Safety/Facts) + 40% AI (Vibes)
            final_score = int((base_algo_score * 0.6) + (nuance_score * 0.4))
            
            # 6. DISPLAY
            if final_score >= 80: color = 0xffffff; title = "💖 𝐸𝑥𝑐𝑒𝑙𝑙𝑒𝑛𝑡 𝑀𝑎𝑡𝑐ℎ"
            elif final_score >= 60: color = 0xffffff; title = "✨ 𝐺𝑜𝑜𝑑 𝑃𝑜𝑡𝑒𝑛𝑡𝑖𝑎𝑙"
            else: color = 0xffffff; title = "🤔 𝑀𝑜𝑑𝑒𝑟𝑎𝑡𝑒 𝐶𝑜𝑚𝑝𝑎𝑡𝑖𝑏𝑖𝑙𝑖𝑡𝑦"

            embed = discord.Embed(title=title, color=color)
            embed.add_field(name="Overall Score", value=f"**{final_score}%**", inline=False)
            embed.add_field(name="🔍 Analysis Breakdown", value=f"• Algorithm Base: {base_algo_score}%\n• Vibe Check (AI): {nuance_score}%", inline=False)
            embed.add_field(name="📝 Emotional Summary", value=f"*{summary}*", inline=False)
            
            # Footer
            embed.set_footer(text="F-35 Hybrid Engine")
            
            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.exception("Analysis Error")
            await interaction.followup.send(f"❌ Error: {str(e)}")

async def setup(bot):
    await bot.add_cog(Matchmaking(bot))