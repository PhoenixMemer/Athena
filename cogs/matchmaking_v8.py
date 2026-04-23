# cogs/matchmaking_f22.py
# Athena F22 "Two-Brain" Matchmaking Engine (Mark VIII Patch)

import discord
from discord import app_commands
from discord.ext import commands
import os
import re
import json
import logging
import unicodedata
import asyncio
from typing import Dict, List, Tuple, Optional

# NEW Google GenAI SDK (v1.0+)
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------- CONFIG & CONSTANTS ----------------
SYNONYMS_FILE = "synonyms.json"
CUPID_ROLES = [1380028499611488276, 1218201074448732270]

# Expanded Base Taxonomy
EXPANDED_CATEGORIES = {
    "video_games": ["gaming", "video games", "games", "genshin", "gacha", "pjsk", "hollow knight", "hoyo", "hsr", "minecraft", "fnaf", "valorant", "fortnite", "roblox", "overwatch", "league of legends", "stardew valley", "rpg", "fps"],
    "anime_manga": ["anime", "manga", "jjk", "kny", "one piece", "death note", "manhwa", "webtoon", "studio ghibli", "naruto", "bleach", "mha"],
    "music": ["music", "citypop", "indie", "kpop", "jpop", "rap", "r&b", "hiphop", "metal", "rock", "classical", "playing instruments", "guitar", "piano", "drums"],
    "reading_writing": ["reading", "books", "fanfiction", "ff", "novels", "writing", "poetry", "literature", "ao3", "wattpad"],
    "arts_crafts": ["art", "drawing", "digital art", "graphic design", "sketching", "painting", "crochet", "knitting", "sewing"],
    "photography": ["photography", "pfp", "matching pfps", "taking pictures", "cameras"],
    "cooking_baking": ["cooking", "baking", "brownies", "cakes", "culinary", "foodie"],
    "vehicles": ["bike", "bikes", "car", "cars", "biker", "motorcycles", "jdm", "f1"],
    "movies_tv": ["movies", "films", "the boys", "dexter", "lucifer", "documentaries", "sitcoms", "kdrama", "shows", "netflix", "cinema"],
    "true_crime_paranormal": ["true crime", "creepypasta", "analog horror", "horror", "mystery", "supernatural", "ghosts"],
    "social_communication": ["vc", "voice chat", "vcing", "chatting", "texting", "yapping", "calling", "hanging out", "going out"],
    "sports_active": ["sports", "gym", "working out", "badminton", "volleyball", "basketball", "soccer", "football", "skating", "swimming", "hiking"],
    "tech_programming": ["coding", "programming", "tech", "computers", "linux", "pc building", "keyboards", "software"],
    "nature_ocean": ["ocean", "nature", "animals", "pets", "sleeping", "sleep"],
    "fashion_beauty": ["fashion", "makeup", "skincare", "clothes", "shopping", "style", "thrifting"]
}

EXPANDED_TRAITS = {
    "empathic": ["empathetic", "caring", "kind", "supportive", "understanding", "sweet", "gentle", "patient"],
    "communicative": ["talkative", "chatty", "yapper", "vocal", "communicative", "expressive", "transparent"],
    "introverted": ["shy", "introverted", "reserved", "quiet", "timid", "listener", "observant"],
    "energetic": ["bubbly", "energetic", "hyper", "loud", "chaotic", "silly", "playful", "funny"],
    "analytical": ["observant", "analytical", "practical", "smart", "logical", "mature", "direct"],
    "loyal": ["loyal", "honest", "reliable", "clingy", "protective"]
}

# ---------------- SYNONYM MANAGER ----------------
class SynonymManager:
    def __init__(self):
        self.categories = EXPANDED_CATEGORIES.copy()
        self.traits = EXPANDED_TRAITS.copy()
        self.load()

    def load(self):
        if not os.path.exists(SYNONYMS_FILE):
            self.save()
            return
        try:
            with open(SYNONYMS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.categories.update(data.get("categories", {}))
                self.traits.update(data.get("trait_clusters", {}))
        except Exception as e:
            logger.error(f"Failed to load synonyms.json: {e}")

    def save(self):
        with open(SYNONYMS_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "categories": self.categories,
                "trait_clusters": self.traits
            }, f, indent=2)

    def categorize(self, word: str) -> Optional[str]:
        w = word.lower().strip()
        for cat, synonyms in self.categories.items():
            if any(syn in w or w in syn for syn in synonyms):
                return cat
        return None

