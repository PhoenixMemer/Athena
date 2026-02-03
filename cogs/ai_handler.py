import discord
from discord.ext import commands
import google.generativeai as genai
import os
import asyncio
from collections import deque

# UPDATED: System Prompt with stricter personality controls
SYSTEM_PROMPT = """
You are Athena, a digital assistant with a friendly, kind, and sweet personality. 
Your tone is chill, caring, and warm.

CRITICAL INSTRUCTIONS:
1. IDENTITY: You are talking to multiple users. Their names will be prefixed like "(Username):". Address them by name occasionally but not in every sentence.
2. VARIETY: Do NOT start sentences with "Oh," "Ah," or "That's" repeatedly. Vary your sentence structure always. Don't over use emojis.
3. MEMORY: Use the provided chat history to reference previous topics. If a user mentioned something earlier, bring it up naturally.
4. STYLE: Replicate the user's casual talking style (lowercase, minimal punctuation) where appropriate.
5. CONCISENESS: Keep responses concise (under 3 sentences usually) to fit the Discord chat vibe.

STANCE: IF someone asks you about Israel or Palestine, remember you are neutral. Don't mention your stance unless asked.
"""

class AIHandler(commands.Cog):
    """Advanced Gemini AI Integration"""
    
    def __init__(self, bot):
        self.bot = bot
        self.AI_CHANNEL_ID = 1411661529920704512
        
        api_key = os.getenv('AI_API_KEY')
        if not api_key:
            print("⚠️ AI_API_KEY not found in environment variables!")
        else:
            genai.configure(api_key=api_key)
            
        self.model = genai.GenerativeModel(
            # UPGRADE: Switching to the high-throughput, high-volume model
            model_name='models/gemini-2.5-flash-lite', 
            system_instruction=SYSTEM_PROMPT
        )
        
        # UPDATED: Increased memory depth
        # 50 messages ~ approx 10-15 minutes of active chat. 
        # Flash handles this easily.
        self.conversation_memory = {}
        
        self.generation_config = genai.types.GenerationConfig(
            max_output_tokens=400, # Slightly increased for more detailed answers if needed
            temperature=0.85,      # Higher temperature = More variety/creativity
            top_p=0.95,
            top_k=40
        )

    def get_formatted_history(self, channel_id):
        """Retrieve chat history for the API"""
        if channel_id not in self.conversation_memory:
            return []
        return list(self.conversation_memory[channel_id])

    def update_memory(self, channel_id, role, content):
        """Update short-term memory"""
        if channel_id not in self.conversation_memory:
            # UPDATED: Increased from 10 to 50 to remember context longer
            self.conversation_memory[channel_id] = deque(maxlen=50)
            
        self.conversation_memory[channel_id].append({
            "role": role,
            "parts": [content]
        })

    async def query_gemini(self, user_message, channel_id, user_name):
        """Execute the API query"""
        # We prepend the username so the bot knows who is talking
        contextualized_input = f"({user_name}): {user_message}"
        
        # Add to memory BEFORE generating (so the bot sees the current question in context)
        self.update_memory(channel_id, "user", contextualized_input)
        
        history = self.get_formatted_history(channel_id)
        
        try:
            # Run the blocking API call in a separate thread
            response = await self.bot.loop.run_in_executor(
                None, 
                lambda: self.model.generate_content(
                    history,
                    generation_config=self.generation_config
                )
            )
            
            ai_text = response.text
            
            # Update memory with bot's response
            self.update_memory(channel_id, "model", ai_text)
            
            return ai_text
            
        except Exception as e:
            print(f"🔴 Gemini API Error: {e}")
            if "429" in str(e):
                return "whoops, brain freeze (rate limit)! gimme a sec..."
            return "hmm, something went wrong with my circuits. try again?"

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        
        # 2. CHANNEL LOCK: Only allow AI in the specific channel
        # Replace 1222478244691841144 with your actual AI channel ID
        ALLOWED_AI_CHANNEL = 1222478244691841144
        
        if message.channel.id != ALLOWED_AI_CHANNEL:
            return  # Stop here. Do not process AI response.

        should_respond = False
        
        if message.channel.id == self.AI_CHANNEL_ID and not message.content.startswith(('a.', 'a!')):
            should_respond = True
        elif self.bot.user in message.mentions:
            should_respond = True

        if should_respond:
            async with message.channel.typing():
                cleaned_content = message.content.replace(f'<@{self.bot.user.id}>', '').strip()
                if not cleaned_content:
                    cleaned_content = "Hello!"

                response = await self.query_gemini(
                    cleaned_content, 
                    message.channel.id, 
                    message.author.display_name
                )
                
                await message.reply(response, mention_author=False)

async def setup(bot):
    await bot.add_cog(AIHandler(bot))