import discord
from discord import app_commands
import json
import os
from dotenv import load_dotenv
import aiohttp
from bs4 import BeautifulSoup
from difflib import get_close_matches
import random
import asyncio
from discord.errors import HTTPException
import time
from collections import deque
import logging
from urllib.parse import quote
import io  # For handling file data in memory
import re  # For pattern matching in route details
import datetime  # For timestamp formatting
from typing import Literal, Optional  # For command parameter types

# ==========================================
# Configure logging
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==========================================
# Load environment variables and data files
# ==========================================
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Load routes data
try:
    with open("zwift_routes.json", "r", encoding='utf-8') as file:
        zwift_routes = json.load(file)
    logger.info(f"Loaded {len(zwift_routes)} routes")
except Exception as e:
    logger.error(f"Error loading routes file: {e}")
    zwift_routes = []

# Load KOMs data
try:
    with open("zwift_koms.json", "r", encoding='utf-8') as file:
        zwift_koms = json.load(file)
    logger.info(f"Loaded {len(zwift_koms)} KOMs")
except Exception as e:
    logger.error(f"Error loading KOMs file: {e}")
    zwift_koms = []

# Load sprints data
try:
    with open("zwift_sprint_segments.json", "r", encoding='utf-8') as file:
        zwift_sprints = json.load(file)
    logger.info(f"Loaded {len(zwift_sprints)} sprints")
except Exception as e:
    logger.error(f"Error loading sprints file: {e}")
    zwift_sprints = []

