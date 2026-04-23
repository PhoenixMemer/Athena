# cogs/matchmaking_f22.py
# Athena F22 "Two-Brain" Matchmaking Engine

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

# Expanded Base Taxonomy (Will be saved to synonyms.json if missing)
EXPANDED_CATEGORIES = {
    "video_games": ["gaming", "video games", "games", "genshin", "gacha", "pjsk", "hollow knight", "hoyo", "hsr", "minecraft", "fnaf", "valorant", "fortnite", "roblox", "overwatch", "league of legends", "stardew valley", "rpg", "fps"],
    "anime_manga": ["anime", "manga", "jjk", "kny", "one piece", "death note", "manhwa", "webtoon", "studio ghibli", "naruto", "bleach", "mha"],
    "music": ["music", "citypop", "indie", "kpop", "jpop", "rap", "r&b", "hiphop", "metal", "rock", "classical", "playing instruments", "guitar", "piano"],
    "reading_writing": ["reading", "books", "fanfiction", "ff", "novels", "writing", "poetry", "literature", "ao3", "wattpad"],
    "arts_crafts": ["art", "drawing", "digital art", "graphic design", "sketching", "painting", "crochet", "knitting", "sewing"],
    "photography": ["photography", "pfp", "matching pfps", "taking pictures", "cameras"],
    "cooking_baking": ["cooking", "baking", "brownies", "cakes", "culinary", "foodie"],
    "vehicles": ["bike", "bikes", "car", "cars", "biker", "motorcycles", "jdm", "f1"],
    "movies_tv": ["movies", "films", "the boys", "dexter", "lucifer", "documentaries", "sitcoms", "kdrama", "shows", "netflix", "cinema"],
    "true_crime_paranormal": ["true crime", "creepypasta", "analog horror", "horror", "mystery", "supernatural", "ghosts"],
    "social_communication": ["vc", "voice chat", "vcing", "chatting", "texting", "yapping", "calling", "hanging out"],
    "sports_active": ["sports", "gym", "working out", "badminton", "volleyball", "basketball", "soccer", "football", "skating", "swimming", "hiking"],
    "tech_programming": ["coding", "programming", "tech", "computers", "linux", "pc building", "keyboards", "software"],
    "fashion_beauty": ["fashion", "makeup", "skincare", "clothes", "shopping", "style", "thrifting"]
}

EXPANDED_FAMILIES = {
    "video_games": "fiction_media", "anime_manga": "fiction_media", "movies_tv": "fiction_media", "reading_writing": "fiction_media",
    "music": "creative_arts", "arts_crafts": "creative_arts", "photography": "creative_arts", "fashion_beauty": "creative_arts",
    "vehicles": "mechanical", "tech_programming": "mechanical",
    "cooking_baking": "home_lifestyle",
    "social_communication": "social",
    "sports_active": "active_lifestyle",
    "true_crime_paranormal": "horror_mystery"
}

EXPANDED_TRAITS = {
    "empathic": ["empathetic", "caring", "kind", "supportive", "understanding", "sweet", "gentle", "patient"],
    "communicative": ["talkative", "chatty", "yapper", "vocal", "communicative", "expressive"],
    "introverted": ["shy", "introverted", "reserved", "quiet", "timid", "listener"],
    "energetic": ["bubbly", "energetic", "hyper", "loud", "chaotic", "silly", "playful"],
    "analytical": ["observant", "analytical", "practical", "smart", "logical", "mature", "direct"],
    "toxic_flag": ["aggressive", "manipulative", "jealous", "possessive", "mean", "short temper", "toxic"]
}

# ---------------- SYNONYM MANAGER ----------------
class SynonymManager:
    def __init__(self):
        self.categories = EXPANDED_CATEGORIES.copy()
        self.families = EXPANDED_FAMILIES.copy()
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
                self.families.update(data.get("families", {}))
                self.traits.update(data.get("trait_clusters", {}))
        except Exception as e:
            logger.error(f"Failed to load synonyms.json: {e}")

    def save(self):
        with open(SYNONYMS_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "categories": self.categories,
                "families": self.families,
                "trait_clusters": self.traits
            }, f, indent=2)

    def add_synonym(self, category: str, word: str) -> bool:
        word = word.lower().strip()
        if category in self.categories:
            if word not in self.categories[category]:
                self.categories[category].append(word)
                self.save()
            return True
        return False

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
    """Extracts a section (You/Them/Other) using keyword boundaries."""
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
    """Splits comma separated lists and removes useless words."""
    if not raw_string: return []
    ignore_words = {"any", "idm", "idc", "idk", "similar", "none", "n/a", "nothing"}
    tokens = [t.strip() for t in re.split(r'[,\n]+', raw_string) if t.strip()]
    return [t for t in tokens if t not in ignore_words]

