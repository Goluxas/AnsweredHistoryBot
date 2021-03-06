"""
Bot for /r/AnsweredHistory by /u/Goluxas

Scans /r/AskHistorians for answers within posts and reposts them as
links to /r/AnsweredHistory.

This bot was inspired by the "comment graveyards" that are (in)famous
in /r/AskHistorians, due to their strict commenting policy. It is impossible
to tell before you click a thread whether or not there is an answer.

The moderation team has reasonable concerns about adding an [Answered] tag
for posts, so I created this bot as an alternative.
"""
from datetime import datetime
import time, os, json
import logging

import praw
import OAuth2Util

VERSION = '1.0'
USER_AGENT = "com.goluxas.AnsweredHistoryBot:v%s (by /u/Goluxas)" % VERSION
LOGFILE = 'answeredhistorybot.log'

# the minimum number of characters an answer 
# is expected to have (if i come up with a 
# better solution this will be deprecated)
MIN_CHARS = 300 
WAIT_TIME = 30 # minutes

META_POST_TITLE = u'Answers for "%s" (/u/%s)'

DEBUG = True

logging.basicConfig(filename=LOGFILE, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %I:%M:%S')
logger = logging.getLogger(__name__)

if DEBUG:
	logger.setLevel(logging.DEBUG)
else:
	logger.setLevel(logging.INFO)

def find_answers(post):
	answers = []

	logger.info('-- Scanning for answers')
	try:
		for c in post.comments:
			try:
				status = None
				# obviously ignore removed comments
				#if u'removed' in unicode(c.body): # no idea why this doesn't work, but it doesn't
				if len(c.body) == 9:
					status = 'Removed'

				# ignore distinguished moderator posts
				if c.distinguished: 
					status = 'Distinguished'

				# ignore follow-up questions
				# not ENTIRELY sure the best way to do this
				# for now, posts with less than MIN_CHARS are considered non-answers
				if len(c.body) < MIN_CHARS:
					status = 'Under Minimum Length (%d of %d chars)' % (len(c.body), MIN_CHARS)

				# ignore posts that are less than 30m old
				# (to give mods time to react)
				age = (datetime.now() - datetime.fromtimestamp( c.created_utc )).seconds / 60
				if age < 30:
					status = 'Under Minimum Age (%d of %d minutes)' % (age, 30)

				if status:
					logger.info(u'---- SKIPPED: %s (/u/%s)' % (status, unicode(c.author).encode('ascii', 'replace')))
				else:
					logger.info(u'---- ANSWER FOUND: "%s..." (/u/%s)' % (c.body[:25].encode('ascii', 'replace'), unicode(c.author).encode('ascii','replace')))
					# anything left is potentially an answer
					answers.append(c)

			except AttributeError:
				# hit a MoreComments, so just skip it
				logger.info('---- SKIPPED: MoreComments')
				continue
	except:
		logger.info('---- SKIPPED: PRAW Exception.')
		return []

	return answers

def sanitize_body(answer_body):
	body = answer_body[:200]
	body = body.replace('\n\n', '\n\n>')
	
	return body

def post_reply(r, sub, title, text):
	tries = 5
	while tries > 0:
		success = True
		try:
			post = r.submit(sub, title, text=text)
		except:
			success = False
			tries -= 1
		finally:
			if success:
				return post

	# if it failed to submit all 5 times, raise an exception
	raise Exception

def post_answer_comment(post, answer):
	# post each answer as a top-level comment that links to the original post
	# ie.
	"""
	[Goluxas replies:](link to comment)

	> First 80 characters of response...
	"""

	# not using /u/ notation because that sends a notification to the author every time
	body = sanitize_body(answer.body)
	text = u'[%s replies:](%s)\n\n> %s...' % (answer.author, answer.permalink, body)

	tries = 5
	while tries > 0:
		success = True
		try:
			post.add_comment(text)
		except:
			success = False
			tries -= 1
		finally:
			if success:
				return post
		logger.info('---- Failed to post answer comment. (%d retries left.)' % tries)

	# if it failed to submit all 5 times, raise an exception
	raise Exception

if __name__ == '__main__':
	# thread_id: previous comment count
	scanned = {} # k,v = AskHistorians thread id, number of comments on last scan
	posted = {} # k,v = AskHistorians thread id, [answer ids]
	posts = {} # k, v = AskHistorians thread id, corresponding meta post object
	
	post_ids = [] # used by history.json, will be expanded into full posts if it's read

	# read history file
	# maybe i can just read in the relevant data for the posts
	# that get scanned
	if os.path.isfile('history.json'):
		logger.info('History file found. Loading...')
		with open('history.json', 'r') as infile:
			data = json.load(infile)
		scanned = data['scanned']
		posted = data['posted']
		post_ids = data['post_ids']
		logger.info('History loaded. %d scanned posts. %d posts with answers.' % (len(scanned), len(posted)))
	else:
		logger.info('Initializing history file...')
		with open('history.json', 'w') as outfile:
			data = {'scanned': {}, 'posted': {}, 'post_ids': {} }
			json.dump(data, outfile)
		logger.info('History initialized')

	logger.info('Bot initiated')

	r = praw.Reddit(user_agent=USER_AGENT)

	# authenticate
	o = OAuth2Util.OAuth2Util(r)
	logger.info('Authenticated')

	""" Shouldn't need this anymore
	if len(post_ids) > 0:
		logger.info('Loading previous posts')
		ah = r.get_subreddit('askhistorians')
		posts = { cid: r.get_submission(submission_id=pid) for cid, pid in post_ids.iteritems() }
	"""

	try:
		while True:
			# keep the auth token alive
			o.refresh()

			ah = r.get_subreddit('askhistorians')

			if DEBUG:
				answers_sub = r.get_subreddit('afh_meta')
			else:
				answers_sub = r.get_subreddit('answeredhistory')

			logger.info('Scanning posts...')

			for post in ah.get_hot(limit=50):
				logger.info(u'Post: %s - by %s' % (post.title.encode('ascii', 'replace'), unicode(post.author).encode('ascii', 'replace')))

				status = None
				# if it's a meta post, skip it
				if (post.link_flair_text and \
					(post.link_flair_text.lower() == 'meta' or \
					 post.link_flair_text.lower() == 'feature')) or \
					 '[meta]' in post.title.lower():
						status = 'Meta/Feature Post'

				# if it's a distinguished mod post, skip it
				if post.distinguished:
					status = 'Distinguished Post'

				# if there's no comments, skip it
				if post.num_comments == 0:
					status = 'No Comments'

				# if there's been no change in comments since last scan, skip it
				if post.id in scanned and post.num_comments == scanned[post.id]:
					status = 'No Change Since Last Scan'

				scanned[post.id] = post.num_comments
				
				if status:
					logger.info('-- SKIPPED: %s' % status)
					continue

				# otherwise, look for answers
				answers = find_answers(post)
				logger.info('-- %d answer(s) found' % len(answers))

				if len(answers) == 0:
					logger.info('-- SKIPPED')
					continue

				# if there are any answers, make a thread for the post
				if post.id not in posts:
					if post.id in post_ids:
						# if it was in post_ids, load the post
						posts[post.id] = r.get_submission(submission_id=post.id)
					else:
						# otherwise, make a new post for the thread
						post_title = META_POST_TITLE % (post.title, post.author)
						if len(post_title) > 300:
							# +4 to make up for the two %s clusters in the format string
							# -3 to make room for the ellipses
							max_title_length = 300 - len(META_POST_TITLE) + 4 - len(str(post.author)) - 3
							post_title = META_POST_TITLE % (post.title[:max_title_length] + '...', post.author)
						post_text = '[ORIGINAL THREAD](%s)' % post.short_link
						try:
							posts[post.id] = post_reply(r, answers_sub, post_title, post_text)
						except:
							logger.info('-- SKIPPED: Too many retries to post meta thread')
							continue

				#import pdb; pdb.set_trace()
				# check for answers from a previous scan
				if post.id in posted:
					prev_answers = list(posted[post.id]) # using list() to copy the list
					logger.info('-- %d answer(s) previously found' % len(prev_answers))
				else:
					prev_answers = []

				logger.info('---- Posting answers...')
				for a in answers:
					# check if it's already been posted
					if a.id not in prev_answers:
						try:
							post_answer_comment(posts[post.id], a)
						except:
							logger.info('----- SKIPPED: Out of retries.')
							continue

						if post.id in posted:
							posted[post.id].append(a.id)
						else:
							posted[post.id] = [a.id]

						logger.info(u'---- New answer from /u/%s' % unicode(a.author).encode('ascii','replace'))

					else:
						prev_answers.remove(a.id)
						logger.info('---- Answer previously found')

				if len(answers) == 0:
					logger.info('-- No answers found')
				else:
					logger.info('-- Answers processed')

				# anything left in prev_answers failed to meet the answer criteria
				# (it was probably deleted)
				if len(prev_answers) > 0:
					logger.info('-- %d previous answer(s) not found' % len(prev_answers))
				for missing in prev_answers:
					# TODO - delete or replace text with [deleted] on original comment
					#posts[a.id].set_flair('DELETED') -- will no longer work
					#logger.info(u'-- Marked as Deleted: %s' % posts[a.id].title
					logger.info('SHOULD BE MARKED DELETED: %s' % missing)
					
			logger.info('Scan complete')

			# write posted answers to history file
			with open('history.json', 'w') as outfile:
				post_ids = { answer_id: post.id for answer_id, post in posts.iteritems() }
				data = {'scanned': scanned,
						'posted': posted,
						'post_ids': post_ids}
				json.dump(data, outfile)
			logger.info('History updated')

			# TODO - scan inbox for missed answers

			logger.info('Waiting %d minutes...' % WAIT_TIME)
			# wait 15 minutes
			time.sleep(60 * WAIT_TIME)

	# Catch-all exception so we can write out the history even if it crashes for some reason
	except:
		import sys, traceback
		exc_type, exc_value, exc_traceback = sys.exc_info()
		traceback.print_exception(exc_type, exc_value, exc_traceback, file=sys.stdout)

		with open('history.json', 'w') as outfile:
			post_ids = { ah_thread_id: post.id for ah_thread_id, post in posts.iteritems() }
			data = {'scanned': scanned,
					'posted': posted,
					'post_ids': post_ids}
			json.dump(data, outfile)
		
