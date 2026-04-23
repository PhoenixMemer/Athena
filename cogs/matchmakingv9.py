# cogs/matchmaking_v9.py
# Athena Mark IX — Pipeline Architecture (Extractor -> Math -> Copywriter)
# Includes: Multi-Model Fallback, Dynamic Taxonomy, & API KEY ROTATOR

import discord
from discord import app_commands
from discord.ext import commands
import os
import json
import logging
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

# Keep 2.5 as the primary, fallback to 2.0 lite if needed
CANDIDATE_MODELS = ['gemini-2.5-flash', 'gemini-2.0-flash-lite']

EXPANDED_CATEGORIES = {
    "video_games": ["gaming", "video games", "games", "genshin", "gacha", "pjsk", "hollow knight", "hoyo", "hsr", "minecraft", "fnaf", "valorant", "fortnite", "roblox", "overwatch", "league", "stardew", "rpg", "fps"],
    "anime_manga": ["anime", "manga", "jjk", "kny", "one piece", "death note", "manhwa", "webtoon", "studio ghibli", "naruto", "bleach", "mha"],
    "music": ["music", "citypop", "indie", "kpop", "jpop", "rap", "r&b", "hiphop", "metal", "rock", "classical", "guitar", "piano", "drums", "deftones"],
    "reading_writing": ["reading", "books", "fanfiction", "ff", "novels", "writing", "poetry", "literature", "ao3", "wattpad"],
    "arts_crafts": ["art", "drawing", "digital art", "graphic design", "sketching", "painting", "crochet", "knitting", "sewing", "crafts"],
    "photography": ["photography", "pfp", "matching pfps", "pictures", "cameras"],
    "cooking_baking": ["cooking", "baking", "brownies", "cakes", "culinary", "foodie"],
    "vehicles": ["bike", "bikes", "car", "cars", "biker", "motorcycles", "jdm", "f1"],
    "movies_tv": ["movies", "films", "the boys", "dexter", "lucifer", "documentaries", "sitcoms", "kdrama", "shows", "netflix", "cinema"],
    "true_crime_paranormal": ["true crime", "creepypasta", "analog horror", "horror", "mystery", "supernatural", "ghosts"],
    "social_communication": ["vc", "voice chat", "vcing", "chatting", "texting", "yapping", "calling", "hanging out", "going out", "talking"],
    "sports_active": ["sports", "gym", "working out", "badminton", "volleyball", "basketball", "soccer", "football", "skating", "swimming", "hiking"],
    "nature_ocean": ["ocean", "nature", "animals", "pets", "sleeping", "sleep"],
    "fashion_beauty": ["fashion", "makeup", "skincare", "clothes", "shopping", "style", "thrifting", "alt"]
}

class SynonymManager:
    def __init__(self):
        self.categories = EXPANDED_CATEGORIES.copy()
        self.load()

    def load(self):
        if not os.path.exists(SYNONYMS_FILE):
            self.save()
            return
        try:
            with open(SYNONYMS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.categories.update(data.get("categories", {}))
        except Exception as e:
            logger.error(f"Failed to load synonyms.json: {e}")

    def save(self):
        with open(SYNONYMS_FILE, "w", encoding="utf-8") as f:
            json.dump({"categories": self.categories}, f, indent=2)

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

# ---------------- PHASE 1: THE AI EXTRACTOR ----------------

async def ai_extract_profile(client: genai.Client, raw_text: str) -> dict:
    prompt = f"""
    You are a strict data extraction bot. Read this user's dating profile and extract the exact fields requested. 
    
    CRITICAL RULES:
    1. AGE: Extract only the integer. If they say "15 (soon 16)" or "17!!", extract just the current age (15 or 17). If missing, return null.
    2. DISLIKES vs TRAITS: Do NOT mix these up. Put things they hate in 'dislikes'. Put words that describe them in 'traits'.
    3. RELATIONSHIP_STYLE: 
       - If they say "Yes" to "Do you mind them being poly?" -> output "MONOGAMOUS".
       - If they say "No" to poly -> output "POLY_OPEN".
    4. TRANS_PREFERENCE:
       - If they say "Yes" to "Do you mind them being trans?" -> output "MUST_BE_CIS".
       - If they say "No" -> output "OPEN_TO_TRANS".
    
    PROFILE TO EXTRACT:
    {raw_text[:1500]}
    
    OUTPUT SCHEMA (JSON ONLY):
    {{
        "name": "string",
        "age": 18,
        "gender": "male" | "female" | "trans_male" | "trans_female" | "nonbinary" | "unknown",
        "sexuality": "straight" | "gay" | "lesbian" | "bisexual" | "pansexual" | "unknown",
        "hobbies_and_likes": ["list", "of", "strings"],
        "dislikes": ["list", "of", "strings"],
        "traits": ["list", "of", "strings"],
        "relationship_style": "MONOGAMOUS" | "POLY_OPEN" | "UNKNOWN",
        "trans_preference": "MUST_BE_CIS" | "OPEN_TO_TRANS" | "UNKNOWN"
    }}
    """
    
    loop = asyncio.get_running_loop()
    
    for model_name in CANDIDATE_MODELS:
        try:
            res = await loop.run_in_executor(
                None, 
                lambda m=model_name: client.models.generate_content(
                    model=m,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.1, 
                        safety_settings=[
                            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
                            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
                            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
                            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
                        ]
                    )
                )
            )
            data = json.loads(res.text)
            data.setdefault("age", None)
            data.setdefault("gender", "unknown")
            data.setdefault("sexuality", "unknown")
            return data
        except Exception as e:
            logger.warning(f"Extraction failed with {model_name}: {e}")
            continue
            
    # We raise an exception here so the Rotator knows this API key is completely dead
    raise Exception("429 RESOURCE_EXHAUSTED or ALL MODELS FAILED")