SYNMAN = SynonymManager()

# ---------------- THE LEFT BRAIN: PARSING & LOGIC ----------------

def de_yassify(text: str) -> str:
    """Removes aesthetic unicode, emojis, and normalizes text for parsing."""
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r'[^\w\s\n:?,\-]', ' ', text)  # Keep basic punctuation
    return text.lower()

def extract_section(text: str, start_keywords: list, end_keywords: list) -> str:
    start_idx = 0
    end_idx = len(text)
    
    for kw in start_keywords:
        match = re.search(rf'\b{kw}\b', text)
        if match:
            start_idx = match.start()
            break
            
    for kw in end_keywords:
        match = re.search(rf'\b{kw}\b', text[start_idx:])
        if match:
            end_idx = start_idx + match.start()
            break
            
    return text[start_idx:end_idx].strip()

def parse_idgaf_filter(raw_string: str) -> List[str]:
    if not raw_string: return []
    ignore_words = {"any", "idm", "idc", "idk", "similar", "none", "n/a", "nothing", "anything"}
    tokens = [t.strip() for t in re.split(r'[,\n]+', raw_string) if t.strip()]
    return [t for t in tokens if t not in ignore_words]

def parse_boolean_question(answer: str) -> Optional[bool]:
    if not answer: return None
    ans = answer.lower()
    
    # "Do you mind? Yes" -> They DO mind -> Not open to it -> False
    if any(w in ans for w in ["yes", "yeah", "yep", "i mind", "prefer not", "do mind"]): 
        return False
        
    # "Do you mind? No" -> They DON'T mind -> Open to it -> True
    if any(w in ans for w in ["no", "nope", "nah", "don't mind", "dont mind", "fine", "ok", "sure", "idm", "idc"]): 
        return True
        
    return None

def parse_profile(raw_text: str) -> dict:
    clean = de_yassify(raw_text)
    
    you_block = extract_section(clean, ["you", "about you"], ["them", "about them", "other"])
    them_block = extract_section(clean, ["them", "about them"], ["other", "note"])
    other_block = extract_section(clean, ["other"], [])
    
    def extract_field(block: str, field: str) -> str:
        match = re.search(rf"{field}\s*:\s*(.*?)(?=\n[a-z\s]+:|$)", block, re.DOTALL)
        return match.group(1).strip() if match else ""
    
    age_raw = extract_field(you_block, "age")
    age = int(re.search(r'\d+', age_raw).group()) if re.search(r'\d+', age_raw) else None
    
    gender = extract_field(you_block, "gender")
    is_trans = "trans" in gender or "mtf" in gender or "ftm" in gender or "transgender" in gender
    
    profile = {
        "name": extract_field(you_block, "name"),
        "age": age,
        "gender": gender,
        "is_trans": is_trans,
        "sexuality": extract_field(you_block, "sexuality") or extract_field(you_block, "orientation"),
        "hobbies": parse_idgaf_filter(extract_field(you_block, "hobbies") + "," + extract_field(you_block, "likes")),
        "traits": parse_idgaf_filter(extract_field(you_block, "traits")),
        "pref_gender": extract_field(them_block, "gender"),
        "open_to_trans": parse_boolean_question(extract_field(other_block, "do you mind them being trans")),
        "open_to_poly": parse_boolean_question(extract_field(other_block, "do you mind them being poly")),
        "timezone": extract_field(you_block, "time zone") or extract_field(you_block, "timezone"),
        "notes": other_block
    }
    return profile