def parse_boolean_question(answer: str) -> Optional[bool]:
    """Resolves the Double-Negative Trap."""
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
    
    # Extract blocks
    you_block = extract_section(clean, ["you", "about you"], ["them", "about them", "other"])
    them_block = extract_section(clean, ["them", "about them"], ["other", "note"])
    other_block = extract_section(clean, ["other"], [])
    
    def extract_field(block: str, field: str) -> str:
        match = re.search(rf"{field}\s*:\s*(.*?)(?=\n[a-z\s]+:|$)", block, re.DOTALL)
        return match.group(1).strip() if match else ""
    
    # Regex Age
    age_raw = extract_field(you_block, "age")
    age = int(re.search(r'\d+', age_raw).group()) if re.search(r'\d+', age_raw) else None
    
    # "Other" questions
    mind_trans = parse_boolean_question(extract_field(other_block, "do you mind them being trans"))
    mind_poly = parse_boolean_question(extract_field(other_block, "do you mind them being poly"))
    
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
        "open_to_trans": mind_trans,
        "open_to_poly": mind_poly,
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

    # 2. SEXUALITY & GENDER ALIGNMENT (Identity vs Preference)
    def check_orientation(subject_sexuality, subject_pref, target_gender):
        sub_sex = subject_sexuality.lower()
        tgt_gen = target_gender.lower()
        
        if "questioning" in sub_sex or "unlabeled" in sub_sex:
            return "review"
            
        if "straight" in sub_sex or "hetero" in sub_sex:
            if "female" in tgt_gen or "woman" in tgt_gen or "mtf" in tgt_gen:
                return "male" in sub_sex or "man" in sub_sex or "boy" in sub_sex
            if "male" in tgt_gen or "man" in tgt_gen or "ftm" in tgt_gen:
                return "female" in sub_sex or "woman" in sub_sex or "girl" in sub_sex
            return False
            
        if "lesbian" in sub_sex:
            return "female" in tgt_gen or "woman" in tgt_gen or "mtf" in tgt_gen
            
        if "gay" in sub_sex:
            return "male" in tgt_gen or "man" in tgt_gen or "ftm" in tgt_gen
            
        # Bi/Pan/Omni pass automatically
        return True

    o1 = check_orientation(p1['sexuality'], p1['pref_gender'], p2['gender'])
    o2 = check_orientation(p2['sexuality'], p2['pref_gender'], p1['gender'])
    
    if o1 == "review" or o2 == "review":
        return False, "Flagged for manual review due to 'Questioning' or 'Unlabeled' sexuality."
    if not o1 or not o2:
        return False, "Fundamental Sexuality/Gender Mismatch."

    # 3. TRANS / POLY PREFERENCES
    # If p1 explicitly minds trans (False), and p2 IS trans -> Block.
    if p1['open_to_trans'] is False and p2['is_trans']:
        return False, f"{p1['name'] or 'User 1'} prefers cisgender partners."
    if p2['open_to_trans'] is False and p1['is_trans']:
        return False, f"{p2['name'] or 'User 2'} prefers cisgender partners."
    if p1['open_to_poly'] is False and ("poly" in p2['sexuality'] or "poly" in p2['notes']):
        return False, f"{p1['name'] or 'User 1'} requires a monogamous partner."
    if p2['open_to_poly'] is False and ("poly" in p1['sexuality'] or "poly" in p1['notes']):
        return False, f"{p2['name'] or 'User 2'} requires a monogamous partner."
    
    return True, "Passed"

def calculate_python_score(p1: dict, p2: dict) -> int:
    """Calculates algorithmic weight score based on taxonomy."""
    score = 25 # Base points for passing gatekeeper
    
    # Hobby Math (35% max)
    cat1 = set([SYNMAN.categorize(h) for h in p1['hobbies'] if SYNMAN.categorize(h)])
    cat2 = set([SYNMAN.categorize(h) for h in p2['hobbies'] if SYNMAN.categorize(h)])
    
    overlap = cat1.intersection(cat2)
    hobby_score = min(35, len(overlap) * 12)
    score += hobby_score
    
    # Trait Math (25% max)
    def get_trait_clusters(traits):
        clusters = set()
        for t in traits:
            for cluster, words in SYNMAN.traits.items():
                if any(w in t.lower() for w in words): clusters.add(cluster)
        return clusters
        
    tc1 = get_trait_clusters(p1['traits'])
    tc2 = get_trait_clusters(p2['traits'])
  
    if "toxic_flag" in tc1 or "toxic_flag" in tc2:
        score -= 20 # Severe penalty for toxic traits
        
    trait_overlap = tc1.intersection(tc2)
    trait_score = min(25, len(trait_overlap) * 10)
    score += trait_score
    
    # Timezone pseudo-math (15% max)
    # If same string, assume +15. Else +5 for trying. (Timezone math is hard without standard input)
    if p1['timezone'] and p2['timezone'] and p1['timezone'] == p2['timezone']:
        score += 15
    else:
        score += 5
        
    return min(100, score)

