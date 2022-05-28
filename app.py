import instagrapi
from instagrapi.exceptions import UserNotFound, PleaseWaitFewMinutes, LoginRequired

import os
import PIL
import sys
import json
import time
import dotenv
import pickle
import requests
import traceback
from pathlib import Path

import logging
from logging.handlers import TimedRotatingFileHandler


if not "logs" in os.listdir(): os.mkdir("logs")
if not "sessions" in os.listdir(): os.mkdir("sessions")
if not "downloads" in os.listdir(): os.mkdir("downloads")
if not "users_preferences.json" in os.listdir(): open('users_preferences.json', 'w').write('{}')


dotenv.load_dotenv()

sys.setrecursionlimit(10**6)

# Silence other loggers
for log_name, log_obj in logging.Logger.manager.loggerDict.items():
	 if log_name != __name__:
		  log_obj.disabled = True

logging.basicConfig(
	format='%(asctime)s %(levelname)-8s %(message)s',
	level=logging.DEBUG,
	datefmt='%Y-%m-%d %H:%M:%S'
)
if not "logs" in os.listdir(): os.mkdir("logs")
handler = TimedRotatingFileHandler("logs/igdl.log", when="midnight", interval=1)
handler.suffix = "%Y%m%d"
formatter = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s")
handler.setFormatter(formatter)
logger = logging.getLogger(__name__)
logger.addHandler(handler)



