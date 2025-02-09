import discord
from discord import app_commands
import json
import os
from dotenv import load_dotenv
from flask import Flask, Response
from threading import Thread
import aiohttp
from bs4 import BeautifulSoup
from difflib import get_close_matches
import random
import asyncio
from discord.errors import HTTPException
import time
from collections import deque
import logging
from werkzeug.serving import WSGIRequestHandler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Flask setup with improved error handling
app = Flask(__name__)
WSGIRequestHandler.protocol_version = "HTTP/1.1"

@app.route('/')
def home():
    try:
        response = Response("Bot is running", status=200)
        response.headers["Content-Type"] = "text/plain"
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response
    except Exception as e:
        logger.error(f"Error in home route: {e}")
        return Response("Error checking status", status=500)

@app.route('/health')
def health():
    try:
        return Response("Healthy", status=200)
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return Response("Unhealthy", status=500)

def run_web():
    """Run the Flask web server with improved error handling"""
    try:
        port = int(os.environ.get("PORT", 4000))
        app.run(
            host='0.0.0.0',
            port=port,
            debug=False,
            use_reloader=False,
            threaded=True
        )
    except Exception as e:
        logger.error(f"Web server error: {e}")
        time.sleep(5)
        run_web()

def keep_alive():
    """Start the web server in a daemon thread"""
    server = Thread(target=run_web, daemon=True)
    try:
        server.start()
        logger.info("Web server started successfully")
    except Exception as e:
        logger.error(f"Failed to start web server: {e}")
        time.sleep(5)
        keep_alive()

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Load data files
try:
    with open("zwift_routes.json", "r", encoding='utf-8') as file:
        zwift_routes = json.load(file)
    logger.info(f"Loaded {len(zwift_routes)} routes")
except Exception as e:
    logger.error(f"Error loading routes file: {e}")
    zwift_routes = []

try:
    with open("zwift_koms.json", "r", encoding='utf-8') as file:
        zwift_koms = json.load(file)
    logger.info(f"Loaded {len(zwift_koms)} KOMs")
except Exception as e:
    logger.error(f"Error loading KOMs file: {e}")
    zwift_koms = []

try:
    with open("zwift_sprint_segments.json", "r", encoding='utf-8') as file:
        zwift_sprints = json.load(file)
    logger.info(f"Loaded {len(zwift_sprints)} sprints")
except Exception as e:
    logger.error(f"Error loading sprints file: {e}")
    zwift_sprints = []

def normalize_route_name(name):
    """Remove special characters and standardize the name"""
    return ''.join(c.lower() for c in name if c.isalnum() or c.isspace())

def get_world_for_route(route_name):
    """Determine the Zwift world for a given route"""
    route_lower = route_name.lower()
    if any(x in route_lower for x in ['makuri', 'neokyo', 'urukazi']):
        return 'Makuri'
    elif any(x in route_lower for x in ['france', 'ven-top', 'casse-pattes']):
        return 'France'
    elif any(x in route_lower for x in ['london', 'greater london', 'london loop']):
        return 'London'
    elif any(x in route_lower for x in ['yorkshire', 'harrogate']):
        return 'Yorkshire'
    elif any(x in route_lower for x in ['innsbruck', 'lutscher']):
        return 'Innsbruck'
    elif any(x in route_lower for x in ['richmond']):
        return 'Richmond'
    elif any(x in route_lower for x in ['paris']):
        return 'Paris'
    elif any(x in route_lower for x in ['glasgow']):
        return 'Scotland'
    else:
        return 'Watopia'

def find_route(search_term):
    """Find a route using fuzzy matching"""
    if not search_term or not zwift_routes:
        return None, []
    search_term = normalize_route_name(search_term)
    for route in zwift_routes:
        if normalize_route_name(route["Route"]) == search_term:
            return route, []
    matches = []
    for route in zwift_routes:
        if search_term in normalize_route_name(route["Route"]):
            matches.append(route)
    if matches:
        return matches[0], matches[1:3]
    route_names = [normalize_route_name(r["Route"]) for r in zwift_routes]
    close_matches = get_close_matches(search_term, route_names, n=3, cutoff=0.6)
    if close_matches:
        matched_routes = [r for r in zwift_routes if normalize_route_name(r["Route"]) == close_matches[0]]
        alternative_routes = [r for r in zwift_routes if normalize_route_name(r["Route"]) in close_matches[1:]]
        if matched_routes:
            return matched_routes[0], alternative_routes
    return None, []