# ---------------- THE RIGHT BRAIN: GENAI VIBE CHECK ----------------

async def generate_vibe_check(p1: dict, p2: dict) -> dict:
    """Sends a compressed payload to GenAI to evaluate EQ and vibes."""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("AI_API_KEY")
    
    if not api_key:
        return {"summary": "AI offline. Provide GEMINI_API_KEY.", "green_flags": ["N/A"], "red_flags": ["N/A"]}

    client = genai.Client(api_key=api_key)
    
    # Compress the payload to prevent 503s
    payload = {
        "User1": {"Traits": p1['traits'], "Hobbies": p1['hobbies'], "Notes": p1['notes'][:100]},
        "User2": {"Traits": p2['traits'], "Hobbies": p2['hobbies'], "Notes": p2['notes'][:100]}
    }
    
    prompt = f"""
    You are Athena, a matchmaking AI. Analyze this compressed profile data.
    DATA: {json.dumps(payload)}
    
    TASK:
    Evaluate their emotional compatibility (EQ) and conversational vibe. Do not mention ages, sexualities, or basic facts. Focus on personality synergy.
    
    OUTPUT SCHEMA:
    {{
        "green_flags": ["short bullet 1", "short bullet 2"],
        "red_flags": ["short friction point 1"],
        "summary": "1-2 sentence maximum summary of their dynamic."
    }}
    """
    
    try:
        loop = asyncio.get_running_loop()
        # Use GenAI v1 SDK standard
        res = await loop.run_in_executor(
            None, 
            lambda: client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.3
                )
            )
        )
    
        data = json.loads(res.text)
        return data
    except Exception as e:
        logger.error(f"GenAI Error: {e}")
        return {"summary": "AI Vibe Check timed out or failed.", "green_flags": [], "red_flags": []}


# ---------------- DISCORD COG & COMMANDS ----------------

class AthenaF22(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def is_cupid():
        """Custom check for Cupid Role IDs"""
        async def predicate(interaction: discord.Interaction):
            user_role_ids = [role.id for role in interaction.user.roles]
            if any(role_id in CUPID_ROLES for role_id in user_role_ids):
                return True
            await interaction.response.send_message("You do not have the Cupid role required to use this.", ephemeral=True)
            return False
        return app_commands.check(predicate)

    @app_commands.command(name="analyze_match", description="F22 Engine: Analyze two profiles for compatibility")
    @app_commands.describe(form1="Paste User 1's full form", form2="Paste User 2's full form")
    async def analyze_match(self, interaction: discord.Interaction, form1: str, form2: str):
        await interaction.response.defer()
        
        try:
            # 1. Parse
            p1 = parse_profile(form1)
            p2 = parse_profile(form2)
            
            # 2. Gatekeeper Logic
            passed, reason = check_gatekeeper_rules(p1, p2)
            if not passed:
                embed = discord.Embed(title="Athena F22: Match Terminated", color=0xff0000)
                embed.add_field(name="Reason", value=f"**{reason}**\n*This match violates core server rules or boundaries.*")
                await interaction.followup.send(embed=embed)
                return
                
            # 3. Math Score
            algo_score = calculate_python_score(p1, p2)
            
            # 4. AI Vibe Check
            ai_data = await generate_vibe_check(p1, p2)
            
            # 5. Build Discord-Safe Embed (< 1024 chars)
            color = 0x2ecc71 if algo_score >= 65 else (0xf1c40f if algo_score >= 40 else 0xe74c3c)
            embed = discord.Embed(title="🤍 Athena F22: Compatibility Report 🤍", color=color)
            
            embed.add_field(name="🎯 System Match Score", value=f"**{algo_score}%**", inline=False)
            
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

    @app_commands.command(name="add_synonym", description="Add a new word to the Matchmaking Taxonomy")
    @app_commands.describe(category="The existing category", word="The new synonym/hobby to add")
    @is_cupid()
    async def add_synonym(self, interaction: discord.Interaction, category: str, word: str):
        cat_clean = category.lower().replace(" ", "_")
        if SYNMAN.add_synonym(cat_clean, word):
            await interaction.response.send_message(f"Successfully added `{word}` to category `{cat_clean}`.", ephemeral=True)
        else:
            await interaction.response.send_message(f"Category `{cat_clean}` doesn't exist. Check `synonyms.json`.", ephemeral=True)

    @add_synonym.autocomplete('category')
    async def category_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        categories = list(SYNMAN.categories.keys())
        return [
            app_commands.Choice(name=cat, value=cat)
            for cat in categories if current.lower() in cat.lower()
        ][:25] # Discord limits to 25 autocomplete choices


async def setup(bot):
    await bot.add_cog(AthenaF22(bot))