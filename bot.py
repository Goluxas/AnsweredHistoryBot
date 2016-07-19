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

import praw
import OAuth2Util

VERSION = '1.0'
USER_AGENT = "com.goluxas.AnsweredHistoryBot:v%s (by /u/Goluxas)" % VERSION

# the minimum number of characters an answer 
# is expected to have (if i come up with a 
# better solution this will be deprecated)
MIN_CHARS = 300 
WAIT_TIME = 30 # minutes

DEBUG = True

def find_answers(post):
	answers = []

	print '-- Scanning for answers'
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
				print u'---- SKIPPED: %s (/u/%s)' % (status, unicode(c.author).encode('ascii', 'replace'))
			else:
				print u'---- ANSWER FOUND: "%s..." (/u/%s)' % (c.body[:25].encode('ascii', 'replace'), unicode(c.author).encode('ascii','replace'))
				# anything left is potentially an answer
				answers.append(c)

		except AttributeError:
			# hit a MoreComments, so just skip it
			print '---- SKIPPED: MoreComments'
			continue

	return answers

def sanitize_body(answer_body):
	body = answer_body[:200]
	body = body.replace('\n\n', '\n\n>')
	
	return body

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
		print 'History file found. Loading...'
		with open('history.json', 'r') as infile:
			data = json.load(infile)
		scanned = data['scanned']
		posted = data['posted']
		post_ids = data['post_ids']
		print 'History loaded. %d scanned posts. %d posts with answers.' % (len(scanned), len(posted))
	else:
		print 'Initializing history file...'
		with open('history.json', 'w') as outfile:
			data = {'scanned': {}, 'posted': {}, 'post_ids': {} }
			json.dump(data, outfile)
		print 'History initialized'

	print 'Bot initiated'

	r = praw.Reddit(user_agent=USER_AGENT)

	# authenticate
	o = OAuth2Util.OAuth2Util(r)
	print 'Authenticated'

	if len(post_ids) > 0:
		print 'Loading previous posts'
		ah = r.get_subreddit('askhistorians')
		posts = { cid: r.get_submission(submission_id=pid) for cid, pid in post_ids.iteritems() }


	try:
		while True:
			# keep the auth token alive
			o.refresh()

			ah = r.get_subreddit('askhistorians')

			if DEBUG:
				answers_sub = r.get_subreddit('afh_meta')
			else:
				answers_sub = r.get_subreddit('answeredhistory')

			print 'Scanning posts...'

			for post in ah.get_hot(limit=50):
				print u'Post: %s - by %s' % (post.title.encode('ascii', 'replace'), unicode(post.author).encode('ascii', 'replace'))

				status = None
				# if it's a meta post, skip it
				if post.link_flair_text and \
					(post.link_flair_text.lower() == 'meta' or \
					 post.link_flair_text.lower() == 'feature'): 
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
					print '-- SKIPPED: %s' % status
					continue

				# otherwise, look for answers
				answers = find_answers(post)
				print '-- %d answer(s) found' % len(answers)

				if len(answers) == 0:
					print '-- SKIPPED'
					continue

				# if there are any answers, make a thread for the post
				if post.id not in posts:
					post_title = u'Answers for "%s" (/u/%s)' % (post.title, post.author)
					post_text = '[ORIGINAL THREAD](%s)' % post.short_link
					posts[post.id] = r.submit(answers_sub, post_title, text=post_text)

				# check for answers from a previous scan
				if post.id in posted:
					prev_answers = list(posted[post.id]) # using list() to copy the list
					print '-- %d answer(s) previously found' % len(prev_answers)
				else:
					prev_answers = []

				print '---- Posting answers...'
				for a in answers:
					# post each answer as a top-level comment that links to the original post
					# ie.
					"""
					[Goluxas replies:](link to comment)

					> First 80 characters of response...
					"""

					# check if it's already been posted
					if a.id not in prev_answers:
						# not using /u/ notation because that sends a notification to the author every time
						body = sanitize_body(a.body)
						text = u'[%s replies:](%s)\n\n> [%s...]' % (a.author, a.permalink, body)

						try:
							posts[post.id].add_comment(text)
							#new_post.set_flair(flair_text=str(a.author))

							if post.id not in posted:
								posted[post.id] = [a.id]
							else:
								posted[post.id].append(a.id)

							print u'---- New answer from /u/%s' % unicode(a.author).encode('ascii','replace')

						except praw.errors.AlreadySubmitted:
							print '---- EXCEPTION: Answer already posted but not in posted dict!'

					else:
						prev_answers.remove(a.id)
						print '---- Answer previously found'

				if len(answers) == 0:
					print '-- No answers found'
				else:
					print '-- Answers processed'

				# anything left in prev_answers failed to meet the answer criteria
				# (it was probably deleted)
				print '-- %d previous answer(s) not found' % len(prev_answers)
				for missing in prev_answers:
					# add a 'deleted' tag to the post
					#posts[a.id].set_flair('DELETED') -- will no longer work
					#print u'-- Marked as Deleted: %s' % posts[a.id].title
					print 'SHOULD BE MARKED DELETED: %s' % missing
					

			# write posted answers to history file
			with open('history.json', 'w') as outfile:
				post_ids = { answer_id: post.id for answer_id, post in posts.iteritems() }
				data = {'scanned': scanned,
						'posted': posted,
						'post_ids': post_ids}
				json.dump(data, outfile)

			# TODO - scan inbox for missed answers

			print 'Scan complete'
			print 'Waiting %d minutes...' % WAIT_TIME
			# wait 15 minutes
			time.sleep(60 * WAIT_TIME)

	# Catch-all exception so we can write out the history even if it crashes for some reason
	except:
		import sys, traceback
		exc_type, exc_value, exc_traceback = sys.exc_info()
		traceback.print_exception(exc_type, exc_value, exc_traceback, file=sys.stdout)

		with open('history.json', 'w') as outfile:
			post_ids = { answer_id: post.id for answer_id, post in posts.iteritems() }
			data = {'scanned': scanned,
					'posted': posted,
					'post_ids': post_ids}
			json.dump(data, outfile)
		
