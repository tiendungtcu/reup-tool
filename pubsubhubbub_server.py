#!/usr/bin/env python3
"""
PubSubHubbub Server for YouTube Video Notifications
Handles real-time webhook notifications from YouTube when new videos are published.
"""

import asyncio
import aiohttp
from aiohttp import web
import xml.etree.ElementTree as ET
import hashlib
import hmac
import json
import os
import time
import threading
from datetime import datetime
from typing import Dict, List, Optional, Callable
import logging
from urllib.parse import urlparse, parse_qs
import requests

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PubSubHubbubServer:
    """PubSubHubbub server for handling YouTube video notifications."""
    
    def __init__(self, port: int = 8080, ngrok_url: Optional[str] = None):
        self.port = port
        self.ngrok_url = ngrok_url
        self.app = web.Application()
        self.app.router.add_post('/webhook', self.handle_webhook)
        self.app.router.add_get('/webhook', self.handle_verification)
        self.app.router.add_post('/subscribe', self.handle_subscribe)
        self.app.router.add_get('/status', self.handle_status)
        
        # Store subscriptions and callbacks
        self.subscriptions = {}  # channel_id -> subscription_info
        self.video_callbacks = []  # List of callback functions
        self.processed_videos = set()
        
        # Load processed videos
        self.load_processed_videos()
        
        # YouTube PubSubHubbub hub URL (Google's official hub)
        self.hub_url = "https://pubsubhubbub.appspot.com/"
        
        # Webhook secret for verification
        self.webhook_secret = "your_webhook_secret_here"
        
        # Statistics
        self.stats = {
            'notifications_received': 0,
            'videos_processed': 0,
            'subscriptions_active': 0,
            'last_notification': None
        }
    
    def load_processed_videos(self):
        """Load processed videos from file."""
        try:
            if os.path.exists("processed_videos.json"):
                with open("processed_videos.json", 'r') as f:
                    processed = json.load(f)
                    self.processed_videos = set(processed)
                logger.info(f"Loaded {len(self.processed_videos)} processed videos")
        except Exception as e:
            logger.error(f"Error loading processed videos: {e}")
            self.processed_videos = set()
    
    def save_processed_videos(self):
        """Save processed videos to file."""
        try:
            with open("processed_videos.json", 'w') as f:
                json.dump(list(self.processed_videos), f)
        except Exception as e:
            logger.error(f"Error saving processed videos: {e}")
    
    def add_video_callback(self, callback: Callable):
        """Add a callback function to be called when new videos are detected."""
        self.video_callbacks.append(callback)
        logger.info(f"Added video callback. Total callbacks: {len(self.video_callbacks)}")
    
    def get_webhook_url(self) -> str:
        """Get the webhook URL for subscriptions."""
        if self.ngrok_url:
            return f"{self.ngrok_url}/webhook"
        else:
            # For local development, you need ngrok or a public URL
            # YouTube's PubSubHubbub hub requires a publicly accessible URL
            logger.warning("No ngrok URL provided. YouTube requires a publicly accessible webhook URL.")
            logger.warning("Please use --ngrok flag or provide --ngrok-url for testing.")
            return f"http://localhost:{self.port}/webhook"
    
    async def handle_verification(self, request: web.Request) -> web.Response:
        """Handle PubSubHubbub verification requests."""
        try:
            params = dict(request.query)
            mode = params.get('hub.mode')
            topic = params.get('hub.topic')
            challenge = params.get('hub.challenge')
            verify_token = params.get('hub.verify_token')
            
            logger.info(f"Verification request: mode={mode}, topic={topic}")
            
            if mode == 'subscribe' and challenge:
                # Verify the subscription
                if self.verify_subscription(topic, verify_token):
                    logger.info(f"Subscription verified for topic: {topic}")
                    return web.Response(text=challenge)
                else:
                    logger.warning(f"Subscription verification failed for topic: {topic}")
                    return web.Response(status=404)
            else:
                logger.warning(f"Invalid verification request: {params}")
                return web.Response(status=400)
                
        except Exception as e:
            logger.error(f"Error handling verification: {e}")
            return web.Response(status=500)
    
    async def handle_webhook(self, request: web.Request) -> web.Response:
        """Handle incoming webhook notifications from YouTube."""
        try:
            # Get the raw body for signature verification
            body = await request.read()
            
            # Verify the signature if present (optional for YouTube)
            signature = request.headers.get('X-Hub-Signature')
            if signature:
                if not self.verify_signature(body, signature):
                    logger.warning("Invalid webhook signature, but continuing...")
                    # Don't return 401, just log the warning and continue
                else:
                    logger.info("Webhook signature verified successfully")
            
            # Parse the XML content
            xml_content = body.decode('utf-8')
            logger.info(f"Received webhook with content length: {len(xml_content)}")
            videos = self.parse_atom_feed(xml_content)
            
            if videos:
                self.stats['notifications_received'] += 1
                self.stats['last_notification'] = datetime.now().isoformat()
                
                logger.info(f"Received notification with {len(videos)} videos")
                
                # Process each video
                for video in videos:
                    logger.info(f"Processing video: {video['title']} (ID: {video['id']})")
                    
                    if video['id'] not in self.processed_videos:
                        self.processed_videos.add(video['id'])
                        self.stats['videos_processed'] += 1
                        
                        logger.info(f"New video detected: {video['title']}")
                        
                        # Call all registered callbacks
                        for callback in self.video_callbacks:
                            try:
                                if asyncio.iscoroutinefunction(callback):
                                    await callback(video)
                                else:
                                    # Run in thread if it's a sync function
                                    loop = asyncio.get_event_loop()
                                    await loop.run_in_executor(None, callback, video)
                            except Exception as e:
                                logger.error(f"Error in video callback: {e}")
                    else:
                        logger.info(f"Video already processed: {video['title']}")
                
                # Save processed videos
                self.save_processed_videos()
            else:
                logger.info("No videos found in webhook notification")
            
            return web.Response(text="OK")
            
        except Exception as e:
            logger.error(f"Error handling webhook: {e}")
            return web.Response(status=500)
    
    async def handle_subscribe(self, request: web.Request) -> web.Request:
        """Handle subscription requests."""
        try:
            data = await request.json()
            channel_id = data.get('channel_id')
            channel_name = data.get('channel_name', 'Unknown')
            
            if not channel_id:
                return web.json_response({'error': 'channel_id is required'}, status=400)
            
            success = await self.subscribe_to_channel(channel_id, channel_name)
            
            if success:
                return web.json_response({'status': 'subscribed', 'channel_id': channel_id})
            else:
                return web.json_response({'error': 'Failed to subscribe'}, status=500)
                
        except Exception as e:
            logger.error(f"Error handling subscribe request: {e}")
            return web.json_response({'error': str(e)}, status=500)
    
    async def handle_status(self, request: web.Request) -> web.Response:
        """Handle status requests."""
        status_data = {
            'server_status': 'running',
            'webhook_url': self.get_webhook_url(),
            'subscriptions': len(self.subscriptions),
            'stats': self.stats,
            'processed_videos_count': len(self.processed_videos)
        }
        return web.json_response(status_data)
    
    def parse_atom_feed(self, xml_content: str) -> List[Dict]:
        """Parse YouTube's Atom feed XML and extract video information."""
        try:
            logger.info(f"Parsing XML content: {xml_content[:200]}...")  # Log first 200 chars
            
            root = ET.fromstring(xml_content)
            
            # Handle different XML namespaces (following YouTube's official format)
            namespaces = {
                'atom': 'http://www.w3.org/2005/Atom',
                'yt': 'http://www.youtube.com/xml/schemas/2015',
                'media': 'http://search.yahoo.com/mrss/'
            }
            
            videos = []
            
            # Find all entry elements (videos)
            entries = root.findall('.//atom:entry', namespaces)
            logger.info(f"Found {len(entries)} entries in XML feed")
            
            # Log the root element to see the feed structure
            logger.info(f"Feed root tag: {root.tag}")
            logger.info(f"Feed namespaces: {root.nsmap if hasattr(root, 'nsmap') else 'No nsmap'}")
            
            for entry in entries:
                try:
                    # Extract video ID using YouTube's specific elements (following official docs)
                    video_id = None
                    
                    # First try to get video ID from yt:videoId element (YouTube's specific format)
                    yt_video_id_elem = entry.find('yt:videoId', namespaces)
                    if yt_video_id_elem is not None:
                        video_id = yt_video_id_elem.text
                        logger.info(f"Extracted video ID from yt:videoId: {video_id}")
                    else:
                        # Fallback to extracting from link (for compatibility)
                        links = entry.findall('atom:link', namespaces)
                        logger.info(f"Found {len(links)} links in entry")
                        
                        for link in links:
                            href = link.get('href', '')
                            logger.info(f"Processing link: {href}")
                            if 'youtube.com/watch?v=' in href:
                                video_id = href.split('v=')[1].split('&')[0]
                                logger.info(f"Extracted video ID from link: {video_id}")
                                break
                    
                    if not video_id:
                        logger.warning("No video ID found in entry, skipping")
                        continue
                    
                    # Extract title
                    title_elem = entry.find('atom:title', namespaces)
                    title = title_elem.text if title_elem is not None else 'Unknown Title'
                    
                    # Extract published date
                    published_elem = entry.find('atom:published', namespaces)
                    published = published_elem.text if published_elem is not None else ''
                    
                    # Extract channel ID from yt:channelId element (YouTube's specific format)
                    channel_id = None
                    yt_channel_id_elem = entry.find('yt:channelId', namespaces)
                    if yt_channel_id_elem is not None:
                        channel_id = yt_channel_id_elem.text
                        logger.info(f"Extracted channel ID from yt:channelId: {channel_id}")
                    
                    # Extract author
                    author_elem = entry.find('atom:author/atom:name', namespaces)
                    author = author_elem.text if author_elem is not None else 'Unknown Channel'
                    
                    # Extract video URL
                    video_url = f"https://www.youtube.com/watch?v={video_id}"
                    
                    video_data = {
                        'id': video_id,
                        'title': title,
                        'url': video_url,
                        'published': published,
                        'author': author,
                        'channel_id': channel_id,
                        'fetched_at': datetime.now().isoformat()
                    }
                    
                    videos.append(video_data)
                    
                except Exception as e:
                    logger.error(f"Error parsing video entry: {e}")
                    continue
            
            return videos
            
        except Exception as e:
            logger.error(f"Error parsing Atom feed: {e}")
            return []
    
    def verify_signature(self, body: bytes, signature: str) -> bool:
        """Verify the webhook signature."""
        try:
            if not signature.startswith('sha1='):
                return False
            
            # If no secret is configured, skip verification
            if not self.webhook_secret:
                logger.warning("No webhook secret configured, skipping signature verification")
                return True
            
            expected_signature = signature[5:]  # Remove 'sha1=' prefix
            calculated_signature = hmac.new(
                self.webhook_secret.encode('utf-8'),
                body,
                hashlib.sha1
            ).hexdigest()
            
            return hmac.compare_digest(expected_signature, calculated_signature)
            
        except Exception as e:
            logger.error(f"Error verifying signature: {e}")
            return False
    
    def verify_subscription(self, topic: str, verify_token: str) -> bool:
        """Verify subscription parameters."""
        # For now, accept all subscriptions
        # In production, you should implement proper verification
        return True
    
    async def subscribe_to_channel(self, channel_id: str, channel_name: str) -> bool:
        """Subscribe to a YouTube channel for notifications."""
        try:
            # Create the topic URL for the channel (following YouTube's official format)
            topic_url = f"https://www.youtube.com/xml/feeds/videos.xml?channel_id={channel_id}"
            
            # Get webhook URL
            webhook_url = self.get_webhook_url()
            
            # Check if webhook URL is publicly accessible
            if not self.ngrok_url and 'localhost' in webhook_url:
                logger.error("Cannot subscribe without a public webhook URL. Please use ngrok or provide a public URL.")
                return False
            
            logger.info(f"Subscribing to channel: {channel_name} ({channel_id})")
            logger.info(f"Topic URL: {topic_url}")
            logger.info(f"Webhook URL: {webhook_url}")
            
            # Prepare subscription data
            subscription_data = {
                'hub.callback': webhook_url,
                'hub.topic': topic_url,
                'hub.mode': 'subscribe',
                # 'hub.verify': 'async',  # Enable async verification
                # 'hub.verify_token': f"token_{channel_id}_{int(time.time())}",
                # 'hub.secret': self.webhook_secret
            }
            
            logger.info(f"Subscription data: {subscription_data}")
            
            # Send subscription request
            async with aiohttp.ClientSession() as session:
                async with session.post(self.hub_url, data=subscription_data) as response:

                    logger.info(f"Subscription response: {response.status} - {response.reason}")
                    
                    # Accept both 204 (No Content) and 202 (Accepted) as success
                    if response.status in [204, 202]:
                        # Store subscription info
                        self.subscriptions[channel_id] = {
                            'name': channel_name,
                            'topic_url': topic_url,
                            'subscribed_at': datetime.now().isoformat(),
                            'status': 'active'
                        }
                        
                        self.stats['subscriptions_active'] = len(self.subscriptions)
                        
                        logger.info(f"Successfully subscribed to channel: {channel_name} ({channel_id})")
                        return True
                    else:
                        response_text = await response.text()
                        logger.error(f"Failed to subscribe to {channel_id}: {response.status} - {response_text}")
                        return False
                        
        except Exception as e:
            logger.error(f"Error subscribing to channel {channel_id}: {e}")
            return False
    
    async def unsubscribe_from_channel(self, channel_id: str) -> bool:
        """Unsubscribe from a YouTube channel."""
        try:
            if channel_id not in self.subscriptions:
                logger.warning(f"Channel {channel_id} not found in subscriptions")
                return False
            
            subscription_info = self.subscriptions[channel_id]
            
            # Prepare unsubscription data
            unsubscription_data = {
                'hub.callback': self.get_webhook_url(),
                'hub.topic': subscription_info['topic_url'],
                'hub.verify': 'async',
                'hub.mode': 'unsubscribe',
                'hub.verify_token': f"token_{channel_id}_{int(time.time())}",
                'hub.secret': self.webhook_secret
            }
            
            # Send unsubscription request
            async with aiohttp.ClientSession() as session:
                async with session.post(self.hub_url, data=unsubscription_data) as response:
                    logger.info(f"Unsubscription response: {response.status} - {response.reason}")
                    
                    # Accept both 204 (No Content) and 202 (Accepted) as success
                    if response.status in [204, 202]:
                        del self.subscriptions[channel_id]
                        self.stats['subscriptions_active'] = len(self.subscriptions)
                        
                        logger.info(f"Successfully unsubscribed from channel: {channel_id}")
                        return True
                    else:
                        response_text = await response.text()
                        logger.error(f"Failed to unsubscribe from {channel_id}: {response.status} - {response_text}")
                        return False
                        
        except Exception as e:
            logger.error(f"Error unsubscribing from channel {channel_id}: {e}")
            return False
    
    async def start_server(self):
        """Start the PubSubHubbub server."""
        runner = web.AppRunner(self.app)
        await runner.setup()
        
        site = web.TCPSite(runner, '0.0.0.0', self.port)
        await site.start()
        
        logger.info(f"PubSubHubbub server started on port {self.port}")
        logger.info(f"Webhook URL: {self.get_webhook_url()}")
        
        if self.ngrok_url:
            logger.info(f"Using ngrok URL: {self.ngrok_url}")
        
        return runner
    
    async def stop_server(self, runner):
        """Stop the PubSubHubbub server."""
        await runner.cleanup()
        logger.info("PubSubHubbub server stopped")