def check_gatekeeper_rules(p1: dict, p2: dict) -> Tuple[bool, str]:
    """The Ironclad Python Logic. Returns (Passed, Reason)"""
    
    # 1. AGE SAFETY
    if p1['age'] is None or p2['age'] is None:
        return False, "Age is missing or unreadable. Safety block active."
    
    age1, age2 = p1['age'], p2['age']
    if (age1 < 18 and age2 >= 18) or (age2 < 18 and age1 >= 18):
        return False, f"Age Safety Block: Minor ({min(age1, age2)}) cannot be matched with Adult ({max(age1, age2)})."
    
    if age1 < 18 and age2 < 18:
        if abs(age1 - age2) > 1: return False, f"Age Rule: Minors can only have a 1 year gap. ({age1} and {age2})."
    else:
        if abs(age1 - age2) > 4: return False, f"Age Rule: Adults cannot exceed a 4 year gap. ({age1} and {age2})."

    # 2. SEXUALITY & GENDER ALIGNMENT (FIXED)
    def check_orientation(subject_sexuality, subject_gender, target_gender):
        sub_sex = (subject_sexuality or "").lower()
        sub_gen = (subject_gender or "").lower()
        tgt_gen = (target_gender or "").lower()
        
        if "questioning" in sub_sex or "unlabeled" in sub_sex:
            return "review"
            
        if "straight" in sub_sex or "hetero" in sub_sex:
            if "female" in tgt_gen or "woman" in tgt_gen or "mtf" in tgt_gen:
                return "male" in sub_gen or "man" in sub_gen or "boy" in sub_gen
            if "male" in tgt_gen or "man" in tgt_gen or "ftm" in tgt_gen:
                return "female" in sub_gen or "woman" in sub_gen or "girl" in sub_gen
            return False
            
        if "lesbian" in sub_sex:
            return "female" in tgt_gen or "woman" in tgt_gen or "mtf" in tgt_gen
            
        if "gay" in sub_sex:
            return "male" in tgt_gen or "man" in tgt_gen or "ftm" in tgt_gen
            
        # Bi/Pan/Omni pass automatically
        return True

    o1 = check_orientation(p1['sexuality'], p1['gender'], p2['gender'])
    o2 = check_orientation(p2['sexuality'], p2['gender'], p1['gender'])
    
    if o1 == "review" or o2 == "review":
        return False, "Flagged for manual review due to 'Questioning' or 'Unlabeled' sexuality."
    if not o1 or not o2:
        return False, "Fundamental Sexuality/Gender Mismatch."

    # 3. TRANS / POLY PREFERENCES
    if p1['open_to_trans'] is False and p2['is_trans']:
        return False, f"{p1['name'] or 'User 1'} prefers cisgender partners."
    if p2['open_to_trans'] is False and p1['is_trans']:
        return False, f"{p2['name'] or 'User 2'} prefers cisgender partners."
    if p1['open_to_poly'] is False and ("poly" in p2['sexuality'] or "poly" in p2['notes']):
        return False, f"{p1['name'] or 'User 1'} requires a monogamous partner."
    if p2['open_to_poly'] is False and ("poly" in p1['sexuality'] or "poly" in p1['notes']):
        return False, f"{p2['name'] or 'User 2'} requires a monogamous partner."
    
    return True, "Passed"

def calculate_python_score(p1: dict, p2: dict) -> Tuple[int, List[str]]:
    """Calculates score and returns (score, shared_categories)."""
    score = 25 
    
    cat1 = set([SYNMAN.categorize(h) for h in p1['hobbies'] if SYNMAN.categorize(h)])
    cat2 = set([SYNMAN.categorize(h) for h in p2['hobbies'] if SYNMAN.categorize(h)])
    
    overlap_cats = cat1.intersection(cat2)
    hobby_score = min(35, len(overlap_cats) * 12)
    score += hobby_score
    
    def get_trait_clusters(traits):
        clusters = set()
        for t in traits:
            for cluster, words in SYNMAN.traits.items():
                if any(w in t.lower() for w in words): clusters.add(cluster)
        return clusters
        
    tc1 = get_trait_clusters(p1['traits'])
    tc2 = get_trait_clusters(p2['traits'])
  
    if "toxic_flag" in tc1 or "toxic_flag" in tc2:
        score -= 20 
        
    trait_overlap = tc1.intersection(tc2)
    trait_score = min(25, len(trait_overlap) * 10)
    score += trait_score
    
    if p1['timezone'] and p2['timezone'] and p1['timezone'] == p2['timezone']:
        score += 15
    else:
        score += 5
        
    return min(100, score), list(overlap_cats)

# ---------------- THE RIGHT BRAIN: GENAI VIBE CHECK ----------------