def find_kom(search_term):
    """Find a KOM using fuzzy matching"""
    if not search_term or not zwift_koms:
        return None, []
    normalized_search = normalize_route_name(search_term)
    for kom in zwift_koms:
        if normalize_route_name(kom["Segment"]) == normalized_search:
            return kom, []
    matches = []
    for kom in zwift_koms:
        if normalized_search in normalize_route_name(kom["Segment"]):
            matches.append(kom)
    if matches:
        return matches[0], matches[1:3]
    kom_names = [normalize_route_name(k["Segment"]) for k in zwift_koms]
    close_matches = get_close_matches(normalized_search, kom_names, n=3, cutoff=0.6)
    if close_matches:
        matched_koms = [k for k in zwift_koms if normalize_route_name(k["Segment"]) == close_matches[0]]
        alternative_koms = [k for k in zwift_koms if normalize_route_name(k["Segment"]) in close_matches[1:]]
        if matched_koms:
            return matched_koms[0], alternative_koms
    return None, []

def find_sprint(search_term):
    """Find a sprint segment using fuzzy matching"""
    if not search_term or not zwift_sprints:
        return None, []
    normalized_search = normalize_route_name(search_term)
    for sprint in zwift_sprints:
        if normalize_route_name(sprint["Segment"]) == normalized_search:
            return sprint, []
    matches = []
    for sprint in zwift_sprints:
        if normalized_search in normalize_route_name(sprint["Segment"]):
            matches.append(sprint)
    if matches:
        return matches[0], matches[1:3]
    sprint_names = [normalize_route_name(s["Segment"]) for s in zwift_sprints]
    close_matches = get_close_matches(normalized_search, sprint_names, n=3, cutoff=0.6)
    if close_matches:
        matched_sprints = [s for s in zwift_sprints if normalize_route_name(s["Segment"]) == close_matches[0]]
        alternative_sprints = [s for s in zwift_sprints if normalize_route_name(s["Segment"]) in close_matches[1:]]
        if matched_sprints:
            return matched_sprints[0], alternative_sprints
    return None, []

