# matchmaking2.py
# F-22 Cupid Engine v3.4 — Hybrid: v3.0 scoring + synonyms.json + Friction Analysis + Typo Fixes
import discord
from discord import app_commands
from discord.ext import commands
import re
import difflib
import math
import json
import os
import time
import logging
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------- CONFIG ----------------
DEBUG = False
SYNONYMS_FILE = "synonyms.json"
FEEDBACK_LOG_FILE = "feedback_log.json"
FUZZY_HIGH = 0.82
FUZZY_MED = 0.55

# ---------------- FALLBACK (v3.0 inline synonyms / canonical map) ----------------
INTEREST_SYNONYMS = {
    "video_games": {"gaming", "video games", "genshin", "gacha", "pjsk", "hsr", "hoyo", "minecraft", "fnaf", "hollow knight", "roblox", "fortnite", "valorant", "rivals"},
    "anime_manga": {"anime", "manga", "jjk", "kny", "one piece", "death note", "manhwa"},
    "music": {"music", "citypop", "indie music", "kpop", "listening to music", "rap", "r&b", "tyler", "kanye"},
    "reading_writing": {"reading", "books", "fanfiction", "ff", "writing"},
    "arts_crafts": {"art", "drawing", "graphic design", "graphics", "editing", "sketching", "crochet"},
    "photography": {"photography", "pfp", "matching pfps", "matching things"},
    "cooking_baking": {"cooking", "baking", "cakes", "brownies"},
    "vehicles": {"bike", "bikes", "car", "cars", "biker"},
    "movies_tv": {"movies", "films", "documentaries", "the boys", "lucifer", "marvel", "spiderman", "sitcoms"},
    "true_crime_paranormal": {"true crime", "creepypasta", "analog horror", "horror"},
    "social_communication": {"vc", "voice chat", "vcing", "chatting", "texting", "yapping", "calling", "talking"},
    "sports": {"badminton", "volleyball", "figure skater", "sports", "basketball", "gym", "football"}
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

# Trait clusters fallback (v3.0 style)
TRAIT_CLUSTERS_FALLBACK = {
    "empathic": {"empathetic", "caring", "kind", "supportive", "understanding", "sweet", "nice"},
    "communicative": {"talkative", "chatty", "yapper", "communicative", "good listener"},
    "introverted": {"shy", "introverted", "reserved", "quiet", "calm"},
    "energetic": {"bubbly", "energetic", "hyper", "playful", "funny", "chaotic"},
    "analytical": {"observant", "analytical", "practical", "smart", "intelligent", "nerd"},
    "passionate": {"affectionate", "clingy", "flirty", "freaky", "passionate"}
}

ENERGY_KEYWORDS_FALLBACK = {
    "shy": 0.2, "introverted": 0.2, "calm": 0.35, "chill": 0.4,
    "talkative": 0.75, "chatty": 0.75, "bubbly": 0.9, "energetic": 0.9, "hyper": 0.95, "chaotic": 0.95
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
            "categories": {}, "families": {}, "trait_clusters": {}, "energy_keywords": {}, "tz_abbreviations": {}
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
        if not os.path.exists(self.path): return
        try:
            if os.path.getmtime(self.path) != self.mtime: self.load()
        except: pass

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

# ---------------- UTILITIES / PARSERS ----------------
def normalize_text_keep_lines(text: str) -> str:
    text = text.replace('╰', '\n').replace('꒰', ' ').replace('୧', ' ').replace('𐔌', '\n')
    text = re.sub(r'[^\x00-\x7F]+', ' ', text)
    text = text.replace('\r\n','\n').replace('\r','\n')
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join([ln for ln in lines if ln])

def split_interest_text(raw: str) -> List[str]:
    if not raw: return []
    s = re.sub(r'\band\b', ',', raw, flags=re.IGNORECASE)
    parts = re.split(r'[,\n;/|•\u2022\-!]+', s) # Added ! delimiter
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
        
    heur = {
        "genshin": "video_games", "gacha": "video_games", "pjsk": "video_games",
        "hoyo": "video_games", "anime": "anime_manga", "manga": "anime_manga", 
        "music": "music", "bake": "cooking_baking", "baking": "cooking_baking",
        "draw": "arts_crafts", "drawing": "arts_crafts", "art": "arts_crafts",
        "photo": "photography", "bike": "vehicles", "car": "vehicles",
        "horror": "true_crime_paranormal", "roblox": "video_games"
    }
    for k, v in heur.items():
        if k in t: return v
    
    if len(t) <= 2: return None
    return f"custom::{t}"

def parse_timezone_offset(tz_raw: str) -> Optional[float]:
    if not tz_raw: return None
    s = tz_raw.lower()
    m = re.search(r'(utc|gmt)\s*([+-]\d+(\.\d+)?)', s)
    if m:
        try: return float(m.group(2))
        except: pass
    m2 = re.search(r'([+-]\d{1,2}(?:\.\d)?)', s)
    if m2 and ('+' in s or '-' in s):
        try: return float(m2.group(1))
        except: pass
    
    SYNMAN.reload_if_needed()
    for abbr, off in SYNMAN.tz_abbrev.items():
        if abbr in s: return float(off)
    
    for abbr, off in {"ist":5.5, "pkt":5, "est":-5, "edt":-4, "pst":-8, "cet":1, "bst":1}.items():
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

# ---------------- PROFILE PARSER ----------------
def find_section_bounds(full_text: str) -> Tuple[str, Optional[str]]:
    mo = re.search(r'(?i)\bthems?\b|𝓣𝒉𝒆𝓂', full_text)
    if mo:
        idx = mo.start()
        you_block = full_text[:idx]
        other_m = re.search(r'(?i)\bother\b|note\b|𝜗𝜚', full_text[idx:])
        them_block = full_text[idx: idx+other_m.start()] if other_m else full_text[idx:]
        return you_block.strip(), them_block.strip()
    return full_text.strip(), None

def parse_profile_block(block: str) -> Dict:
    profile = {
        'name': None, 'age': None, 'age_pref': None, 'birthday': None,
        'gender': None, 'sexuality': None, 'timezone_raw': None, 'tz_offset': None,
        'dislikes': [], 'likes': [], 'hobbies': [], 'traits': [], 'other': {}
    }
    text = normalize_text_keep_lines(block)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    
    # Q/A in other
    for i, ln in enumerate(lines):
        if '?' in ln:
            q, _, rest = ln.partition('?')
            ans = rest.strip()
            if not ans and i+1 < len(lines):
                ans = lines[i+1].strip()
            profile['other'][q.strip().lower()] = ans.strip().lower()

    accum = {}
    current = None
    
    # --- TYPO FIX: Added 'ag ', 'ag:', 'ages' ---
    label_map = {
        'name': ['name'], 
        'age': ['age', 'ag ', 'ag:', 'ages'], 
        'birthday': ['birthday', 'bday'],
        'gender': ['gender', 'sex'], 
        'sexuality': ['sexuality', 'orientation'],
        'time_zone': ['time zone', 'timezone', 'time'], 
        'dislikes': ['dislikes', 'dislike'],
        'likes': ['likes', 'like'], 
        'hobbies': ['hobbies', 'hobby'],
        'traits': ['your traits', 'their traits', 'traits']
    }
    
    for ln in lines:
        # Check colons first
        if ':' in ln:
            left, _, right = ln.partition(':')
            left_key = left.strip().lower()
            # Try to match label
            found = False
            for key, variants in label_map.items():
                for v in variants:
                    if v in left_key:
                        current = key
                        accum.setdefault(current, [])
                        if right.strip(): accum[current].append(right.strip())
                        found = True
                        break
                if found: break
            if found: continue
            
        # Check startswith
        found = False
        for key, variants in label_map.items():
            for v in variants:
                if ln.lower().startswith(v):
                    tail = ln[len(v):].lstrip(':').strip()
                    accum.setdefault(key, [])
                    if tail: accum[key].append(tail)
                    current = key
                    found = True
                    break
            if found: break
        else:
            if current: accum.setdefault(current, []).append(ln)

    def join_acc(k): return " ".join(accum[k]) if k in accum else None
    
    profile['name'] = join_acc('name')
    age_raw = join_acc('age')
    if age_raw:
        age_val, age_pref = parse_age_field(age_raw)
        profile['age'] = age_val
        profile['age_pref'] = age_pref
    profile['birthday'] = join_acc('birthday')
    profile['gender'] = (join_acc('gender') or '').lower()
    profile['sexuality'] = (join_acc('sexuality') or '').lower()
    tz_raw = join_acc('time_zone')
    profile['timezone_raw'] = tz_raw
    profile['tz_offset'] = parse_timezone_offset(tz_raw) if tz_raw else None
    
    for field in ('likes', 'hobbies', 'dislikes', 'traits'):
        raw = join_acc(field)
        if field == 'traits' and not raw:
            bullets = [ln.lstrip('•-* ').strip() for ln in lines if ln.startswith('•') or ln.startswith('-') or ln.startswith('*')]
            if bullets: raw = "\n".join(bullets)
        if raw:
            toks = split_interest_text(raw)
            normalized = []
            for t in toks:
                if field in ['likes', 'hobbies']:
                    c = canonicalize_interest(t)
                    if c: normalized.append(c)
                else:
                    normalized.append(t.lower()) # keep traits/dislikes raw for now
            profile[field] = list(dict.fromkeys(normalized))
            
    # Trait cluster logic
    raw_traits_text = join_acc('traits') or ""
    if raw_traits_text:
         phrases = [p.strip().lower() for p in re.split(r'[,\n;•\-]+', raw_traits_text) if p.strip()]
         profile['traits'] = list(dict.fromkeys(profile.get('traits', []) + phrases))
         
    return profile

# ---------------- SCORING ----------------
def interested_in(subject_sexuality: str, target_gender: str) -> bool:
    if not subject_sexuality or 'any' in subject_sexuality: return True
    s = subject_sexuality.lower(); t = (target_gender or "").lower()
    if 'bi' in s or 'pan' in s: return True
    if 'lesbian' in s: return any(w in t for w in ['female','woman','girl','fem'])
    if 'gay' in s: return any(w in t for w in ['male','man','boy','masc'])
    if 'straight' in s or 'hetero' in s: return True
    return True

def category_family_of(token: str) -> Optional[str]:
    SYNMAN.reload_if_needed()
    fam = SYNMAN.family_of(token) or CATEGORY_TO_FAMILY_FALLBACK.get(token)
    return fam

def compute_interest_score(list_a: List[str], list_b: List[str]) -> Tuple[float, List[Tuple[str,str,float]]]:
    if not list_a and not list_b: return 0.5, []
    a_list = list(dict.fromkeys(list_a)); b_list = list(dict.fromkeys(list_b))
    matched_examples = []; weight_sum = 0.0
    total_possible = max(len(a_list), len(b_list), 1)
    for a in a_list:
        best_score = 0.0; best_b = None
        for b in b_list:
            if a == b:
                best_score = 1.0; best_b = b; break
        if not best_b:
            for b in b_list:
                sim = fuzzy_match_score(a, b)
                if sim > best_score:
                    best_score = sim; best_b = b
        if best_score < FUZZY_MED:
            fam_a = category_family_of(a)
            for b in b_list:
                fam_b = category_family_of(b)
                if fam_a and fam_b and fam_a == fam_b:
                    best_score = max(best_score, 0.75); best_b = b; break
        if best_score >= FUZZY_HIGH:
            weight_sum += 1.0; matched_examples.append((a,best_b,1.0))
        elif best_score >= FUZZY_MED:
            weight_sum += 0.6; matched_examples.append((a,best_b,0.6))
    score = weight_sum / total_possible
    return max(0.0, min(1.0, score)), matched_examples

def compute_trait_vector(traits: List[str]) -> Dict:
    SYNMAN.reload_if_needed()
    clusters = {}
    raw_blob = " ".join(traits).lower()
    
    source_clusters = SYNMAN.trait_clusters if SYNMAN.trait_clusters else TRAIT_CLUSTERS_FALLBACK
    for cname, keywords in source_clusters.items():
        count = sum(1 for kw in keywords if kw in raw_blob)
        clusters[cname] = min(1.0, count / 3.0)
        
    energy_vals = []
    source_energy = SYNMAN.energy_map if SYNMAN.energy_map else ENERGY_KEYWORDS_FALLBACK
    for kw, val in source_energy.items():
        if kw in raw_blob:
            energy_vals.append(val)
            
    energy = sum(energy_vals)/len(energy_vals) if energy_vals else 0.5
    return {"clusters": clusters, "energy": energy}

def trait_similarity_score(traits_a: List[str], traits_b: List[str]) -> float:
    va = compute_trait_vector(traits_a)
    vb = compute_trait_vector(traits_b)
    keys = set(list(va["clusters"].keys()) + list(vb["clusters"].keys()))
    vec_a = [va["clusters"].get(k,0.0) for k in keys]
    vec_b = [vb["clusters"].get(k,0.0) for k in keys]
    dot = sum(x*y for x,y in zip(vec_a, vec_b))
    na = math.sqrt(sum(x*x for x in vec_a)) or 1.0
    nb = math.sqrt(sum(x*x for x in vec_b)) or 1.0
    cosine = dot/(na*nb)
    energy_bonus = max(0.0, 1.0 - abs(va["energy"] - vb["energy"])*0.9)
    score = 0.75*cosine + 0.25*energy_bonus
    return max(0.0, min(1.0, score))

def dislike_conflict_penalty(p1: Dict, p2: Dict) -> float:
    penalty = 0.0
    for a in (p1.get('likes', []) + p1.get('hobbies', [])):
        if a in p2.get('dislikes', []): penalty += 0.12
    for b in (p2.get('likes', []) + p2.get('hobbies', [])):
        if b in p1.get('dislikes', []): penalty += 0.12
    return min(0.5, penalty)

def timezone_compat_score(offset_a: Optional[float], offset_b: Optional[float], raw_a: Optional[str], raw_b: Optional[str]) -> float:
    if raw_a and isinstance(raw_a, str) and 'any' in raw_a.lower(): return 0.65
    if raw_b and isinstance(raw_b, str) and 'any' in raw_b.lower(): return 0.65
    if offset_a is None or offset_b is None: return 0.5
    diff = abs(offset_a - offset_b)
    if diff <= 1: return 1.0
    if diff <= 3: return 0.9
    if diff <= 6: return 0.65
    if diff <= 9: return 0.4
    return 0.2

def age_compatibility(age_a: Optional[int], age_pref_b: Optional[Tuple[Optional[int], Optional[int]]]) -> float:
    if age_a is None or not age_pref_b: return 0.5
    min_age, max_age = age_pref_b
    if min_age is None and max_age is None: return 0.5
    if min_age is not None and max_age is not None:
        return 1.0 if (min_age <= age_a <= max_age) else 0.0
    if min_age is not None: return 1.0 if age_a >= min_age else 0.0
    if max_age is not None: return 1.0 if age_a <= max_age else 0.0
    return 0.5

def calibrate_score(raw: float) -> float:
    adjusted = raw * 1.10 + 0.04
    return max(0.0, min(1.0, adjusted))

def compute_confidence_index(p1: Dict, p2: Dict) -> Tuple[float, str]:
    points = 0.0
    for p in (p1, p2):
        if p.get('likes'): points += 0.15
        if p.get('hobbies'): points += 0.10
        if p.get('traits'): points += 0.15
        if p.get('timezone_raw'): points += 0.10
        if p.get('age') is not None: points += 0.05
        if p.get('sexuality'): points += 0.05
    conf = min(1.0, points)
    tokens_count = len(p1.get('likes',[])+p1.get('hobbies',[])+p2.get('likes',[])+p2.get('hobbies',[]))
    conf += min(0.15, tokens_count * 0.01)
    conf = min(1.0, conf)
    explanation = f"Sections filled: likes/hobbies/traits/timezone/age/sex coverage; tokens={tokens_count}"
    return conf, explanation

# ---------------- FEEDBACK VIEW ----------------
class FeedbackView(discord.ui.View):
    def __init__(self, match_id: str):
        super().__init__(timeout=None)
        self.match_id = match_id

    @discord.ui.button(emoji="👍", style=discord.ButtonStyle.green, custom_id="approve_btn")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.record_feedback(interaction.user, True)
        await interaction.response.send_message("💚 Thanks for approving this match!", ephemeral=True)

    @discord.ui.button(emoji="👎", style=discord.ButtonStyle.red, custom_id="disapprove_btn")
    async def disapprove(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.record_feedback(interaction.user, False)
        await interaction.response.send_message("💔 Feedback noted — we'll consider it for improvements.", ephemeral=True)

    async def record_feedback(self, user: discord.User, approved: bool):
        entry = {
            "match_id": self.match_id,
            "user_id": str(user.id),
            "username": f"{user.name}#{user.discriminator}",
            "approved": approved,
            "timestamp": int(time.time())
        }
        try:
            if os.path.exists(FEEDBACK_LOG_FILE):
                with open(FEEDBACK_LOG_FILE, "r", encoding="utf-8") as f:
                    logs = json.load(f)
            else:
                logs = []
            logs.append(entry)
            with open(FEEDBACK_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(logs, f, indent=2)
            logger.info("Feedback recorded: %s", entry)
        except Exception:
            logger.exception("Failed to write feedback log")

# ---------------- COG ----------------
class Matchmaking(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_conflict_details(self, p1: Dict, p2: Dict) -> List[str]:
        """Helper to find specific words causing conflict penalty"""
        conflicts = []
        p1_interests = set(p1.get('likes', []) + p1.get('hobbies', []))
        p2_dislikes = set(p2.get('dislikes', []))
        for item in p1_interests:
            if item in p2_dislikes:
                conflicts.append(f"• **{p1.get('name', 'P1')}** likes `{item}`, but **{p2.get('name', 'P2')}** dislikes it.")
        
        p2_interests = set(p2.get('likes', []) + p2.get('hobbies', []))
        p1_dislikes = set(p1.get('dislikes', []))
        for item in p2_interests:
            if item in p1_dislikes:
                conflicts.append(f"• **{p2.get('name', 'P2')}** likes `{item}`, but **{p1.get('name', 'P1')}** dislikes it.")
        return conflicts

    @app_commands.command(name="analyze_compatibility", description="Analyze compatibility between two matchmaking forms")
    @app_commands.describe(
        form1="Paste first full form",
        form2="Paste second full form",
        engine="Choose which engine to use"
    )
    @app_commands.choices(engine=[
        app_commands.Choice(name="F-22", value="f22")
    ])
    async def analyze_compatibility(
        self,
        interaction: discord.Interaction,
        form1: str,
        form2: str,
        engine: app_commands.Choice[str]
    ):
        await interaction.response.defer()
        try:
            SYNMAN.reload_if_needed()
            you1, _ = find_section_bounds(form1)
            you2, _ = find_section_bounds(form2)
            p1 = parse_profile_block(you1)
            p2 = parse_profile_block(you2)

            # Dealbreaker checks (reuse existing logic if defined, otherwise define helpers here)
            deal1, reason1 = detect_dealbreaker_orientation(p1, p2)
            deal2, reason2 = detect_dealbreaker_other(p1, p2)
            if deal1:
                em = discord.Embed(title="₍^. .^₎⟆ 𝑂ℎ 𝑚𝑦! 𝐹𝑢𝑛𝑑𝑎𝑚𝑒𝑛𝑡𝑎𝑙 𝐼𝑛𝑐𝑜𝑚𝑝𝑎𝑡𝑖𝑏𝑖𝑙𝑖𝑡𝑦", description=reason1 or "𝑊𝑜𝑎ℎ! 𝑆𝑒𝑥𝑢𝑎𝑙𝑖𝑡𝑦/𝑔𝑒𝑛𝑑𝑒𝑟 𝑚𝑖𝑠𝑚𝑎𝑡𝑐ℎ", color=0xff0000)
                await interaction.followup.send(embed=em); return
            if deal2:
                em = discord.Embed(title="₍^. .^₎⟆ 𝑃𝑟𝑒𝑓𝑒𝑟𝑒𝑛𝑐𝑒 𝐶𝑜𝑛𝑓𝑙𝑖𝑐𝑡", description=reason2 or "𝑃𝑟𝑒𝑓𝑒𝑟𝑒𝑛𝑐𝑒 𝐶𝑜𝑛𝑓𝑙𝑖𝑐𝑡", color=0xff0000)
                await interaction.followup.send(embed=em); return

            # Score Calculations (Full Complexity)
            interests1 = p1.get('likes', []) + p1.get('hobbies', [])
            interests2 = p2.get('likes', []) + p2.get('hobbies', [])
            interest_score_12, matches_12 = compute_interest_score(interests1, interests2)
            interest_score_21, matches_21 = compute_interest_score(interests2, interests1)
            interest_score = (interest_score_12 + interest_score_21) / 2.0

            trait_score = trait_similarity_score(p1.get('traits', []), p2.get('traits', []))

            tz_score = timezone_compat_score(p1.get('tz_offset'), p2.get('tz_offset'), p1.get('timezone_raw'), p2.get('timezone_raw'))
            age_score_a = age_compatibility(p1.get('age'), p2.get('age_pref'))
            age_score_b = age_compatibility(p2.get('age'), p1.get('age_pref'))
            age_score = (age_score_a + age_score_b) / 2.0
            practical_score = tz_score * 0.6 + age_score * 0.4

            conflict_pen = dislike_conflict_penalty(p1, p2)

            token_count_interests = max(len(interests1) + len(interests2), 1)
            token_count_traits = max(len(p1.get('traits', [])) + len(p2.get('traits', [])), 1)
            if token_count_traits >= token_count_interests:
                weights = {'interests': 0.30, 'emotional': 0.45, 'practical': 0.25}
            else:
                weights = {'interests': 0.45, 'emotional': 0.30, 'practical': 0.25}

            raw_overall = (interest_score * weights['interests'] +
                           trait_score * weights['emotional'] +
                           practical_score * weights['practical'])
            raw_overall = max(0.0, raw_overall - conflict_pen)
            overall = calibrate_score(raw_overall)
            overall_pct = int(round(overall * 100))

            conf, conf_expl = compute_confidence_index(p1, p2)
            conf_pct = int(round(conf * 100))

            if overall_pct >= 75:
                level = "➤ Excellent Match"; color = 0xffffff
            elif overall_pct >= 55:
                level = "➤ Good Potential"; color = 0xffffff
            elif overall_pct >= 40:
                level = "➤ Moderate Compatibility"; color = 0xffffff
            else:
                level = "➤ Low Compatibility"; color = 0xffffff

            embed = discord.Embed(title="<:s_white2:1382052523166142486> 𝐴𝑡ℎ𝑒𝑛𝑎 𝑀𝑎𝑡𝑐ℎ𝑚𝑎𝑘𝑖𝑛𝑔 𝐸𝑛𝑔𝑖𝑛𝑒 <:s_white2:1382052523166142486>", description=level, color=color)
            embed.add_field(name="<:p_hearts:1378053399525982288> 𝑂𝑣𝑒𝑟𝑎𝑙𝑙 𝑆𝑐𝑜𝑟𝑒", value=f"**{overall_pct}%**", inline=False)
            embed.add_field(name="<:p_hearts:1378053399525982288> 𝐵𝑟𝑒𝑎𝑘𝑑𝑜𝑤𝑛 𝑜𝑓 𝐸𝑛𝑔𝑖𝑛𝑒 𝐴𝑛𝑎𝑙𝑦𝑠𝑖𝑠", value=f"• **Interests**: {int(round(interest_score*100))}%\n• **Emotional/Traits**: {int(round(trait_score*100))}%\n• **Practical (timezone/age)**: {int(round(practical_score*100))}%", inline=False)
            embed.add_field(name="<:p_hearts:1378053399525982288> 𝐹𝑜𝑟𝑚 𝐶𝑜𝑛𝑓𝑖𝑑𝑒𝑛𝑐𝑒", value=f"{conf_pct}% — {conf_expl}", inline=False)

            # ... (keep previous code) ...
            
            # --- FIXED SHARED INTERESTS DISPLAY ---
            matches_combined = matches_12 + matches_21
            if matches_combined:
                lines = []
                seen = set()
                for a, b, w in matches_combined[:6]:
                    # Sort them so A-B and B-A count as the same pair
                    pair = tuple(sorted((a, b)))
                    if pair in seen: continue
                    seen.add(pair)
                    
                    # Clean up the text (Remove "custom::" and underscores)
                    clean_a = a.replace("custom::", "").replace("_", " ").title()
                    clean_b = b.replace("custom::", "").replace("_", " ").title()
                    
                    lines.append(f"• `{clean_a}` ↔ `{clean_b}` ({int(round(w*100))}%)")
                    
                embed.add_field(name="<:p_hearts:1378053399525982288> 𝑆ℎ𝑎𝑟𝑒𝑑 𝐼𝑛𝑡𝑒𝑟𝑒𝑠𝑡𝑠", value="\n".join(lines), inline=False)
            else:
                embed.add_field(name="<:p_hearts:1378053399525982288> 𝑆ℎ𝑎𝑟𝑒𝑑 𝐼𝑛𝑡𝑒𝑟𝑒𝑠𝑡𝑠", value="No clear shared items found.", inline=False)

            # ... (keep the rest of the code) ...
            # --- NEW: FRICTION ANALYSIS ---
            friction_points = []
            
            # 1. Dislike Conflicts
            if conflict_pen > 0:
                conflicts = self.get_conflict_details(p1, p2)
                friction_points.extend(conflicts)

            # 2. Timezone Issues
            if tz_score < 0.6 and p1.get('tz_offset') is not None and p2.get('tz_offset') is not None:
                diff = abs(p1['tz_offset'] - p2['tz_offset'])
                friction_points.append(f"• **Large Time Difference**: {diff} hours apart (Practicality Penalty).")

            # 3. Age Issues
            if age_score < 1.0:
                if p1.get('age') and p2.get('age_pref'):
                    if age_compatibility(p1.get('age'), p2.get('age_pref')) < 1.0:
                        friction_points.append(f"• **Age Mismatch**: {p1.get('name','P1')}'s age ({p1.get('age')}) is outside {p2.get('name','P2')}'s range.")
                if p2.get('age') and p1.get('age_pref'):
                    if age_compatibility(p2.get('age'), p1.get('age_pref')) < 1.0:
                        friction_points.append(f"• **Age Mismatch**: {p2.get('name','P2')}'s age ({p2.get('age')}) is outside {p1.get('name','P1')}'s range.")
                # If ages are missing, warn about confidence
                if p1.get('age') is None or p2.get('age') is None:
                     friction_points.append("• **Unknown Age**: One or both profiles are missing age data, causing lower confidence.")

            # 4. Energy Mismatch
            vec1 = compute_trait_vector(p1.get('traits', []))
            vec2 = compute_trait_vector(p2.get('traits', []))
            if abs(vec1['energy'] - vec2['energy']) > 0.4:
                e1_str = "High" if vec1['energy'] > 0.6 else "Low" if vec1['energy'] < 0.4 else "Mid"
                e2_str = "High" if vec2['energy'] > 0.6 else "Low" if vec2['energy'] < 0.4 else "Mid"
                friction_points.append(f"• **Energy Mismatch**: {e1_str}-Energy vs {e2_str}-Energy.")

            if friction_points:
                embed.add_field(name="⚠️ 𝐹𝑟𝑖𝑐𝑡𝑖𝑜𝑛 𝑃𝑜𝑖𝑛𝑡𝑠 (𝑊ℎ𝑦 𝑖𝑠 𝑡ℎ𝑒 𝑠𝑐𝑜𝑟𝑒 𝑙𝑜𝑤?)", value="\n".join(friction_points), inline=False)
            
            # --- END NEW SECTION ---

            def emotional_summary(p):
                vec = compute_trait_vector(p.get('traits', []))
                clusters_active = [c for c, s in vec['clusters'].items() if s > 0.2]
                return clusters_active, vec['energy']
            c1, e1 = emotional_summary(p1); c2, e2 = emotional_summary(p2)
            cluster_intersection = set(c1).intersection(set(c2))
            if cluster_intersection:
                emot_line = f"Both show similar traits: {', '.join(cluster_intersection)}."
            else:
                emot_line = "Traits don't show strong overlap — consider a test chat."
            energy_diff = abs(e1-e2)
            emot_line += " Energy levels compatible." if energy_diff <= 0.25 else " Energy levels differ somewhat."

            embed.add_field(name="𝐴𝑡ℎ𝑒𝑛𝑎'𝑠 𝐸𝑚𝑜𝑡𝑖𝑜𝑛𝑎𝑙 𝑆𝑢𝑚𝑚𝑎𝑟𝑦", value=emot_line, inline=False)

            if DEBUG:
                embed.add_field(name="🛠 Parsed Profile 1", value=str(p1)[:1000], inline=False)
                embed.add_field(name="🛠 Parsed Profile 2", value=str(p2)[:1000], inline=False)

            match_id = str(int(time.time()*1000))
            view = FeedbackView(match_id)
            await interaction.followup.send(embed=embed, view=view)
        except Exception:
            logger.exception("F-22 v3.4 analysis failed")
            await interaction.followup.send("𐔌՞. .՞𐦯 𝐴𝑛𝑎𝑙𝑦𝑠𝑖𝑠 𝑓𝑎𝑖𝑙𝑒𝑑 — 𝑐ℎ𝑒𝑐𝑘 𝑡ℎ𝑒 𝑓𝑜𝑟𝑚𝑠 𝑎𝑛𝑑 𝑡𝑟𝑦 𝑎𝑔𝑎𝑖𝑛.")

    @app_commands.command(name="reload_synonyms", description="Reload synonyms.json (admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def reload_synonyms(self, interaction: discord.Interaction):
        SYNMAN.load()
        await interaction.response.send_message("✅ synonyms.json reloaded.", ephemeral=True)

# ---------------- HELPERS (Dealbreakers) ----------------
def detect_dealbreaker_orientation(pA: Dict, pB: Dict) -> Tuple[bool, Optional[str]]:
    a_to_b = interested_in(pA.get('sexuality', ''), pB.get('gender', ''))
    b_to_a = interested_in(pB.get('sexuality', ''), pA.get('gender', ''))
    if not a_to_b and not b_to_a:
        return True, "Neither person's declared sexuality suggests attraction to the other's declared gender."
    return False, None

def detect_dealbreaker_other(pA: Dict, pB: Dict) -> Tuple[bool, Optional[str]]:
    other_a = pA.get('other', {}); other_b = pB.get('other', {})
    def parse_ans(ans: str) -> Optional[bool]:
        if not ans: return None
        an = ans.lower()
        if any(x in an for x in ['no', "don't", "dont", "nope", 'nah']): return False
        if any(x in an for x in ['yes','i do','prefer','i mind']): return True
        return None
    trans_a = parse_ans(other_a.get('do you mind them being trans', ''))
    trans_b = parse_ans(other_b.get('do you mind them being trans', ''))
    poly_a = parse_ans(other_a.get('do you mind them being poly', ''))
    poly_b = parse_ans(other_b.get('do you mind them being poly', ''))
    for mind, otherp in [(trans_a,pB),(trans_b,pA)]:
        if mind is True:
            combined = " ".join([str(otherp.get('gender','')), str(otherp.get('sexuality','')), " ".join(otherp.get('traits',[]))])
            if 'trans' in combined.lower(): return True, "One person does not accept trans partners while the other is trans."
    for mind, otherp in [(poly_a,pB),(poly_b,pA)]:
        if mind is True:
            combined = " ".join([str(otherp.get('sexuality','')), " ".join(otherp.get('traits',[]))])
            if 'poly' in combined.lower(): return True, "One person prefers monogamy while the other indicates polyamory."
    return False, None

async def setup(bot):
    await bot.add_cog(Matchmaking(bot))