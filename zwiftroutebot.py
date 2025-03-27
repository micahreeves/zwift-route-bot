"""
ZwiftRouteBot - Discord Bot for Zwift Routes
-------------------------------------------
A Discord bot that provides information about Zwift routes, segments, and more.
Features both direct route lookup and a natural language interface.

Key Features:
- /route command for direct route information lookup
- /zwiftds command for natural language questions about Zwift
- Conversation context tracking for follow-up questions
- Quick reply buttons for common actions
- Route comparison functionality
- Comprehensive route data with images from multiple sources

Author: [Your Name]
Version: 2.0
Last Updated: March 24, 2025
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

# Global variables
zwift_routes = []
zwift_koms = []
zwift_sprints = []

# Function to load JSON data
def load_json_file(file_path, default_value=None):
    """Load JSON data from a file with error handling"""
    if default_value is None:
        default_value = []
    
    try:
        with open(file_path, "r", encoding='utf-8') as file:
            data = json.load(file)
        logger.info(f"Successfully loaded {file_path} with {len(data)} items")
        return data
    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
        return default_value
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON in file: {file_path}")
        return default_value
    except Exception as e:
        logger.error(f"Error loading {file_path}: {e}")
        return default_value

# Load all data files
zwift_routes = load_json_file("zwift_routes.json")
zwift_koms = load_json_file("zwift_koms.json")
zwift_sprints = load_json_file("zwift_sprint_segments.json")

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

    global zwift_routes

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
    global zwift_sprints
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
    Find a KOM segment using fuzzy matching.
    
    Args:
        search_term: The search query
        
    Returns:
        tuple: (matched_kom, alternative_koms)
    """
    global zwift_koms
    
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