async def generate_vibe_check(p1: dict, p2: dict) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("AI_API_KEY")
    if not api_key:
        return {"summary": "AI offline. Provide API Key.", "green_flags": ["N/A"], "red_flags": ["N/A"]}

    client = genai.Client(api_key=api_key)
    
    payload = {
        "User1": {"Traits": p1['traits'], "Hobbies": p1['hobbies'], "Notes": p1['notes'][:150]},
        "User2": {"Traits": p2['traits'], "Hobbies": p2['hobbies'], "Notes": p2['notes'][:150]}
    }
    
    prompt = f"""
    You are Athena, a matchmaking AI. Analyze this compressed profile data.
    DATA: {json.dumps(payload)}
    
    TASK:
    Evaluate emotional compatibility (EQ) and conversational vibe. Ignore basic logic like age or gender. Focus purely on personality synergy and hobbies. Be brutally honest but concise.
    
    OUTPUT SCHEMA:
    {{
        "green_flags": ["short bullet 1", "short bullet 2"],
        "red_flags": ["short friction point 1"],
        "summary": "1-2 sentence maximum summary of their dynamic."
    }}
    """
    
    try:
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(
            None, 
            lambda: client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.3,
                    # SAFETY OVERRIDE: Prevent the "Internal Error" from racial/gender preferences
                    safety_settings=[
                        types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
                        types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
                        types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
                        types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
                    ]
                )
            )
        )
        return json.loads(res.text)
    except Exception as e:
        logger.error(f"GenAI Error: {e}")
        return {"summary": "AI Vibe Check timed out or failed.", "green_flags": [], "red_flags": []}

# ---------------- DISCORD COG & COMMANDS ----------------

class AthenaF22(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="analyze_match", description="F22 Engine: Analyze two profiles for compatibility")
    @app_commands.describe(form1="Paste User 1's full form", form2="Paste User 2's full form")
    async def analyze_match(self, interaction: discord.Interaction, form1: str, form2: str):
        # We wrap in a try-except to catch 503 HTTP defer errors gracefully
        try:
            await interaction.response.defer()
        except discord.errors.HTTPException:
            return

        try:
            # 1. Parse
            p1 = parse_profile(form1)
            p2 = parse_profile(form2)
            
            # 2. Gatekeeper Logic (Python)
            passed, reason = check_gatekeeper_rules(p1, p2)
            if not passed:
                embed = discord.Embed(title="Athena F22: Match Terminated", color=0xff0000)
                embed.add_field(name="Reason", value=f"**{reason}**\n*This match violates core server rules or boundaries.*")
                await interaction.followup.send(embed=embed)
                return
                
            # 3. Math Score & Category Grouping
            algo_score, shared_cats = calculate_python_score(p1, p2)
            
            # 4. AI Vibe Check
            ai_data = await generate_vibe_check(p1, p2)
            
            # 5. Build Embed
            color = 0x2ecc71 if algo_score >= 65 else (0xf1c40f if algo_score >= 40 else 0xe74c3c)
            embed = discord.Embed(title="🤍 Athena F22: Compatibility Report 🤍", color=color)
            
            embed.add_field(name="🎯 System Match Score", value=f"**{algo_score}%**", inline=False)
            
            # Show shared categories explicitly (Fixes the Roblox/Minecraft grouping issue)
            cat_strings = [c.replace("_", " ").title() for c in shared_cats]
            shared_text = ", ".join(cat_strings) if cat_strings else "No direct category overlap."
            embed.add_field(name="<:p_hearts:1378053399525982288> Shared Interests", value=f"• {shared_text}", inline=False)
            
            # Formulate Flags
            g_flags = "\n".join([f"✅ {f}" for f in ai_data.get("green_flags", [])[:3]]) or "None detected."
            r_flags = "\n".join([f"⚠️ {f}" for f in ai_data.get("red_flags", [])[:2]]) or "None detected."
            embed.add_field(name="Strengths", value=g_flags, inline=False)
            embed.add_field(name="Friction Points", value=r_flags, inline=False)
            
            # AI Summary explicitly capped
            summary = ai_data.get("summary", "Analysis complete.")[:500]
            embed.add_field(name="Athena's Conclusion", value=f"*{summary}*", inline=False)
            
            embed.set_footer(text="F22 Hybrid Engine | Left-Brain Math + Right-Brain EQ")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.exception("Engine Failure in analyze_match")
            await interaction.followup.send(f"❌ Athena Engine encountered an error: {e}")

async def setup(bot):
    await bot.add_cog(AthenaF22(bot))