# ==========================================
# Helper Functions
# ==========================================
async def bike_loading_animation(interaction):
    """Create a bike riding animation in Discord embed"""
    track_length = 20  # How long the "track" is
    bike = "🚲"
    track = "═"
    loading_titles = ["Finding route...", "Calculating distance...", "Checking traffic...", "Almost there!"]
    
    loading_message = await interaction.followup.send(
        embed=discord.Embed(
            title=loading_titles[0],
            description=track * track_length,
            color=0xFC6719
        )
    )
    
    for position in range(track_length):
        # Change title every 5 positions
        current_title = loading_titles[min(position // 5, len(loading_titles) - 1)]
        
        # Create the track with bike position
        track_display = (track * position) + bike + (track * (track_length - position - 1))
        
        try:
            await loading_message.edit(
                embed=discord.Embed(
                    title=current_title,
                    description=track_display,
                    color=0xFC6719
                )
            )
            # Gradually speed up the animation
            await asyncio.sleep(max(0.2, 0.5 - (position * 0.015)))
        except discord.NotFound:
            break
        except Exception as e:
            logger.error(f"Error updating loading animation: {e}")
            break
    
    return loading_message

def normalize_route_name(name):
    """Remove special characters and standardize the name"""
    return ''.join(c.lower() for c in name if c.isalnum() or c.isspace())

def get_world_for_route(route_name):
    """Determine the Zwift world for a given route"""
    route_lower = route_name.lower()
    
    # Define world mappings with specific patterns
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
    

# ==========================================
# Route Finding Functions
# ==========================================
def find_route(search_term):
    """Find a route using fuzzy matching"""
    if not search_term or not zwift_routes:
        return None, []
    search_term = normalize_route_name(search_term)
    
    # Check for exact match first
    for route in zwift_routes:
        if normalize_route_name(route["Route"]) == search_term:
            return route, []
            
    # Check for partial matches
    matches = []
    for route in zwift_routes:
        if search_term in normalize_route_name(route["Route"]):
            matches.append(route)
    if matches:
        return matches[0], matches[1:3]
        
    # Try fuzzy matching if no direct matches found
    route_names = [normalize_route_name(r["Route"]) for r in zwift_routes]
    close_matches = get_close_matches(search_term, route_names, n=3, cutoff=0.6)
    if close_matches:
        matched_routes = [r for r in zwift_routes if normalize_route_name(r["Route"]) == close_matches[0]]
        alternative_routes = [r for r in zwift_routes if normalize_route_name(r["Route"]) in close_matches[1:]]
        if matched_routes:
            return matched_routes[0], alternative_routes
    return None, []

def find_sprint(search_term):
    """Find a sprint segment using fuzzy matching"""
    if not search_term or not zwift_sprints:
        return None, []
    normalized_search = normalize_route_name(search_term)
    
    # Check for exact match first
    for sprint in zwift_sprints:
        if normalize_route_name(sprint["Segment"]) == normalized_search:
            return sprint, []
            
    # Check for partial matches
    matches = []
    for sprint in zwift_sprints:
        if normalized_search in normalize_route_name(sprint["Segment"]):
            matches.append(sprint)
    if matches:
        return matches[0], matches[1:3]
        
    # Try fuzzy matching if no direct matches found
    sprint_names = [normalize_route_name(s["Segment"]) for s in zwift_sprints]
    close_matches = get_close_matches(normalized_search, sprint_names, n=3, cutoff=0.6)
    if close_matches:
        matched_sprints = [s for s in zwift_sprints if normalize_route_name(s["Segment"]) == close_matches[0]]
        alternative_sprints = [s for s in zwift_sprints if normalize_route_name(s["Segment"]) in close_matches[1:]]
        if matched_sprints:
            return matched_sprints[0], alternative_sprints
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


# ==========================================
# Route Information Fetching
# ==========================================
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

# ==========================================
# Discord Bot Class Definition
# ==========================================
class ZwiftBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.command_cooldowns = {}
        self.global_command_times = deque(maxlen=50)
        self.rate_limit_lock = asyncio.Lock()
        self.USER_COOLDOWN = 5.0
        self.GLOBAL_RATE_LIMIT = 20
        
        # Constants for cache management
        self.CACHE_DIR = "/app/data"
        self.CACHE_FILE = os.path.join(self.CACHE_DIR, "route_details_cache.json")
        self.CACHE_AGE_DAYS = 14  # How many days before refreshing the cache
        
# ==========================================
    # Route Image Finder Function
    # ==========================================
    # Features:
    # - Fixed path handling for Docker environment
    # - Enhanced logging for easier troubleshooting
    # - Added direct path checking based on Docker volume mounts
    # - Improved error handling with traceback logging
    # - Expanded file type detection capabilities
    # ==========================================
    
    def get_local_svg(self, route_name: str) -> str:
        """
        Get local image path using RapidFuzz for better matching.

        Args:
            route_name (str): The name of the route to find an image for
        
        Returns:
            str or None: Path to the image file if found, None otherwise
        """
        try:
            # Try to import RapidFuzz
            try:
                from rapidfuzz import process, fuzz
            except ImportError:
                logger.warning("RapidFuzz not installed. Trying to install it...")
                try:
                    import pip
                    pip.main(['install', 'rapidfuzz'])
                    from rapidfuzz import process, fuzz
                    logger.info("Successfully installed and imported RapidFuzz")
                except Exception as install_err:
                    logger.error(f"Failed to install RapidFuzz: {install_err}")
                    return None
            
            import os
        
            # Get official name from your existing fuzzy matching
            route_result, _ = find_route(route_name)
            if not route_result:
                logger.error(f"Could not find route match for {route_name}")
                return None
            
            official_name = route_result["Route"]
            logger.info(f"Looking for image for route: {official_name}")
        
            # Try multiple directories based on Docker volume mapping
            dirs_to_check = [
                "/app/route_images/maps",
                "/app/route_images/profiles",
                "/app/route_images"
            ]
            
            # Find first directory that exists
            dir_path = None
            for path in dirs_to_check:
                if os.path.exists(path):
                    logger.info(f"Found existing directory: {path}")
                    dir_path = path
                    # Check if there are any files in this directory
                    if os.listdir(path):
                        break
            
            if not dir_path:
                logger.error("No valid image directories found")
                # List all directories in /app to help troubleshoot
                try:
                    logger.info(f"Contents of /app: {os.listdir('/app')}")
                    if os.path.exists('/app/route_images'):
                        logger.info(f"Contents of /app/route_images: {os.listdir('/app/route_images')}")
                except Exception as list_err:
                    logger.error(f"Error listing directories: {list_err}")
                return None
                
            logger.info(f"Using directory for images: {dir_path}")
        
            # Get list of PNG and SVG files
            image_files = []
            for root, _, files in os.walk(dir_path):
                for file in files:
                    if file.lower().endswith(('.png', '.svg', '.webp')):
                        image_files.append(os.path.join(root, file))
        
            if not image_files:
                logger.error(f"No image files found in directory {dir_path}")
                return None
            
            logger.info(f"Found {len(image_files)} image files")
        
            # Prepare clean version of the route name
            clean_name = ''.join(c for c in official_name.lower() if c.isalnum() or c.isspace())
            name_with_underscores = clean_name.replace(' ', '_')
        
            # Try different strategies in order
            strategies = [
                # Strategy 1: WRatio on original name (handles many cases well)
                {"query": official_name, "scorer": fuzz.WRatio, "cutoff": 60},
            
                # Strategy 2: token_set_ratio on underscored name (handles word reordering)
                {"query": name_with_underscores, "scorer": fuzz.token_set_ratio, "cutoff": 65},
            
                # Strategy 3: partial_ratio on clean name (handles partial matches)
                {"query": clean_name, "scorer": fuzz.partial_ratio, "cutoff": 75},
            ]
        
            # Extract just the filenames for matching
            filenames_for_matching = [os.path.basename(file) for file in image_files]
            
            # Try each strategy
            best_match_file = None
            best_match_score = 0
            
            for strategy in strategies:
                match_result = process.extractOne(
                    query=strategy["query"],
                    choices=filenames_for_matching,
                    scorer=strategy["scorer"],
                    score_cutoff=strategy["cutoff"]
                )
            
                if match_result:
                    # Handle both tuple formats (RapidFuzz might return different formats)
                    if isinstance(match_result, tuple) and len(match_result) >= 2:
                        best_match_filename = match_result[0]
                        score = match_result[1]
                        
                        # Find the full path that matches this filename
                        for file_path in image_files:
                            if os.path.basename(file_path) == best_match_filename:
                                if score > best_match_score:
                                    best_match_file = file_path
                                    best_match_score = score
                        
                        scorer_name = strategy["scorer"].__name__
                        logger.info(f"Found match with {scorer_name}: {best_match_filename} (score: {score})")
            
            if best_match_file:
                logger.info(f"Best match found: {best_match_file} with score {best_match_score}")
                return best_match_file
        
            # Special case for problematic routes
            special_cases = {
                "queen": "highway",
                "mech": "isle",
                "london": "loop",
                "tour": "london"
            }
            
            for key, value in special_cases.items():
                if key in clean_name and (value in clean_name or not value):
                    logger.info(f"Checking special case for {key}/{value}")
                    for file_path in image_files:
                        filename_lower = os.path.basename(file_path).lower()
                        if key in filename_lower and (value in filename_lower or not value):
                            logger.info(f"Found special case match: {file_path}")
                            return file_path
            
            # Direct filename checks
            exact_name = official_name.lower().replace(' ', '_').replace('-', '_')
            for file_path in image_files:
                filename = os.path.basename(file_path).lower()
                filename_no_ext = os.path.splitext(filename)[0]
                
                # Try various transformations of the name
                if (exact_name in filename_no_ext or 
                    filename_no_ext in exact_name or
                    clean_name in filename_no_ext or
                    filename_no_ext in clean_name):
                    logger.info(f"Found direct filename match: {file_path}")
                    return file_path
                    
            logger.info(f"No image found for {official_name}")
            return None
        
        except Exception as e:
            logger.error(f"Error in get_local_svg: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
            
  # ==========================================
# Image Type Helper Functions
# - Handles PNG from ZwiftInsider and SVG from ZwiftHacks
# ==========================================
    def handle_local_image(self, local_path: str, embed: discord.Embed) -> tuple:
        """
        Handle PNG and SVG files for route images.
        Returns the file and source type for the embed.
        """
        try:
            if not local_path:
                return None, None
                
            file_lower = local_path.lower()
            
            # Handle PNGs from ZwiftInsider
            if '_png' in file_lower:
                image_file = discord.File(local_path, filename="route.png")
                embed.set_image(url="attachment://route.png")
                return image_file, "zwiftinsider"
                
            # Handle SVGs from ZwiftHacks
            elif '_svg' in file_lower:
                image_file = discord.File(local_path, filename="route.svg")
                embed.set_image(url="attachment://route.svg")
                return image_file, "svg"
                
            return None, None
                
        except Exception as e:
            logger.error(f"Error handling image: {e}")
            return None, None


# ==========================================
    # ZwiftHacks Map Finder Function
    # ==========================================
    # Features:
    # - Fixed path handling for Docker environment
    # - Enhanced error logging with traceback
    # - Added support for multiple directory structures
    # - Improved file type detection
    # - Better fuzzy matching settings for route names
    # ==========================================
    
    def get_zwifthacks_map(self, route_name: str) -> str:
        """
        Get the ZwiftHacks map image for a route.
        
        Args:
            route_name (str): The name of the route to find a map image for
            
        Returns:
            str or None: Path to the map image file if found, None otherwise
        """
        try:
            # Try to import RapidFuzz for better matching
            try:
                from rapidfuzz import process, fuzz
            except ImportError:
                logger.warning("RapidFuzz not installed for ZwiftHacks maps.")
                try:
                    import pip
                    pip.main(['install', 'rapidfuzz'])
                    from rapidfuzz import process, fuzz
                    logger.info("Successfully installed RapidFuzz for map matching")
                except Exception as install_err:
                    logger.error(f"Failed to install RapidFuzz: {install_err}")
                    return None
                
            import os
        
            # Get official name from existing fuzzy matching
            route_result, _ = find_route(route_name)
            if not route_result:
                logger.error(f"Could not find route match for {route_name}")
                return None
            
            official_name = route_result["Route"]
            logger.info(f"Looking for ZwiftHacks map for route: {official_name}")
        
            # Try multiple potential directories
            dir_paths = [
                "/app/route_images/maps", 
                "/app/route_images/profiles",
                "/app/route_images"
            ]
            
            # Find directories that exist and have files
            valid_dirs = []
            for path in dir_paths:
                if os.path.exists(path):
                    logger.info(f"Found existing directory: {path}")
                    # Check if there are any files in this directory
                    files = os.listdir(path)
                    if files:
                        valid_dirs.append(path)
                        logger.info(f"Directory {path} contains {len(files)} files")
                        
            if not valid_dirs:
                logger.error("No valid map directories found")
                return None
                
            # Get list of all image files in all valid directories
            image_files = []
            for dir_path in valid_dirs:
                for root, _, files in os.walk(dir_path):
                    for file in files:
                        if file.lower().endswith(('.png', '.svg')):
                            image_files.append(os.path.join(root, file))
        
            if not image_files:
                logger.error(f"No image files found in directories: {valid_dirs}")
                return None
                
            logger.info(f"Found {len(image_files)} total image files")
        
            # Prepare clean version of the route name
            clean_name = ''.join(c for c in official_name.lower() if c.isalnum() or c.isspace())
            name_with_underscores = clean_name.replace(' ', '_')
        
            # Using slightly more permissive strategies than get_local_svg
            strategies = [
                {"query": official_name, "scorer": fuzz.WRatio, "cutoff": 60},
                {"query": name_with_underscores, "scorer": fuzz.token_set_ratio, "cutoff": 60},
                {"query": clean_name, "scorer": fuzz.partial_ratio, "cutoff": 70},
            ]
            
            # Extract just the filenames for matching
            filenames_for_matching = [os.path.basename(file) for file in image_files]
            
            # Try each strategy
            best_match_file = None
            best_match_score = 0
            
            for strategy in strategies:
                match_result = process.extractOne(
                    query=strategy["query"],
                    choices=filenames_for_matching,
                    scorer=strategy["scorer"],
                    score_cutoff=strategy["cutoff"]
                )
            
                if match_result:
                    # Handle both tuple formats
                    if isinstance(match_result, tuple) and len(match_result) >= 2:
                        best_match_filename = match_result[0]
                        score = match_result[1]
                        
                        # Find the full path that matches this filename
                        for file_path in image_files:
                            if os.path.basename(file_path) == best_match_filename:
                                if score > best_match_score:
                                    best_match_file = file_path
                                    best_match_score = score
                        
                        logger.info(f"Found ZwiftHacks map match: {best_match_filename} (score: {score})")
            
            if best_match_file:
                logger.info(f"Best ZwiftHacks map match: {best_match_file} with score {best_match_score}")
                return best_match_file
        
            # Special case handling
            special_cases = {
                "queen": "highway",
                "mech": "isle",
                "london": "loop",
                "watopia": "flat",
                "tour": "france"
            }
            
            for key, value in special_cases.items():
                if key in clean_name and (value in clean_name or not value):
                    logger.info(f"Checking special map case for {key}/{value}")
                    for file_path in image_files:
                        filename_lower = os.path.basename(file_path).lower()
                        if key in filename_lower and (value in filename_lower or not value):
                            logger.info(f"Found special case map match: {file_path}")
                            return file_path
            
            # Direct filename checks
            for file_path in image_files:
                filename = os.path.basename(file_path).lower()
                filename_no_ext = os.path.splitext(filename)[0]
                
                # Try various transformations of the name
                if (clean_name in filename_no_ext or 
                    filename_no_ext in clean_name or
                    name_with_underscores in filename_no_ext or
                    filename_no_ext in name_with_underscores):
                    logger.info(f"Found direct filename map match: {file_path}")
                    return file_path
        
            logger.info(f"No ZwiftHacks map found for {official_name}")
            return None
        
        except Exception as e:
            logger.error(f"Error in get_zwifthacks_map: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None


    # ==========================================
    # ZwiftHacks Map Handler Function
    # ==========================================
    # Features:
    # - Fixed file handling for Discord attachments
    # - Enhanced error logging with traceback
    # - Improved file type detection
    # ==========================================

    def handle_zwifthacks_map(self, map_path: str) -> discord.File:
        """
        Create a Discord file object for a ZwiftHacks map.
        
        Args:
            map_path (str): Path to the map file
            
        Returns:
            discord.File: File object for the map, or None if error
        """
        try:
            if not map_path:
                logger.warning("No map path provided to handle_zwifthacks_map")
                return None
                
            logger.info(f"Creating Discord file for map: {map_path}")
            
            # Determine file type
            file_lower = map_path.lower()
            
            if file_lower.endswith('.svg'):
                # For SVG files
                map_file = discord.File(map_path, filename="route_map.svg")
                logger.info("Created Discord file for SVG map")
                return map_file
            elif file_lower.endswith('.png') or '.png' in file_lower:
                # For PNG files (most common)
                map_file = discord.File(map_path, filename="route_map.png")
                logger.info("Created Discord file for PNG map")
                return map_file
            else:
                # Try to detect file type by content
                try:
                    with open(map_path, 'rb') as f:
                        header = f.read(10)
                        if header.startswith(b'<svg') or header.startswith(b'<?xml'):
                            map_file = discord.File(map_path, filename="route_map.svg")
                            logger.info("Created Discord file for SVG map (content detection)")
                            return map_file
                        elif header.startswith(b'\x89PNG'):
                            map_file = discord.File(map_path, filename="route_map.png")
                            logger.info("Created Discord file for PNG map (content detection)")
                            return map_file
                except Exception as read_err:
                    logger.error(f"Error reading file content: {read_err}")
                
                # Fallback - try to use it as PNG
                try:
                    map_file = discord.File(map_path, filename="route_map.png")
                    logger.info("Created Discord file for map as fallback PNG")
                    return map_file
                except Exception as fallback_err:
                    logger.error(f"Fallback file creation failed: {fallback_err}")
                
                logger.error(f"Could not determine file type for {map_path}")
                return None
                
        except Exception as e:
            logger.error(f"Error handling ZwiftHacks map: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
            
# ==========================================
    # Discord View for Share Buttons
    # ==========================================
    # Features:
    # - Adds a "Share to Channel" button to ephemeral messages
    # - Allows users to make private results public
    # - Customizes the share message based on command type
    # ==========================================
    
    class ShareButtonView(discord.ui.View):
        def __init__(self, embed, files=None, command_type="route"):
            super().__init__(timeout=300)  # 5 minute timeout
            self.embed = embed
            self.files = files if files else []
            self.command_type = command_type
            
            # Store file data since files can only be sent once
            self.file_data = []
            for file in self.files:
                # Get file data and reset cursor
                file.fp.seek(0)
                self.file_data.append((file.filename, file.fp.read()))
            
        @discord.ui.button(label="Share to Channel", style=discord.ButtonStyle.primary, emoji="📢")
        async def share_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            """Share the current result to the channel"""
            # Create a new set of files from the stored data
            new_files = []
            for filename, data in self.file_data:
                new_file = discord.File(io.BytesIO(data), filename=filename)
                new_files.append(new_file)
            
            # Clone the embed
            new_embed = discord.Embed.from_dict(self.embed.to_dict())
            
            # Add footer to indicate who shared it
            existing_footer = new_embed.footer.text if new_embed.footer else ""
            new_embed.set_footer(text=f"Shared by {interaction.user.display_name} • {existing_footer}")
            
            # Create share message based on command type
            share_messages = {
                "findroute": "shared route search results",
                "random": "shared a random Zwift route",
                "stats": "shared Zwift route statistics",
                "worldroutes": "shared routes from a Zwift world"
            }
            share_message = share_messages.get(self.command_type, "shared Zwift information")
            
            # Send to channel
            await interaction.channel.send(
                content=f"{interaction.user.mention} {share_message}:",
                embed=new_embed,
                files=new_files if new_files else None
            )
            
            # Confirm to user
            await interaction.response.send_message("Shared to channel!", ephemeral=True)

    # ==========================================
    # Helper Function for Sending Ephemeral Responses
    # ==========================================
    
    async def send_ephemeral_response(self, interaction, embed, files=None, command_type="route"):
        """
        Send an ephemeral response with a share button
        
        Args:
            interaction: The Discord interaction
            embed: The embed to send
            files: List of discord.File objects
            command_type: Type of command for customizing share message
        """
        # Create view with share button
        view = ShareButtonView(embed, files, command_type)
        
        # Send the response
        await interaction.followup.send(
            embed=embed,
            files=files if files else None,
            view=view,
            ephemeral=True
        )
 
 # ==========================================
    # Route Cache System
    # ==========================================
    # Features:
    # - Fetches and stores detailed route information from ZwiftInsider
    # - Persists data across container restarts using volume mounts
    # - Automatically refreshes cache when it becomes outdated
    # - Enables fast filtering for enhanced bot commands
    # ==========================================



    async def load_or_update_route_cache(self):
        """Load existing route cache or create a new one if needed"""
        try:
            if os.path.exists(self.CACHE_FILE):
                # Check if cache is recent
                cache_age = time.time() - os.path.getmtime(self.CACHE_FILE)
                if cache_age < self.CACHE_AGE_DAYS * 24 * 60 * 60:
                    with open(self.CACHE_FILE, 'r', encoding='utf-8') as f:
                        route_cache = json.load(f)
                        logger.info(f"Loaded cache with {len(route_cache)} routes")
                        return route_cache
                else:
                    logger.info(f"Cache is {cache_age/86400:.1f} days old, refreshing...")
            else:
                logger.info("No cache file found, creating new cache...")
            
            # Create a new cache
            return await self.cache_route_details()
            
        except Exception as e:
            logger.error(f"Error loading route cache: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}

    async def cache_route_details(self):
        """Fetch and cache detailed route information from ZwiftInsider"""
        logger.info("Starting route data cache update...")
        
        # Create a cache dictionary
        route_cache = {}
        
        # Counter for progress tracking
        total_routes = len(zwift_routes)
        processed = 0
        
        # Use aiohttp for parallel requests
        async with aiohttp.ClientSession() as session:
            # Create tasks for all routes (with rate limiting)
            tasks = []
            for route in zwift_routes:
                # Avoid overloading the server
                if processed > 0 and processed % 5 == 0:
                    await asyncio.sleep(2)  # Sleep between batches
                
                task = asyncio.create_task(self.fetch_route_details(session, route))
                tasks.append(task)
                processed += 1
                
                # Log progress
                if processed % 10 == 0:
                    logger.info(f"Created tasks for {processed}/{total_routes} routes")
            
            # Wait for all tasks to complete
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            for route_data in results:
                if isinstance(route_data, Exception):
                    logger.error(f"Error fetching route data: {route_data}")
                    continue
                    
                if route_data and 'route_name' in route_data:
                    route_cache[route_data['route_name']] = route_data
        
        # Save cache to file
        try:
            with open(self.CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(route_cache, f, indent=2)
            logger.info(f"Successfully cached details for {len(route_cache)} routes")
        except Exception as e:
            logger.error(f"Error saving route cache: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
        return route_cache
        
    async def fetch_route_details(self, session, route):
        """Fetch detailed information for a single route including time estimates"""
        try:
            route_name = route['Route']
            url = route['URL']
            
            logger.info(f"Fetching details for {route_name}")
            
            async with session.get(url, timeout=15) as response:
                if response.status != 200:
                    logger.error(f"Error {response.status} fetching {url}")
                    return None
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                # Extract relevant information
                route_data = {
                    'route_name': route_name,
                    'url': url,
                    'world': get_world_for_route(route_name),
                    'last_updated': datetime.datetime.now().strftime("%Y-%m-%d")
                }
                
                # Find distance and elevation
                distance_km = None
                distance_miles = None
                elevation_m = None
                elevation_ft = None
                
                # Try to extract lead-in distance
                lead_in_km = 0
                
                for p in soup.find_all('p'):
                    text = p.get_text().lower()
                    
                    # Check for distance information
                    if 'distance:' in text:
                        distance_text = text.split('distance:')[1].strip().split('\n')[0]
                        
                        # Extract km value
                        km_match = re.search(r'(\d+\.?\d*)\s*km', distance_text)
                        if km_match:
                            distance_km = float(km_match.group(1))
                        
                        # Extract miles value
                        miles_match = re.search(r'(\d+\.?\d*)\s*mi', distance_text)
                        if miles_match:
                            distance_miles = float(miles_match.group(1))
                            
                        # If only one unit is found, calculate the other
                        if distance_km and not distance_miles:
                            distance_miles = round(distance_km * 0.621371, 1)
                        elif distance_miles and not distance_km:
                            distance_km = round(distance_miles * 1.60934, 1)
                    
                    # Check for elevation information
                    if 'elevation:' in text or 'climbing:' in text:
                        elev_key = 'elevation:' if 'elevation:' in text else 'climbing:'
                        elev_text = text.split(elev_key)[1].strip().split('\n')[0]
                        
                        # Extract meters value
                        m_match = re.search(r'(\d+\.?\d*)\s*m', elev_text)
                        if m_match:
                            elevation_m = float(m_match.group(1))
                        
                        # Extract feet value
                        ft_match = re.search(r'(\d+\.?\d*)\s*ft', elev_text)
                        if ft_match:
                            elevation_ft = float(ft_match.group(1))
                            
                        # If only one unit is found, calculate the other
                        if elevation_m and not elevation_ft:
                            elevation_ft = round(elevation_m * 3.28084, 1)
                        elif elevation_ft and not elevation_m:
                            elevation_m = round(elevation_ft * 0.3048, 1)
                    
                    # Check for lead-in information
                    lead_in_match = re.search(r'lead-in:?\s*(\d+\.?\d*)\s*km', text, re.IGNORECASE)
                    if lead_in_match:
                        lead_in_km = float(lead_in_match.group(1))
                
                # Add extracted data to route_data
                if distance_km:
                    route_data['distance_km'] = distance_km
                if distance_miles:
                    route_data['distance_miles'] = distance_miles
                if elevation_m:
                    route_data['elevation_m'] = elevation_m
                if elevation_ft:
                    route_data['elevation_ft'] = elevation_ft
                if lead_in_km:
                    route_data['lead_in_km'] = lead_in_km
                
                # Extract time estimates from ZwiftInsider table - just for stats display
                time_estimates = {}
                
                # Look for the time estimate table
                tables = soup.find_all('table')
                for table in tables:
                    # Check if it's the time estimate table
                    headers = table.find_all('th')
                    header_text = ' '.join([h.get_text().strip().lower() for h in headers])
                    
                    if 'time' in header_text and ('experience' in header_text or 'level' in header_text):
                        # This is likely the time estimate table
                        rows = table.find_all('tr')
                        
                        for row in rows[1:]:  # Skip header row
                            cols = row.find_all(['td', 'th'])
                            if len(cols) >= 2:
                                level = cols[0].get_text().strip()
                                time_text = cols[1].get_text().strip()
                                
                                # Extract hours and minutes from time format (e.g., "1:15:00" or "32:30")
                                time_parts = time_text.split(':')
                                minutes = 0
                                
                                if len(time_parts) == 3:  # HH:MM:SS format
                                    minutes = int(time_parts[0]) * 60 + int(time_parts[1])
                                elif len(time_parts) == 2:  # MM:SS format
                                    minutes = int(time_parts[0])
                                
                                if level.lower() in ['a', 'a+', 'b', 'c', 'd', 'e']:
                                    time_estimates[level.upper()] = minutes
                
                # Add time estimates if found
                if time_estimates:
                    route_data['time_estimates'] = time_estimates
                    logger.info(f"Found time estimates for {route_name}: {time_estimates}")
                
                # Calculate route badges/type
                badges = []
                
                # Check if route exists and has distance/elevation data
                if distance_km and elevation_m:
                    # Calculate elevation per km
                    elev_per_km = elevation_m / distance_km
                    
                    # Determine if route is flat, mixed, or hilly
                    if elev_per_km < 8:
                        badges.append("Flat")
                    elif elev_per_km < 15:
                        badges.append("Mixed")
                    else:
                        badges.append("Hilly")
                    
                    # Determine if route is short, medium, or long
                    if distance_km < 15:
                        badges.append("Short")
                    elif distance_km < 30:
                        badges.append("Medium")
                    else:
                        badges.append("Long")
                    
                    # Check if route is epic (over 40km or over 400m climbing)
                    if distance_km > 40 or elevation_m > 400:
                        badges.append("Epic")
                    
                    # Use B category time if available or use a rough estimate
                    if 'time_estimates' in route_data and 'B' in route_data['time_estimates']:
                        route_data['estimated_time_min'] = route_data['time_estimates']['B']
                    else:
                        # Fallback calculation
                        speed = 30  # Average B rider speed in km/h
                        
                        # Adjust for elevation - reduce speed by 1 km/h per 100m of climbing per 10km
                        elevation_factor = 1.0
                        elev_per_10km = (elevation_m / distance_km) * 10
                        elevation_factor = max(0.7, 1.0 - (elev_per_10km / 100) * 0.1)
                        
                        adjusted_speed = speed * elevation_factor
                        time_hours = distance_km / adjusted_speed
                        route_data['estimated_time_min'] = round(time_hours * 60)
                
                route_data['badges'] = badges
                
                return route_data
                
        except Exception as e:
            logger.error(f"Error processing {route.get('Route', 'unknown')}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    async def periodic_cache_update(self):
        """Periodically update the route cache"""
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                # Sleep for 24 hours
                await asyncio.sleep(24 * 60 * 60)
                
                # Check if cache needs update
                if os.path.exists(self.CACHE_FILE):
                    cache_age = time.time() - os.path.getmtime(self.CACHE_FILE)
                    if cache_age > self.CACHE_AGE_DAYS * 24 * 60 * 60:
                        logger.info("Starting scheduled cache update...")
                        self.route_cache = await self.cache_route_details()
                        logger.info(f"Cache updated with {len(self.route_cache)} routes")
            except Exception as e:
                logger.error(f"Error in periodic cache update: {e}")
                import traceback
                logger.error(traceback.format_exc())
                await asyncio.sleep(60)  # Short sleep on error before retry
                

                    
                    



    async def check_rate_limit(self, user_id):
        """Check and enforce rate limits"""
        async with self.rate_limit_lock:
            now = time.time()
            if user_id in self.command_cooldowns:
                time_since_last = now - self.command_cooldowns[user_id]
                if time_since_last < self.USER_COOLDOWN:
                    wait_time = self.USER_COOLDOWN - time_since_last
                    raise HTTPException(response=discord.WebhookMessage, 
                                     message=f"Please wait {wait_time:.1f} seconds before trying again.")
                                     
                                     
    

# ==========================================
    # Updated Route Command Implementation
    # ==========================================
    # Features:
    # - Fixed image display issues with proper path handling
    # - Removed bold formatting from World field
    # - Improved file attachment logic
    # - Enhanced error handling for image processing
    # - Fixed Discord embed structure
    # ==========================================

    async def route(self, interaction: discord.Interaction, name: str):
        """Handle the /route command with both profile and map images"""
        if not interaction.user:
            return
            
        try:
            logger.info(f"Route command started for: {name}")
            
            # Check rate limits
            try:
                await self.check_rate_limit(interaction.user.id)
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

            # Find route and defer response
            result, alternatives = find_route(name)
            logger.info(f"Route search result: {result['Route'] if result else 'Not found'}")
            
            if not interaction.response.is_done():
                await interaction.response.defer(thinking=True)
                logger.info("Interaction deferred")
            
            # Show loading animation
            loading_message = None
            try:
                loading_message = await bike_loading_animation(interaction)
            except Exception as e:
                logger.error(f"Error in loading animation: {e}")
            
            if result:
                # Fetch route details
                stats, zwift_img_url = await fetch_route_info(result["URL"])
                logger.info(f"ZwiftInsider image URL: {zwift_img_url}")
                
                # Create embed
                embed = discord.Embed(
                    title=f"🚲 {result['Route']}",
                    url=result["URL"],
                    description="\n".join(stats) if stats else "View full route details on ZwiftInsider",
                    color=0xFC6719
                )
                logger.info("Basic embed created")
                
                # Add alternatives if any
                if alternatives:
                    similar_routes = "\n\n**Similar routes:**\n" + "\n".join(f"• {r['Route']}" for r in alternatives)
                    if embed.description:
                        embed.description += similar_routes
                    else:
                        embed.description = similar_routes
                    logger.info("Added alternatives to embed")
                
                # Setup for file attachments
                files_to_send = []
                
                # Setup for primary image (profile)
                image_source = None
                primary_image_file = None

                # 1. Try GitHub profile image (for Cyccal)
                if result.get("ImageURL") and 'github' in result["ImageURL"].lower():
                    logger.info("Using GitHub profile image")
                    embed.set_image(url=result["ImageURL"])

                    # Add Cyccal link
                    cyccal_url = f"https://cyccal.com/{result['Route'].lower().replace(' ', '-')}/"
                    embed.add_field(
                        name="Additional Resources",
                        value=f"[View on Cyccal]({cyccal_url})",
                        inline=False
                    )
                    image_source = "github"
                    logger.info(f"Added Cyccal link: {cyccal_url}")

                # 2. Try local image if no GitHub image
                elif local_path := self.get_local_svg(result["Route"]):
                    logger.info(f"Found local image: {local_path}")
                    primary_image_file, image_source = self.handle_local_image(local_path, embed)
                    if primary_image_file:
                        files_to_send.append(primary_image_file)
                        logger.info(f"Successfully added primary image to files_to_send")
                    else:
                        logger.warning(f"Failed to create image file from {local_path}")
                    logger.info(f"Primary image processed - source: {image_source}")

                # 3. Fall back to ZwiftInsider image
                elif zwift_img_url:
                    logger.info("Using ZwiftInsider web image")
                    embed.set_image(url=zwift_img_url)
                    image_source = "zwiftinsider"

                # Always try to add ZwiftHacks map
                zwifthacks_map_path = self.get_zwifthacks_map(result["Route"])
                if zwifthacks_map_path:
                    logger.info(f"Found ZwiftHacks map: {zwifthacks_map_path}")
                    map_file = self.handle_zwifthacks_map(zwifthacks_map_path)
                    if map_file:
                        files_to_send.append(map_file)
                        
                    
                        logger.info("Added ZwiftHacks map")
                    else:
                        logger.warning(f"Failed to create map file from {zwifthacks_map_path}")


                # Add thumbnail
                embed.set_thumbnail(url="https://zwiftinsider.com/wp-content/uploads/2022/12/zwift-logo.png")

                # Determine footer based on image sources
                if image_source == "github" and zwifthacks_map_path:
                    footer_text = "ZwiftGuy • Profile from Cyccal, Map from ZwiftHacks • Use /route to find routes"
                elif image_source == "zwiftinsider" and zwifthacks_map_path:
                    footer_text = "ZwiftGuy • Profile from ZwiftInsider, Map from ZwiftHacks • Use /route to find routes"
                elif image_source == "local" and zwifthacks_map_path:
                    footer_text = "ZwiftGuy • Profile from ZwiftInsider, Map from ZwiftHacks • Use /route to find routes"
                elif image_source == "svg" and zwifthacks_map_path:
                    footer_text = "ZwiftGuy • Profile from ZwiftHacks, Map from ZwiftHacks • Use /route to find routes"
                elif zwifthacks_map_path:
                    footer_text = "ZwiftGuy • Map from ZwiftHacks • Use /route to find routes"
                else:
                    footer_text = "ZwiftGuy • Use /route to find routes"
                
                embed.set_footer(text=footer_text)
                
                # Check description length
                if len(embed.description) > 4096:
                    embed.description = embed.description[:4093] + "..."
                
                # Log embed details
                logger.info(f"Embed title: {embed.title}")
                logger.info(f"Embed description length: {len(embed.description)}")
                logger.info(f"Embed has image: {embed.image is not None}")
                logger.info(f"Image source: {image_source}")
                logger.info(f"Number of files to send: {len(files_to_send)}")
                
            else:
                # Create not found embed
                suggestions = random.sample(zwift_routes, min(3, len(zwift_routes)))
                embed = discord.Embed(
                    title="❌ Route Not Found",
                    description=f"Could not find a route matching `{name}`.\n\n**Try these routes:**\n" + 
                               "\n".join(f"• {r['Route']}" for r in suggestions),
                    color=discord.Color.red()
                )
                logger.info("Created 'not found' embed")
                files_to_send = []

            # Send response and clean up loading message
            try:
                # Make sure we send files properly if they exist
                if files_to_send:
                    await interaction.followup.send(embed=embed, files=files_to_send)
                else:
                    await interaction.followup.send(embed=embed)
                logger.info("Successfully sent embed")
                
                # Delete loading animation if it exists
                if loading_message:
                    try:
                        await loading_message.delete()
                        logger.info("Deleted loading animation message")
                    except Exception as e:
                        logger.error(f"Error deleting loading animation: {e}")
            except discord.HTTPException as e:
                logger.error(f"Discord HTTP error when sending embed: {e}")
                # Try without images as fallback
                embed.set_image(url=None)
                await interaction.followup.send(embed=embed)
                
                # Try to delete loading message even if main response failed
                if loading_message:
                    try:
                        await loading_message.delete()
                    except Exception as e:
                        logger.error(f"Error deleting loading animation: {e}")
                        
        except Exception as e:
            logger.error(f"Error in route command: {e}")
            import traceback
            logger.error(traceback.format_exc())
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
            except Exception as err:
                logger.error(f"Failed to send error message: {err}")



    # ==========================================
    # Sprint Command Implementation
    # ==========================================
    async def sprint(self, interaction: discord.Interaction, name: str):
        """Handle the /sprint command"""
        if not interaction.user:
            return
        
        try:
            # Check rate limits
            try:
                await self.check_rate_limit(interaction.user.id)
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

            # Find sprint and defer response
            result, alternatives = find_sprint(name)
            
            if not interaction.response.is_done():
                await interaction.response.defer()
            
            if result:
                # Create sprint embed
                embed = discord.Embed(
                    title=f"⚡ {result['Segment']}",
                    url=result['URL'],
                    description=f"Location: {result['Location']}",
                    color=0x00FF00
                )
                
                # Add sprint details
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

                # Add alternatives if any
                if alternatives:
                    similar_sprints = "\n\n**Similar segments:**\n" + "\n".join(
                        f"• {s['Segment']} ({s['Length_m']}m, {s['Grade']}%)" 
                        for s in alternatives
                    )
                    embed.add_field(name="", value=similar_sprints, inline=False)
                
                # Add thumbnail and footer
                embed.set_thumbnail(url="https://zwiftinsider.com/wp-content/uploads/2022/12/zwift-logo.png")
                embed.set_footer(text="ZwiftGuy • Use /sprint to find segments")
            else:
                # Create not found embed
                suggestions = random.sample(zwift_sprints, min(3, len(zwift_sprints)))
                embed = discord.Embed(
                    title="❌ Sprint Not Found",
                    description=f"Could not find a sprint segment matching `{name}`.\n\n**Try these segments:**\n" + 
                               "\n".join(f"• {s['Segment']} ({s['Length_m']}m, {s['Grade']}%)" 
                                       for s in suggestions),
                    color=discord.Color.red()
                )

            # Send response
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
            except Exception as err:
                logger.error(f"Failed to send error message: {err}")

# ==========================================
    # Image Type Helper Functions
    # ==========================================
    # Features:
    # - Fixed image handling to properly identify file types
    # - Enhanced error logging for troubleshooting
    # - Added explicit file extension detection for PNG and SVG
    # - Improved return value consistency for embed integration
    # ==========================================
    
    def handle_local_image(self, local_path: str, embed: discord.Embed) -> tuple:
        """
        Handle PNG and SVG files for route images.
        Returns the file and source type for the embed.
        
        Args:
            local_path (str): Path to the image file
            embed (discord.Embed): The embed to attach the image to
            
        Returns:
            tuple: (discord.File or None, str or None) - The file object and source type
        """
        try:
            if not local_path:
                logger.warning("No local path provided to handle_local_image")
                return None, None
                
            file_lower = local_path.lower()
            logger.info(f"Handling local image: {file_lower}")
            
            # First check for actual file extensions
            if file_lower.endswith('.png'):
                logger.info("Detected PNG file by extension")
                image_file = discord.File(local_path, filename="route.png")
                embed.set_image(url="attachment://route.png")
                return image_file, "local"
                
            elif file_lower.endswith('.svg'):
                logger.info("Detected SVG file by extension")
                image_file = discord.File(local_path, filename="route.svg")
                embed.set_image(url="attachment://route.svg")
                return image_file, "svg"
            
            # Then check for naming patterns
            elif '_png' in file_lower or '/png/' in file_lower:
                logger.info("Detected PNG file by naming pattern")
                image_file = discord.File(local_path, filename="route.png")
                embed.set_image(url="attachment://route.png")
                return image_file, "local"
                
            elif '_svg' in file_lower or '/svg/' in file_lower:
                logger.info("Detected SVG file by naming pattern")
                image_file = discord.File(local_path, filename="route.svg")
                embed.set_image(url="attachment://route.svg")
                return image_file, "svg"
                
            else:
                logger.warning(f"Unable to determine file type for {local_path}")
                # Try to detect file type by reading first few bytes
                try:
                    with open(local_path, 'rb') as f:
                        header = f.read(10)
                        if header.startswith(b'<svg') or header.startswith(b'<?xml'):
                            logger.info("Detected SVG file by content")
                            image_file = discord.File(local_path, filename="route.svg")
                            embed.set_image(url="attachment://route.svg")
                            return image_file, "svg"
                        elif header.startswith(b'\x89PNG'):
                            logger.info("Detected PNG file by content")
                            image_file = discord.File(local_path, filename="route.png")
                            embed.set_image(url="attachment://route.png")
                            return image_file, "local"
                except Exception as inner_e:
                    logger.error(f"Error reading file content: {inner_e}")
                
                logger.error(f"Unsupported file type for {local_path}")
                return None, None
                
        except Exception as e:
            logger.error(f"Error handling local image: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None, None
                
                
    async def kom(self, interaction: discord.Interaction, name: str):
        """Handle the /kom command"""
        if not interaction.user:
            return
        
        try:
            try:
                await self.check_rate_limit(interaction.user.id)
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

            result, alternatives = find_kom(name)
            
            if not interaction.response.is_done():
                await interaction.response.defer()
            
            if result:
                embed = discord.Embed(
                    title=f"🏔️ {result['Segment']}",
                    url=result['URL'],
                    description=f"Location: {result['Location']}",
                    color=0xFF6B6B
                )
                
                embed.add_field(
                    name="Distance", 
                    value=f"{result['Length_km']}km ({result['Length_miles']} miles)", 
                    inline=True
                )
                embed.add_field(
                    name="Elevation", 
                    value=f"{result['Elev_Gain_m']}m ({result['Elev_Gain_ft']} ft)", 
                    inline=True
                )
                embed.add_field(
                    name="Grade", 
                    value=f"{result['Grade']}%", 
                    inline=True
                )

                if alternatives:
                    similar_koms = "\n\n**Similar segments:**\n" + "\n".join(
                        f"• {k['Segment']} ({k['Length_km']}km, {k['Grade']}%)" 
                        for k in alternatives
                    )
                    embed.add_field(name="", value=similar_koms, inline=False)
                
                embed.set_thumbnail(url="https://zwiftinsider.com/wp-content/uploads/2022/12/zwift-logo.png")
                embed.set_footer(text="ZwiftGuy • Use /kom to find KOM segments")
            else:
                suggestions = random.sample(zwift_koms, min(3, len(zwift_koms)))
                embed = discord.Embed(
                    title="❌ KOM Not Found",
                    description=f"Could not find a KOM segment matching `{name}`.\n\n**Try these segments:**\n" + 
                               "\n".join(f"• {k['Segment']} ({k['Length_km']}km, {k['Grade']}%)" 
                                       for k in suggestions),
                    color=discord.Color.red()
                )

            await interaction.followup.send(embed=embed)
                
        except Exception as e:
            logger.error(f"Error in kom command: {e}")
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
            except Exception as err:
                logger.error(f"Failed to send error message: {err}")
                
                
# ==========================================
    # Random Route Command
    # ==========================================
    # Features:
    # - Provides a randomly selected route
    # - Supports optional filters for world, type, and duration
    # - Uses route cache for quick responses
    # - Includes route images when available
    # ==========================================
    
    @app_commands.command(name="random", description="Get a random Zwift route")
    @app_commands.describe(
        world="Filter by Zwift world (e.g., Watopia, London)",
        route_type="Type of route (flat, mixed, hilly)",
        duration="Duration category (short, medium, long)"
    )
    async def random_route(self, interaction: discord.Interaction, 
                         world: str = None,
                         route_type: Literal["flat", "mixed", "hilly"] = None,
                         duration: Literal["short", "medium", "long"] = None):
        """Get a random Zwift route with optional filters (Ephemeral with share button)"""
        if not interaction.user:
            return
            
        await interaction.response.defer(thinking=True, ephemeral=True)
        loading_message = await bike_loading_animation(interaction)
        
        try:
            # Check if cache is initialized
            if not hasattr(self, 'route_cache') or not self.route_cache:
                logger.warning("Route cache not initialized, loading now...")
                self.route_cache = await self.load_or_update_route_cache()
            
            # Filter routes based on criteria
            filtered_routes = []
            
            for route_name, data in self.route_cache.items():
                # Skip routes with missing core data
                if 'distance_km' not in data or 'elevation_m' not in data:
                    continue
                    
                # World filter (case insensitive)
                if world and world.lower() not in data['world'].lower():
                    continue
                
                # Route type filter
                if route_type:
                    route_type_cap = route_type.capitalize()
                    if route_type_cap not in data.get('badges', []):
                        continue
                
                # Duration filter
                if duration:
                    duration_cap = duration.capitalize()
                    if duration_cap not in data.get('badges', []):
                        continue
                
                # All filters passed, add to results
                filtered_routes.append(data)
            
            if not filtered_routes:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="❌ No Matching Routes",
                        description="No routes match your filters. Try different criteria.",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
                
                # Delete loading animation
                if loading_message:
                    try:
                        await loading_message.delete()
                    except Exception as e:
                        logger.error(f"Error deleting loading animation: {e}")
                return
            
            # Select a random route
            selected_route = random.choice(filtered_routes)
            
            # Create response embed
            embed = discord.Embed(
                title=f"🎲 Random Route: {selected_route['route_name']}",
                url=selected_route['url'],
                description="Your randomly selected route:",
                color=0x9B59B6
            )
            
            # Format estimated time
            est_time = selected_route.get('estimated_time_min', 0)
            if est_time >= 60:
                time_str = f"{est_time // 60}h {est_time % 60}m"
            else:
                time_str = f"{est_time}m"
            
            # Add route details
            embed.add_field(
                name="Details",
                value=f"🌎 {selected_route.get('world', 'Unknown')}\n"
                      f"📏 {selected_route.get('distance_km', '?')} km "
                      f"({selected_route.get('distance_miles', '?')} mi)\n"
                      f"⛰️ {selected_route.get('elevation_m', '?')} m "
                      f"({selected_route.get('elevation_ft', '?')} ft)\n"
                      f"⏱️ Est. time: {time_str}",
                inline=False
            )
            
            # Add badges if available
            badges = selected_route.get('badges', [])
            if badges:
                embed.add_field(
                    name="Type",
                    value=", ".join(badges),
                    inline=False
                )
            
            # Setup for file attachments
            files_to_send = []
            
            # Try to get an image from original route data
            route_data = next((r for r in zwift_routes if r['Route'] == selected_route['route_name']), None)
            if route_data and route_data.get("ImageURL") and 'github' in route_data["ImageURL"].lower():
                embed.set_image(url=route_data["ImageURL"])
            else:
                # Try local image
                local_path = self.get_local_svg(selected_route['route_name'])
                if local_path:
                    image_file, _ = self.handle_local_image(local_path, embed)
                    if image_file:
                        files_to_send.append(image_file)
            
            # Always try to add ZwiftHacks map
            zwifthacks_map_path = self.get_zwifthacks_map(selected_route['route_name'])
            if zwifthacks_map_path:
                map_file = self.handle_zwifthacks_map(zwifthacks_map_path)
                if map_file:
                    files_to_send.append(map_file)
            
            # Add footer based on filters
            footer_text = "ZwiftGuy • Use /random for a surprise route"
            if world or route_type or duration:
                filter_parts = []
                if world:
                    filter_parts.append(f"World: {world}")
                if route_type:
                    filter_parts.append(f"Type: {route_type}")
                if duration:
                    filter_parts.append(f"Duration: {duration}")
                filters_text = ", ".join(filter_parts)
                footer_text += f" • Filters: {filters_text}"
            
            embed.set_footer(text=footer_text)
            
            # Send ephemeral response with share button
            await self.send_ephemeral_response(
                interaction, 
                embed, 
                files_to_send if files_to_send else None,
                command_type="random"
            )
            
        except Exception as e:
            logger.error(f"Error in random route command: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Error",
                    description="An error occurred while selecting a random route. Please try again later.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
        finally:
            # Delete loading animation
            if loading_message:
                try:
                    await loading_message.delete()
                except Exception as e:
                    logger.error(f"Error deleting loading animation: {e}")
                    
# ==========================================
    # Find Route Command
    # ==========================================
    # Features:
    # - Allows users to find routes based on various criteria
    # - Supports filtering by distance, elevation, world, and route type
    # - Uses the route cache for fast responses
    # - Presents results in an organized Discord embed with share button
    # ==========================================

    @app_commands.command(name="findroute", description="Find routes matching your criteria")
    @app_commands.describe(
        min_km="Minimum route distance in kilometers",
        max_km="Maximum route distance in kilometers",
        min_elev="Minimum elevation in meters",
        max_elev="Maximum elevation in meters",
        world="Zwift world (e.g., Watopia, London, Makuri)",
        route_type="Type of route (flat, mixed, hilly)",
        duration="Duration category (short, medium, long)"
    )
    async def findroute(self, interaction: discord.Interaction, 
                      min_km: app_commands.Range[int, 0, 100] = None, 
                      max_km: app_commands.Range[int, 0, 100] = None,
                      min_elev: app_commands.Range[int, 0, 2000] = None,
                      max_elev: app_commands.Range[int, 0, 2000] = None,
                      world: str = None,
                      route_type: Literal["flat", "mixed", "hilly"] = None,
                      duration: Literal["short", "medium", "long"] = None):
        """Find routes matching specific criteria (Ephemeral with share button)"""
        if not interaction.user:
            return
            
        # Defer response and show animation
        await interaction.response.defer(thinking=True, ephemeral=True)
        loading_message = await bike_loading_animation(interaction)
        
        try:
            # Set default values if not provided
            _min_km = min_km if min_km is not None else 0
            _max_km = max_km if max_km is not None else 999
            _min_elev = min_elev if min_elev is not None else 0
            _max_elev = max_elev if max_elev is not None else 9999
            
            # Check if cache is initialized
            if not hasattr(self, 'route_cache') or not self.route_cache:
                logger.warning("Route cache not initialized, loading now...")
                self.route_cache = await self.load_or_update_route_cache()
            
            # Filter routes based on criteria
            matching_routes = []
            
            for route_name, data in self.route_cache.items():
                # Skip routes with missing data
                if 'distance_km' not in data or 'elevation_m' not in data:
                    continue
                    
                # Apply filters
                if data['distance_km'] < _min_km:
                    continue
                if data['distance_km'] > _max_km:
                    continue
                if data['elevation_m'] < _min_elev:
                    continue
                if data['elevation_m'] > _max_elev:
                    continue
                
                # World filter (case insensitive)
                if world and world.lower() not in data['world'].lower():
                    continue
                
                # Route type filter
                if route_type:
                    route_type_cap = route_type.capitalize()
                    if route_type_cap not in data.get('badges', []):
                        continue
                
                # Duration filter
                if duration:
                    duration_cap = duration.capitalize()
                    if duration_cap not in data.get('badges', []):
                        continue
                
                # All filters passed, add to results
                matching_routes.append(data)
            
            # Create response embed
            if matching_routes:
                # Sort routes by distance
                matching_routes.sort(key=lambda x: x.get('distance_km', 0))
                
                # Create embed with filter information
                filter_desc = []
                if min_km is not None or max_km is not None:
                    distance_range = f"{_min_km if min_km is not None else 'any'}-{_max_km if max_km is not None else 'any'} km"
                    filter_desc.append(f"Distance: {distance_range}")
                
                if min_elev is not None or max_elev is not None:
                    elev_range = f"{_min_elev if min_elev is not None else 'any'}-{_max_elev if max_elev is not None else 'any'} m"
                    filter_desc.append(f"Elevation: {elev_range}")
                
                if world:
                    filter_desc.append(f"World: {world}")
                
                if route_type:
                    filter_desc.append(f"Type: {route_type}")
                    
                if duration:
                    filter_desc.append(f"Duration: {duration}")
                
                filter_text = ", ".join(filter_desc) if filter_desc else "No filters applied"
                
                embed = discord.Embed(
                    title=f"🔍 Found {len(matching_routes)} Routes",
                    description=f"Filters: {filter_text}\n\n"
                               f"Here are the top matches:",
                    color=0x3498DB
                )
                
                # Show top 5 matches
                display_count = min(5, len(matching_routes))
                for i, route in enumerate(matching_routes[:display_count]):
                    # Format estimated time
                    est_time = route.get('estimated_time_min', 0)
                    if est_time >= 60:
                        time_str = f"{est_time // 60}h {est_time % 60}m"
                    else:
                        time_str = f"{est_time}m"
                    
                    # Format badges
                    badges = route.get('badges', [])
                    badges_str = ", ".join(badges) if badges else "Unknown"
                    
                    embed.add_field(
                        name=f"{i+1}. {route['route_name']}",
                        value=f"🌎 {route.get('world', 'Unknown')}\n"
                              f"📏 {route.get('distance_km', '?')} km "
                              f"({route.get('distance_miles', '?')} mi)\n"
                              f"⛰️ {route.get('elevation_m', '?')} m "
                              f"({route.get('elevation_ft', '?')} ft)\n"
                              f"⏱️ Est. time: {time_str}\n"
                              f"🏷️ {badges_str}\n"
                              f"[View details]({route['url']})",
                        inline=False
                    )
                
                # Add note if there are more results
                if len(matching_routes) > display_count:
                    embed.set_footer(text=f"Showing top {display_count} of {len(matching_routes)} matches • Use more specific filters to narrow results")
                else:
                    embed.set_footer(text="ZwiftGuy • Use /findroute to search for routes")
                
            else:
                # No matches found
                embed = discord.Embed(
                    title="❌ No Matching Routes",
                    description="No routes match your criteria. Try broadening your search filters.",
                    color=discord.Color.red()
                )
                
                # Suggest some routes for common categories
                if world:
                    # If world was specified but no routes found, suggest some routes from that world
                    world_routes = [r for _, r in self.route_cache.items() 
                                 if 'world' in r and world.lower() in r['world'].lower()]
                    
                    if world_routes:
                        sample = random.sample(world_routes, min(3, len(world_routes)))
                        suggestions = "\n\n**Some routes in {}:**\n".format(world)
                        for route in sample:
                            suggestions += f"• {route['route_name']} ({route.get('distance_km', '?')} km, {route.get('elevation_m', '?')} m)\n"
                        embed.description += suggestions
            
            # Send the ephemeral embed with share button
            await self.send_ephemeral_response(interaction, embed, command_type="findroute")
            
        except Exception as e:
            logger.error(f"Error in findroute command: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            # Send error message
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Error",
                    description="An error occurred while searching for routes. Please try again later.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
        finally:
            # Delete loading animation
            if loading_message:
                try:
                    await loading_message.delete()
                except Exception as e:
                    logger.error(f"Error deleting loading animation: {e}")

    # ==========================================
    # Stats Command with Time Estimates
    # ==========================================
    # Features:
    # - Shows basic route statistics as before
    # - Adds time estimate information from ZwiftInsider 
    # - Includes option to select rider category
    # - Displays time-related fun facts
    # ==========================================
    
    @app_commands.command(name="stats", description="Get statistics about Zwift routes")
    @app_commands.describe(
        category="Rider category for time estimates (A/B/C/D)",
        focus="Choose which stats to highlight"
    )
    async def generate_route_stats(self, interaction: discord.Interaction, 
                        category: Literal["A", "B", "C", "D"] = "B",
                        focus: Literal["general", "distance", "climbing", "time"] = "general"):
        """Display statistics about Zwift routes with time estimates (Ephemeral with share button)"""
        if not interaction.user:
            return
            
        await interaction.response.defer(thinking=True, ephemeral=True)
        loading_message = await bike_loading_animation(interaction)
        
        try:
            # Check if cache is initialized
            if not hasattr(self, 'route_cache') or not self.route_cache:
                logger.warning("Route cache not initialized, loading now...")
                self.route_cache = await self.load_or_update_route_cache()
            
            # Filter to routes with complete data
            valid_routes = [r for r in self.route_cache.values() 
                          if 'distance_km' in r and 'elevation_m' in r]
            
            # Calculate statistics
            total_routes = len(valid_routes)
            
            if total_routes == 0:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="❌ No Route Data",
                        description="Route statistics are not available. The cache may still be building.",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
                return
            
            # World stats
            worlds = {}
            for route in valid_routes:
                world = route.get('world', 'Unknown')
                if world not in worlds:
                    worlds[world] = 0
                worlds[world] += 1
            
            # Sort worlds by route count
            sorted_worlds = sorted(worlds.items(), key=lambda x: x[1], reverse=True)
            
            # Route type stats
            route_types = {'Flat': 0, 'Mixed': 0, 'Hilly': 0}
            for route in valid_routes:
                for badge in route.get('badges', []):
                    if badge in route_types:
                        route_types[badge] += 1
            
            # Duration stats
            durations = {'Short': 0, 'Medium': 0, 'Long': 0}
            for route in valid_routes:
                for badge in route.get('badges', []):
                    if badge in durations:
                        durations[badge] += 1
            
            # Elevation stats
            elevation_data = [r['elevation_m'] for r in valid_routes]
            avg_elevation = sum(elevation_data) / len(elevation_data)
            max_elevation = max(elevation_data)
            min_elevation = min(elevation_data)
            
            # Distance stats
            distance_data = [r['distance_km'] for r in valid_routes]
            avg_distance = sum(distance_data) / len(distance_data)
            max_distance = max(distance_data)
            min_distance = min(distance_data)
            
            # Total distance and elevation
            total_distance = sum(distance_data)
            total_elevation = sum(elevation_data)
            
            # Time estimate stats for selected category
            time_data = []
            category_times = []
            routes_with_time = 0
            
            for route in valid_routes:
                if 'time_estimates' in route and category in route['time_estimates']:
                    time_min = route['time_estimates'][category]
                    category_times.append(time_min)
                    time_data.append({
                        'route': route['route_name'],
                        'time_min': time_min,
                        'distance_km': route['distance_km'],
                        'elevation_m': route['elevation_m'],
                        'world': route['world']
                    })
                    routes_with_time += 1
            
            # Calculate time stats if we have data
            time_stats = {}
            if category_times:
                avg_time = sum(category_times) / len(category_times)
                max_time = max(category_times)
                min_time = min(category_times)
                
                # Format times nicely
                format_time = lambda min: f"{min // 60}h {min % 60}m" if min >= 60 else f"{min}m"
                
                time_stats = {
                    'avg': format_time(int(avg_time)),
                    'max': format_time(max_time),
                    'min': format_time(min_time),
                    'count': len(category_times)
                }
                
                # Sort routes by time
                time_data.sort(key=lambda r: r['time_min'])
            
            # Create embed
            embed = discord.Embed(
                title=f"📊 Zwift Route Statistics",
                description=f"Stats based on {total_routes} routes with complete data",
                color=0x3498DB
            )
            
            # Change focus based on user selection
            if focus == "general" or focus == "distance":
                # Add world stats
                world_stats = "\n".join([f"{world}: {count} routes" for world, count in sorted_worlds[:5]])
                if len(sorted_worlds) > 5:
                    world_stats += f"\n+ {len(sorted_worlds) - 5} more worlds"
                embed.add_field(
                    name="Routes by World",
                    value=world_stats,
                    inline=True
                )
                
                # Add type and duration stats
                type_stats = "\n".join([f"{type_}: {count} routes" for type_, count in route_types.items()])
                duration_stats = "\n".join([f"{dur}: {count} routes" for dur, count in durations.items()])
                embed.add_field(
                    name="Routes by Type",
                    value=type_stats,
                    inline=True
                )
                embed.add_field(
                    name="Routes by Duration",
                    value=duration_stats,
                    inline=True
                )
            
            if focus == "general" or focus == "distance":
                # Add distance stats
                distance_stats = (
                    f"Total: {total_distance:.1f} km\n"
                    f"Average: {avg_distance:.1f} km\n"
                    f"Shortest: {min_distance:.1f} km\n"
                    f"Longest: {max_distance:.1f} km"
                )
                embed.add_field(
                    name="Distance Stats",
                    value=distance_stats,
                    inline=True
                )
            
            if focus == "general" or focus == "climbing":
                # Add elevation stats
                elevation_stats = (
                    f"Total: {total_elevation:.1f} m\n"
                    f"Average: {avg_elevation:.1f} m\n"
                    f"Flattest: {min_elevation:.1f} m\n"
                    f"Hilliest: {max_elevation:.1f} m"
                )
                embed.add_field(
                    name="Elevation Stats",
                    value=elevation_stats,
                    inline=True
                )
            
            # Add time estimates for selected category if available
            if focus == "general" or focus == "time":
                if time_stats:
                    time_summary = (
                        f"Routes with data: {time_stats['count']}\n"
                        f"Average: {time_stats['avg']}\n"
                        f"Shortest: {time_stats['min']}\n"
                        f"Longest: {time_stats['max']}"
                    )
                    embed.add_field(
                        name=f"Category {category} Times",
                        value=time_summary,
                        inline=True
                    )
                    
                    # Add quickest and slowest routes
                    if time_data:
                        quickest = time_data[0]
                        slowest = time_data[-1]
                        
                        time_routes = (
                            f"Quickest: {quickest['route']} "
                            f"({format_time(quickest['time_min'])})\n"
                            f"Longest: {slowest['route']} "
                            f"({format_time(slowest['time_min'])})"
                        )
                        embed.add_field(
                            name=f"Time Extremes",
                            value=time_routes,
                            inline=True
                        )
                else:
                    embed.add_field(
                        name=f"Category {category} Times",
                        value="No time data available for this category",
                        inline=True
                    )
                    
                # Add note about time estimates
                time_coverage = routes_with_time / total_routes * 100 if total_routes > 0 else 0
                time_note = (
                    f"*Note: Time estimates are from ZwiftInsider and available for "
                    f"{routes_with_time} routes ({time_coverage:.1f}% of total).*"
                )
                if focus == "time":
                    embed.description += f"\n\n{time_note}"
            
            # Add interesting stats
            if focus == "general":
                # Find routes with highest elevation/km ratio
                routes_by_gradient = sorted(valid_routes, 
                                          key=lambda r: r['elevation_m'] / r['distance_km'], 
                                          reverse=True)
                steepest_route = routes_by_gradient[0]
                steepest_gradient = steepest_route['elevation_m'] / steepest_route['distance_km']
                
                # Find longest ride time
                routes_by_time = sorted(valid_routes, 
                                      key=lambda r: r.get('estimated_time_min', 0), 
                                      reverse=True)
                longest_time_route = routes_by_time[0]
                longest_time = longest_time_route.get('estimated_time_min', 0)
                hours = longest_time // 60
                minutes = longest_time % 60
                time_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
                
                fun_facts = (
                    f"Steepest Route: {steepest_route['route_name']} "
                    f"({steepest_gradient:.1f} m/km)\n"
                    f"Longest Ride: {longest_time_route['route_name']} "
                    f"(est. {time_str})\n"
                    f"Epic Routes: {sum(1 for r in valid_routes if 'Epic' in r.get('badges', []))}"
                )
                
                embed.add_field(
                    name="Fun Facts",
                    value=fun_facts,
                    inline=False
                )
            
            # If focus is time, add more time-related information
            if focus == "time":
                # Add time duration distribution if we have the data
                if time_data:
                    # Group routes by time ranges
                    time_ranges = {
                        "< 30m": 0,
                        "30-60m": 0,
                        "1-2h": 0,
                        "2-3h": 0,
                        "> 3h": 0
                    }
                    
                    for route in time_data:
                        time_min = route['time_min']
                        if time_min < 30:
                            time_ranges["< 30m"] += 1
                        elif time_min < 60:
                            time_ranges["30-60m"] += 1
                        elif time_min < 120:
                            time_ranges["1-2h"] += 1
                        elif time_min < 180:
                            time_ranges["2-3h"] += 1
                        else:
                            time_ranges["> 3h"] += 1
                    
                    time_distribution = "\n".join([f"{range_}: {count} routes" 
                                                for range_, count in time_ranges.items() if count > 0])
                    
                    embed.add_field(
                        name=f"Time Distribution",
                        value=time_distribution,
                        inline=True
                    )
                    
                    # Calculate average times by world
                    world_times = {}
                    for route in time_data:
                        world = route['world']
                        if world not in world_times:
                            world_times[world] = []
                        world_times[world].append(route['time_min'])
                    
                    # Find average time by world
                    avg_world_times = {}
                    for world, times in world_times.items():
                        if len(times) >= 3:  # Only include worlds with enough routes
                            avg_world_times[world] = sum(times) / len(times)
                    
                    # Sort and format
                    sorted_worlds = sorted(avg_world_times.items(), key=lambda x: x[1])
                    
                    if sorted_worlds:
                        worlds_text = "\n".join([
                            f"{world}: {format_time(int(avg_time))}" 
                            for world, avg_time in sorted_worlds[:5]
                        ])
                        
                        embed.add_field(
                            name="Avg Time by World",
                            value=worlds_text,
                            inline=True
                        )
            
            # Add cache info
            cache_date = None
            if os.path.exists(self.CACHE_FILE):
                cache_mtime = os.path.getmtime(self.CACHE_FILE)
                cache_date = datetime.datetime.fromtimestamp(cache_mtime).strftime("%Y-%m-%d")
            
            footer_text = f"ZwiftGuy • Cache last updated: {cache_date or 'Unknown'} • Category {category} selected"
            embed.set_footer(text=footer_text)
            
            # Send ephemeral response with share button
            await self.send_ephemeral_response(interaction, embed, command_type="stats")
            
        except Exception as e:
            logger.error(f"Error in route stats command: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Error",
                    description="An error occurred while generating route statistics. Please try again later.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
        finally:
            # Delete loading animation
            if loading_message:
                try:
                    await loading_message.delete()
                except Exception as e:
                    logger.error(f"Error deleting loading animation: {e}")

    # ==========================================
    # World Routes Command
    # ==========================================
    # Features:
    # - Lists all routes in a specific Zwift world
    # - Organizes routes by length or elevation
    # - Uses the route cache for complete information
    # - Displays results in an organized format with share button
    # ==========================================
    
    @app_commands.command(name="worldroutes", description="List all routes in a specific Zwift world")
    @app_commands.describe(
        world="Zwift world to show routes for",
        sort_by="How to sort the routes"
    )
    async def world_routes(self, interaction: discord.Interaction, 
                         world: str,
                         sort_by: Literal["distance", "elevation", "name"] = "distance"):
        """List all routes in a specific Zwift world (Ephemeral with share button)"""
        if not interaction.user:
            return
            
        await interaction.response.defer(thinking=True, ephemeral=True)
        loading_message = await bike_loading_animation(interaction)
        
        try:
            # Check if cache is initialized
            if not hasattr(self, 'route_cache') or not self.route_cache:
                logger.warning("Route cache not initialized, loading now...")
                self.route_cache = await self.load_or_update_route_cache()
            
            # Filter routes by world (case-insensitive partial match)
            world_routes = []
            for route_data in self.route_cache.values():
                route_world = route_data.get('world', '')
                if world.lower() in route_world.lower():
                    world_routes.append(route_data)
            
            if not world_routes:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="❌ World Not Found",
                        description=f"Could not find routes for world '{world}'.\n\n"
                                  f"Try one of these: Watopia, London, New York, Paris, France, "
                                  f"Innsbruck, Yorkshire, Makuri, Scotland, Richmond",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
                return
            
            # Get proper world name from first result
            proper_world = world_routes[0]['world']
            
            # Sort the routes
            if sort_by == "distance":
                world_routes.sort(key=lambda r: r.get('distance_km', 0))
                sort_text = "by distance (shortest to longest)"
            elif sort_by == "elevation":
                world_routes.sort(key=lambda r: r.get('elevation_m', 0))
                sort_text = "by elevation (flattest to hilliest)"
            else:  # name
                world_routes.sort(key=lambda r: r['route_name'])
                sort_text = "alphabetically"
            
            # Create embed
            embed = discord.Embed(
                title=f"🌍 Routes in {proper_world}",
                description=f"Found {len(world_routes)} routes in {proper_world}, sorted {sort_text}:",
                color=0x3498DB
            )
            
            # Create route list with details
            # Discord has a 1024 character limit per field and 6000 overall
            route_entries = []
            
            for route in world_routes:
                # Format entry
                entry = (
                    f"**{route['route_name']}**\n"
                    f"📏 {route.get('distance_km', '?')} km • "
                    f"⛰️ {route.get('elevation_m', '?')} m • "
                )
                
                # Add badges if available
                badges = route.get('badges', [])
                if badges:
                    entry += f"🏷️ {', '.join(badges)}\n"
                else:
                    entry += "\n"
                
                route_entries.append(entry)
            
            # Split into chunks for fields (roughly 5 routes per field)
            chunks = []
            current_chunk = ""
            
            for entry in route_entries:
                if len(current_chunk) + len(entry) > 1000:  # Leave some margin
                    chunks.append(current_chunk)
                    current_chunk = entry
                else:
                    current_chunk += entry
                    
            if current_chunk:
                chunks.append(current_chunk)
            
            # Add fields
            for i, chunk in enumerate(chunks):
                field_name = f"Routes {i+1}/{len(chunks)}" if len(chunks) > 1 else "Routes"
                embed.add_field(
                    name=field_name,
                    value=chunk,
                    inline=False
                )
            
            # Add footer with sorting options
            embed.set_footer(
                text=f"ZwiftGuy • Use /worldroutes with sort_by parameter to change sorting"
            )
            
            # Send ephemeral response with share button
            await self.send_ephemeral_response(interaction, embed, command_type="worldroutes")
            
        except Exception as e:
            logger.error(f"Error in world routes command: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Error",
                    description="An error occurred while listing world routes. Please try again later.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
        finally:
            # Delete loading animation
            if loading_message:
                try:
                    await loading_message.delete()
                except Exception as e:
                    logger.error(f"Error deleting loading animation: {e}")


# ==========================================
    # Cache Info Command
    # ==========================================
    # Features:
    # - Shows information about the route cache
    # - Displays cache status, coverage, and missing data
    # - Admin-only command for monitoring
    # ==========================================
    
    @app_commands.command(name="cacheinfo", description="Show information about the route cache")
    async def cache_info(self, interaction: discord.Interaction):
        """Display information about the route cache (Admin only)"""
        if not interaction.user:
            return
        
        # Check if user is admin - adjust IDs as needed
        ADMIN_IDS = [182621539539025920]  # Replace with actual admin IDs
        is_admin = interaction.user.id in ADMIN_IDS
        
        if not is_admin:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="⛔ Permission Denied",
                    description="This command is only available to bot administrators.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return
            
        await interaction.response.defer(thinking=True, ephemeral=True)
        
        try:
            # Check cache file status
            cache_status = "Not Found"
            cache_size = "0 KB"
            cache_date = "Never"
            
            if os.path.exists(self.CACHE_FILE):
                # Get file stats
                cache_stats = os.stat(self.CACHE_FILE)
                cache_size = f"{cache_stats.st_size / 1024:.1f} KB"
                cache_date = datetime.datetime.fromtimestamp(cache_stats.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                cache_status = "Found"
            
            # Check cache in memory
            memory_cache_size = 0
            route_count = 0
            complete_routes = 0
            incomplete_routes = 0
            missing_fields = {}
            
            if hasattr(self, 'route_cache') and self.route_cache:
                route_count = len(self.route_cache)
                
                # Check for data completeness
                required_fields = ['route_name', 'url', 'world', 'distance_km', 'elevation_m']
                
                for route_name, data in self.route_cache.items():
                    missing = [field for field in required_fields if field not in data]
                    
                    if missing:
                        incomplete_routes += 1
                        # Track which fields are most commonly missing
                        for field in missing:
                            missing_fields[field] = missing_fields.get(field, 0) + 1
                    else:
                        complete_routes += 1
                        
                # Estimate memory usage (rough approximation)
                import sys
                memory_cache_size = sys.getsizeof(str(self.route_cache)) / 1024  # KB
                
            # Create embed
            embed = discord.Embed(
                title="🔍 Route Cache Information",
                description="Status of the route cache system",
                color=0x3498DB
            )
            
            # Add file info
            embed.add_field(
                name="Cache File",
                value=f"Status: {cache_status}\n"
                      f"Size: {cache_size}\n"
                      f"Last Updated: {cache_date}",
                inline=True
            )
            
            # Add memory cache info
            embed.add_field(
                name="Memory Cache",
                value=f"Routes: {route_count}\n"
                      f"Complete: {complete_routes}\n"
                      f"Incomplete: {incomplete_routes}\n"
                      f"Size: {memory_cache_size:.1f} KB",
                inline=True
            )
            
            # Add data quality info
            coverage = f"{complete_routes / max(1, route_count) * 100:.1f}%" if route_count > 0 else "N/A"
            
            missing_fields_info = "\n".join([f"{field}: {count}" for field, count in 
                                          sorted(missing_fields.items(), key=lambda x: x[1], reverse=True)])
            if not missing_fields_info:
                missing_fields_info = "None"
                
            embed.add_field(
                name="Data Quality",
                value=f"Coverage: {coverage}\n"
                      f"Missing Fields:\n{missing_fields_info}",
                inline=False
            )
            
            # Add cache directory info
            cache_dir_status = "Not Found"
            cache_dir_contents = "Empty"
            
            if os.path.exists(self.CACHE_DIR):
                cache_dir_status = "Found"
                dir_contents = os.listdir(self.CACHE_DIR)
                if dir_contents:
                    cache_dir_contents = ", ".join(dir_contents[:5])
                    if len(dir_contents) > 5:
                        cache_dir_contents += f"... (+{len(dir_contents) - 5} more)"
                else:
                    cache_dir_contents = "Empty"
            
            embed.add_field(
                name="Cache Directory",
                value=f"Path: {self.CACHE_DIR}\n"
                      f"Status: {cache_dir_status}\n"
                      f"Contents: {cache_dir_contents}",
                inline=False
            )
            
            # Add time estimate info
            time_estimate_count = sum(1 for _, data in self.route_cache.items() 
                                   if 'time_estimates' in data and data['time_estimates'])
            
            time_coverage = f"{time_estimate_count / max(1, route_count) * 100:.1f}%" if route_count > 0 else "N/A"
            
            # Count available categories
            categories = {'A': 0, 'B': 0, 'C': 0, 'D': 0}
            for _, data in self.route_cache.items():
                if 'time_estimates' in data:
                    for cat in categories.keys():
                        if cat in data['time_estimates']:
                            categories[cat] += 1
            
            categories_info = "\n".join([f"{cat}: {count} routes" for cat, count in categories.items() if count > 0])
            if not categories_info:
                categories_info = "None"
            
            embed.add_field(
                name="Time Estimates",
                value=f"Routes with times: {time_estimate_count}\n"
                      f"Coverage: {time_coverage}\n"
                      f"Available Categories:\n{categories_info}",
                inline=False
            )
            
            # Add system info
            embed.set_footer(text=f"ZwiftGuy • Cache System • Admin View")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error in cache info command: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Error",
                    description="An error occurred while retrieving cache information.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
                
# ==========================================
# Setup Hook Method
# ==========================================
# Features:
# - Registers all commands using basic implementation
# - Initializes the route cache for data access
# - Starts periodic cache update background task
# ==========================================

    async def setup_hook(self):
        """Initialize command tree and cache when bot starts up"""
        # Store the instance as a local variable to ensure proper method resolution
        bot_instance = self
        
        # Route command
        @self.tree.command(name="route", description="Get a Zwift route URL by name")
        async def route_command(interaction, name: str):
            await bot_instance.route(interaction, name)
        
        # Sprint command
        @self.tree.command(name="sprint", description="Get information about a Zwift sprint segment")
        async def sprint_command(interaction, name: str):
            await bot_instance.sprint(interaction, name)
        
        # KOM command
        @self.tree.command(name="kom", description="Get information about a Zwift KOM segment")
        async def kom_command(interaction, name: str):
            await bot_instance.kom(interaction, name)
        
        # Find route command
        @self.tree.command(name="findroute", description="Find routes matching your criteria")
        async def findroute_command(
            interaction, 
            min_km: int = None, 
            max_km: int = None, 
            min_elev: int = None, 
            max_elev: int = None, 
            world: str = None, 
            route_type: str = None, 
            duration: str = None
        ):
            await bot_instance.findroute(interaction, min_km, max_km, min_elev, max_elev, world, route_type, duration)
        
        # Random route command
        @self.tree.command(name="random", description="Get a random Zwift route")
        async def random_command(
            interaction, 
            world: str = None, 
            route_type: str = None, 
            duration: str = None
        ):
            await bot_instance.random_route(interaction, world, route_type, duration)
        
        # Stats command - use the instance variable to ensure proper method resolution
        @self.tree.command(name="stats", description="Get statistics about Zwift routes")
        async def stats_command(
            interaction, 
            category: str = "B", 
            focus: str = "general"
        ):
            # Call the correct method - generate_route_stats instead of route_stats
            await bot_instance.generate_route_stats(interaction, category, focus)
        
        # World routes command
        @self.tree.command(name="worldroutes", description="List all routes in a specific Zwift world")
        async def worldroutes_command(
            interaction, 
            world: str, 
            sort_by: str = "distance"
        ):
            await bot_instance.world_routes(interaction, world, sort_by)
        
        # Cache info command
        @self.tree.command(name="cacheinfo", description="Show information about the route cache")
        async def cacheinfo_command(interaction):
            await bot_instance.cache_info(interaction)

        # Sync the command tree
        await self.tree.sync()

        # Initialize route cache
        logger.info("Initializing route cache...")
        os.makedirs(self.CACHE_DIR, exist_ok=True)
        self.route_cache = await self.load_or_update_route_cache()
        logger.info(f"Route cache initialized with {len(self.route_cache)} routes")
        self.bg_task = self.loop.create_task(self.periodic_cache_update())
               


# ==========================================
# Main Program
# ==========================================
def main():
    """Main program loop with retry logic"""
    retries = 0
    max_retries = 5
    
    while retries < max_retries:
        try:
            logger.info("Starting bot...")
            client.run(TOKEN)
            return  # Successfully ran, exit the function
        except Exception as e:
            retries += 1
            logger.error(f"Main program error (attempt {retries}/{max_retries}): {e}")
            if retries < max_retries:
                wait_time = min(300, 5 * (2 ** retries))
                logger.info(f"Waiting {wait_time} seconds before retry...")
                try:
                    time.sleep(wait_time)
                except KeyboardInterrupt:
                    logger.info("Shutdown requested")
                    return
            else:
                logger.critical("Max retries reached, shutting down")
                return

if __name__ == "__main__":
    try:
        client = ZwiftBot()
        main()
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        logger.info("Bot shutdown complete")