class InstagramDownloader:
	def __init__(self, username: str, password: str):
		self.username = username
		session_path = Path(f"sessions/{self.username}")

		if os.path.exists(session_path):
			with open(session_path, "rb") as f:
				# I would like to be able to encrypt the data.. but how?
				self.session = pickle.load(f, encoding="utf-8")
		else:
			self.session = {}

		self.bot = instagrapi.Client(settings=self.session)
		try:
			self.bot.login(username, password)
		except:
			self.bot = instagrapi.Client()
			self.bot.login(username, password)


		try:
			self.bot_account = self.bot.account_info()
		except LoginRequired:
			logger.warning("Login in again! Invalid session -> instagrapi.exceptions.LoginRequired was raised..")

			return InstagramDownloader(username=username, password=password, fresh_login=True)


		self.session = self.bot.get_settings()
		with open(session_path, "wb") as f:
			# I would like to be able to encrypt the data.. but how?
			pickle.dump(self.session, f)

		self.running = True
		self.temp_dl_path = Path('downloads/')

		logger.info("Logged in")

	def start(self, **kwargs):
		self.checkForNewThreadMessages(**kwargs)


	def checkForNewThreadMessages(self, every: int=20, _429ed: int=0):
		while self.running:
			logger.debug("Checking for new messages")

			try:
				new = self.bot.direct_threads(selected_filter="unread")
				new += self.bot.direct_pending_inbox()
			except Exception as e:
				if isinstance(e, PleaseWaitFewMinutes):
					logger.error("Rate limited.. Sleeping for a while")
				else:
					logger.critical("%s", str(e))


				_429ed += 1
				time.sleep(every*(5+_429ed))

				return self.checkForNewThreadMessages(every=every, _429ed=_429ed)

			if new: logger.info("Found %s threads with unread message(s)", len(new))
			else: logger.debug("No unread messages")

			for thread in new:
				self.handleNewThreadMessages(thread)

			time.sleep(every)

			# Delete previous check medias
			[f.unlink() for f in Path("downloads").glob("*") if f.is_file()]

			# Re-loop
			self.checkForNewThreadMessages(every=every)

	def handleNewThreadMessages(self, thread):
		unread_msgs = []
		for msg in thread.messages:
			if str(msg.user_id) == str(self.bot_account.pk):
				# If message is from bot, let's suppose that everything older than this message
				# was already seen and handled.
				# Had to do this check in order to not handle multiple times raven_media s
				break

			try:
				if msg.id == thread.last_seen_at[self.bot_account.pk]['item_id']:
					# For an unknown reason, if item_type is raven_media,
					# the last_seen_at obj update itself to msg id even if not really seen
					if msg.item_type != "raven_media":
						break
					else:
						# OR it has been seen for real (but not yet by bot, like, just manually)
						if msg.visual_media['seen_count'] > 0:
							break
			except:
				# Bot never seens the conversation?
				pass#continue

			unread_msgs.append(msg)


		for i,msg in enumerate(reversed(unread_msgs)): #From older to newer instead of latest to oldest
			try:
				if msg.item_type == "text":
					self.handleText(msg)
				elif msg.item_type == "link":
					self.handleLink(msg)
				elif msg.item_type == "animated_media":
					self.handleSticker(msg)
				elif msg.item_type == "media":
					self.handleMedia(msg)
				
				elif msg.item_type == "felix_share":
					self.handleIGTV(msg)
				elif msg.item_type == "media_share":
					self.handleSharedPost(msg)
				elif msg.item_type == "clip":
					self.handleReel(msg)
				elif msg.item_type == "story_share":
					self.handleStory(msg)
				elif msg.item_type == "raven_media":
					self.handleTempPicture(msg)

				elif msg.item_type == "placeholder":
					self.handleUnavailableThing(msg)
				elif msg.item_type == "action_log":
					pass

				else:
					print(msg.item_type, msg.timestamp)
					print(msg)

			except Exception as e:
				logger.error(e)

				if str(e) == "Transcode not finished yet.":
					thread.messages = thread.messages[i:]
					return self.handleNewThreadMessages(thread)

				else:
					raise e

		self.bot.direct_send_seen(thread.id)
		#except: self.bot.direct_answer(thread.id, f"Hello! I am @{self.bot_account.username}\nCheck me out!")


	def handleText(self, msg):
		logger.debug("Handling a text message from %s on %s", msg.user_id, msg.thread_id)

		text = False
		is_command = False

		words = msg.text.split()


		if msg.text[0] == "/":
			is_command = True
			command = msg.text.split()[0][1:].lower()
			args = msg.text.split()[1:]


		if not is_command:
			if "help" in words:
				text = "Hi! I am @ghrlt.downloader and I'm a bot.\n@gahrlt made me in order to allow any Instagram user to download any content they want to save, easily, securely and in an asynchronous way.\n\nYou browse content, you send me some, and once you ended your browsing session, you download the content I sent you back!"
			elif "donation" in words or "support" in words:
				text = "Hey! If you would like to support me (@gahrlt), don't hesitate to send me a dm.\nIt would means a lot to me 💖"

			elif ("not" in words and "working" in words) or "bug" in words:
				text = "Did you just encounter a problem? If so, contact me here -> @gahrlt"

		else:
			if command == "sendback":
				if args[0] == "link":
					self.editUserPreferences(
						msg.user_id, {"send_link_to_media_instead_of_media": True}
					)
					text = "Successfully updated your preferences."

				elif args[0] == "media":
					self.editUserPreferences(
						msg.user_id, {"send_link_to_media_instead_of_media": False}
					)
					text = "Successfully updated your preferences."

				else:
					text = f"Unknow parameter {args[0]} for /{command}"

		
		if text: dm = self.bot.direct_answer(msg.thread_id, text)

		logger.debug("Handled a text message from %s on %s! (%s)", msg.user_id, msg.thread_id, "replied smth" if text else "ignored msg")

	def handleLink(self, msg):
		logger.debug("Handling a link message from %s on %s", msg.user_id, msg.thread_id)

		print(msg)

	def handleTempPicture(self, msg):
		logger.debug("Handling a raven_media from %s on %s", msg.user_id, msg.thread_id)
		
		if msg.visual_media['media'].get('id'): #Not seen yet
			is_video = False
			img = msg.visual_media['media']['image_versions2']['candidates'][0]['url']
	
			if msg.visual_media['media']['video_versions']:
				is_video = True
				video = msg.visual_media['media']['video_versions'][0]['url']

			if self.getUserPreferences(msg.user_id).get('send_link_to_media_instead_of_media'):
				dm = self.bot.direct_send(img if not is_video else video, thread_ids=[msg.thread_id])
				logger.debug("Obtained and sent back a link to raven_media to %s", msg.thread_id)

			else:
				if is_video:
					path = self.bot.video_download_by_url(video, folder=self.temp_dl_path)

					dm = self.bot.direct_send_video(path, thread_ids=[msg.thread_id])
				else:
					path = self.bot.photo_download_by_url(img, folder=self.temp_dl_path)
					if str(path).endswith('.webp'):
						new_path = str(path).split('.')[0] + ".jpg"
						im = PIL.Image.open(path).convert('RGB')
						im.save(new_path, "JPEG")

						path = new_path

					dm = self.bot.direct_send_photo(path, thread_ids=[msg.thread_id])
				
				logger.debug("Downloaded and sent back a raven_media to %s", msg.thread_id)

			
			# UNABLE TO MARK AS READ....
			#r = self.bot.private.request(
			#	"GET",
			#	msg.visual_media['media']['image_versions2']['candidates'][0]['fallback']['url']
			#)
			#print(r, r.content) #<Response [400]> b'{"message":"can\'t load media","status":"fail"}'

	def handleSticker(self, msg):
		logger.debug("Handling a sticker sent by %s on %s", msg.user_id, msg.thread_id)

		url = msg.animated_media['images']['fixed_height']['mp4']
		
		if self.getUserPreferences(msg.user_id).get('send_link_to_media_instead_of_media'):
			dm = self.bot.direct_send(url, thread_ids=[msg.thread_id])

			logger.debug("Obtained and sent back a link to sticker to %s", msg.thread_id)
		else:
			fp = f"{self.temp_dl_path}/{msg.animated_media['id']}.mp4"

			r = requests.get(url).content
			with open(fp, 'wb') as f:
				f.write(r)

			dm = self.bot.direct_send_video(fp, thread_ids=[msg.thread_id])
		
			logger.info("Downloaded and sent back a sticker to %s", msg.thread_id)

	def handleUnavailableThing(self, msg):
		logger.debug("Handling a placeholder message from %s on %s", msg.user_id, msg.thread_id)

		if msg.placeholder['title'] == "Post Unavailable":
			self.bot.direct_answer(msg.thread_id, msg.placeholder['message'])
		else:
			logging.critical("%s - %s | %s", msg.user_id, msg.thread_id, msg.placeholder)

		logger.debug("Handled placeholder message from %s on %s", msg.user_id, msg.thread_id)

	def handleMedia(self, msg):
		logger.debug("Handling a media sent by %s on %s", msg.user_id, msg.thread_id)

		dm = self.bot.direct_answer(msg.thread_id, "Here it is lol ↗")

		logger.info("Replied to %s who wanted me to download a normal media", msg.user_id)

	def handleSharedPost(self, msg):
		logger.debug("Handling a post sent by %s on %s", msg.user_id, msg.thread_id)
		
		dms = []
		path = None
		
		if msg.media_share.media_type == 1:
			url = self.bot.media_info(msg.media_share.pk).thumbnail_url

			if self.getUserPreferences(msg.user_id).get('send_link_to_media_instead_of_media'):
				dms.append( self.bot.direct_send(url, thread_ids=[msg.thread_id]) )
			else:
				path = self.bot.photo_download_by_url(url, self.temp_dl_path)
				dms.append( self.bot.direct_send_photo(path, thread_ids=[msg.thread_id]) )

		elif msg.media_share.media_type == 2:
			url = self.bot.media_info(msg.media_share.pk).video_url

			if self.getUserPreferences(msg.user_id).get('send_link_to_media_instead_of_media'):
				dms.append(self.bot.direct_send(url, thread_ids=[msg.thread_id]) )
			else:
				path = self.bot.video_download_by_url(url, self.temp_dl_path)
				dms.append( self.bot.direct_send_video(path, thread_ids=[msg.thread_id]) )

		elif msg.media_share.media_type == 8:
			if self.getUserPreferences(msg.user_id).get('send_link_to_media_instead_of_media'):
				media = self.bot.media_info(msg.media_share.pk)
				for resource in media.resources:
					if resource.media_type == 1:
						dms.append( self.bot.direct_send(resource.thumbnail_url, thread_ids=[msg.thread_id]) )

					elif resource.media_type == 2:
						dms.append( self.bot.direct_send(resource.video_url, thread_ids=[msg.thread_id]) )

			else:
				paths = self.bot.album_download(msg.media_share.pk, self.temp_dl_path)

				for path in paths:
					if str(path).endswith('.mp4'):
						try: dms.append( self.bot.direct_send_video(path, thread_ids=[msg.thread_id]) )
						except: dms.append( self.bot.direct_send_video(path, thread_ids=[msg.thread_id]) )

					elif str(path).endswith('.jpg'):
						dms.append( self.bot.direct_send_photo(path, thread_ids=[msg.thread_id]) )

					elif str(path).endswith('.webp'):				
						new_path = str(path).split('.')[0] + ".jpg"

						im = PIL.Image.open(path).convert('RGB')
						im.save(new_path, "JPEG")

						path = new_path

						dms.append( self.bot.direct_send_photo(path, thread_ids=[msg.thread_id]) )

					else:
						logger.critical("WTF - Unknown file format downloaded... %s", path)


		if self.getUserPreferences(msg.user_id).get('send_link_to_media_instead_of_media'):
			logger.info("Sent back post media link (%s media) to %s", len(dms), msg.thread_id)
		else:
			logger.info("Downloaded and sent back a post (%s media) to %s", len(dms), msg.thread_id)

	def handleReel(self, msg):
		logger.debug("Handling a reel sent by %s on %s", msg.user_id, msg.thread_id)
		
		url = self.bot.media_info(msg.clip.pk).video_url
		if self.getUserPreferences(msg.user_id).get('send_link_to_media_instead_of_media'):
			dm = self.bot.direct_send(url, thread_ids=[msg.thread_id])

			logger.info("Sent back a Reel media link to %s", msg.thread_id)
		else:
			path = self.bot.clip_download_by_url(url, self.temp_dl_path)
			dm = self.bot.direct_send_video(path, thread_ids=[msg.thread_id])

			logger.info("Downloaded and sent back a reel to %s", msg.thread_id)

	def handleIGTV(self, msg):
		logger.debug("Handling an IGTV post sent by %s on %s", msg.user_id, msg.thread_id)


		url = self.bot.media_info(msg.felix_share['video']['pk']).video_url
	
		if self.getUserPreferences(msg.user_id).get('send_link_to_media_instead_of_media'):
			dm = self.bot.direct_send(url, thread_ids=[msg.thread_id])
			
			logger.debug("Obtained and sent back a link to an IGTV post to %s", msg.thread_id)
		else:
			path = self.bot.igtv_download_by_url(url, self.temp_dl_path)
			dm = self.bot.direct_send_video(path, thread_ids=[msg.thread_id])
		
			logger.info("Downloaded and sent back an IGTV post to %s", msg.thread_id)

	def handleStory(self, msg):
		logger.debug("Handling a shared story from %s on %s", msg.user_id, msg.thread_id)

		story = self.bot.story_info(msg.story_share['media']['pk'])
		url = story.video_url or story.thumbnail_url

		if self.getUserPreferences(msg.user_id).get('send_link_to_media_instead_of_media'):
			dm = self.bot.direct_send(url, thread_ids=[msg.thread_id])

			logger.debug("Obtained and sent back a story media link to %s", msg.thread_id)

		else:
			path = self.bot.story_download_by_url(url, folder=self.temp_dl_path)

			if str(path).endswith('.mp4'):
				dm = self.bot.direct_send_video(path, thread_ids=[msg.thread_id])
			elif str(path).endswith('.jpg'):
				dm = self.bot.direct_send_photo(path, thread_ids=[msg.thread_id])
			elif str(path).endswith('.webp'):
				new_path = str(path).split('.')[0] + ".jpg"
				im = PIL.Image.open(path).convert('RGB')
				im.save(new_path, "JPEG")

				path = new_path
				dm = self.bot.direct_send_photo(path, thread_ids=[msg.thread_id])


			logger.debug("Downloaded and sent back story of %s to %s on %s", msg.story_share['media']['user']['pk'], msg.user_id, msg.thread_id)


	""" User preferences """
	def editUserPreferences(self, user_id: str, preferences: dict):
		with open('users_preferences.json', 'r', encoding='utf-8') as f:
			uprefs = json.load(f)

		if not user_id in uprefs.keys():
			uprefs[user_id] = {}

		uprefs[user_id] = {**uprefs[user_id], **preferences} # Order is important! preferences have to overwrite current user preferences

		with open('users_preferences.json', 'w', encoding='utf-8') as f:
			json.dump(uprefs, f, indent=2, ensure_ascii=False)

	def getUserPreferences(self, user_id: str):
		with open('users_preferences.json', 'r', encoding='utf-8') as f:
			uprefs = json.load(f)

		if not isinstance(user_id, str):
			user_id = str(user_id)

		return uprefs.get(user_id) or {}




username, password = os.getenv("instagram_username"), os.getenv("instagram_password")
app = InstagramDownloader(username or input("Username: "), password or input("Password: "))
app.start()
