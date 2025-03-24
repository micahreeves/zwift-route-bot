"""
ZwiftRouteBot - Discord Bot for Zwift Routes
-------------------------------------------
A Discord bot that provides information about Zwift routes, segments, and more.
Allows users to search for routes, find KOMs/sprints, and view route details.

Part 1: Initial Setup, Imports, and Utility Functions
"""

# ==========================================
# Imports and Dependencies
# ==========================================
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
from typing import Literal, Optional, List, Dict, Tuple, Any, Union

# ==========================================
# Configure Logging
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==========================================
# Load Environment Variables and Data Files
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
# Core Utility Functions
# ==========================================

def normalize_route_name(name):
    """
    Remove special characters and standardize the name for matching purposes.
    
    Args:
        name: The route name to normalize
        
    Returns:
        Normalized string with only alphanumeric characters and spaces
    """
    return ''.join(c.lower() for c in name if c.isalnum() or c.isspace())

def get_world_for_route(route_name):
    """
    Determine the Zwift world for a given route based on name patterns.
    
    Args:
        route_name: The name of the route
        
    Returns:
        The identified Zwift world name
    """
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
# User Interface Helpers
# ==========================================

async def bike_loading_animation(interaction):
    """
    Create a bike riding animation in Discord embed.
    
    Args:
        interaction: The Discord interaction
        
    Returns:
        The animation message if successful, None if error
    """
    track_length = 20  # How long the "track" is
    bike = "🚲"
    track = "═"
    loading_titles = ["Finding route...", "Calculating distance...", "Checking traffic...", "Almost there!"]
    
    try:
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
    except Exception as e:
        logger.error(f"Error in loading animation: {e}")
        return None

# ==========================================
# Data Finding Functions
# ==========================================

def find_route(search_term):
    """
    Find a route using fuzzy matching.
    
    Args:
        search_term: The search query
        
    Returns:
        tuple: (matched_route, alternative_routes)
            matched_route: The best matching route or None
            alternative_routes: List of other potential matches
    """
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
    """
    Find a sprint segment using fuzzy matching.
    
    Args:
        search_term: The search query
        
    Returns:
        tuple: (matched_sprint, alternative_sprints)
    """
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
    """
    Find a KOM using fuzzy matching.
    
    Args:
        search_term: The search query
        
    Returns:
        tuple: (matched_kom, alternative_koms)
    """
    if not search_term or not zwift_koms:
        return None, []
    
    normalized_search = normalize_route_name(search_term)
    
    # Check for exact match first
    for kom in zwift_koms:
        if normalize_route_name(kom["Segment"]) == normalized_search:
            return kom, []
            
    # Check for partial matches
    matches = []
    for kom in zwift_koms:
        if normalized_search in normalize_route_name(kom["Segment"]):
            matches.append(kom)
    if matches:
        return matches[0], matches[1:3]
        
    # Try fuzzy matching if no direct matches found
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
    """
    Fetch route information from ZwiftInsider.
    
    Args:
        url: The URL of the route page
        
    Returns:
        tuple: (stats, image_url)
            stats: List of text stats about the route
            image_url: URL to route image if found
    """
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
    
"""
ZwiftRouteBot - Discord Bot for Zwift Routes
-------------------------------------------
Part 2: Image Handling Functions
"""

# ==========================================
# Image Handling Functions
# ==========================================
# Note: This section consolidates several overlapping image handling functions
# from the original code into a more streamlined design.

