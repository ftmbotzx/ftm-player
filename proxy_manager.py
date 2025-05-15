# ###############################################################
# #                                                             #
# #              Proxy Manager for Spotify Bot                  #
# #                Copyright © ftmdeveloperz                    #
# #                     #ftmdeveloperz                          #
# #                                                             #
# ###############################################################

import os
import json
import random
import logging
from typing import List, Dict, Optional, Union
from datetime import datetime, timedelta

# Set up logging
logger = logging.getLogger(__name__)

class ProxyManager:
    """
    Manage a pool of proxies for rotating between requests to avoid IP blocks.
    This class handles proxy rotation, tracking failures, and cooldown periods.
    """
    
    def __init__(self, proxy_file: str = "proxies.json", cooldown_minutes: int = 30):
        """
        Initialize the proxy manager
        
        Args:
            proxy_file: Path to JSON file containing proxies
            cooldown_minutes: Minutes to wait after a proxy failure before using it again
        """
        self.proxy_file = proxy_file
        self.cooldown_minutes = cooldown_minutes
        self.proxies = []
        self.failed_proxies = {}  # proxy_url -> last_failure_time
        self.load_proxies()
    
    def load_proxies(self) -> None:
        """Load proxies from the configuration file"""
        try:
            if os.path.exists(self.proxy_file):
                with open(self.proxy_file, 'r') as f:
                    data = json.load(f)
                    self.proxies = data.get('proxies', [])
                logger.info(f"Loaded {len(self.proxies)} proxies from {self.proxy_file}")
            else:
                logger.warning(f"Proxy file {self.proxy_file} not found. Using no proxies.")
                self.proxies = []
        except Exception as e:
            logger.error(f"Error loading proxies: {e}")
            self.proxies = []
    
    def get_proxy(self) -> Optional[Dict[str, str]]:
        """
        Get a random available proxy that isn't on cooldown
        
        Returns:
            Dict with proxy configuration or None if no proxies available
        """
        # Clean up old failures first
        self._clean_failed_proxies()
        
        # Get eligible proxies (not currently in failure cooldown)
        available_proxies = [
            p for p in self.proxies 
            if p['url'] not in self.failed_proxies
        ]
        
        if not available_proxies:
            # If no proxies are available, check if we can use any failed ones
            # that have the oldest failure timestamps
            if self.failed_proxies:
                # Use least recently failed proxy if we have to
                oldest_failed = min(
                    self.failed_proxies.items(), 
                    key=lambda x: x[1]
                )[0]
                
                # Find the proxy in our list
                for p in self.proxies:
                    if p['url'] == oldest_failed:
                        logger.warning(f"Using recently failed proxy {oldest_failed} as no others available")
                        return p
            
            # No proxies available at all
            logger.warning("No proxies available")
            return None
        
        # Choose a random proxy from available ones
        proxy = random.choice(available_proxies)
        logger.info(f"Using proxy: {proxy['url']}")
        return proxy
    
    def yt_dlp_proxy_settings(self, proxy: Optional[Dict[str, str]] = None) -> Dict[str, Union[str, bool]]:
        """
        Generate yt-dlp proxy settings dictionary
        
        Args:
            proxy: Optional proxy to use, if None will get a new one
            
        Returns:
            Dictionary with yt-dlp proxy settings
        """
        if proxy is None:
            proxy = self.get_proxy()
            
        # If we still don't have a proxy, return empty settings
        if not proxy:
            logger.warning("No proxy available for yt-dlp")
            return {}
            
        # Format based on proxy type
        proxy_url = proxy['url']
        proxy_type = proxy.get('type', 'http').lower()
        
        # Build yt-dlp proxy arguments
        proxy_args: Dict[str, Union[str, bool]] = {
            'proxy': proxy_url
        }
        
        # Add authentication if provided
        if 'username' in proxy and 'password' in proxy:
            # yt-dlp handles auth in the proxy URL for certain proxy types
            if proxy_type in ['http', 'https']:
                auth_proxy = proxy_url.replace('://', f'://{proxy["username"]}:{proxy["password"]}@')
                proxy_args['proxy'] = auth_proxy
            else:
                username = proxy.get('username')
                password = proxy.get('password')
                if username is not None:
                    proxy_args['proxy_username'] = username
                if password is not None:
                    proxy_args['proxy_password'] = password
        
        return proxy_args
    
    def report_failure(self, proxy_url: str) -> None:
        """
        Report a proxy as failed to put it on cooldown
        
        Args:
            proxy_url: The URL of the failed proxy
        """
        logger.warning(f"Marking proxy as failed: {proxy_url}")
        self.failed_proxies[proxy_url] = datetime.now()
    
    def report_success(self, proxy_url: str) -> None:
        """
        Report a proxy as successful to remove from cooldown
        
        Args:
            proxy_url: The URL of the successful proxy
        """
        if proxy_url in self.failed_proxies:
            logger.info(f"Removing proxy from failure list: {proxy_url}")
            del self.failed_proxies[proxy_url]
    
    def _clean_failed_proxies(self) -> None:
        """Remove proxies from the failed list if their cooldown has expired"""
        now = datetime.now()
        cooldown_delta = timedelta(minutes=self.cooldown_minutes)
        
        # Create list of proxies to remove (can't modify dict during iteration)
        to_remove = []
        
        for proxy_url, failure_time in self.failed_proxies.items():
            if now - failure_time > cooldown_delta:
                to_remove.append(proxy_url)
        
        # Remove expired cooldowns
        for proxy_url in to_remove:
            logger.info(f"Proxy cooldown expired: {proxy_url}")
            del self.failed_proxies[proxy_url]
    
    def add_proxy(self, proxy_url: str, proxy_type: str = "http", 
                 username: Optional[str] = None, password: Optional[str] = None) -> None:
        """
        Add a new proxy to the pool
        
        Args:
            proxy_url: The proxy URL (e.g., "http://proxy.example.com:8080")
            proxy_type: The proxy type (http, https, socks4, socks5)
            username: Optional proxy username
            password: Optional proxy password
        """
        new_proxy = {
            "url": proxy_url,
            "type": proxy_type
        }
        
        if username and password:
            new_proxy["username"] = username
            new_proxy["password"] = password
        
        # Check if proxy already exists
        for existing in self.proxies:
            if existing["url"] == proxy_url:
                return  # Already exists
        
        # Add new proxy
        self.proxies.append(new_proxy)
        self.save_proxies()
        logger.info(f"Added new proxy: {proxy_url}")
    
    def remove_proxy(self, proxy_url: str) -> bool:
        """
        Remove a proxy from the pool
        
        Args:
            proxy_url: The proxy URL to remove
            
        Returns:
            True if proxy was removed, False if not found
        """
        for i, proxy in enumerate(self.proxies):
            if proxy["url"] == proxy_url:
                self.proxies.pop(i)
                self.save_proxies()
                
                # Also remove from failed list if present
                if proxy_url in self.failed_proxies:
                    del self.failed_proxies[proxy_url]
                    
                logger.info(f"Removed proxy: {proxy_url}")
                return True
        
        logger.warning(f"Proxy not found for removal: {proxy_url}")
        return False
    
    def save_proxies(self) -> None:
        """Save current proxy list to configuration file"""
        try:
            with open(self.proxy_file, 'w') as f:
                json.dump({"proxies": self.proxies}, f, indent=2)
            logger.info(f"Saved {len(self.proxies)} proxies to {self.proxy_file}")
        except Exception as e:
            logger.error(f"Error saving proxies: {e}")


# Create a global instance for use throughout the application
proxy_manager = ProxyManager()