async def fetch_route_info(url):
    """Fetch route information from ZwiftInsider"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    stats = []
                    for p in soup.find_all('p'):
                        text = p.get_text()
                        if any(key in text.lower() for key in ['distance:', 'elevation:', 'length:', 'climb:']):
                            stats.append(text.strip())
                    img = soup.find('img', class_='wp-post-image')
                    img_url = img['src'] if img else None
                    return stats[:3], img_url
    except Exception as e:
        logger.error(f"Error fetching route info: {e}")
    return [], None

# Updated helper functions for URL handling
async def get_cyccal_url(route_name):
    """Convert route name to Cyccal URL format"""
    formatted_name = route_name.lower().replace(' ', '-')
    formatted_name = ''.join(c for c in formatted_name if c.isalnum() or c == '-')
    formatted_name = '-'.join(filter(None, formatted_name.split('-')))
    return f"https://cyccal.com/{formatted_name}/"

async def get_cyccal_image(route_name):
    """Get the elevation profile image URL using the correct Cyccal format"""
    world = get_world_for_route(route_name)
    words = route_name.split()
    formatted_words = []
    
    # Words that should remain lowercase in the URL
    lowercase_words = {'and', 'of', 'the', 'to', 'in', 'on', 'at', 'by'}
    
    for word in words:
        if word.lower() in lowercase_words:
            formatted_words.append(word.lower())
        else:
            formatted_words.append(word.title())
    
    route_formatted = '_'.join(formatted_words)
    return f"https://cyccal.com/wp-content/uploads/2024/11/{world}_{route_formatted}_profile.png"

def get_world_for_route(route_name):
    """Determine the Zwift world for a given route with improved accuracy"""
    route_lower = route_name.lower()
    
    # Define world mappings with more specific patterns
    world_patterns = {
        'Makuri': ['makuri', 'neokyo', 'urukazi', 'castle', 'temple', 'rooftop'],
        'France': ['france', 'ven-top', 'casse-pattes', 'petit', 'ventoux'],
        'London': ['london', 'greater london', 'london loop', 'leith', 'box hill', 'surrey'],
        'Yorkshire': ['yorkshire', 'harrogate', 'royal pump'],
        'Innsbruck': ['innsbruck', 'lutscher'],
        'Richmond': ['richmond'],
        'Paris': ['paris', 'champs', 'lutece'],
        'Scotland': ['glasgow', 'scotland', 'sgurr', 'loch'],
        'New York': ['new york', 'ny', 'central park', 'astoria'],
    }
    
    # Check each world's patterns
    for world, patterns in world_patterns.items():
        if any(pattern in route_lower for pattern in patterns):
            return world
            
    # Default to Watopia if no other world matches
    return 'Watopia'

# Updated route command with improved error handling and logging
@client.tree.command(name="route", description="Get a Zwift route URL by name")
async def route(interaction: discord.Interaction, name: str):
    if not interaction.user:
        return
        
    try:
        logger.info(f"Route command started for: {name}")
        
        try:
            await client.check_rate_limit(interaction.user.id)
        except HTTPException as e:
            logger.warning(f"Rate limit hit: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="⏳ Rate Limited",
                        description=str(e),
                        color=discord.Color.orange()
                    ),
                    ephemeral=True
                )
            return

        result, alternatives = find_route(name)
        logger.info(f"Route search result: {result['Route'] if result else 'Not found'}")
        
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True)
            logger.info("Interaction deferred")
        
        if result:
            stats, zwift_img_url = await fetch_route_info(result["URL"])
            logger.info(f"ZwiftInsider image URL: {zwift_img_url}")
            
            embed = discord.Embed(
                title=f"🚲 {result['Route']}",
                url=result["URL"],
                description="\n".join(stats) if stats else "View full route details on ZwiftInsider",
                color=0xFC6719
            )
            logger.info("Basic embed created")
            
            if alternatives:
                similar_routes = "\n\n**Similar routes:**\n" + "\n".join(f"• {r['Route']}" for r in alternatives)
                if embed.description:
                    embed.description += similar_routes
                else:
                    embed.description = similar_routes
                logger.info("Added alternatives to embed")
            
            # Attempt to get Cyccal image
            try:
                cyccal_url = await get_cyccal_url(result["Route"])
                cyccal_img_url = await get_cyccal_image(result["Route"])
                logger.info(f"Cyccal image URL: {cyccal_img_url}")
                
                async with aiohttp.ClientSession() as session:
                    try:
                        async with session.head(cyccal_img_url, timeout=5) as response:
                            logger.info(f"Cyccal image status code: {response.status}")
                            if response.status == 200:
                                embed.set_image(url=cyccal_img_url)
                                logger.info("Successfully set Cyccal image")
                            else:
                                logger.warning(f"Cyccal image not found, status: {response.status}")
                                if zwift_img_url:
                                    embed.set_image(url=zwift_img_url)
                                    logger.info("Fallback to ZwiftInsider image")
                    except asyncio.TimeoutError:
                        logger.warning("Timeout fetching Cyccal image")
                        if zwift_img_url:
                            embed.set_image(url=zwift_img_url)
                    except Exception as e:
                        logger.error(f"Error checking Cyccal image: {e}")
                        if zwift_img_url:
                            embed.set_image(url=zwift_img_url)
            except Exception as e:
                logger.error(f"Error in Cyccal image processing: {e}")
                if zwift_img_url:
                    embed.set_image(url=zwift_img_url)
            
            # Ensure URL is properly encoded
            if embed.image:
                embed.set_image(url=quote(embed.image.url, safe=':/?=&'))
                logger.info(f"Final image URL: {embed.image.url}")
            
            embed.set_thumbnail(url="https://zwiftinsider.com/wp-content/uploads/2022/12/zwift-logo.png")
            embed.set_footer(text="ZwiftGuy • Use /route to find routes")
            
            # Add length checks
            if len(embed.description) > 4096:
                embed.description = embed.description[:4093] + "..."
            
            # Log embed details before sending
            logger.info(f"Embed title: {embed.title}")
            logger.info(f"Embed description length: {len(embed.description)}")
            logger.info(f"Embed has image: {embed.image is not None}")
            
        else:
            suggestions = random.sample(zwift_routes, min(3, len(zwift_routes)))
            embed = discord.Embed(
                title="❌ Route Not Found",
                description=f"Could not find a route matching `{name}`.\n\n**Try these routes:**\n" + 
                           "\n".join(f"• {r['Route']}" for r in suggestions),
                color=discord.Color.red()
            )
            logger.info("Created 'not found' embed")

        # Try to send the embed with error handling
        try:
            await interaction.followup.send(embed=embed)
            logger.info("Successfully sent embed")
        except discord.HTTPException as e:
            logger.error(f"Discord HTTP error when sending embed: {e}")
            # Try without image as fallback
            embed.set_image(url=None)
            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Unknown error when sending embed: {e}")
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Error",
                    description="An error occurred while sending the route information.",
                    color=discord.Color.red()
                )
            )
            
    except Exception as e:
        logger.error(f"Error in route command: {e}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="❌ Error",
                        description="An error occurred while processing your request.",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
        except:
            pass

@client.tree.command(name="sprint", description="Get information about a Zwift sprint segment")
async def sprint(interaction: discord.Interaction, name: str):
    if not interaction.user:
        return
    try:
        try:
            await client.check_rate_limit(interaction.user.id)
        except HTTPException as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="⏳ Rate Limited",
                        description=str(e),
                        color=discord.Color.orange()
                    ),
                    ephemeral=True
                )
            return

        result, alternatives = find_sprint(name)
        
        if not interaction.response.is_done():
            await interaction.response.defer()
        
        if result:
            embed = discord.Embed(
                title=f"⚡ {result['Segment']}",
                url=result['URL'],
                description=f"Location: {result['Location']}",
                color=0x00FF00
            )
            
            embed.add_field(
                name="Distance", 
                value=f"{result['Length_m']}m", 
                inline=True
            )
            embed.add_field(
                name="Grade", 
                value=f"{result['Grade']}%", 
                inline=True
            )

            if alternatives:
                similar_sprints = "\n\n**Similar segments:**\n" + "\n".join(
                    f"• {s['Segment']} ({s['Length_m']}m, {s['Grade']}%)" 
                    for s in alternatives
                )
                embed.add_field(name="", value=similar_sprints, inline=False)
            
            embed.set_thumbnail(url="https://zwiftinsider.com/wp-content/uploads/2022/12/zwift-logo.png")
            embed.set_footer(text="ZwiftGuy • Use /sprint to find segments")
        else:
            suggestions = random.sample(zwift_sprints, min(3, len(zwift_sprints)))
            embed = discord.Embed(
                title="❌ Sprint Not Found",
                description=f"Could not find a sprint segment matching `{name}`.\n\n**Try these segments:**\n" + 
                           "\n".join(f"• {s['Segment']} ({s['Length_m']}m, {s['Grade']}%)" 
                                   for s in suggestions),
                color=discord.Color.red()
            )

        await interaction.followup.send(embed=embed)
            
    except Exception as e:
        logger.error(f"Error in sprint command: {e}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="❌ Error",
                        description="An error occurred while processing your request.",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
        except:
            pass

def main():
    retries = 0
    max_retries = 5
    
    while retries < max_retries:
        try:
            logger.info("Starting bot...")
            keep_alive()
            client.run(TOKEN)
            break
        except Exception as e:
            retries += 1
            logger.error(f"Main program error (attempt {retries}/{max_retries}): {e}")
            if retries < max_retries:
                wait_time = min(300, 5 * (2 ** retries))
                logger.info(f"Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
            else:
                logger.critical("Max retries reached, shutting down")
                break

if __name__ == "__main__":
    main()