def find_route_images(route_name):
    """
    Find all images related to a route using robust matching strategies.
    This combines multiple image search functions into a unified approach.
    
    Args:
        route_name (str): The name of the route to find images for
        
    Returns:
        dict: Dictionary with categorized image paths:
             - 'profile_images': List of profile image paths (ZwiftHacks)
             - 'map_images': List of map image paths (ZwiftHub)
             - 'incline_images': List of incline image paths
             - 'other_images': List of other image paths
             - 'cyccal_url': Cyccal GitHub URL if available
    """
    result = {
        "profile_images": [],  # For profile images (ZwiftHacks)
        "map_images": [],      # For map images (ZwiftHub)
        "incline_images": [],  # For incline image paths
        "other_images": [],    # For any other image paths
        "cyccal_url": None     # For Cyccal GitHub URL
    }
    
    try:
        # Try to import RapidFuzz for better matching
        try:
            from rapidfuzz import process, fuzz
            have_fuzz = True
        except ImportError:
            logger.warning("RapidFuzz not installed. Using basic matching.")
            try:
                import pip
                pip.main(['install', 'rapidfuzz'])
                from rapidfuzz import process, fuzz
                logger.info("Successfully installed and imported RapidFuzz")
                have_fuzz = True
            except Exception as install_err:
                logger.error(f"Failed to install RapidFuzz: {install_err}")
                have_fuzz = False
        
        import os
        
        # Directories to check (in order of priority)
        profile_dirs = ["/app/route_images/profiles"]
        map_dirs = ["/app/route_images/maps"]
        incline_dirs = ["/app/route_images/inclines"]
        other_dirs = ["/app/route_images", "/app/data/route_images", "/app/images"]
        
        # Get clean versions of route name for matching
        clean_name = route_name.lower()
        normalized_name = normalize_route_name(route_name)
        words = [w for w in route_name.lower().split() if len(w) > 2]
        
        logger.info(f"Finding images for route: {route_name}")
        logger.info(f"Clean name: {clean_name}")
        logger.info(f"Normalized name: {normalized_name}")
        logger.info(f"Key words: {words}")
        
        # Helper function to check for matches
        def check_for_matches(file, file_lower, file_norm):
            is_match = False
            match_type = ""
            
            # Strategy 1: Direct substring match
            if clean_name in file_lower or file_lower in clean_name:
                is_match = True
                match_type = "Direct substring"
            
            # Strategy 2: Normalized name match
            elif normalized_name in file_norm or file_norm in normalized_name:
                is_match = True
                match_type = "Normalized"
            
            # Strategy 3: Key words match (check if most words appear in filename)
            elif words and sum(1 for w in words if w in file_lower) >= max(1, len(words) // 2):
                is_match = True
                match_type = "Key words"
            
            # Strategy 4: Try RapidFuzz if available
            elif have_fuzz:
                score = fuzz.token_sort_ratio(clean_name, file_lower)
                if score >= 70:  # 70% similarity threshold
                    is_match = True
                    match_type = f"Fuzzy ({score}%)"
                    
            return is_match, match_type
        
        # ==========================================
        # 1. Look for profile images (ZwiftHacks)
        # ==========================================
        for directory in profile_dirs:
            if not os.path.exists(directory) or not os.path.isdir(directory):
                continue
                
            logger.info(f"Checking profile directory: {directory}")
            
            all_files = os.listdir(directory)
            image_files = [f for f in all_files if f.lower().endswith(('.png', '.svg', '.webp'))]
            
            # Try different matching strategies
            for file in image_files:
                file_lower = file.lower()
                file_norm = normalize_route_name(file)
                
                is_match, match_type = check_for_matches(file, file_lower, file_norm)
                
                if is_match:
                    file_path = os.path.join(directory, file)
                    result["profile_images"].append(file_path)
                    logger.info(f"Found profile image: {file_path} (Match: {match_type})")
        
        # ==========================================
        # 2. Look for map images (ZwiftHub)
        # ==========================================
        for directory in map_dirs:
            if not os.path.exists(directory) or not os.path.isdir(directory):
                continue
                
            logger.info(f"Checking map directory: {directory}")
            
            all_files = os.listdir(directory)
            image_files = [f for f in all_files if f.lower().endswith(('.png', '.svg', '.webp'))]
            
            # Use the same matching strategies
            for file in image_files:
                file_lower = file.lower()
                file_norm = normalize_route_name(file)
                
                is_match, match_type = check_for_matches(file, file_lower, file_norm)
                
                if is_match:
                    file_path = os.path.join(directory, file)
                    result["map_images"].append(file_path)
                    logger.info(f"Found map image: {file_path} (Match: {match_type})")
        
        # ==========================================
        # 3. Look for incline images
        # ==========================================
        for directory in incline_dirs:
            if not os.path.exists(directory) or not os.path.isdir(directory):
                continue
                
            logger.info(f"Checking incline directory: {directory}")
            
            all_files = os.listdir(directory)
            image_files = [f for f in all_files if f.lower().endswith(('.png', '.svg', '.webp'))]
            
            # Use the same matching strategies
            for file in image_files:
                file_lower = file.lower()
                file_norm = normalize_route_name(file)
                
                is_match, match_type = check_for_matches(file, file_lower, file_norm)
                
                if is_match:
                    file_path = os.path.join(directory, file)
                    result["incline_images"].append(file_path)
                    logger.info(f"Found incline image: {file_path} (Match: {match_type})")
        
        # ==========================================
        # 4. Look for other images in fallback directories
        # ==========================================
        for directory in other_dirs:
            if not os.path.exists(directory) or not os.path.isdir(directory):
                continue
                
            logger.info(f"Checking other directory: {directory}")
            
            all_files = os.listdir(directory)
            image_files = [f for f in all_files if f.lower().endswith(('.png', '.svg', '.webp'))]
            
            # Use same matching strategies
            for file in image_files:
                file_lower = file.lower()
                file_norm = normalize_route_name(file)
                
                is_match, match_type = check_for_matches(file, file_lower, file_norm)
                
                if is_match:
                    file_path = os.path.join(directory, file)
                    
                    # Skip if this file is already in profile, map or incline images to avoid duplicates
                    if (file_path in result["profile_images"] or 
                        file_path in result["map_images"] or
                        file_path in result["incline_images"]):
                        continue
                        
                    result["other_images"].append(file_path)
                    logger.info(f"Found other image: {file_path} (Match: {match_type})")
        
        # ==========================================
        # 5. Check for Cyccal URL from the original route data
        # ==========================================
        try:
            original_route = next((r for r in zwift_routes if r['Route'] == route_name), None)
            if original_route and original_route.get("ImageURL") and 'github' in original_route.get("ImageURL", "").lower():
                result["cyccal_url"] = original_route.get("ImageURL")
                logger.info(f"Found Cyccal URL: {result['cyccal_url']}")
        except Exception as cyccal_err:
            logger.error(f"Error finding Cyccal URL: {cyccal_err}")
        
        # Return the collected images
        logger.info(f"Found {len(result['profile_images'])} profile images, "
                    f"{len(result['map_images'])} map images, "
                    f"{len(result['incline_images'])} incline images, "
                    f"{len(result['other_images'])} other images")
        return result
        
    except Exception as e:
        logger.error(f"Error in find_route_images: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return result  # Return whatever we found before the error

def handle_local_image(local_path, embed):
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

def handle_zwifthacks_map(map_path):
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
"""
ZwiftRouteBot - Discord Bot for Zwift Routes
-------------------------------------------
Part 3: UI Components and Cache System
"""

# ==========================================
# Discord UI Components
# ==========================================

class ShareButtonView(discord.ui.View):
    """
    Discord view component that adds a "Share to Channel" button to ephemeral messages.
    
    Features:
    - Allows users to share private results with the entire channel
    - Stores file data to allow sharing of attachments
    - Handles expired interaction tokens with fallback methods
    - Customizes the share message based on command type
    """
    
    def __init__(self, embed, files=None, command_type="route"):
        """
        Initialize the ShareButtonView.
        
        Args:
            embed (discord.Embed): The embed to share
            files (list, optional): List of discord.File objects
            command_type (str, optional): Type of command for customizing share message
        """
        super().__init__(timeout=300)  # 5 minute timeout (Discord interaction tokens expire after ~15 minutes)
        self.embed = embed
        self.files = files if files else []
        self.command_type = command_type
        
        # Store file data since files can only be sent once
        self.file_data = []
        for file in self.files:
            # Get file data and reset cursor
            if hasattr(file, 'fp') and file.fp:
                file.fp.seek(0)
                self.file_data.append((file.filename, file.fp.read()))
    
    @discord.ui.button(label="Share to Channel", style=discord.ButtonStyle.primary)
    async def share_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        Share the current result to the channel with improved error handling.
        
        Args:
            interaction: The Discord interaction
            button: The button that was clicked
        """
        try:
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
                "worldroutes": "shared routes from a Zwift world",
                "routestats": "shared detailed route information"
            }
            share_message = share_messages.get(self.command_type, "shared Zwift information")
            
            # Try sending with response first (for fresh interactions)
            try:
                await interaction.response.send_message(
                    content=f"{interaction.user.mention} {share_message}:",
                    embed=new_embed,
                    files=new_files if new_files else None,
                    ephemeral=False  # Make this visible to everyone
                )
                return  # If successful, we're done
            except discord.errors.NotFound as e:
                # If interaction expired (404 error), we'll try a different approach
                if "404" in str(e) or "10062" in str(e):
                    logger.info("Interaction expired, trying alternate approach for sharing")
                    # Continue to alternate method below
                else:
                    # Re-raise if it's a different NotFound error
                    raise
            
            # Alternate method: Use the channel directly
            # This is a fallback if the interaction has expired
            try:
                # We need the channel where this interaction took place
                channel = interaction.channel
                if channel:
                    # Create new files again (since the previous attempt may have consumed them)
                    channel_files = []
                    for filename, data in self.file_data:
                        channel_file = discord.File(io.BytesIO(data), filename=filename)
                        channel_files.append(channel_file)
                    
                    await channel.send(
                        content=f"{interaction.user.mention} {share_message}:",
                        embed=new_embed,
                        files=channel_files if channel_files else None
                    )
                    
                    # Disable all buttons since we've handled this share
                    for child in self.children:
                        if isinstance(child, discord.ui.Button):
                            child.disabled = True
                    
                    # Try to update the original message to show buttons as disabled
                    try:
                        await interaction.message.edit(view=self)
                    except:
                        pass
                        
                else:
                    logger.error("Could not determine channel for fallback sharing")
                    raise ValueError("Channel not available")
                    
            except Exception as channel_err:
                logger.error(f"Error in fallback channel sharing: {channel_err}")
                raise
                
        except Exception as e:
            # Log the error
            logger.error(f"Error sharing to channel: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            # Try to inform the user
            try:
                # We'll try both methods of responding, based on whether the interaction is still valid
                try:
                    await interaction.response.send_message(
                        "Error sharing to channel. The button may have expired or you might not have permission to post in this channel.",
                        ephemeral=True
                    )
                except:
                    # If the above fails, the original message might still be available
                    if hasattr(interaction, 'message') and interaction.message:
                        await interaction.message.reply(
                            "Error sharing to channel. The share button has expired. Please use the command again for a fresh response."
                        )
            except:
                # At this point, we've tried everything reasonable
                pass

# ==========================================
# Helper Function for Ephemeral Responses
# ==========================================

async def send_ephemeral_response(interaction, embed, files=None, command_type="route"):
    """
    Send an ephemeral response with a share button
    
    Args:
        interaction: The Discord interaction
        embed: The embed to send
        files: List of discord.File objects
        command_type: Type of command for customizing share message
    """
    try:
        # Ensure files is a list or None
        file_list = [] if files is None else files if isinstance(files, list) else [files]
        
        # Create view with share button
        view = ShareButtonView(embed, file_list, command_type)
        
        # Send the response
        await interaction.followup.send(
            embed=embed,
            files=file_list if file_list else None,
            view=view,
            ephemeral=True
        )
    except Exception as e:
        logger.error(f"Error in send_ephemeral_response: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
        # Try a simplified response without view or files
        try:
            await interaction.followup.send(
                embed=embed,
                ephemeral=True
            )
        except Exception as fallback_error:
            logger.error(f"Fallback response also failed: {fallback_error}")
            
            # Last resort - send a simple message
            try:
                simple_embed = discord.Embed(
                    title="Response Error",
                    description="An error occurred while formatting the response. Please try again.",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=simple_embed, ephemeral=True)
            except:
                logger.error("All response attempts failed")

# ==========================================
# Route Cache System
# ==========================================
# Fetches and stores detailed route information to provide
# enhanced functionality and improve response times.

class RouteCache:
    """
    Cache system for storing route details.
    Provides persistence across container restarts and automatic refresh.
    """
    
    def __init__(self, cache_dir="/app/data", cache_file_name="route_details_cache.json", age_days=14):
        """
        Initialize the cache system.
        
        Args:
            cache_dir: Directory to store the cache file
            cache_file_name: Name of the cache file
            age_days: Number of days before a cache refresh is triggered
        """
        self.CACHE_DIR = cache_dir
        self.CACHE_FILE = os.path.join(cache_dir, cache_file_name)
        self.CACHE_AGE_DAYS = age_days
        
        # Ensure the cache directory exists
        os.makedirs(cache_dir, exist_ok=True)
        
        # Initialize empty cache
        self.route_cache = {}
    
    async def load_or_update(self):
        """
        Load existing route cache or create a new one if needed.
        
        Returns:
            dict: The loaded or created cache
        """
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
        """
        Fetch and cache detailed route information from ZwiftInsider.
        
        Returns:
            dict: Cache of route details
        """
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
        """
        Fetch detailed information for a single route including time estimates.
        
        Args:
            session: aiohttp session
            route: Basic route info from the routes data file
            
        Returns:
            dict: Detailed route information
        """
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
                lead_in_km = 0
                
                # Process each paragraph for route data
                for p in soup.find_all(['p', 'div', 'li']):
                    text = p.get_text().lower()
                    
                    # Check for distance information first - be more specific with pattern
                    if 'distance:' in text or 'length:' in text:
                        # Extract kilometers value
                        km_match = re.search(r'(?:distance|length):\s*(\d+\.?\d*)\s*km', text, re.IGNORECASE)
                        if km_match:
                            distance_km = float(km_match.group(1))
                            logger.info(f"Found distance: {distance_km} km")
                        
                        # Extract miles value - look specifically for parenthetical pattern
                        miles_match = re.search(r'(?:distance|length):[^(]*\(\s*(\d+\.?\d*)\s*(?:mi|miles)\)', text, re.IGNORECASE)
                        if miles_match:
                            distance_miles = float(miles_match.group(1))
                            logger.info(f"Found distance: {distance_miles} miles")
                        
                        # If only one unit is found, calculate the other - with validation check
                        if distance_km and not distance_miles:
                            distance_miles = round(distance_km * 0.621371, 1)
                            logger.info(f"Calculated miles from km: {distance_miles}")
                        elif distance_miles and not distance_km:
                            distance_km = round(distance_miles * 1.60934, 1)
                            logger.info(f"Calculated km from miles: {distance_km}")
                    
                    # Now check for elevation - after distance to avoid confusion
                    if 'elevation:' in text or 'climbing:' in text:
                        # Extract meters value - explicitly look for 'm' unit
                        m_match = re.search(r'(?:elevation|climbing):\s*(\d+\.?\d*)\s*(?:m|meters)\b', text, re.IGNORECASE)
                        if m_match:
                            elevation_m = float(m_match.group(1))
                            logger.info(f"Found elevation: {elevation_m} m")
                        
                        # Extract feet value - look for ft unit or measurement symbol
                        ft_match = re.search(r'(?:elevation|climbing):[^(]*\(\s*(\d+\.?\d*)\s*(?:ft|feet|\')\)', text, re.IGNORECASE)
                        if ft_match:
                            elevation_ft = float(ft_match.group(1))
                            logger.info(f"Found elevation: {elevation_ft} feet")
                        
                        # If only one unit is found, calculate the other - with validation
                        if elevation_m and not elevation_ft:
                            elevation_ft = round(elevation_m * 3.28084, 1)
                            logger.info(f"Calculated feet from meters: {elevation_ft}")
                        elif elevation_ft and not elevation_m:
                            elevation_m = round(elevation_ft * 0.3048, 1)
                            logger.info(f"Calculated meters from feet: {elevation_m}")
                    
                    # Check for lead-in information with specific pattern
                    lead_in_match = re.search(r'(?:lead-in|lead in):\s*(\d+\.?\d*)\s*km', text, re.IGNORECASE)
                    if lead_in_match:
                        lead_in_km = float(lead_in_match.group(1))
                        logger.info(f"Found lead-in: {lead_in_km} km")
                
                # Validate the extracted values
                if distance_km:
                    # Check for reasonable distance range (0.1 - 150 km)
                    if 0.1 <= distance_km <= 150:
                        route_data['distance_km'] = distance_km
                    else:
                        logger.warning(f"Distance value out of expected range: {distance_km}km")
                        if 0.1 <= distance_km * 0.621371 <= 150:
                            logger.info("Distance might be in miles, converting")
                            distance_km = distance_km * 0.621371 * 1.60934
                            route_data['distance_km'] = distance_km
                            
                if distance_miles:
                    route_data['distance_miles'] = distance_miles
                    
                if elevation_m:
                    # Check for reasonable elevation range (0 - 3000 m)
                    if 0 <= elevation_m <= 3000:
                        route_data['elevation_m'] = elevation_m
                    else:
                        logger.warning(f"Elevation value out of expected range: {elevation_m}m")
                        if 0 <= elevation_m * 0.3048 <= 3000:
                            logger.info("Elevation might be in feet, converting")
                            elevation_m = elevation_m * 0.3048
                            route_data['elevation_m'] = elevation_m
                            
                if elevation_ft:
                    route_data['elevation_ft'] = elevation_ft
                    
                if lead_in_km:
                    route_data['lead_in_km'] = lead_in_km
                
                # Look for time estimates
                time_estimates = {}
                
                # Try to find the time estimates section
                for element in soup.find_all(['p', 'div']):
                    text = element.get_text()
                    
                    # Check if this is the time estimates section
                    if 'time estimates' in text.lower() or 'w/kg' in text.lower():
                        logger.info(f"Found potential time estimates text: {text[:100]}...")
                        
                        # Extract all wattage-based estimates
                        wkg_matches = re.findall(r'(\d+)\s*W/kg:\s*(\d+)\s*minutes', text)
                        
                        if wkg_matches:
                            for wkg, minutes in wkg_matches:
                                category = None
                                
                                # Map W/kg to rider categories based on common Zwift standards
                                wkg_float = float(wkg)
                                if wkg_float >= 4.0:
                                    category = 'A'
                                elif wkg_float >= 3.2:
                                    category = 'B'
                                elif wkg_float >= 2.5:
                                    category = 'C'
                                elif wkg_float >= 1.0:
                                    category = 'D'
                                
                                if category:
                                    time_estimates[category] = int(minutes)
                                    
                                    # Also store the raw W/kg value
                                    if 'wkg_times' not in route_data:
                                        route_data['wkg_times'] = {}
                                    route_data['wkg_times'][wkg] = int(minutes)
                                    
                                    logger.info(f"Mapped {wkg} W/kg ({minutes} min) to category {category}")
                
                # Add time estimates to route data
                if time_estimates:
                    route_data['time_estimates'] = time_estimates
                    logger.info(f"Found time estimates for {route_name}: {time_estimates}")
                
                # Calculate route badges/type
                badges = []
                
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
                    
                    # Use B category time or estimate based on speed
                    if 'time_estimates' in route_data and 'B' in route_data['time_estimates']:
                        route_data['estimated_time_min'] = route_data['time_estimates']['B']
                    else:
                        # Try to use 3 W/kg time if available (typical B rider)
                        if 'wkg_times' in route_data and '3' in route_data['wkg_times']:
                            route_data['estimated_time_min'] = route_data['wkg_times']['3']
                        else:
                            # Fallback calculation based on distance and elevation
                            speed = 30  # Average B rider speed in km/h
                            elevation_factor = max(0.7, 1.0 - ((elevation_m / distance_km) * 10 / 100) * 0.1)
                            adjusted_speed = speed * elevation_factor
                            time_hours = distance_km / adjusted_speed
                            route_data['estimated_time_min'] = round(time_hours * 60)
                
                route_data['badges'] = badges
                
                # Extract segments (sprint and KOM)
                try:
                    # Define navigation terms that indicate we've picked up the wrong content
                    navigation_terms = ['get started', 'zwift account', 'how to get started', 
                                       'course maps', 'calendar', 'exhaustive', 'tiny races']
                    
                    # First, try to isolate the main article content to avoid navigation
                    article_content = soup.find('article') or soup.find('div', class_='entry-content')
                    
                    # Find segments (sprint and KOM) and Strava segments separately
                    sprint_kom_segments = None
                    strava_segments = None
                    
                    if article_content:
                        logger.info("Found article content container, searching within it")
                        
                        # Look for segments section within article content only
                        segment_headings = article_content.find_all(['h2', 'h3', 'h4'])
                        for heading in segment_headings:
                            heading_text = heading.get_text().strip().lower()
                            
                            # Only process headings that look like segment headers
                            if ('sprint' in heading_text and ('kom' in heading_text or 'qom' in heading_text)) or \
                               ('segment' in heading_text and any(x in heading_text for x in ['sprint', 'kom', 'qom'])):
                                
                                logger.info(f"Found segment heading in article: {heading.get_text()}")
                                
                                # Find the next paragraph or list after this heading
                                next_content = None
                                current = heading.next_sibling
                                
                                # Look through next elements until we find content
                                while current and not next_content:
                                    if isinstance(current, str) and current.strip():
                                        next_content = current.strip()
                                    elif hasattr(current, 'name'):
                                        if current.name in ['p', 'ul', 'ol']:
                                            next_content = current.get_text().strip()
                                    current = current.next_sibling
                                
                                if next_content and any(x in next_content.lower() for x in ['km', 'miles', 'sprint', 'kom', '%']):
                                    sprint_kom_segments = next_content
                                    break
                    
                    # Add segments to route data
                    if sprint_kom_segments:
                        route_data['sprint_kom_segments'] = sprint_kom_segments
                        # Also keep the original 'segments' field for backward compatibility
                        if not route_data.get('segments'):
                            route_data['segments'] = sprint_kom_segments
                        
                    if strava_segments:
                        # Validate Strava segments too
                        if not any(term in strava_segments.lower() for term in navigation_terms):
                            route_data['strava_segments'] = strava_segments
                            # Append to 'segments' field if it exists, otherwise create it
                            if 'segments' in route_data:
                                route_data['segments'] += "\n\nStrava Segments:\n" + strava_segments
                            else:
                                route_data['segments'] = "Strava Segments:\n" + strava_segments
                
                except Exception as e:
                    logger.error(f"Error extracting segments for {route_name}: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                
                return route_data
                
        except Exception as e:
            logger.error(f"Error in fetch_route_details for {route.get('Route', 'unknown')}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    async def periodic_update(self, bot):
        """
        Periodically update the route cache.
        
        Args:
            bot: The Discord bot instance
        """
        await bot.wait_until_ready()
        while not bot.is_closed():
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
"""
ZwiftRouteBot - Discord Bot for Zwift Routes
-------------------------------------------
Part 4: Bot Core and Rate Limiting System
"""

# ==========================================
# Discord Bot Class Definition
# ==========================================

class ZwiftBot(discord.Client):
    """
    Main Discord bot class for handling Zwift route information and commands.
    Manages the command tree, rate limiting, and caching system.
    """
    
# ==========================================
    # ZwiftBot Initialization Method
    # ==========================================
    # Features:
    # - Initializes the Discord bot with default settings
    # - Sets up rate limiting system for commands
    # - Determines appropriate cache directory based on environment
    # - Falls back to alternative directories if primary is not writable
    # - Works in both Docker container and local development environments
    # ==========================================

    def __init__(self):
        """Initialize the ZwiftBot with default settings"""
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        
        # Rate limiting system
        self.command_cooldowns = {}  # User-specific cooldowns
        self.global_command_times = deque(maxlen=50)  # Track recent commands
        self.rate_limit_lock = asyncio.Lock()  # Lock for rate limit checking
        self.USER_COOLDOWN = 5.0  # Seconds between commands for a single user
        self.GLOBAL_RATE_LIMIT = 20  # Max commands per minute
        
        # Initialize cache with a path that works in both Docker and local environments
        import tempfile  # Add this import at the top of the file
        
        cache_path = "/app/data"  # Default for Docker
        
        # Check if the default path is writable, if not use a fallback
        if not os.access("/app", os.W_OK):
            # Try to use a local directory relative to the script
            script_dir = os.path.dirname(os.path.abspath(__file__))
            cache_path = os.path.join(script_dir, "data")
            
            # If that doesn't exist, create it
            os.makedirs(cache_path, exist_ok=True)
            
            # If we still can't write to it, fall back to temp directory
            if not os.access(cache_path, os.W_OK):
                cache_path = os.path.join(tempfile.gettempdir(), "zwift_bot_data")
                os.makedirs(cache_path, exist_ok=True)
        
        logger.info(f"Using cache directory: {cache_path}")
        
        # Initialize the route cache with the determined path
        self.route_cache = RouteCache(cache_dir=cache_path)
        
    async def setup_hook(self):
        """Initialize command tree and cache when bot starts up"""
        # Register all commands
        await self.register_commands()
        
        # Sync the command tree
        await self.tree.sync()

        # Initialize route cache
        logger.info("Initializing route cache...")
        self.cache = RouteCache()
        self.route_cache_data = await self.cache.load_or_update()
        logger.info(f"Route cache initialized with {len(self.route_cache_data)} routes")
        
        # Start background cache update task
        self.bg_task = self.loop.create_task(self.cache.periodic_update(self))
    
    async def register_commands(self):
        """Register all bot commands with the command tree"""
        # Use direct method references to avoid issues with self referencing
        route_method = self.route
        sprint_method = self.sprint
        kom_method = self.kom
        random_route_method = self.random_route
        findroute_method = self.findroute
        world_routes_method = self.world_routes
        cache_info_method = self.cache_info
        route_stats_method = self.route_stats
        refresh_cache_method = self.refresh_cache
        
        # Route command
        @self.tree.command(name="route", description="Get a Zwift route URL by name")
        async def route_command(interaction, name: str):
            await route_method(interaction, name)
        
        # Sprint command
        @self.tree.command(name="sprint", description="Get information about a Zwift sprint segment")
        async def sprint_command(interaction, name: str):
            await sprint_method(interaction, name)
        
        # KOM command
        @self.tree.command(name="kom", description="Get information about a Zwift KOM segment")
        async def kom_command(interaction, name: str):
            await kom_method(interaction, name)
        
        # Random route command
        @self.tree.command(name="random", description="Get a random Zwift route")
        @app_commands.describe(
            world="Filter by Zwift world (e.g., Watopia, London)",
            route_type="Type of route (flat, mixed, hilly)",
            duration="Duration category (short, medium, long)"
        )
        async def random_command(interaction, 
                               world: str = None,
                               route_type: Literal["flat", "mixed", "hilly"] = None,
                               duration: Literal["short", "medium", "long"] = None):
            await random_route_method(interaction, world, route_type, duration)
        
        # Find route command
        @self.tree.command(name="findroute", description="Find routes matching your criteria")
        @app_commands.describe(
            min_km="Minimum route distance in kilometers",
            max_km="Maximum route distance in kilometers",
            min_elev="Minimum elevation in meters",
            max_elev="Maximum elevation in meters",
            world="Zwift world (e.g., Watopia, London, Makuri)",
            route_type="Type of route (flat, mixed, hilly)",
            duration="Duration category (short, medium, long)"
        )
        async def findroute_command(interaction, 
                                  min_km: app_commands.Range[int, 0, 100] = None, 
                                  max_km: app_commands.Range[int, 0, 100] = None,
                                  min_elev: app_commands.Range[int, 0, 2000] = None,
                                  max_elev: app_commands.Range[int, 0, 2000] = None,
                                  world: str = None,
                                  route_type: Literal["flat", "mixed", "hilly"] = None,
                                  duration: Literal["short", "medium", "long"] = None):
            await findroute_method(interaction, min_km, max_km, min_elev, max_elev, world, route_type, duration)
        
        # Route stats command
        @self.tree.command(name="routestats", description="Get detailed statistics for a specific Zwift route")
        @app_commands.describe(
            name="Name of the Zwift route",
            category="Rider category for time estimates (A/B/C/D)"
        )
        async def routestats_command(interaction, 
                                  name: str,
                                  category: Literal["A", "B", "C", "D"] = "B"):
           await route_stats_method(interaction, name, category)
        
        # World routes command
        @self.tree.command(name="worldroutes", description="List all routes in a specific Zwift world")
        @app_commands.describe(
            world="Zwift world to show routes for",
            sort_by="How to sort the routes"
        )
        async def worldroutes_command(interaction, 
                                   world: str,
                                   sort_by: Literal["distance", "elevation", "name"] = "distance"):
            await world_routes_method(interaction, world, sort_by)
        
        # Cache info command
        @self.tree.command(name="cacheinfo", description="Show information about the route cache")
        async def cacheinfo_command(interaction):
            await cache_info_method(interaction)
            
        # Cache refresh command
        @self.tree.command(name="refreshcache", description="Force a refresh of the route cache")
        async def refreshcache_command(interaction):
            await refresh_cache_method(interaction)
    
    # ==========================================
    # Rate Limiting System
    # ==========================================
    
    async def check_rate_limit(self, user_id):
        """
        Check and enforce rate limits for commands.
        
        Args:
            user_id: The ID of the user making the request
            
        Raises:
            HTTPException: If the rate limit is exceeded
        """
        async with self.rate_limit_lock:
            now = time.time()
            
            # Check user-specific cooldown
            if user_id in self.command_cooldowns:
                time_since_last = now - self.command_cooldowns[user_id]
                if time_since_last < self.USER_COOLDOWN:
                    wait_time = self.USER_COOLDOWN - time_since_last
                    raise HTTPException(
                        response=discord.WebhookMessage, 
                        message=f"Please wait {wait_time:.1f} seconds before trying again."
                    )
            
            # Update user's last command time
            self.command_cooldowns[user_id] = now
            
            # Check global rate limit
            self.global_command_times.append(now)
            if len(self.global_command_times) >= self.GLOBAL_RATE_LIMIT:
                oldest = self.global_command_times[0]
                time_window = now - oldest
                if time_window < 60:  # If more than GLOBAL_RATE_LIMIT commands in less than 60 seconds
                    wait_time = 60 - time_window
                    raise HTTPException(
                        response=discord.WebhookMessage, 
                        message=f"Bot is experiencing high traffic. Please try again in {wait_time:.1f} seconds."
                    )
    
    # ==========================================
    # Cache Management Commands
    # ==========================================
    
    async def refresh_cache(self, interaction):
        """
        Force a refresh of the route cache (Admin only).
        
        Args:
            interaction: The Discord interaction
        """
        if not interaction.user:
            return
        
        # Check if user is admin
        ADMIN_IDS = [837025118613798945]  # Replace with actual admin IDs
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
        
        # Create a progress embed
        progress_embed = discord.Embed(
            title="🔄 Cache Refresh Started",
            description="Starting a complete refresh of the route cache...",
            color=discord.Color.blue()
        )
        progress_message = await interaction.followup.send(embed=progress_embed, ephemeral=True)
        
        try:
            # Force a cache rebuild
            start_time = time.time()
            new_cache = await self.cache.cache_route_details()
            end_time = time.time()
            
            # Update the bot's cache
            self.route_cache_data = new_cache
            
            # Calculate statistics
            elapsed_time = end_time - start_time
            routes_count = len(new_cache)
            routes_with_times = sum(1 for data in new_cache.values() if 'time_estimates' in data and data['time_estimates'])
            time_coverage = (routes_with_times / max(1, routes_count)) * 100
            
            # Update the progress message
            success_embed = discord.Embed(
                title="✅ Cache Refresh Complete",
                description=f"Successfully refreshed the route cache in {elapsed_time:.1f} seconds.\n\n"
                          f"**Stats:**\n"
                          f"• Routes: {routes_count}\n"
                          f"• Routes with time estimates: {routes_with_times} ({time_coverage:.1f}%)",
                color=discord.Color.green()
            )
            await progress_message.edit(embed=success_embed)
            
        except Exception as e:
            logger.error(f"Error in cache refresh: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            # Update with error message
            error_embed = discord.Embed(
                title="❌ Cache Refresh Failed",
                description=f"An error occurred while refreshing the cache: {str(e)}",
                color=discord.Color.red()
            )
            await progress_message.edit(embed=error_embed)
    
    async def cache_info(self, interaction):
        """
        Display information about the route cache (Admin only).
        
        Args:
            interaction: The Discord interaction
        """
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
            cache_file = self.cache.CACHE_FILE
            
            # Check cache file status
            cache_status = "Not Found"
            cache_size = "0 KB"
            cache_date = "Never"
            
            if os.path.exists(cache_file):
                # Get file stats
                cache_stats = os.stat(cache_file)
                cache_size = f"{cache_stats.st_size / 1024:.1f} KB"
                cache_date = datetime.datetime.fromtimestamp(cache_stats.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                cache_status = "Found"
            
            # Check cache in memory
            memory_cache_size = 0
            route_count = 0
            complete_routes = 0
            incomplete_routes = 0
            missing_fields = {}
            
            if self.route_cache_data:
                route_count = len(self.route_cache_data)
                
                # Check for data completeness
                required_fields = ['route_name', 'url', 'world', 'distance_km', 'elevation_m']
                
                for route_name, data in self.route_cache_data.items():
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
                memory_cache_size = sys.getsizeof(str(self.route_cache_data)) / 1024  # KB
                
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
            cache_dir = self.cache.CACHE_DIR
            cache_dir_status = "Not Found"
            cache_dir_contents = "Empty"
            
            if os.path.exists(cache_dir):
                cache_dir_status = "Found"
                dir_contents = os.listdir(cache_dir)
                if dir_contents:
                    cache_dir_contents = ", ".join(dir_contents[:5])
                    if len(dir_contents) > 5:
                        cache_dir_contents += f"... (+{len(dir_contents) - 5} more)"
                else:
                    cache_dir_contents = "Empty"
            
            embed.add_field(
                name="Cache Directory",
                value=f"Path: {cache_dir}\n"
                      f"Status: {cache_dir_status}\n"
                      f"Contents: {cache_dir_contents}",
                inline=False
            )
            
            # Add time estimate info
            time_estimate_count = sum(1 for _, data in self.route_cache_data.items() 
                                   if 'time_estimates' in data and data['time_estimates'])
            
            time_coverage = f"{time_estimate_count / max(1, route_count) * 100:.1f}%" if route_count > 0 else "N/A"
            
            # Count available categories
            categories = {'A': 0, 'B': 0, 'C': 0, 'D': 0}
            for _, data in self.route_cache_data.items():
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
    # Main Command Implementations (Route, Sprint, KOM)
    # ==========================================
    
    async def route(self, interaction, name):
        """
        Handle the /route command with both profile and map images.
        Displays information about a Zwift route by name.
        
        Args:
            interaction: The Discord interaction
            name: The name of the route to look up
        """
        if not interaction.user:
            return
            
        try:
            logger.info(f"Route command started for: {name}")
            
            # IMMEDIATE DEFER - do this first before any other processing
            # This prevents the 3-second timeout from causing problems
            try:
                await interaction.response.defer(thinking=True)
                logger.info("Interaction deferred")
            except discord.errors.NotFound:
                logger.error("Could not defer interaction - it may have expired")
                return  # Exit early if we can't defer
            except Exception as defer_error:
                logger.error(f"Error deferring interaction: {defer_error}")
            
            # Check rate limits
            try:
                await self.check_rate_limit(interaction.user.id)
            except HTTPException as e:
                logger.warning(f"Rate limit hit: {e}")
                try:
                    await interaction.followup.send(
                        embed=discord.Embed(
                            title="⏳ Rate Limited",
                            description=str(e),
                            color=discord.Color.orange()
                        ),
                        ephemeral=True
                    )
                except Exception as followup_error:
                    logger.error(f"Error sending rate limit message: {followup_error}")
                return

            # Find route
            result, alternatives = find_route(name)
            logger.info(f"Route search result: {result['Route'] if result else 'Not found'}")
            
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
                
                # Find images using the consolidated image finding function
                found_images = find_route_images(result["Route"])
                
                # Setup for file attachments
                files_to_send = []
                image_sources = []
                has_embed_image = False
                already_added_paths = set()  # Track which files we've already added
                
                # First, try to set a profile image as the primary embedded image
                if found_images['profile_images']:
                    profile_path = found_images['profile_images'][0]  # Use the first profile image
                    logger.info(f"Setting profile as primary embed image: {profile_path}")
                    profile_file, image_source = handle_local_image(profile_path, embed)
                    if profile_file:
                        files_to_send.append(profile_file)
                        image_sources.append("ZwiftHacks")
                        has_embed_image = True
                        already_added_paths.add(profile_path)
                
                # Fall back to ZwiftInsider image if no other images have been added
                if not has_embed_image and zwift_img_url:
                    logger.info("Using ZwiftInsider web image as fallback")
                    embed.set_image(url=zwift_img_url)
                    image_sources.append("ZwiftInsider")
                    has_embed_image = True
                
                # Now add ALL remaining profile images as attachments
                for i, profile_path in enumerate(found_images['profile_images']):
                    if profile_path not in already_added_paths:
                        try:
                            file_lower = profile_path.lower()
                            if file_lower.endswith('.svg'):
                                profile_file = discord.File(profile_path, filename=f"profile_{i}.svg")
                            else:
                                profile_file = discord.File(profile_path, filename=f"profile_{i}.png")
                                
                            files_to_send.append(profile_file)
                            if "ZwiftHacks" not in image_sources:
                                image_sources.append("ZwiftHacks")
                            already_added_paths.add(profile_path)
                            logger.info(f"Added additional profile image: {profile_path}")
                        except Exception as e:
                            logger.error(f"Error adding profile image: {e}")
                
                # Add ALL incline images as attachments
                for i, incline_path in enumerate(found_images['incline_images']):
                    if incline_path not in already_added_paths:
                        try:
                            file_lower = incline_path.lower()
                            if file_lower.endswith('.svg'):
                                incline_file = discord.File(incline_path, filename=f"incline_{i}.svg")
                            else:
                                incline_file = discord.File(incline_path, filename=f"incline_{i}.png")
                                
                            files_to_send.append(incline_file)
                            if "Incline" not in image_sources:
                                image_sources.append("Incline")
                            already_added_paths.add(incline_path)
                            logger.info(f"Added incline image: {incline_path}")
                        except Exception as e:
                            logger.error(f"Error adding incline image: {e}")
                
                # Add ALL map images as attachments
                for i, map_path in enumerate(found_images['map_images']):
                    if map_path not in already_added_paths:
                        try:
                            file_lower = map_path.lower()
                            if file_lower.endswith('.svg'):
                                map_file = discord.File(map_path, filename=f"map_{i}.svg")
                            else:
                                map_file = discord.File(map_path, filename=f"map_{i}.png")
                                
                            files_to_send.append(map_file)
                            if "ZwiftHub" not in image_sources:
                                image_sources.append("ZwiftHub")
                            already_added_paths.add(map_path)
                            logger.info(f"Added map image: {map_path}")
                        except Exception as e:
                            logger.error(f"Error adding map image: {e}")
                
                # Always add Cyccal link regardless of whether it exists
                if "Additional Resources" not in [field.name for field in embed.fields]:
                    route_name = result['Route'].lower().replace(' ', '-')
                    cyccal_web_url = f"https://cyccal.com/{route_name}/"
                    
                    embed.add_field(
                        name="Additional Resources",
                        value=f"[View on Cyccal]({cyccal_web_url})",
                        inline=False
                    )
                
                # Add thumbnail
                embed.set_thumbnail(url="https://zwiftinsider.com/wp-content/uploads/2022/12/zwift-logo.png")
                
                # Determine footer based on image sources
                footer_text = "ZwiftGuy"
                if image_sources:
                    sources_text = ", ".join(image_sources)
                    footer_text += f" • Images from: {sources_text}"
                footer_text += " • Use /route to find routes"
                
                embed.set_footer(text=footer_text)
                
                # Check description length
                if len(embed.description) > 4096:
                    embed.description = embed.description[:4093] + "..."
                
                # Log embed details
                logger.info(f"Embed title: {embed.title}")
                logger.info(f"Embed description length: {len(embed.description)}")
                logger.info(f"Embed has image: {embed.image is not None}")
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
                try:
                    await interaction.followup.send(embed=embed)
                except Exception as followup_err:
                    logger.error(f"Error in followup after HTTP error: {followup_err}")
                
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
                # Only try to send an error message if we haven't already responded
                if interaction.response.is_done():
                    await interaction.followup.send(
                        embed=discord.Embed(
                            title="❌ Error",
                            description="An error occurred while processing your request.",
                            color=discord.Color.red()
                        ),
                        ephemeral=True
                    )
                else:
                    # Try to respond if we haven't already
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
"""
ZwiftRouteBot - Discord Bot for Zwift Routes
-------------------------------------------
Part 5: Sprint, KOM and Random Route Commands
"""

# ==========================================
# Sprint and KOM Commands
# ==========================================

async def sprint(self, interaction, name):
    """
    Handle the /sprint command.
    Displays information about Zwift sprint segments.
    
    Args:
        interaction: The Discord interaction
        name: The name of the sprint segment to search for
    """
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

async def kom(self, interaction, name):
    """
    Handle the /kom command.
    Displays information about Zwift KOM segments.
    
    Args:
        interaction: The Discord interaction
        name: The name of the KOM segment to search for
    """
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

async def random_route(self, interaction, 
                     world=None,
                     route_type=None,
                     duration=None):
    """
    Get a randomly selected route that meets filter criteria.
    
    Args:
        interaction: The Discord interaction
        world: Filter by Zwift world (e.g., Watopia, London)
        route_type: Type of route (flat, mixed, hilly)
        duration: Duration category (short, medium, long)
    """
    if not interaction.user:
        return
        
    try:
        await interaction.response.defer(thinking=True, ephemeral=True)
        logger.info("Interaction deferred")
    except discord.errors.NotFound:
        logger.error("Could not defer interaction - it may have expired")
        return  # Exit early if we can't defer
    except Exception as defer_error:
        logger.error(f"Error deferring interaction: {defer_error}")

    loading_message = await bike_loading_animation(interaction)
    
    try:
        # Check if cache is initialized
        if not hasattr(self, 'route_cache_data') or not self.route_cache_data:
            logger.warning("Route cache not initialized, loading now...")
            self.route_cache_data = await self.cache.load_or_update()
        
        # Filter routes based on criteria
        filtered_routes = []
        
        for route_name, data in self.route_cache_data.items():
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
        route_name = selected_route['route_name']
        logger.info(f"Selected random route: {route_name}")
        
        # Create response embed
        embed = discord.Embed(
            title=f"🎲 Random Route: {route_name}",
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
        
        # Use the find_route_images function
        found_images = find_route_images(route_name)
        
        # Setup for file attachments
        files_to_send = []
        image_sources = []
        has_embed_image = False
        already_added_paths = set()  # Track which files we've already added
        
        # Get Cyccal URL if available from original route data
        original_route = next((r for r in zwift_routes if r['Route'] == route_name), None)
        cyccal_url = original_route.get("ImageURL") if original_route and original_route.get("ImageURL") and 'github' in original_route.get("ImageURL", "").lower() else None
        
        # 1. Try profile images (highest priority - "ZwiftHacks")
        if found_images['profile_images'] and not has_embed_image:
            profile_path = found_images['profile_images'][0]  # Use the first profile image
            logger.info(f"Setting profile (ZwiftHacks) as primary embed image: {profile_path}")
            profile_file, image_source = handle_local_image(profile_path, embed)
            if profile_file:
                files_to_send.append(profile_file)
                image_sources.append("ZwiftHacks")
                has_embed_image = True
                already_added_paths.add(profile_path)
        
        # 2. Try Cyccal GitHub (second priority - "Cyccal")
        if cyccal_url and not has_embed_image:
            logger.info(f"Setting Cyccal as primary embed image: {cyccal_url}")
            embed.set_image(url=cyccal_url)
            image_sources.append("Cyccal")
            has_embed_image = True
            
            # Add Cyccal link
            cyccal_web_url = f"https://cyccal.com/{route_name.lower().replace(' ', '-')}/"
            embed.add_field(
                name="Additional Resources",
                value=f"[View on Cyccal]({cyccal_web_url})",
                inline=False
            )
        
        # 3. Try map images (third priority - "ZwiftHub")
        if found_images['map_images'] and not has_embed_image:
            map_path = found_images['map_images'][0]  # Use the first map image
            logger.info(f"Setting map (ZwiftHub) as primary embed image: {map_path}")
            map_file, image_source = handle_local_image(map_path, embed)
            if map_file:
                files_to_send.append(map_file)
                image_sources.append("ZwiftHub")
                has_embed_image = True
                already_added_paths.add(map_path)
        
        # 4. Try other images if still no image set
        if found_images['other_images'] and not has_embed_image:
            other_path = found_images['other_images'][0]
            logger.info(f"Setting other image as primary embed image: {other_path}")
            other_file, image_source = handle_local_image(other_path, embed)
            if other_file:
                files_to_send.append(other_file)
                image_sources.append("Other")
                has_embed_image = True
                already_added_paths.add(other_path)
        
        # Try ZwiftInsider as last resort
        if not has_embed_image:
            try:
                stats, zwift_img_url = await fetch_route_info(selected_route['url'])
                if zwift_img_url:
                    logger.info(f"Using ZwiftInsider image for {route_name}: {zwift_img_url}")
                    embed.set_image(url=zwift_img_url)
                    has_embed_image = True
                    image_sources.append("ZwiftInsider")
            except Exception as img_err:
                logger.error(f"Error fetching ZwiftInsider image: {img_err}")
        
        # Now add secondary images (if not already used as primary)
        
        # Try to add a map image if not already included
        if found_images['map_images']:
            for map_path in found_images['map_images']:
                if map_path not in already_added_paths:
                    try:
                        file_lower = map_path.lower()
                        if file_lower.endswith('.svg'):
                            map_file = discord.File(map_path, filename="route_map.svg")
                        else:
                            map_file = discord.File(map_path, filename="route_map.png")
                            
                        files_to_send.append(map_file)
                        if "ZwiftHub" not in image_sources:
                            image_sources.append("ZwiftHub")
                        already_added_paths.add(map_path)
                        logger.info(f"Added map as secondary image: {map_path}")
                        break  # Just add one map image as secondary
                    except Exception as e:
                        logger.error(f"Error adding map as secondary image: {e}")
        
        # Try to add a profile image if not already included
        if found_images['profile_images']:
            for profile_path in found_images['profile_images']:
                if profile_path not in already_added_paths:
                    try:
                        file_lower = profile_path.lower()
                        if file_lower.endswith('.svg'):
                            profile_file = discord.File(profile_path, filename="route_profile.svg")
                        else:
                            profile_file = discord.File(profile_path, filename="route_profile.png")
                            
                        files_to_send.append(profile_file)
                        if "ZwiftHacks" not in image_sources:
                            image_sources.append("ZwiftHacks")
                        already_added_paths.add(profile_path)
                        logger.info(f"Added profile as secondary image: {profile_path}")
                        break  # Just add one profile image as secondary
                    except Exception as e:
                        logger.error(f"Error adding profile as secondary image: {e}")
        
        # Always add Cyccal link if it exists (even if not used for embed)
        if cyccal_url and "Additional Resources" not in [field.name for field in embed.fields]:
            cyccal_web_url = f"https://cyccal.com/{route_name.lower().replace(' ', '-')}/"
            embed.add_field(
                name="Additional Resources",
                value=f"[View on Cyccal]({cyccal_web_url})",
                inline=False
            )
        
        # Add thumbnail
        embed.set_thumbnail(url="https://zwiftinsider.com/wp-content/uploads/2022/12/zwift-logo.png")
        
        # Set footer based on filters and image sources
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
        
        # Add image sources to footer
        if image_sources:
            sources_text = ", ".join(image_sources)
            footer_text += f" • Images: {sources_text}"
            
        embed.set_footer(text=footer_text)
        
        # Log what we're sending
        logger.info(f"Random route response for {route_name} with {len(files_to_send)} files")
        for i, file in enumerate(files_to_send):
            logger.info(f"File {i+1}: {file.filename}")
        
        # Send using the improved send_ephemeral_response method
        await send_ephemeral_response(
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
                description=f"An error occurred while selecting a random route: {str(e)}",
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
"""
ZwiftRouteBot - Discord Bot for Zwift Routes
-------------------------------------------
Part 6-A: Find Route Command

This section implements the findroute command which allows users to search for routes
based on various criteria like distance, elevation, world, type, and duration.
"""

# ==========================================
# Find Route Command
# ==========================================

async def findroute(self, interaction, 
                  min_km=None, 
                  max_km=None,
                  min_elev=None,
                  max_elev=None,
                  world=None,
                  route_type=None,
                  duration=None):
    """
    Find routes matching specific criteria.
    
    Args:
        interaction: The Discord interaction
        min_km: Minimum route distance in kilometers
        max_km: Maximum route distance in kilometers
        min_elev: Minimum elevation in meters
        max_elev: Maximum elevation in meters
        world: Zwift world to filter by
        route_type: Type of route (flat, mixed, hilly)
        duration: Duration category (short, medium, long)
    """
    if not interaction.user:
        return
        
    try:
        await interaction.response.defer(thinking=True, ephemeral=True)
        logger.info("Interaction deferred")
    except discord.errors.NotFound:
        logger.error("Could not defer interaction - it may have expired")
        return  # Exit early if we can't defer
    except Exception as defer_error:
        logger.error(f"Error deferring interaction: {defer_error}")

    loading_message = await bike_loading_animation(interaction)
    
    try:
        # Set default values if not provided
        _min_km = min_km if min_km is not None else 0
        _max_km = max_km if max_km is not None else 999
        _min_elev = min_elev if min_elev is not None else 0
        _max_elev = max_elev if max_elev is not None else 9999
        
        # Check if cache is initialized
        if not hasattr(self, 'route_cache_data') or not self.route_cache_data:
            logger.warning("Route cache not initialized, loading now...")
            self.route_cache_data = await self.cache.load_or_update()
        
        # Filter routes based on criteria
        matching_routes = []
        
        for route_name, data in self.route_cache_data.items():
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
                world_routes = [r for _, r in self.route_cache_data.items() 
                             if 'world' in r and world.lower() in r['world'].lower()]
                
                if world_routes:
                    sample = random.sample(world_routes, min(3, len(world_routes)))
                    suggestions = "\n\n**Some routes in {}:**\n".format(world)
                    for route in sample:
                        suggestions += f"• {route['route_name']} ({route.get('distance_km', '?')} km, {route.get('elevation_m', '?')} m)\n"
                    embed.description += suggestions
        
        # Send the ephemeral embed with share button
        await send_ephemeral_response(interaction, embed, command_type="findroute")
        
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
"""
ZwiftRouteBot - Discord Bot for Zwift Routes
-------------------------------------------
Part 6-B: World Routes Command

This section implements the worldroutes command which lists all routes available
in a specific Zwift world, with options for sorting by distance, elevation, or name.
"""

# ==========================================
# World Routes Command
# ==========================================

async def world_routes(self, interaction, world, sort_by="distance"):
    """
    List all routes in a specific Zwift world.
    
    Args:
        interaction: The Discord interaction
        world: Zwift world to show routes for
        sort_by: How to sort the routes (distance, elevation, name)
    """
    if not interaction.user:
        return
        
    await interaction.response.defer(thinking=True, ephemeral=True)
    loading_message = await bike_loading_animation(interaction)
    
    try:
        # Check if cache is initialized
        if not hasattr(self, 'route_cache_data') or not self.route_cache_data:
            logger.warning("Route cache not initialized, loading now...")
            self.route_cache_data = await self.cache.load_or_update()
        
        # Filter routes by world (case-insensitive partial match)
        world_routes = []
        for route_data in self.route_cache_data.values():
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
        await send_ephemeral_response(interaction, embed, command_type="worldroutes")
        
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
"""
ZwiftRouteBot - Discord Bot for Zwift Routes
-------------------------------------------
Part 6-C: Route Stats Command (Beginning)

This section implements the first part of the routestats command which displays
detailed information about a specific Zwift route, including distance, elevation,
time estimates, and more.
"""

# ==========================================
# Route Stats Command (Part 1)
# ==========================================

async def route_stats(self, interaction, name, category="B"):
    """
    Display detailed statistics for a specific Zwift route.
    
    Args:
        interaction: The Discord interaction
        name: Name of the route to display stats for
        category: Rider category for time estimates (A/B/C/D)
    """
    if not interaction.user:
        return
        
    try:
        await interaction.response.defer(thinking=True, ephemeral=True)
        logger.info("Interaction deferred")
    except discord.errors.NotFound:
        logger.error("Could not defer interaction - it may have expired")
        return  # Exit early if we can't defer
    except Exception as defer_error:
        logger.error(f"Error deferring interaction: {defer_error}")

    loading_message = await bike_loading_animation(interaction)
    
    try:
        # Find the route first
        route_result, alternatives = find_route(name)
        
        if not route_result:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Route Not Found",
                    description=f"Could not find a route matching `{name}`.\n\n"
                              "Try using a more specific name or check the spelling.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            if loading_message:
                try:
                    await loading_message.delete()
                except Exception as e:
                    logger.error(f"Error deleting loading animation: {e}")
            return
        
        # Get route name from search result
        route_name = route_result['Route']
        logger.info(f"Found route: {route_name}")
        
        # Look up detailed information from cache
        detailed_info = None
        if hasattr(self, 'route_cache_data') and self.route_cache_data:
            detailed_info = self.route_cache_data.get(route_name)
        
        # If not in cache, try to fetch it
        if not detailed_info:
            logger.warning(f"Route {route_name} not found in cache, attempting to fetch")
            # Create a single-use session for fetching
            async with aiohttp.ClientSession() as session:
                detailed_info = await self.cache.fetch_route_details(session, route_result)
        
        # Create the embed
        embed = discord.Embed(
            title=f"📊 {route_name}",
            url=route_result.get("URL", ""),
            color=0x3498DB
        )
        
        # Basic details section
        basic_details = []
        
        # Add world information
        world = detailed_info.get('world') if detailed_info else get_world_for_route(route_name)
        basic_details.append(f"🌎 **World:** {world}")
        
        # Add distance information
        if detailed_info and 'distance_km' in detailed_info:
            distance_km = detailed_info['distance_km']
            distance_miles = detailed_info.get('distance_miles', round(distance_km * 0.621371, 1))
            basic_details.append(f"📏 **Distance:** {distance_km} km ({distance_miles} miles)")
        
        # Add elevation information
        if detailed_info and 'elevation_m' in detailed_info:
            elevation_m = detailed_info['elevation_m']
            elevation_ft = detailed_info.get('elevation_ft', round(elevation_m * 3.28084))
            basic_details.append(f"⛰️ **Elevation:** {elevation_m} m ({elevation_ft} ft)")
        
        # Add lead-in information if available
        if detailed_info and 'lead_in_km' in detailed_info and detailed_info['lead_in_km'] > 0:
            lead_in_km = detailed_info['lead_in_km']
            lead_in_miles = round(lead_in_km * 0.621371, 1)
            basic_details.append(f"🔄 **Lead-in:** {lead_in_km} km ({lead_in_miles} miles)")
        
        # Add route badges if available
        if detailed_info and 'badges' in detailed_info and detailed_info['badges']:
            badges = detailed_info['badges']
            basic_details.append(f"🏷️ **Type:** {', '.join(badges)}")
        
        # Add ZI rating if available
        if detailed_info and 'zi_rating' in detailed_info:
            zi_rating = detailed_info['zi_rating']
            basic_details.append(f"⭐ **ZI Rating:** {zi_rating}/100")
        
        # Add the basic details to the embed
        embed.add_field(
            name="Route Details",
            value="\n".join(basic_details),
            inline=False
        )
        

# ==========================================
# Route Stats Command (Part 2 - Time Estimates & Segments)
# ==========================================

        # Time estimates section
        time_estimates = []
        
        # Function to format time
        def format_time(minutes):
            if minutes >= 60:
                hours = minutes // 60
                mins = minutes % 60
                return f"{hours}h {mins}m"
            else:
                return f"{minutes}m"
        
        # Add time estimates if available
        if detailed_info and 'time_estimates' in detailed_info:
            estimates = detailed_info['time_estimates']
            
            # First add the requested category
            if category in estimates:
                time_estimates.append(f"**Selected Category ({category}):** {format_time(estimates[category])}")
            
            # Then add all categories in order
            for cat in ['A', 'B', 'C', 'D']:
                if cat in estimates and (cat != category or not time_estimates):  # Skip if already shown
                    time_estimates.append(f"**Category {cat}:** {format_time(estimates[cat])}")
        
        # Add W/kg estimates if available
        if detailed_info and 'wkg_times' in detailed_info:
            wkg_times = detailed_info['wkg_times']
            time_estimates.append("\n**By Power-to-Weight:**")
            
            for wkg, minutes in sorted(wkg_times.items(), key=lambda x: int(x[0])):
                time_estimates.append(f"{wkg} W/kg: {format_time(int(minutes))}")
        
        # Add time estimates to the embed if available
        if time_estimates:
            embed.add_field(
                name="Time Estimates",
                value="\n".join(time_estimates),
                inline=True
            )
        
        # Display segments appropriately based on available data
        if detailed_info:
            # Check for the enhanced segment fields first
            if 'sprint_kom_segments' in detailed_info and detailed_info['sprint_kom_segments']:
                # Display Sprint & KOM segments
                sprint_kom = detailed_info['sprint_kom_segments']
                # Truncate if too long for Discord embed field
                if len(sprint_kom) >= 1024:
                    sprint_kom = sprint_kom[:1020] + "..."
                embed.add_field(
                    name="Sprint & KOM Segments",
                    value=sprint_kom,
                    inline=False
                )
            
            # Check for Strava segments
            if 'strava_segments' in detailed_info and detailed_info['strava_segments']:
                # Display Strava segments
                strava = detailed_info['strava_segments']
                # Truncate if too long for Discord embed field
                if len(strava) >= 1024:
                    strava = strava[:1020] + "..."
                embed.add_field(
                    name="Strava Segments",
                    value=strava,
                    inline=False
                )
            
            # Fallback to original segments field if the new fields aren't available
            elif 'segments' in detailed_info and detailed_info['segments']:
                segments = detailed_info['segments']
                # Truncate if too long for Discord embed field
                if len(segments) >= 1024:
                    segments = segments[:1020] + "..."
                
                # Try to detect if this is a Strava-only segment list
                if segments.lower().startswith('strava'):
                    field_name = "Strava Segments"
                else:
                    field_name = "Segments"
                
                embed.add_field(
                    name=field_name,
                    value=segments,
                    inline=False
                )


# ==========================================
# Route Stats Command (Part 3 - Image Handling)
# ==========================================

        # Find images for the route
        found_images = find_route_images(route_name)
        
        # Setup for file attachments
        files_to_send = []
        image_sources = []
        image_count = 0
        main_image_set = False
        already_added_paths = set()  # Track which files we've already added
        
        # Get Cyccal URL if available
        cyccal_url = route_result.get("ImageURL") if route_result.get("ImageURL") and 'github' in route_result.get("ImageURL", "").lower() else None
        
        # 1. Try profile images (highest priority - "ZwiftHacks")
        if found_images['profile_images'] and not main_image_set:
            profile_path = found_images['profile_images'][0]  # Use the first profile image
            logger.info(f"Setting profile (ZwiftHacks) as primary embed image: {profile_path}")
            profile_file, image_source = handle_local_image(profile_path, embed)
            if profile_file:
                files_to_send.append(profile_file)
                image_sources.append("ZwiftHacks")
                main_image_set = True
                image_count += 1
                already_added_paths.add(profile_path)
        
        # 2. Try Cyccal GitHub (second priority - "Cyccal")
        if cyccal_url and not main_image_set:
            logger.info(f"Setting Cyccal as primary embed image: {cyccal_url}")
            embed.set_image(url=cyccal_url)
            image_sources.append("Cyccal")
            main_image_set = True
            image_count += 1
            
            # Add Cyccal link since we're using their image
            cyccal_web_url = f"https://cyccal.com/{route_name.lower().replace(' ', '-')}/"
            embed.add_field(
                name="Additional Resources",
                value=f"[View on Cyccal]({cyccal_web_url})",
                inline=False
            )
        
        # 3. Try map images (third priority - "ZwiftHub")
        if found_images['map_images'] and not main_image_set:
            map_path = found_images['map_images'][0]  # Use the first map image
            logger.info(f"Setting map (ZwiftHub) as primary embed image: {map_path}")
            map_file, image_source = handle_local_image(map_path, embed)
            if map_file:
                files_to_send.append(map_file)
                image_sources.append("ZwiftHub")
                main_image_set = True
                image_count += 1
                already_added_paths.add(map_path)
        
        # 4. Try other images if still no image set
        if found_images['other_images'] and not main_image_set:
            other_path = found_images['other_images'][0]
            logger.info(f"Setting other image as primary embed image: {other_path}")
            other_file, image_source = handle_local_image(other_path, embed)
            if other_file:
                files_to_send.append(other_file)
                image_sources.append("Other")
                main_image_set = True
                image_count += 1
                already_added_paths.add(other_path)
        
        # Always add Cyccal link if it exists (even if not used for embed)
        if cyccal_url and "Additional Resources" not in [field.name for field in embed.fields]:
            cyccal_web_url = f"https://cyccal.com/{route_name.lower().replace(' ', '-')}/"
            embed.add_field(
                name="Additional Resources",
                value=f"[View on Cyccal]({cyccal_web_url})",
                inline=False
            )


# ==========================================
# Route Stats Command (Part 4 - Additional Images and Response)
# ==========================================

        # Add a profile image if not already included
        if found_images['profile_images']:
            for profile_path in found_images['profile_images']:
                if profile_path not in already_added_paths:
                    try:
                        file_lower = profile_path.lower()
                        if file_lower.endswith('.svg'):
                            profile_file = discord.File(profile_path, filename="route_profile.svg")
                        else:
                            profile_file = discord.File(profile_path, filename="route_profile.png")
                            
                        files_to_send.append(profile_file)
                        image_count += 1
                        if "ZwiftHacks" not in image_sources:
                            image_sources.append("ZwiftHacks")
                        already_added_paths.add(profile_path)
                        logger.info(f"Added additional profile image: {profile_path}")
                        break  # Just add one extra profile image
                    except Exception as e:
                        logger.error(f"Error adding profile image: {e}")
        
        # Add a map image if not already included
        if found_images['map_images']:
            for map_path in found_images['map_images']:
                if map_path not in already_added_paths:
                    try:
                        file_lower = map_path.lower()
                        if file_lower.endswith('.svg'):
                            map_file = discord.File(map_path, filename="route_map.svg")
                        else:
                            map_file = discord.File(map_path, filename="route_map.png")
                            
                        files_to_send.append(map_file)
                        image_count += 1
                        if "ZwiftHub" not in image_sources:
                            image_sources.append("ZwiftHub")
                        already_added_paths.add(map_path)
                        logger.info(f"Added additional map image: {map_path}")
                        break  # Just add one extra map image
                    except Exception as e:
                        logger.error(f"Error adding map image: {e}")
        
        # Add an incline image if available
        if found_images['incline_images']:
            for incline_path in found_images['incline_images']:
                if incline_path not in already_added_paths:
                    try:
                        file_lower = incline_path.lower()
                        if file_lower.endswith('.svg'):
                            incline_file = discord.File(incline_path, filename="route_incline.svg")
                        else:
                            incline_file = discord.File(incline_path, filename="route_incline.png")
                            
                        files_to_send.append(incline_file)
                        image_count += 1
                        if "Incline" not in image_sources:
                            image_sources.append("Incline")
                        already_added_paths.add(incline_path)
                        logger.info(f"Added incline image: {incline_path}")
                        break  # Just add one incline image
                    except Exception as e:
                        logger.error(f"Error adding incline image: {e}")
        
        # Fall back to ZwiftInsider image if no other images have been added
        if not main_image_set:
            try:
                stats, zwift_img_url = await fetch_route_info(route_result["URL"])
                if zwift_img_url:
                    logger.info(f"Using ZwiftInsider image: {zwift_img_url}")
                    embed.set_image(url=zwift_img_url)
                    image_sources.append("ZwiftInsider")
                    image_count += 1
            except Exception as img_err:
                logger.error(f"Error fetching ZwiftInsider image: {img_err}")
        
        # Add image count to description
        if image_count > 0:
            # Modify description to include image count
            description = f"**{image_count} image{'s' if image_count > 1 else ''} found for this route.**"
            embed.description = description
        
        # Add custom thumbnail
        embed.set_thumbnail(url="https://zwiftinsider.com/wp-content/uploads/2022/12/zwift-logo.png")
        
        # Set footer with image sources if any
        footer_text = "ZwiftGuy"
        if image_sources:
            # Make the list of sources unique to avoid duplicates
            unique_sources = list(dict.fromkeys(image_sources))
            sources_text = ", ".join(unique_sources)
            footer_text += f" • Images from: {sources_text}"
        footer_text += " • Use /routestats for detailed route information"
        
        embed.set_footer(text=footer_text)
        
        # Log what's being sent
        logger.info(f"Sending response with {len(files_to_send)} files out of {image_count} total images")
        if files_to_send:
            for i, file in enumerate(files_to_send):
                logger.info(f"File {i+1}: {file.filename}")
        
        # Ensure we have a list for files
        files_list = files_to_send if files_to_send else None
        
        # Send ephemeral response with share button
        logger.info("Sending ephemeral response with command_type='routestats'")
        await send_ephemeral_response(
            interaction, 
            embed, 
            files_list,
            command_type="routestats"  # Make sure this matches exactly with a key in share_messages dictionary
        )
        
    except Exception as e:
        logger.error(f"Error in route stats command: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
        await interaction.followup.send(
            embed=discord.Embed(
                title="❌ Error",
                description=f"An error occurred while generating route statistics: {str(e)}",
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
                
"""
ZwiftRouteBot - Discord Bot for Zwift Routes
-------------------------------------------
Part 7: Main Program and Entry Point

This section implements the main program entry point with retry logic
and graceful error handling.
"""

# ==========================================
# Main Program
# ==========================================

def main():
    """
    Main program loop with retry logic.
    Handles startup, retries, and graceful shutdown.
    """
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
                # Exponential backoff for retry delays
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
        # Create bot instance
        client = ZwiftBot()
        # Run the main program
        main()
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        logger.info("Bot shutdown complete")