# ---------------- PHASE 2: THE PYTHON BOUNCER (GATEKEEPER) ----------------

def check_gatekeeper_rules(p1: dict, p2: dict) -> Tuple[bool, str]:
    if not isinstance(p1.get('age'), int) or not isinstance(p2.get('age'), int):
        return False, "Age is missing or unreadable. Safety block active."
    
    age1, age2 = p1['age'], p2['age']
    if (age1 < 18 and age2 >= 18) or (age2 < 18 and age1 >= 18):
        return False, f"Age Safety Block: Minor ({min(age1, age2)}) cannot be matched with Adult ({max(age1, age2)})."
    
    if age1 < 18 and age2 < 18:
        if abs(age1 - age2) > 1: return False, f"Age Rule: Minors can only have a 1 year gap. ({age1} and {age2})."
    else:
        if abs(age1 - age2) > 4: return False, f"Age Rule: Adults cannot exceed a 4 year gap. ({age1} and {age2})."

    def check_orientation(sexuality, subject_gender, target_gender):
        sx = (sexuality or "").lower()
        sg = (subject_gender or "").lower()
        tg = (target_gender or "").lower()
        
        if "unknown" in sx: return "review"
        if "straight" in sx:
            if "female" in tg: return "male" in sg
            if "male" in tg: return "female" in sg
            return False
        if "lesbian" in sx or "gay" in sx:
            if "female" in tg: return "female" in sg
            if "male" in tg: return "male" in sg
            return False
        return True

    o1 = check_orientation(p1['sexuality'], p1['gender'], p2['gender'])
    o2 = check_orientation(p2['sexuality'], p2['gender'], p1['gender'])
    
    if o1 == "review" or o2 == "review": return False, "Sexuality unreadable. Manual review required."
    if not o1 or not o2: return False, "Fundamental Sexuality/Gender Mismatch."

    s1 = p1.get('relationship_style')
    s2 = p2.get('relationship_style')
    if (s1 == "MONOGAMOUS" and s2 == "POLY_OPEN") or (s2 == "MONOGAMOUS" and s1 == "POLY_OPEN"):
        return False, "Relationship Style Mismatch (Monogamous vs Poly)."

    p1_is_trans = "trans" in p1['gender'].lower()
    p2_is_trans = "trans" in p2['gender'].lower()
    
    if p1.get('trans_preference') == "MUST_BE_CIS" and p2_is_trans:
        return False, f"{p1.get('name', 'User 1')} prefers cisgender partners."
    if p2.get('trans_preference') == "MUST_BE_CIS" and p1_is_trans:
        return False, f"{p2.get('name', 'User 2')} prefers cisgender partners."

    return True, "Passed"

# ---------------- PHASE 3: THE PYTHON MATH ----------------

def calculate_python_score(p1: dict, p2: dict) -> Tuple[int, List[str]]:
    score = 30 
    
    cat1 = set([SYNMAN.categorize(h) for h in p1.get('hobbies_and_likes', []) if SYNMAN.categorize(h)])
    cat2 = set([SYNMAN.categorize(h) for h in p2.get('hobbies_and_likes', []) if SYNMAN.categorize(h)])
    
    overlap_cats = cat1.intersection(cat2)
    hobby_score = min(40, len(overlap_cats) * 12)
    score += hobby_score
    
    t1 = set([t.lower() for t in p1.get('traits', [])])
    t2 = set([t.lower() for t in p2.get('traits', [])])
    if len(t1.intersection(t2)) > 0:
        score += 15
        
    for item in p1.get('hobbies_and_likes', []):
        if any(item.lower() in d.lower() for d in p2.get('dislikes', [])): score -= 10
    for item in p2.get('hobbies_and_likes', []):
        if any(item.lower() in d.lower() for d in p1.get('dislikes', [])): score -= 10
        
    return min(100, max(0, score)), list(overlap_cats)

# ---------------- PHASE 4: THE AI COPYWRITER ----------------