# Utility functions for ngrok integration
def get_ngrok_url() -> Optional[str]:
    """Get the ngrok public URL."""
    try:
        response = requests.get('http://localhost:4040/api/tunnels')
        tunnels = response.json()['tunnels']
        
        for tunnel in tunnels:
            if tunnel['proto'] == 'https':
                return tunnel['public_url']
        
        return None
    except Exception as e:
        logger.error(f"Error getting ngrok URL: {e}")
        return None

def start_ngrok_tunnel(port: int = 8080) -> Optional[str]:
    """Start ngrok tunnel for the specified port."""
    try:
        import subprocess
        import time
        
        # Start ngrok in background with hidden console window (Windows)
        if hasattr(subprocess, 'STARTUPINFO'):  # Windows only
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            process = subprocess.Popen([
                'ngrok', 'http', str(port),
                '--log=stdout'
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
        else:
            process = subprocess.Popen([
                'ngrok', 'http', str(port),
                '--log=stdout'
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # Wait a bit for ngrok to start
        time.sleep(3)
        
        # Get the public URL
        ngrok_url = get_ngrok_url()
        
        if ngrok_url:
            logger.info(f"ngrok tunnel started: {ngrok_url}")
            return ngrok_url
        else:
            logger.error("Failed to get ngrok URL")
            return None
            
    except Exception as e:
        logger.error(f"Error starting ngrok: {e}")
        return None

async def main():
    """Main function to run the PubSubHubbub server."""
    import argparse
    
    parser = argparse.ArgumentParser(description='PubSubHubbub Server for YouTube')
    parser.add_argument('--port', type=int, default=8080, help='Server port')
    parser.add_argument('--ngrok', action='store_true', help='Start ngrok tunnel')
    parser.add_argument('--ngrok-url', type=str, help='Use existing ngrok URL')
    
    args = parser.parse_args()
    
    # Start ngrok if requested
    ngrok_url = args.ngrok_url
    if args.ngrok and not ngrok_url:
        ngrok_url = start_ngrok_tunnel(args.port)
    
    # Create and start server
    server = PubSubHubbubServer(port=args.port, ngrok_url=ngrok_url)
    runner = await server.start_server()
    
    try:
        # Keep the server running
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
    finally:
        await server.stop_server(runner)

if __name__ == "__main__":
    asyncio.run(main())
