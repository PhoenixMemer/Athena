import discord
from discord import app_commands
from discord.ext import commands
import re
from typing import Dict, List, Tuple
import datetime

class Matchmaking(commands.Cog):
    """Advanced Cupid Compatibility Analysis System - Custom Parser for Cheriies Template"""
    
    def __init__(self, bot):
        self.bot = bot
        
    @app_commands.command(name="analyze", 
                         description="Analyze compatibility between two forms.")
    @app_commands.describe(
        form1="Paste the first user's form text",
        form2="Paste the second user's form text"
    )
    async def analyze_compatibility(self, interaction: discord.Interaction, form1: str, form2: str):
        """Main compatibility analysis command"""
        
        await interaction.response.defer()
        
        try:
            # Parse both forms using custom template parser
            profile1 = self.parse_cheriies_form(form1)
            profile2 = self.parse_cheriies_form(form2)
            
            # Validate critical data
            validation_errors = self.validate_profiles(profile1, profile2)
            if validation_errors:
                return await interaction.followup.send(f"❌ **Validation Error:** {validation_errors}")
            
            # Calculate compatibility scores
            compatibility_report = self.calculate_compatibility(profile1, profile2)
            
            # Generate detailed embed report
            embed = self.generate_compatibility_embed(profile1, profile2, compatibility_report)
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            await interaction.followup.send(f"❌ **Analysis Error:** {str(e)}")

    def parse_cheriies_form(self, form_text: str) -> Dict:
        """Custom parser specifically for Cheriies server template format"""
        profile = {
            'personal': self.extract_personal_section(form_text),
            'preferences': self.extract_preferences_section(form_text),
            'other': self.extract_other_section(form_text),
            'raw_text': form_text
        }
        return profile

    def extract_personal_section(self, text: str) -> Dict:
        """Extract personal information from 'You' section"""
        personal = {}
        
        # Extract You section
        you_section_match = re.search(r'𝓨𝒐𝒖[^𝓣𝒉𝒆𝒎]+', text, re.DOTALL)
        if you_section_match:
            you_section = you_section_match.group(0)
            
            # Extract each field with template-specific patterns
            personal['name'] = self.extract_field(you_section, 'Name')
            personal['age'] = self.extract_age_field(you_section, 'Age')
            personal['birthday'] = self.extract_field(you_section, 'Birthday')
            personal['gender'] = self.extract_field(you_section, 'Gender')
            personal['sexuality'] = self.extract_field(you_section, 'Sexuality')
            personal['timezone'] = self.extract_field(you_section, 'Time zone')
            personal['dislikes'] = self.extract_list_field(you_section, 'Dislikes')
            personal['likes'] = self.extract_list_field(you_section, 'Likes')
            personal['hobbies'] = self.extract_list_field(you_section, 'Hobbies')
            personal['traits'] = self.extract_list_field(you_section, 'Your traits')
        
        return personal

    def extract_preferences_section(self, text: str) -> Dict:
        """Extract partner preferences from 'Them' section"""
        preferences = {}
        
        # Extract Them section
        them_section_match = re.search(r'𝓣𝒉𝒆𝒎[^𝜗𝜚]+', text, re.DOTALL)
        if them_section_match:
            them_section = them_section_match.group(0)
            
            preferences['age'] = self.extract_age_range_field(them_section, 'Age')
            preferences['gender'] = self.extract_field(them_section, 'Gender')
            preferences['sexuality'] = self.extract_field(them_section, 'Sexuality')
            preferences['likes'] = self.extract_list_field(them_section, 'Likes')
            preferences['dislikes'] = self.extract_list_field(them_section, 'Dislikes')
            preferences['hobbies'] = self.extract_list_field(them_section, 'Hobbies')
            preferences['timezone'] = self.extract_field(them_section, 'Time zone')
            preferences['traits'] = self.extract_list_field(them_section, 'Their traits')
        
        return preferences

    def extract_other_section(self, text: str) -> Dict:
        """Extract other preferences (trans, poly, notes)"""
        other = {}
        
        # Extract trans preference
        trans_match = re.search(r'trans\?[^!]*!([^୧]*)', text, re.IGNORECASE)
        if trans_match:
            other['trans_ok'] = 'yes' in trans_match.group(1).lower() or 'ok' in trans_match.group(1).lower()
        else:
            other['trans_ok'] = None
        
        # Extract poly preference
        poly_match = re.search(r'poly\?[^!]*!([^୧]*)', text, re.IGNORECASE)
        if poly_match:
            other['poly_ok'] = 'yes' in poly_match.group(1).lower() or 'ok' in poly_match.group(1).lower()
        else:
            other['poly_ok'] = None
        
        # Extract note
        note_match = re.search(r'Note[^!]*!([^୧]*)', text, re.IGNORECASE)
        if note_match:
            other['note'] = note_match.group(1).strip()
        else:
            other['note'] = None
        
        return other

    def extract_field(self, section: str, field_name: str) -> str:
        """Extract a specific field value"""
        pattern = rf'╰\s*{field_name}:\s*([^\n╰𝜗𐔌]*)'
        match = re.search(pattern, section, re.IGNORECASE)
        return match.group(1).strip() if match else "Unknown"

    def extract_age_field(self, section: str, field_name: str) -> int:
        """Extract age as integer"""
        pattern = rf'╰\s*{field_name}:\s*(\d+)'
        match = re.search(pattern, section, re.IGNORECASE)
        if match:
            try:
                age = int(match.group(1))
                if 13 <= age <= 100:
                    return age
            except ValueError:
                pass
        return 0

    def extract_age_range_field(self, section: str, field_name: str) -> Tuple[int, int]:
        """Extract age range (e.g., 19-22)"""
        pattern = rf'╰\s*{field_name}:\s*(\d+)\s*-\s*(\d+)'
        match = re.search(pattern, section, re.IGNORECASE)
        if match:
            try:
                min_age = int(match.group(1))
                max_age = int(match.group(2))
                return (min_age, max_age)
            except ValueError:
                pass
        
        # Fallback for single age
        single_age = self.extract_age_field(section, field_name)
        if single_age > 0:
            return (single_age - 2, single_age + 2)  # Default range
        
        return (18, 30)  # Default range if nothing found

    def extract_list_field(self, section: str, field_name: str) -> List[str]:
        """Extract list-based fields (likes, dislikes, hobbies, traits)"""
        pattern = rf'╰\s*{field_name}:\s*([^\n╰𝜗𐔌]*)'
        match = re.search(pattern, section, re.IGNORECASE)
        if match:
            text = match.group(1).strip()
            # Split by commas, but be smart about it
            items = []
            current_item = ""
            in_parentheses = False
            
            for char in text + ',':  # Add comma to process last item
                if char == '(':
                    in_parentheses = True
                    current_item += char
                elif char == ')':
                    in_parentheses = False
                    current_item += char
                elif char == ',' and not in_parentheses:
                    if current_item.strip():
                        items.append(current_item.strip())
                    current_item = ""
                else:
                    current_item += char
            
            return [item for item in items if item]
        return []

    def validate_profiles(self, profile1: Dict, profile2: Dict) -> str:
        """Validate profiles for critical data and safety checks"""
        age1 = profile1['personal'].get('age', 0)
        age2 = profile2['personal'].get('age', 0)
        
        if age1 == 0 or age2 == 0:
            return "Could not extract valid ages from one or both forms"
        
        if age1 < 13 or age2 < 13:
            return "Ages must be 13 or older for safety reasons"
        
        return None

    def calculate_compatibility(self, profile1: Dict, profile2: Dict) -> Dict:
        """Calculate comprehensive compatibility scores"""
        scores = {
            'age_score': self.calculate_age_compatibility(profile1, profile2),
            'timezone_score': self.calculate_timezone_compatibility(profile1, profile2),
            'interest_score': self.calculate_interest_compatibility(profile1, profile2),
            'trait_score': self.calculate_trait_compatibility(profile1, profile2),
            'preference_score': self.calculate_preference_compatibility(profile1, profile2),
            'dealbreaker_score': self.calculate_dealbreaker_compatibility(profile1, profile2)
        }
        
        # Weighted overall score (dealbreakers can veto)
        weights = {
            'age_score': 0.20, 'timezone_score': 0.15, 'interest_score': 0.20,
            'trait_score': 0.15, 'preference_score': 0.20, 'dealbreaker_score': 0.10
        }
        
        # Apply dealbreaker penalty
        dealbreaker_penalty = 1.0 if scores['dealbreaker_score'] > 0.3 else 0.0
        overall_score = sum(scores[key] * weights[key] for key in scores) * dealbreaker_penalty
        
        return {
            'overall_score': overall_score,
            'category_scores': scores,
            'details': self.generate_compatibility_details(profile1, profile2, scores),
            'dealbreaker_penalty': dealbreaker_penalty
        }

    def calculate_age_compatibility(self, profile1: Dict, profile2: Dict) -> float:
        """Calculate age compatibility considering preferences"""
        age1 = profile1['personal'].get('age', 0)
        age2 = profile2['personal'].get('age', 0)
        
        # Check if ages fall within each other's preferred ranges
        pref1_min, pref1_max = profile1['preferences'].get('age', (18, 30))
        pref2_min, pref2_max = profile2['preferences'].get('age', (18, 30))
        
        age1_in_pref2 = pref2_min <= age1 <= pref2_max
        age2_in_pref1 = pref1_min <= age2 <= pref1_max
        
        if age1_in_pref2 and age2_in_pref1:
            return 1.0  # Perfect match
        elif age1_in_pref2 or age2_in_pref1:
            return 0.7  # One-sided match
        else:
            # Calculate based on age difference
            age_diff = abs(age1 - age2)
            if age1 < 18 or age2 < 18:
                return 1.0 if age_diff <= 1 else 0.0  # Strict for minors
            else:
                if age_diff <= 2: return 0.8
                elif age_diff <= 4: return 0.5
                else: return 0.2

    def calculate_timezone_compatibility(self, profile1: Dict, profile2: Dict) -> float:
        """Calculate timezone compatibility with preferences"""
        tz1 = profile1['personal'].get('timezone', 'Unknown').upper()
        tz2 = profile2['personal'].get('timezone', 'Unknown').upper()
        pref_tz1 = profile1['preferences'].get('timezone', 'Any').upper()
        pref_tz2 = profile2['preferences'].get('timezone', 'Any').upper()
        
        tz_diff = self.extract_timezone_difference(tz1, tz2)
        
        # Check preferences
        tz1_meets_pref2 = pref_tz2 == 'ANY' or tz1 in pref_tz2 or 'EST' in tz1 and 'EST' in pref_tz2
        tz2_meets_pref1 = pref_tz1 == 'ANY' or tz2 in pref_tz1 or 'EST' in tz2 and 'EST' in pref_tz1
        
        base_score = 1.0 if tz_diff <= 2 else 0.7 if tz_diff <= 4 else 0.4 if tz_diff <= 6 else 0.1
        
        if tz1_meets_pref2 and tz2_meets_pref1:
            return min(1.0, base_score + 0.2)
        elif tz1_meets_pref2 or tz2_meets_pref1:
            return base_score
        else:
            return base_score * 0.5

    def calculate_interest_compatibility(self, profile1: Dict, profile2: Dict) -> float:
        """Calculate interest overlap"""
        likes1 = set(profile1['personal'].get('likes', []))
        likes2 = set(profile2['personal'].get('likes', []))
        hobbies1 = set(profile1['personal'].get('hobbies', []))
        hobbies2 = set(profile2['personal'].get('hobbies', []))
        
        all_interests1 = likes1.union(hobbies1)
        all_interests2 = likes2.union(hobbies2)
        
        if not all_interests1 or not all_interests2:
            return 0.5
        
        intersection = all_interests1.intersection(all_interests2)
        union = all_interests1.union(all_interests2)
        
        return len(intersection) / len(union) if union else 0.0

    def calculate_trait_compatibility(self, profile1: Dict, profile2: Dict) -> float:
        """Calculate personality trait compatibility"""
        traits1 = profile1['personal'].get('traits', [])
        traits2 = profile2['personal'].get('traits', [])
        pref_traits1 = profile1['preferences'].get('traits', [])
        pref_traits2 = profile2['preferences'].get('traits', [])
        
        score = 0.5
        
        # Check if traits match preferences
        trait_matches = 0
        for trait in traits1:
            if any(pref in trait for pref in pref_traits2):
                trait_matches += 1
        for trait in traits2:
            if any(pref in trait for pref in pref_traits1):
                trait_matches += 1
        
        if trait_matches > 0:
            score = min(1.0, 0.5 + (trait_matches * 0.1))
        
        return score

    def calculate_preference_compatibility(self, profile1: Dict, profile2: Dict) -> float:
        """Calculate compatibility based on gender/sexuality preferences"""
        gender1 = profile1['personal'].get('gender', '').lower()
        gender2 = profile2['personal'].get('gender', '').lower()
        sexuality1 = profile1['personal'].get('sexuality', '').lower()
        sexuality2 = profile2['personal'].get('sexuality', '').lower()
        
        pref_gender1 = profile1['preferences'].get('gender', '').lower()
        pref_gender2 = profile2['preferences'].get('gender', '').lower()
        pref_sexuality1 = profile1['preferences'].get('sexuality', '').lower()
        pref_sexuality2 = profile2['preferences'].get('sexuality', '').lower()
        
        # Check basic compatibility
        gender_match = self.check_gender_compatibility(gender1, pref_gender2) and \
                      self.check_gender_compatibility(gender2, pref_gender1)
        
        sexuality_match = self.check_sexuality_compatibility(sexuality1, pref_sexuality2) and \
                         self.check_sexuality_compatibility(sexuality2, pref_sexuality1)
        
        if gender_match and sexuality_match:
            return 1.0
        elif gender_match or sexuality_match:
            return 0.7
        else:
            return 0.3

    def calculate_dealbreaker_compatibility(self, profile1: Dict, profile2: Dict) -> float:
        """Calculate dealbreaker compatibility (trans/poly preferences)"""
        trans1_ok = profile1['other'].get('trans_ok')
        trans2_ok = profile2['other'].get('trans_ok')
        poly1_ok = profile1['other'].get('poly_ok')
        poly2_ok = profile2['other'].get('poly_ok')
        
        score = 1.0
        
        # Trans compatibility
        if trans1_ok is not None and trans2_ok is not None:
            if not trans1_ok and self.is_trans(profile2):
                score *= 0.0
            if not trans2_ok and self.is_trans(profile1):
                score *= 0.0
        
        # Poly compatibility
        if poly1_ok is not None and poly2_ok is not None:
            if not poly1_ok and poly2_ok:
                score *= 0.0
            if not poly2_ok and poly1_ok:
                score *= 0.0
        
        return score

    def is_trans(self, profile: Dict) -> bool:
        """Check if profile indicates transgender identity"""
        gender = profile['personal'].get('gender', '').lower()
        traits = ' '.join(profile['personal'].get('traits', [])).lower()
        
        trans_indicators = ['trans', 'transgender', 'ftm', 'mtf', 'non-binary', 'nb', 'enby']
        return any(indicator in gender or indicator in traits for indicator in trans_indicators)

    def check_gender_compatibility(self, gender: str, preference: str) -> bool:
        """Check if gender matches preference"""
        if preference in ['any', 'anything', 'all']:
            return True
        return gender in preference or preference in gender

    def check_sexuality_compatibility(self, sexuality: str, preference: str) -> bool:
        """Check if sexuality is compatible with preference"""
        if preference in ['any', 'anything', 'all']:
            return True
        
        # Basic compatibility checks
        straight_compatible = sexuality == 'straight' and preference == 'straight'
        gay_compatible = 'gay' in sexuality and 'gay' in preference
        bi_compatible = 'bi' in sexuality or 'pan' in sexuality
        
        return straight_compatible or gay_compatible or bi_compatible

    def extract_timezone_difference(self, tz1: str, tz2: str) -> int:
        """Extract timezone difference in hours"""
        tz_offsets = {
            'est': -5, 'pst': -8, 'cst': -6, 'mst': -7, 'ast': -4,
            'gmt': 0, 'utc': 0, 'cet': 1, 'eet': 2, 'aest': 10,
            'jst': 9, 'ist': 5.5, 'bst': 1
        }
        
        def get_offset(tz):
            tz_lower = tz.lower()
            for key, offset in tz_offsets.items():
                if key in tz_lower:
                    return offset
            match = re.search(r'[+-]?(\d+)', tz)
            return int(match.group(0)) if match else 0
        
        return abs(get_offset(tz1) - get_offset(tz2))

    def generate_compatibility_details(self, profile1: Dict, profile2: Dict, scores: Dict) -> List[str]:
        """Generate specific compatibility details"""
        details = []
        
        # Age details
        age1 = profile1['personal'].get('age', 0)
        age2 = profile2['personal'].get('age', 0)
        pref1_min, pref1_max = profile1['preferences'].get('age', (18, 30))
        pref2_min, pref2_max = profile2['preferences'].get('age', (18, 30))
        
        age1_in_range = pref2_min <= age1 <= pref2_max
        age2_in_range = pref1_min <= age2 <= pref1_max
        
        if age1_in_range and age2_in_range:
            details.append(f"✅ **Age**: Perfect match within preferred ranges")
        elif age1_in_range or age2_in_range:
            details.append(f"⚠️ **Age**: Partial match to preferences")
        else:
            details.append(f"❌ **Age**: Outside preferred ranges")
        
        # Dealbreaker details
        if scores['dealbreaker_score'] <= 0.3:
            details.append("🚫 **Dealbreakers**: Critical incompatibilities detected")
        
        # Timezone details
        tz_diff = self.extract_timezone_difference(
            profile1['personal'].get('timezone', 'Unknown'),
            profile2['personal'].get('timezone', 'Unknown')
        )
        if tz_diff <= 2:
            details.append(f"✅ **Timezone**: Excellent alignment")
        elif tz_diff <= 4:
            details.append(f"⚠️ **Timezone**: Manageable difference")
        else:
            details.append(f"❌ **Timezone**: Significant challenge")
        
        return details

    def generate_compatibility_embed(self, profile1: Dict, profile2: Dict, report: Dict) -> discord.Embed:
        """Generate a beautiful compatibility report embed"""
        overall_score = report['overall_score']
        score_percentage = int(overall_score * 100)
        
        # Determine match level
        if score_percentage >= 80:
            match_level = "🎯 **EXCELLENT MATCH**"
            color = 0xffffff
        elif score_percentage >= 60:
            match_level = "👍 **GOOD POTENTIAL**" 
            color = 0xffffff
        elif score_percentage >= 40:
            match_level = "⚠️ **MODERATE COMPATIBILITY**"
            color = 0xffffff
        else:
            match_level = "❌ **LOW COMPATIBILITY**"
            color = 0xffffff
        
        embed = discord.Embed(
            title="💝 Cupid Compatibility Analysis",
            description=match_level,
            color=color
        )
        
        # Score overview
        embed.add_field(
            name="📊 Overall Compatibility Score",
            value=f"**{score_percentage}%**",
            inline=False
        )
        
        # Detailed breakdown
        details_text = "\n".join(report['details'])
        embed.add_field(
            name="🔍 Detailed Analysis",
            value=details_text,
            inline=False
        )
        
        # Dealbreaker warning
        if report['dealbreaker_penalty'] <= 0.3:
            embed.add_field(
                name="🚫 Critical Warning",
                value="**Dealbreaker incompatibilities detected!**\nThis match has fundamental issues that may prevent success.",
                inline=False
            )
        
        # Recommendations
        if score_percentage >= 70:
            recommendation = "💖 **Strong recommendation** - Excellent potential!"
        elif score_percentage >= 50:
            recommendation = "🤔 **Worth considering** - Some areas need discussion"
        else:
            recommendation = "💭 **Proceed with caution** - Significant differences"
        
        embed.add_field(
            name="💌 Cupid Recommendation",
            value=recommendation,
            inline=False
        )
        
        embed.set_footer(text="Analysis tailored for Cheriies server template • Human judgment essential!")
        
        return embed

async def setup(bot):
    await bot.add_cog(Matchmaking(bot))