async def generate_vibe_check(client: genai.Client, p1: dict, p2: dict, score: int, shared_cats: list) -> str:
    prompt = f"""
    You are a matchmaker writing a final summary.
    
    User 1 Traits: {p1.get('traits')}
    User 2 Traits: {p2.get('traits')}
    Shared Categories: {shared_cats}
    Final Match Score: {score}%
    
    Write EXACTLY 2 sentences summarizing why they match based ONLY on their traits and hobbies. 
    DO NOT mention their dislikes. DO NOT mention their values/trans/poly status. DO NOT preach. Keep it fun and conversational.
    """
    
    loop = asyncio.get_running_loop()
    
    for model_name in CANDIDATE_MODELS:
        try:
            res = await loop.run_in_executor(
                None, 
                lambda m=model_name: client.models.generate_content(
                    model=m,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.6,
                        safety_settings=[
                            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
                            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
                            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
                            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
                        ]
                    )
                )
            )
            return res.text.strip()
        except Exception as e:
            logger.warning(f"Vibe check failed with {model_name}: {e}")
            continue
            
    return "You share some great interests and complementary traits! Start a chat and see where it goes."

# ---------------- DISCORD COG ----------------

class AthenaV9(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def is_cupid():
        async def predicate(interaction: discord.Interaction):
            user_role_ids = [role.id for role in interaction.user.roles]
            if any(role_id in CUPID_ROLES for role_id in user_role_ids):
                return True
            await interaction.response.send_message("You do not have the Cupid role required to use this.", ephemeral=True)
            return False
        return app_commands.check(predicate)

    async def safe_defer(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
            return True
        except discord.errors.HTTPException:
            return False

    @app_commands.command(name="analyze_match", description="Mark IX Engine: Ironclad Pipeline Analysis")
    @app_commands.describe(form1="Paste User 1's full form", form2="Paste User 2's full form")
    async def analyze_match(self, interaction: discord.Interaction, form1: str, form2: str):
        if not await self.safe_defer(interaction): return

        # Get all keys from the .env file
        keys_string = os.environ.get("GEMINI_API_KEYS") or os.environ.get("GEMINI_API_KEY") or os.environ.get("AI_API_KEY")
        if not keys_string:
            await interaction.followup.send("❌ Error: No API Keys found in the .env file.")
            return

        api_keys = [k.strip() for k in keys_string.split(',') if k.strip()]
        
        # --- THE ROTATOR ENGINE ---
        working_client = None
        p1, p2 = None, None
        
        for attempt, key in enumerate(api_keys):
            try:
                logger.info(f"Attempting Match with API Key #{attempt + 1}...")
                client = genai.Client(api_key=key)
                
                # Phase 1: Try to extract with this key
                p1, p2 = await asyncio.gather(
                    ai_extract_profile(client, form1),
                    ai_extract_profile(client, form2)
                )
                
                # If we get here without an exception, this key works! Save it for the copywriter.
                working_client = client
                break 
                
            except Exception as e:
                logger.warning(f"API Key #{attempt + 1} failed or ran out of quota. Switching to next key...")
                continue # Try the next key in the loop

        if not p1 or not p2 or not working_client:
            await interaction.followup.send("❌ **CRITICAL ERROR:** All provided API Keys have exhausted their daily quota! Go beg your Cupids to generate more keys on their alt accounts.")
            return

        try:
            # Phase 2: Gatekeeper
            passed, reason = check_gatekeeper_rules(p1, p2)
            if not passed:
                embed = discord.Embed(title="Athena Mark IX: Match Terminated", color=0xff0000)
                embed.add_field(name="Reason", value=f"**{reason}**\n*This match violates core server bounds.*")
                await interaction.followup.send(embed=embed)
                return
                
            # Phase 3: Math Score
            algo_score, shared_cats = calculate_python_score(p1, p2)
            
            # Phase 4: Copywriter (Re-using the working key)
            summary = await generate_vibe_check(working_client, p1, p2, algo_score, shared_cats)
            
            # Build Embed
            color = 0x2ecc71 if algo_score >= 65 else (0xf1c40f if algo_score >= 40 else 0xe74c3c)
            embed = discord.Embed(title="🤍 Athena Mark IX: Compatibility Report 🤍", color=color)
            
            embed.add_field(name="🎯 System Match Score", value=f"**{algo_score}%**", inline=False)
            
            cat_strings = [c.replace("_", " ").title() for c in shared_cats]
            shared_text = ", ".join(cat_strings) if cat_strings else "No direct category overlap."
            embed.add_field(name="<:p_hearts:1378053399525982288> Shared Interests", value=f"• {shared_text}", inline=False)
            
            embed.add_field(name="Athena's Conclusion", value=f"*{summary[:500]}*", inline=False)
            embed.set_footer(text="Mark IX Pipeline Engine | API Rotator Active")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.exception("Engine Failure in analyze_match")
            await interaction.followup.send(f"❌ Athena Engine encountered a critical error during math/vibe check: {e}")

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
        ][:25] 

async def setup(bot):
    await bot.add_cog(AthenaV9(bot))