# ==========================================
# UI Components for Quick Replies
# ==========================================




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
    
    async def cache_route_details(self):
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
                
                return route_data
                
        except Exception as e:
            logger.error(f"Error in fetch_route_details for {route.get('Route', 'unknown')}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    async def periodic_update(self, bot_instance):
        try:
            while True:
            # Wait for update interval (once per day)
                await asyncio.sleep(24 * 60 * 60)  # 24 hours
            
                logger.info("Starting periodic cache update...")
                try:
                # Refresh the cache
                    updated_cache = await self.cache_route_details()
                
                # Update the bot's cached data
                    if updated_cache:
                        bot_instance.route_cache_data = updated_cache
                        logger.info(f"Successfully updated route cache with {len(updated_cache)} routes")
                except Exception as e:
                    logger.error(f"Error during periodic cache update: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
        except asyncio.CancelledError:
            logger.info("Periodic update task cancelled")
        except Exception as e:
            logger.error(f"Unexpected error in periodic update task: {e}")
            import traceback
            logger.error(traceback.format_exc())


# ==========================================
# Main Bot Class Definition
# ==========================================

class ZwiftBot(discord.Client):
    """
    Main Discord bot class for handling Zwift route information and commands.
    Features both direct route lookup with /route and natural language interface with /zwiftds.
    Maintains a cache of route data for quick access.
    """
    
    # ==========================================
    # ZwiftBot Initialization
    # ==========================================
    
    def __init__(self):
        """Initialize the ZwiftBot with default settings"""
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        
        # Context tracking system for zwiftds command
        self.conversation_context = {}  # user_id -> context
        
        # Rate limiting system
        self.command_cooldowns = {}  # User-specific cooldowns
        self.global_command_times = deque(maxlen=50)  # Track recent commands
        self.rate_limit_lock = asyncio.Lock()  # Lock for rate limit checking
        self.USER_COOLDOWN = 5.0  # Seconds between commands for a single user
        self.GLOBAL_RATE_LIMIT = 20  # Max commands per minute
        
        # Initialize cache with a path that works in both Docker and local environments
        import tempfile
        
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
        
        # Route command
        @self.tree.command(name="route", description="Get a Zwift route INFO by name")
        async def route_command(interaction, name: str):
            await self.route(interaction, name)
        
        # ZwiftDS command - natural language interface for all other functions
        @self.tree.command(name="zwiftds", description="Ask any question about Zwift routes, segments, or worlds")
        @app_commands.describe(
            question="Your question about Zwift routes, segments, or worlds"
        )
        async def zwiftds_command(interaction, question: str):
            await self.zwiftds(interaction, question)
    
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
# Route Command Implementation
# ==========================================

    async def route(self, interaction, name):
        """
        Show Zwift route details and all available images.
        
        Args:
            interaction: The Discord interaction object
            name: The name of the route to look up
        """
        if not interaction.user:
            return
        
        try:
            logger.info(f"Route command started for: {name}")
        
            # Defer the response
            await interaction.response.defer(thinking=True)
                
            # Check rate limits
            try:
                await self.check_rate_limit(interaction.user.id)
            except HTTPException as e:
                logger.warning(f"Rate limit hit: {e}")
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="⏳ Rate Limited",
                        description=str(e),
                        color=discord.Color.orange()
                    ),
                    ephemeral=True
                )
                return
            
            # Find route
            result, alternatives = find_route(name)
            logger.info(f"Route search result: {result['Route'] if result else 'Not found'}")
            
            if result:
                # Create the base embed with route details
                embed = discord.Embed(
                    title=f"🚲 {result['Route']}",
                    url=result["URL"],
                    color=0xFC6719
                )
                
                # Get route world
                route_world = get_world_for_route(result['Route'])
                embed.add_field(name="World", value=route_world, inline=True)
                
                # Get detailed info from cache
                detailed_info = self.route_cache_data.get(result['Route'], {})
                
                # Add key stats if available
                if detailed_info:
                    if 'distance_km' in detailed_info:
                        embed.add_field(
                            name="Distance", 
                            value=f"{detailed_info['distance_km']} km ({detailed_info.get('distance_miles', '?')} mi)", 
                            inline=True
                        )
                    
                    if 'elevation_m' in detailed_info:
                        embed.add_field(
                            name="Elevation", 
                            value=f"{detailed_info['elevation_m']} m ({detailed_info.get('elevation_ft', '?')} ft)", 
                            inline=True
                        )
                    
                    # Add estimated time if available
                    if 'estimated_time_min' in detailed_info:
                        est_time = detailed_info['estimated_time_min']
                        time_str = f"{est_time // 60}h {est_time % 60}m" if est_time >= 60 else f"{est_time}m"
                        embed.add_field(name="Est. Time", value=time_str, inline=True)
                    
                    # Add route type/badges if available
                    if 'badges' in detailed_info and detailed_info['badges']:
                        embed.add_field(
                            name="Type", 
                            value=", ".join(detailed_info['badges']), 
                            inline=True
                        )
                
                # Prepare route name variations for smarter image matching
                route_name = result['Route']
                route_name_lower = route_name.lower()
                route_variations = [
                    route_name_lower.replace(' ', '_').replace("'", '').replace('-', '_'),
                    route_name_lower.replace(' ', '').replace("'", '').replace('-', ''),
                    route_name_lower.replace(' ', '-').replace("'", ''),
                    ''.join(c for c in route_name_lower if c.isalnum())
                ]
                
                logger.info(f"Looking for images with variations: {route_variations}")
                
                # Try both absolute and relative paths
                base_paths = [
                    "/app/route_images",
                    "route_images",
                    "/home/micah-reeves/Desktop/zwift-route-bot/route_images"
                ]
                
                # Find valid base path
                valid_base = None
                for base in base_paths:
                    if os.path.exists(base) and os.path.isdir(base):
                        valid_base = base
                        logger.info(f"Found valid base path: {valid_base}")
                        break
                
                # Define image types to look for
                image_types = {
                    "Profile": "profiles",
                    "Incline": "inclines", 
                    "Map": "maps"
                }
                
                # Find images
                existing_images = {}
                if valid_base:
                    for img_type, subdir in image_types.items():
                        subdir_path = os.path.join(valid_base, subdir)
                        
                        if not os.path.exists(subdir_path) or not os.path.isdir(subdir_path):
                            logger.warning(f"Directory not found: {subdir_path}")
                            continue
                            
                        # Try exact matches with all name variations
                        found = False
                        for variation in route_variations:
                            img_path = os.path.join(subdir_path, f"{variation}.png")
                            if os.path.exists(img_path):
                                existing_images[img_type] = img_path
                                logger.info(f"Found {img_type} image: {img_path}")
                                found = True
                                break
                                
                        # If no exact match, try fuzzy matching with directory listing
                        if not found:
                            try:
                                files = [f for f in os.listdir(subdir_path) if f.lower().endswith('.png')]
                                
                                # Strip extensions for matching
                                file_bases = [os.path.splitext(f)[0].lower() for f in files]
                                
                                # Try difflib for fuzzy matching
                                for variation in route_variations:
                                    close_matches = get_close_matches(variation, file_bases, n=1, cutoff=0.7)
                                    
                                    if close_matches:
                                        match_index = file_bases.index(close_matches[0])
                                        matched_file = files[match_index]
                                        img_path = os.path.join(subdir_path, matched_file)
                                        existing_images[img_type] = img_path
                                        logger.info(f"Found fuzzy match for {img_type}: {matched_file}")
                                        break
                            except Exception as e:
                                logger.error(f"Error listing directory {subdir_path}: {e}")
                
                # Add a description with available resources
                description_parts = []
                description_parts.append(f"View full details on [ZwiftInsider]({result['URL']})")
                
                # Format route name for Cyccal URL
                cyccal_route_name = result['Route'].lower().replace(' ', '-')
                cyccal_url = f"https://cyccal.com/{cyccal_route_name}/"
                description_parts.append(f"Check [Cyccal]({cyccal_url}) for user times")
                
                if existing_images:
                    description_parts.append(f"**{len(existing_images)} route images available below**")
                else:
                    description_parts.append("**No route images found**")
                
                embed.description = "\n".join(description_parts)
                
                # Add thumbnail
                embed.set_thumbnail(url="https://zwiftinsider.com/wp-content/uploads/2022/12/zwift-logo.png")
                
                # Send the initial embed with route details
                await interaction.followup.send(embed=embed)
                
                # Send each image as a separate message with a descriptive embed
                for image_name, image_path in existing_images.items():
                    try:
                        logger.info(f"Preparing to send {image_name} image from {image_path}")
                        
                        img_embed = discord.Embed(
                            title=f"{result['Route']}",
                            color=0xFC6719
                        )
                        
                        # Use a simple filename for Discord attachment
                        simple_filename = f"{image_name.lower()}.png"
                        
                        # Create file object and set image
                        file = discord.File(image_path, filename=simple_filename)
                        img_embed.set_image(url=f"attachment://{simple_filename}")
                        
                        # Send with attachment
                        await interaction.followup.send(embed=img_embed, file=file)
                        logger.info(f"Successfully sent {image_name} image")
                    except Exception as img_error:
                        logger.error(f"Error sending {image_name} image: {img_error}")
                        import traceback
                        logger.error(traceback.format_exc())
                
                # Add a note about alternatives if any
                if alternatives:
                    alt_text = "\n".join(f"• {r['Route']}" for r in alternatives)
                    alt_embed = discord.Embed(
                        title="Similar Routes",
                        description=f"You might also be interested in:\n{alt_text}",
                        color=0xFC6719
                    )
                    await interaction.followup.send(embed=alt_embed)
            
            else:
                # Route not found
                suggestions = random.sample(zwift_routes, min(3, len(zwift_routes)))
                embed = discord.Embed(
                    title="❌ Route Not Found",
                    description=f"Could not find a route matching `{name}`.\n\n**Try these routes:**\n" + 
                               "\n".join(f"• {r['Route']}" for r in suggestions),
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed)
                
        except Exception as e:
            logger.error(f"Error in route command: {e}")
            import traceback
            logger.error(traceback.format_exc())
            try:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="❌ Error",
                        description="An error occurred while processing your request.",
                        color=discord.Color.red()
                    )
                )
            except Exception as err:
                logger.error(f"Failed to send error message: {err}")

    # ==========================================
    # ZwiftDS Command Implementation
    # ==========================================
    
    async def zwiftds(self, interaction, question):
        """
        Natural language interface for Zwift information requests.
        Analyzes the query and routes to appropriate functionality.
        
        Args:
            interaction: The Discord interaction
            question: The user's natural language query
        """
        if not interaction.user:
            return
        
        user_id = str(interaction.user.id)
        
        # Initialize or refresh context if needed
        if user_id not in self.conversation_context:
            self.conversation_context[user_id] = {
                'last_route': None,
                'last_world': None,
                'last_segment': None,
                'last_intent': None,
                'timestamp': time.time()
            }
        
        # Check if context is too old (expire after 10 minutes)
        context = self.conversation_context[user_id]
        if time.time() - context['timestamp'] > 600:
            context = {
                'last_route': None,
                'last_world': None, 
                'last_segment': None,
                'last_intent': None,
                'timestamp': time.time()
            }
            self.conversation_context[user_id] = context
        
        # Update timestamp
        context['timestamp'] = time.time()
        try:
            await interaction.response.defer(thinking=True, ephemeral=True)
            logger.info(f"ZwiftDS received question: {question}")
            
        
            
            try:
                # Check if question depends on previous context
                context_dependent = self.is_context_dependent_query(question)
                logger.info(f"Question context dependent: {context_dependent}")
                
                # Analyze the question to determine intent
                intent = self.analyze_question_intent(question)
                logger.info(f"Detected intent: {intent['type']}")
                
                # If query seems to depend on context, augment it
                if context_dependent:
                    intent = self.augment_intent_with_context(intent, context)
                    logger.info(f"Intent after context: {intent['type']}")
                
                # Route the question to the appropriate handler based on intent
                if intent['type'] == 'route_lookup':
                    # User is looking for a specific route
                    await self.handle_route_lookup(interaction, intent)
                    
                    # Update context with route information
                    if 'route_name' in intent:
                        context['last_route'] = intent['route_name']
                        context['last_intent'] = 'route_lookup'
                    
                elif intent['type'] == 'find_routes':
                    # User wants to find routes matching criteria
                    await self.handle_find_routes(interaction, intent)
                    context['last_intent'] = 'find_routes'
                    
                elif intent['type'] == 'segment_lookup':
                    # User is looking for KOM or sprint segment
                    await self.handle_segment_lookup(interaction, intent)
                    
                    # Update context with segment information
                    if 'segment_name' in intent:
                        context['last_segment'] = intent['segment_name']
                        context['last_intent'] = 'segment_lookup'
                    
                elif intent['type'] == 'world_info':
                    # User wants information about a world
                    await self.handle_world_info(interaction, intent)
                    
                    # Update context with world information
                    if 'world_name' in intent:
                        context['last_world'] = intent['world_name']
                        context['last_intent'] = 'world_info'
                    
                elif intent['type'] == 'route_comparison':
                    # User wants to compare routes
                    await self.handle_route_comparison(interaction, intent['routes'])
                    context['last_intent'] = 'route_comparison'
                    
                elif intent['type'] == 'random_route':
                    # User wants a random route suggestion
                    await self.handle_random_route(interaction, intent)
                    context['last_intent'] = 'random_route'
                    
                else:
                    # General question or unrecognized intent
                    await self.handle_general_question(interaction, question)
                    
            except Exception as process_error:
                logger.error(f"Error processing question: {process_error}")
                import traceback
                logger.error(traceback.format_exc())
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="❓ I'm not sure how to answer that",
                        description="I had trouble understanding your question. Try asking something more specific about Zwift routes or segments.",
                        color=discord.Color.orange()
                    ),
                    ephemeral=True
                )
        except Exception as e:
            logger.error(f"Error in zwiftds command: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            try:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="❌ Error",
                        description="I encountered an error while processing your question. Please try again later.",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
            except:
                logger.error("Failed to send error message")
            

    # ==========================================
    # Question Analysis Methods
    # ==========================================
    
    def is_context_dependent_query(self, question):
        """
        Check if a question likely depends on previous context.
        
        Args:
            question: The user's question
            
        Returns:
            bool: True if the question appears to depend on context
        """
        question_lower = question.lower()
        
        # Patterns that suggest the query depends on previous context
        context_patterns = [
            r'\bit\b',           # "How long is it?"
            r'\bthis\b',         # "Is this route hilly?"
            r'\bthat\b',         # "Tell me more about that"
            r'\bthe route\b',    # "What's the elevation of the route?"
            r'how (long|far)',   # "How long is the climb?"
            r'how (hard|difficult)', # "How hard is it?"
            r'how (steep|flat)',  # "How steep is it?"
            r'what about',       # "What about the elevation?"
            r'where is',         # "Where is the route?"
            r'which world',      # "Which world is it in?"
        ]
        
        for pattern in context_patterns:
            if re.search(pattern, question_lower):
                return True
                
        return False
    
    def augment_intent_with_context(self, intent, context):
        """
        Add context information to the intent if needed.
        
        Args:
            intent: The detected intent
            context: The conversation context
            
        Returns:
            dict: The augmented intent
        """
        # If it's a general question but we have context
        if intent['type'] == 'general_question':
            last_intent = context['last_intent']
            
            if last_intent == 'route_lookup' and context['last_route']:
                # Convert to a route lookup with the previous route
                intent['type'] = 'route_lookup'
                intent['route_name'] = context['last_route']
                
            elif last_intent == 'world_info' and context['last_world']:
                # Convert to a world info query
                intent['type'] = 'world_info'
                intent['world_name'] = context['last_world']
                
            elif last_intent == 'segment_lookup' and context['last_segment']:
                # Convert to a segment lookup
                intent['type'] = 'segment_lookup'
                intent['segment_name'] = context['last_segment']
                # Keep the same segment type or default to KOM
                intent['segment_type'] = intent.get('segment_type', 'kom')
        
        return intent
# ==========================================
# Question Intent Analysis - Pattern Recognition
# ==========================================

    def analyze_question_intent(self, question):
        """
        Analyze the user's question to determine the intent and extract parameters.
        Uses simple keyword and pattern matching.
        
        Args:
            question: The user's natural language query
            
        Returns:
            dict: Intent information with type and relevant parameters
        """
        question_lower = question.lower()
        
        # Route lookup intent
        route_patterns = [
            r'tell me about (?:the )?(?:route |route: )?([\w\s\'-]+)',
            r'what is (?:the )?(?:route |route: )?([\w\s\'-]+)',
            r'show (?:me )?(?:the )?(?:route |route: )?([\w\s\'-]+)',
            r'route (?:information|info|details) (?:for|about) ([\w\s\'-]+)',
            r'info (?:for|about) (?:route |route: )?([\w\s\'-]+)',
            r'i want to know about (?:route |route: )?([\w\s\'-]+)',
            r'details (?:for|about|on) (?:route |route: )?([\w\s\'-]+)',
            r'what (?:map|world) is (?:the )?(?:route |route: )?([\w\s\'-]+) on',
            r'where is (?:the )?(?:route |route: )?([\w\s\'-]+)',
            r'which (?:map|world) (?:is|has) (?:the )?(?:route |route: )?([\w\s\'-]+)'
        ]
        
        for pattern in route_patterns:
            match = re.search(pattern, question_lower)
            if match:
                route_name = match.group(1).strip()
                return {'type': 'route_lookup', 'route_name': route_name}
        
        # Finding routes based on criteria
        if any(x in question_lower for x in ['find routes', 'routes with', 'routes that', 'search for routes', 'looking for routes']):
            criteria = {}
            
            # Extract distance criteria
            distance_patterns = [
                r'(\d+)(?:\.\d+)? ?(?:to|-) ?(\d+)(?:\.\d+)? ?km',
                r'(\d+)(?:\.\d+)? ?(?:to|-) ?(\d+)(?:\.\d+)? ?kilometers',
                r'between (\d+)(?:\.\d+)? and (\d+)(?:\.\d+)? ?km',
                r'less than (\d+)(?:\.\d+)? ?km',
                r'more than (\d+)(?:\.\d+)? ?km',
                r'around (\d+)(?:\.\d+)? ?km',
            ]
            
            for pattern in distance_patterns:
                match = re.search(pattern, question_lower)
                if match:
                    if len(match.groups()) > 1 and match.group(2):  # Range specified
                        criteria['min_km'] = float(match.group(1))
                        criteria['max_km'] = float(match.group(2))
                    elif 'less than' in question_lower:
                        criteria['max_km'] = float(match.group(1))
                    elif 'more than' in question_lower:
                        criteria['min_km'] = float(match.group(1))
                    else:  # Around a specific distance
                        target = float(match.group(1))
                        criteria['min_km'] = target * 0.8
                        criteria['max_km'] = target * 1.2
                    break
                    
            # Extract elevation criteria
            elev_patterns = [
                r'(\d+)(?:\.\d+)? ?(?:to|-) ?(\d+)(?:\.\d+)? ?m elevation',
                r'less than (\d+)(?:\.\d+)? ?m (?:of )?elevation',
                r'more than (\d+)(?:\.\d+)? ?m (?:of )?elevation',
                r'around (\d+)(?:\.\d+)? ?m (?:of )?elevation',
                r'elevation (?:of )?(\d+)(?:\.\d+)? ?m',
            ]
            
            for pattern in elev_patterns:
                match = re.search(pattern, question_lower)
                if match:
                    if len(match.groups()) > 1 and match.group(2):  # Range specified
                        criteria['min_elev'] = float(match.group(1))
                        criteria['max_elev'] = float(match.group(2))
                    elif 'less than' in question_lower:
                        criteria['max_elev'] = float(match.group(1))
                    elif 'more than' in question_lower:
                        criteria['min_elev'] = float(match.group(1))
                    else:  # Around a specific elevation
                        target = float(match.group(1))
                        criteria['min_elev'] = target * 0.8
                        criteria['max_elev'] = target * 1.2
                    break
                    
            # Extract world
            worlds = ['watopia', 'london', 'richmond', 'new york', 'innsbruck', 
                     'yorkshire', 'france', 'paris', 'makuri', 'scotland']
            
            for world in worlds:
                if world in question_lower:
                    criteria['world'] = world.capitalize()
                    break
                    
            # Extract route type
            if 'flat' in question_lower:
                criteria['route_type'] = 'flat'
            elif 'hilly' in question_lower:
                criteria['route_type'] = 'hilly'
            elif 'mixed' in question_lower:
                criteria['route_type'] = 'mixed'
                
            # Extract duration
            if any(x in question_lower for x in ['short route', 'short routes', 'quick ride']):
                criteria['duration'] = 'short'
            elif any(x in question_lower for x in ['long route', 'long routes', 'long ride']):
                criteria['duration'] = 'long'
            elif any(x in question_lower for x in ['medium route', 'medium routes', 'medium ride']):
                criteria['duration'] = 'medium'
                
            return {'type': 'find_routes', 'criteria': criteria}
            
        # Random route intent - improved detection for suggest/recommend
        if any(x in question_lower for x in ['random route']) or \
           ('suggest' in question_lower and any(x in question_lower for x in ['route', 'ride'])) or \
           ('recommend' in question_lower and any(x in question_lower for x in ['route', 'ride'])):
            filters = {}
            
            # Extract world
            worlds = ['watopia', 'london', 'richmond', 'new york', 'innsbruck', 
                     'yorkshire', 'france', 'paris', 'makuri', 'scotland']
            
            for world in worlds:
                if world in question_lower:
                    filters['world'] = world.capitalize()
                    break
                    
            # Extract route type
            if 'flat' in question_lower:
                filters['route_type'] = 'flat'
            elif 'hilly' in question_lower:
                filters['route_type'] = 'hilly'
            elif 'mixed' in question_lower:
                filters['route_type'] = 'mixed'
                
            # Extract duration
            if any(x in question_lower for x in ['short route', 'short ride', 'quick']):
                filters['duration'] = 'short'
            elif any(x in question_lower for x in ['long route', 'long ride']):
                filters['duration'] = 'long'
            elif any(x in question_lower for x in ['medium route', 'medium ride']):
                filters['duration'] = 'medium'
                
            return {'type': 'random_route', 'filters': filters}
            
        # Segment lookup intent (KOM or Sprint)
        segment_patterns = [
            r'tell me about (?:the )?([\w\s\'-]+) (kom|king of the mountain|climb|sprint)',
            r'what is (?:the )?([\w\s\'-]+) (kom|king of the mountain|climb|sprint)',
            r'show (?:me )?(?:the )?([\w\s\'-]+) (kom|king of the mountain|climb|sprint)',
            r'info (?:for|about) (?:the )?([\w\s\'-]+) (kom|king of the mountain|climb|sprint)',
            r'(kom|king of the mountain|climb|sprint)(?: called| named)? ([\w\s\'-]+)',
        ]
        
        for pattern in segment_patterns:
            match = re.search(pattern, question_lower)
            if match:
                segment_name = ""
                segment_type = ""
                
                if "kom" in match.group(2) or "king" in match.group(2) or "climb" in match.group(2):
                    segment_type = "kom"
                    segment_name = match.group(1).strip()
                elif "sprint" in match.group(2):
                    segment_type = "sprint"
                    segment_name = match.group(1).strip()
                else:
                    # Pattern with segment type first, name second
                    segment_type = "kom" if "kom" in match.group(1) or "king" in match.group(1) or "climb" in match.group(1) else "sprint"
                    segment_name = match.group(2).strip()
                
                return {'type': 'segment_lookup', 'segment_type': segment_type, 'segment_name': segment_name}
        
        # World information intent
        world_patterns = [
            r'what routes are in ([\w\s\'-]+)',
            r'show (?:me )?routes in ([\w\s\'-]+)',
            r'routes in (?:the )?([\w\s\'-]+) world',
            r'routes in ([\w\s\'-]+)',
            r'tell me about (?:the )?([\w\s\'-]+) world',
        ]
        
        for pattern in world_patterns:
            match = re.search(pattern, question_lower)
            if match:
                world_name = match.group(1).strip()
                
                # Determine sort order
                sort_by = 'distance'
                if any(x in question_lower for x in ['by elevation', 'sort by elevation', 'hilliest']):
                    sort_by = 'elevation'
                elif any(x in question_lower for x in ['alphabetical', 'by name', 'sort by name']):
                    sort_by = 'name'
                    
                return {'type': 'world_info', 'world_name': world_name, 'sort_by': sort_by}
        
        # Route comparison intent
        comparison_patterns = [
            r'compare (?:routes? )?([\w\s\'-]+) and ([\w\s\'-]+)',
            r'difference between ([\w\s\'-]+) and ([\w\s\'-]+)',
            r'which is (better|harder|longer|shorter|steeper)(?: between)? ([\w\s\'-]+) and ([\w\s\'-]+)',
            r'how does ([\w\s\'-]+) compare to ([\w\s\'-]+)',
        ]
        
        for pattern in comparison_patterns:
            match = re.search(pattern, question_lower)
            if match:
                routes = []
                if 'better|harder|longer|shorter|steeper' in pattern:
                    # This pattern has the routes in groups 2 and 3
                    routes = [match.group(2).strip(), match.group(3).strip()]
                elif 'difference between' in pattern or 'how does' in pattern:
                    # This pattern has the routes in groups 1 and 2
                    routes = [match.group(1).strip(), match.group(2).strip()]
                else:
                    # This pattern has the routes in groups 1 and 2
                    routes = [match.group(1).strip(), match.group(2).strip()]
                    
                return {'type': 'route_comparison', 'routes': routes}
        
        # Default to general question
        return {'type': 'general_question'}
    
# ==========================================
# Route Lookup Handler - Natural Language Interface
# ==========================================

    async def handle_route_lookup(self, interaction, intent):
        """
        Handle route lookup requests.
        
        Args:
            interaction: The Discord interaction
            intent: The detected intent with route_name
        """
        route_name = intent.get('route_name', '')
        if not route_name:
            await self.handle_general_question(interaction, "routes")
            return
            
        # Use existing find_route function
        result, alternatives = find_route(route_name)
        
        if result:
            # Similar to existing route command
            stats, zwift_img_url = await fetch_route_info(result["URL"])
            
            embed = discord.Embed(
                title=f"🚲 {result['Route']}",
                url=result["URL"],
                description="\n".join(stats) if stats else "View full route details on ZwiftInsider",
                color=0xFC6719
            )
            
            # Add alternatives if any
            if alternatives:
                similar_routes = "\n\n**Similar routes:**\n" + "\n".join(f"• {r['Route']}" for r in alternatives)
                if embed.description:
                    embed.description += similar_routes
                else:
                    embed.description = similar_routes
                    
            # Add thumbnail and footer
            embed.set_thumbnail(url="https://zwiftinsider.com/wp-content/uploads/2022/12/zwift-logo.png")
            
            # Add Cyccal link
            route_name = result['Route'].lower().replace(' ', '-')
            cyccal_web_url = f"https://cyccal.com/{route_name}/"
            
            embed.add_field(
                name="Additional Resources",
                value=f"[View on Cyccal]({cyccal_web_url})",
                inline=False
            )
            
           
            
            # Format route name for file path (lowercase, replace spaces with underscores)
            route_file_name = result['Route'].lower().replace(' ', '_').replace("'", '').replace('-', '_')
            profile_image_path = f"route_images/profiles/{route_file_name}.png"

            # Check if profile image exists to embed in the main response
            if os.path.exists(profile_image_path):
                file = discord.File(profile_image_path, filename=f"{route_file_name}_profile.png")
                embed.set_image(url=f"attachment://{route_file_name}_profile.png")
                await interaction.followup.send(embed=embed)
            else:
                # If no profile image, just send the embed with the view
                await interaction.followup.send(embed=embed)
        else:
            # Not found response
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❓ Route Not Found",
                    description=f"I couldn't find a route matching '{route_name}'. Could you try a different route name?",
                    color=discord.Color.orange()
                ),
                ephemeral=True
            )   
    
    async def handle_find_routes(self, interaction, intent):
        """
        Handle finding routes based on criteria.
        
        Args:
            interaction: The Discord interaction
            intent: The detected intent with criteria
        """
        criteria = intent.get('criteria', {})
        
        # Set default values if not provided
        _min_km = criteria.get('min_km', 0)
        _max_km = criteria.get('max_km', 999)
        _min_elev = criteria.get('min_elev', 0)
        _max_elev = criteria.get('max_elev', 9999)
        world = criteria.get('world')
        route_type = criteria.get('route_type')
        duration = criteria.get('duration')
        
        # Filter routes based on criteria
        matching_routes = []
        
        for route_name, data in self.route_cache_data.items():
            # Skip routes with missing data
            if 'distance_km' not in data or 'elevation_m' not in data:
                continue
                
            # Apply filters
            if data['distance_km'] < _min_km or data['distance_km'] > _max_km:
                continue
            if data['elevation_m'] < _min_elev or data['elevation_m'] > _max_elev:
                continue
            
            # World filter
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
            
            # All filters passed
            matching_routes.append(data)
        # Create response
        if matching_routes:
            # Sort routes by distance
            matching_routes.sort(key=lambda x: x.get('distance_km', 0))
            
            # Build criteria description
            criteria_desc = []
            if 'min_km' in criteria or 'max_km' in criteria:
                distance_range = f"{_min_km if 'min_km' in criteria else 'any'}-{_max_km if 'max_km' in criteria else 'any'} km"
                criteria_desc.append(f"Distance: {distance_range}")
            
            if 'min_elev' in criteria or 'max_elev' in criteria:
                elev_range = f"{_min_elev if 'min_elev' in criteria else 'any'}-{_max_elev if 'max_elev' in criteria else 'any'} m"
                criteria_desc.append(f"Elevation: {elev_range}")
            
            if world:
                criteria_desc.append(f"World: {world}")
            
            if route_type:
                criteria_desc.append(f"Type: {route_type}")
                
            if duration:
                criteria_desc.append(f"Duration: {duration}")
            
            criteria_text = ", ".join(criteria_desc) if criteria_desc else "No filters applied"
            
            # Create embed
            embed = discord.Embed(
                title=f"🔍 Found {len(matching_routes)} Routes",
                description=f"Filters: {criteria_text}\n\n"
                           f"Here are the top matches:",
                color=0x3498DB
            )
            
            # Show top matches
            display_count = min(5, len(matching_routes))
            for i, route in enumerate(matching_routes[:display_count]):
                # Format time
                est_time = route.get('estimated_time_min', 0)
                time_str = f"{est_time // 60}h {est_time % 60}m" if est_time >= 60 else f"{est_time}m"
                
                # Get badges
                badges = route.get('badges', [])
                badges_str = ", ".join(badges) if badges else "Unknown"
                
                embed.add_field(
                    name=f"{i+1}. {route['route_name']}",
                    value=f"🌎 {route.get('world', 'Unknown')}\n"
                          f"📏 {route.get('distance_km', '?')} km\n"
                          f"⛰️ {route.get('elevation_m', '?')} m\n"
                          f"⏱️ Est. time: {time_str}\n"
                          f"🏷️ {badges_str}\n"
                          f"[View details]({route['url']})",
                    inline=False
                )
            
            # Add note if there are more results
            if len(matching_routes) > display_count:
                embed.set_footer(text=f"Showing top {display_count} of {len(matching_routes)} matches • Ask for more specific criteria to narrow results")
            else:
                embed.set_footer(text="Try asking about a specific route for more details")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(
                title="❌ No Matching Routes",
                description="I couldn't find any routes matching your criteria. Try broadening your search by removing some filters.",
                color=discord.Color.red()
            )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
    async def handle_segment_lookup(self, interaction, intent):
        """
        Handle KOM/sprint segment lookup.
        
        Args:
            interaction: The Discord interaction
            intent: The detected intent with segment_type and segment_name
        """
        segment_type = intent.get('segment_type', 'unknown')
        segment_name = intent.get('segment_name', '')
        
        if not segment_name:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❓ Segment Not Specified",
                    description=f"Please specify a segment name to look up.",
                    color=discord.Color.orange()
                ),
                ephemeral=True
            )
            return
        
        # Find the segment based on type
        if segment_type == 'kom':
            result, alternatives = find_kom(segment_name)
            
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
                embed.set_footer(text="Ask about any KOM or sprint segment")
            else:
                suggestions = random.sample(zwift_koms, min(3, len(zwift_koms)))
                embed = discord.Embed(
                    title="❌ KOM Not Found",
                    description=f"Could not find a KOM segment matching '{segment_name}'.\n\n**Try these segments:**\n" + 
                               "\n".join(f"• {k['Segment']} ({k['Length_km']}km, {k['Grade']}%)" 
                                       for k in suggestions),
                    color=discord.Color.red()
                )
        else:  # Sprint
            result, alternatives = find_sprint(segment_name)
            
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
                embed.set_footer(text="Ask about any KOM or sprint segment")
            else:
                suggestions = random.sample(zwift_sprints, min(3, len(zwift_sprints)))
                embed = discord.Embed(
                    title="❌ Sprint Not Found",
                    description=f"Could not find a sprint segment matching '{segment_name}'.\n\n**Try these segments:**\n" + 
                               "\n".join(f"• {s['Segment']} ({s['Length_m']}m, {s['Grade']}%)" 
                                       for s in suggestions),
                    color=discord.Color.red()
                )

        await interaction.followup.send(embed=embed, ephemeral=True)
    
    async def handle_world_info(self, interaction, intent):
        """
        Handle world information requests.
        
        Args:
            interaction: The Discord interaction
            intent: The detected intent with world_name and sort_by
        """
        world_name = intent.get('world_name', '')
        sort_by = intent.get('sort_by', 'distance')
        
        if not world_name:
            # If no world specified, show list of all worlds
            worlds = ['Watopia', 'London', 'Richmond', 'New York', 'Innsbruck',
                     'Yorkshire', 'France', 'Paris', 'Makuri', 'Scotland']
            
            embed = discord.Embed(
                title="🌍 Zwift Worlds",
                description="Here are the available Zwift worlds. Ask about a specific world to see its routes:",
                color=0x3498DB
            )
            
            worlds_list = "\n".join([f"• {world}" for world in worlds])
            embed.add_field(name="Available Worlds", value=worlds_list, inline=False)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        # Find routes in the specified world
        world_routes = []
        for route_data in self.route_cache_data.values():
            route_world = route_data.get('world', '')
            if world_name.lower() in route_world.lower():
                world_routes.append(route_data)
        
        if not world_routes:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ World Not Found",
                    description=f"Could not find routes for world '{world_name}'.\n\n"
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
            text=f"Try asking about a specific route for more details"
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def handle_route_comparison(self, interaction, routes_to_compare):
        """
        Compare multiple routes side by side.
        
        Args:
            interaction: The Discord interaction
            routes_to_compare: List of route names to compare
        """
        route_data = []
        
        # Get data for each route
        for route_name in routes_to_compare:
            result, _ = find_route(route_name)
            if result:
                # Get detailed info from cache
                detailed_info = self.route_cache_data.get(result['Route'])
                if detailed_info:
                    route_data.append(detailed_info)
                else:
                    # Try to use basic info from route result
                    basic_info = {
                        'route_name': result['Route'],
                        'url': result['URL'],
                        'world': get_world_for_route(result['Route'])
                    }
                    route_data.append(basic_info)
        if len(route_data) < 2:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Comparison Error",
                    description="I couldn't find enough routes to compare. Please specify at least two valid routes.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return
        
        # Create comparison embed
        embed = discord.Embed(
            title=f"🔄 Route Comparison",
            description=f"Comparing {len(route_data)} routes",
            color=0x3498DB
        )
        
        # Add comparison table
        comparison_text = "```\n"
        comparison_text += f"{'Route':<20} | {'Distance':<10} | {'Elevation':<10} | {'Est. Time':<10}\n"
        comparison_text += "-" * 55 + "\n"
        
        for route in route_data:
            name = route['route_name'][:17] + "..." if len(route['route_name']) > 20 else route['route_name']
            distance = f"{route.get('distance_km', '?')} km"
            elevation = f"{route.get('elevation_m', '?')} m"
            
            # Format time
            est_time = route.get('estimated_time_min', 0)
            time_str = f"{est_time // 60}h {est_time % 60}m" if est_time >= 60 else f"{est_time}m"
            
            comparison_text += f"{name:<20} | {distance:<10} | {elevation:<10} | {time_str:<10}\n"
        
        comparison_text += "```"
        embed.add_field(name="Comparison Table", value=comparison_text, inline=False)
        
        # Add badges comparison
        badges_text = ""
        for route in route_data:
            badges = route.get('badges', [])
            badges_text += f"**{route['route_name']}**: {', '.join(badges)}\n"
        
        embed.add_field(name="Route Types", value=badges_text, inline=False)
        
        # Add difficulty comparison (elevation per km)
        difficulty_text = ""
        for route in route_data:
            if 'distance_km' in route and 'elevation_m' in route and route['distance_km'] > 0:
                elev_per_km = route['elevation_m'] / route['distance_km']
                difficulty_text += f"**{route['route_name']}**: {elev_per_km:.1f} m/km\n"
        
        if difficulty_text:
            embed.add_field(name="Climbing Difficulty", value=difficulty_text, inline=False)
        
        # Add direct links to compare
        links_text = ""
        for route in route_data:
            links_text += f"[{route['route_name']}]({route.get('url', '')})\n"
        
        embed.add_field(name="Links", value=links_text, inline=False)
        
        # Send embed with comparison
        await interaction.followup.send(embed=embed, ephemeral=True)
    async def handle_random_route(self, interaction, intent):
        """
        Handle random route requests.
        
        Args:
            interaction: The Discord interaction
            intent: The detected intent with filters
        """
        filters = intent.get('filters', {})
        
        # Get world filter
        world = filters.get('world')
        route_type = filters.get('route_type')
        duration = filters.get('duration')
        
        # Filter routes based on criteria
        filtered_routes = []
        
        for route_name, data in self.route_cache_data.items():
            # Skip routes with missing core data
            if 'distance_km' not in data or 'elevation_m' not in data:
                continue
                
            # World filter
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
            return
        
        # Select a random route
        selected_route = random.choice(filtered_routes)
        route_name = selected_route['route_name']
        logger.info(f"Selected random route: {route_name}")
        
        # Create response embed
        embed = discord.Embed(
            title=f"🎲 Random Route: {route_name}",
            url=selected_route['url'],
            description="Here's a randomly selected route that matches your criteria:",
            color=0x9B59B6
        )
        
        # Format estimated time
        est_time = selected_route.get('estimated_time_min', 0)
        time_str = f"{est_time // 60}h {est_time % 60}m" if est_time >= 60 else f"{est_time}m"
        
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
        
        # Get route world for buttons
        route_world = selected_route.get('world', '')
        
        
        # Send response
        await interaction.followup.send(embed=embed)
    
    async def handle_general_question(self, interaction, question):
        """
        Handle general questions about Zwift.
        
        Args:
            interaction: The Discord interaction
            question: The user's question
        """
        # Provide general information or hints
        embed = discord.Embed(
            title="🚲 Zwift Digital Support",
            description="I'm your Zwift Digital Support assistant. I can help with:\n\n"
                      "• Finding specific routes (e.g., \"Tell me about Alpe Du Zwift\")\n"
                      "• Suggesting routes based on criteria (e.g., \"Find flat routes in Watopia under 20km\")\n"
                      "• Information about KOMs and sprint segments (e.g., \"What is the Box Hill KOM?\")\n"
                      "• Routes in specific worlds (e.g., \"What routes are in London?\")\n"
                      "• Comparing routes (e.g., \"Compare Alpe Du Zwift and Road to Sky\")\n"
                      "• Random route suggestions (e.g., \"Suggest a hilly route\")\n\n"
                      "What would you like to know about Zwift?",
            color=0x3498DB
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)


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
    
    
